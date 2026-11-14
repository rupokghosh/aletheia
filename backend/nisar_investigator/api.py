"""HTTP API. Start it with:  backend/.venv/bin/uvicorn nisar_investigator.api:app --port 8000

Every endpoint answers in JSON. The three workflow endpoints always answer with a WorkflowResult and HTTP 200:
whether the analysis worked is in its `status` field ("ok", "unsupported" or "error") with the reason in
`summary.headline`. Other problems answer with {"error": <code>, "message": <plain sentence>}.
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import re
from collections.abc import Callable
from pathlib import Path

import requests
from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import __version__, agent, catalog, config, provenance
from .schemas import ChangeRequest, Coverage, InvestigateRequest, MotionRequest, TimeSeriesRequest, WorkflowResult
from .workflows import common
from .workflows.change import run_change
from .workflows.timeseries import run_timeseries

MOTION_MODULE = "nisar_investigator.workflows.motion"
DEFAULT_CORS_ORIGINS = ["http://localhost:3000"]

_RESULT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,80}")
_FILENAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,120}")
_CONTENT_TYPES = {
    ".png": "image/png",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".csv": "text/csv; charset=utf-8",
    ".json": "application/json",
}


class ApiError(Exception):
    """A problem to report to the client as {"error": code, "message": message}."""

    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def _cors_origins() -> list[str]:
    extra = [o.strip().rstrip("/") for o in os.environ.get("NISAR_CORS_ORIGINS", "").split(",") if o.strip()]
    return list(dict.fromkeys(DEFAULT_CORS_ORIGINS + extra))


app = FastAPI(
    title="Aletheia API",
    version=__version__,
    description="Radar-backed answers from NISAR data, with receipts.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


# ------------------------------------------------------------------- errors


def _error(status_code: int, code: str, message: str, **extra) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"error": code, "message": message, **extra})


@app.exception_handler(ApiError)
async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
    return _error(exc.status_code, exc.code, exc.message)


@app.exception_handler(RequestValidationError)
async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    problems = []
    for err in exc.errors():
        where = ".".join(str(part) for part in err.get("loc", ()) if part not in ("body", "query", "path"))
        problems.append({"field": where, "problem": err.get("msg", "invalid value")})
    message = "; ".join(f"{p['field']}: {p['problem']}" if p["field"] else p["problem"] for p in problems)
    return _error(422, "invalid_request", f"The request is not valid. {message}.", fields=problems)


@app.exception_handler(StarletteHTTPException)
async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = "not_found" if exc.status_code == 404 else "http_error"
    return _error(exc.status_code, code, str(exc.detail))


@app.exception_handler(Exception)
async def _unexpected_error(_: Request, exc: Exception) -> JSONResponse:
    common.log_failure("api", exc)
    return _error(500, "internal_error", f"The server hit an unexpected problem ({type(exc).__name__}).")


# ----------------------------------------------------------------- catalogue


@app.get("/api/health")
async def health() -> dict:
    return {
        "status": "ok",
        "service": "aletheia",
        "version": __version__,
        "workflows": {
            "change": True,
            "timeseries": True,
            "motion": importlib.util.find_spec(MOTION_MODULE) is not None,
        },
        "investigator": {
            "provider": config.agent_provider(),
            "model": config.AGENT_MODEL if config.agent_provider() == "anthropic" else config.LLM_MODEL,
        },
    }


def _parse_bbox(text: str) -> tuple[float, float, float, float]:
    try:
        west, south, east, north = (float(v) for v in text.split(","))
    except ValueError:
        raise ApiError(422, "invalid_request", "bbox must be four numbers: west,south,east,north.") from None
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        raise ApiError(
            422, "invalid_request", "bbox must be west,south,east,north in degrees, with west < east and south < north."
        )
    return west, south, east, north


@app.get("/api/coverage", response_model=Coverage)
async def coverage(
    lon: float | None = Query(None, ge=-180, le=180),
    lat: float | None = Query(None, ge=-90, le=90),
    bbox: str | None = Query(None, description="west,south,east,north in degrees"),
) -> Coverage:
    """What NISAR has for a point (lon and lat) or a box (bbox)."""
    if bbox is not None:
        where: dict = {"bbox": _parse_bbox(bbox)}
    elif lon is not None and lat is not None:
        where = {"lon": lon, "lat": lat}
    else:
        raise ApiError(422, "invalid_request", "Give either lon and lat, or bbox=west,south,east,north.")
    try:
        return await run_in_threadpool(lambda: catalog.coverage(**where))
    except requests.RequestException:
        raise ApiError(
            502, "catalogue_unavailable", "NASA's catalogue (CMR) could not be reached. Try again in a moment."
        ) from None


# ----------------------------------------------------------------- workflows


async def _run(workflow: str, run: Callable[[BaseModel], WorkflowResult], req: BaseModel) -> WorkflowResult:
    """Run a blocking workflow off the event loop. Whatever happens, the client gets a WorkflowResult."""
    try:
        return await run_in_threadpool(run, req)
    except Exception as exc:  # noqa: BLE001 - workflows report their own problems; this is the last line of defence
        common.log_failure(workflow, exc)
        headline = f"The {workflow} analysis failed unexpectedly ({type(exc).__name__}). Nothing was measured."
        return common.failure(workflow, "error", headline, req.model_dump(mode="json"))


@app.post("/api/change", response_model=WorkflowResult)
async def change(req: ChangeRequest) -> WorkflowResult:
    """Workflow A: backscatter change between two dates of one stack."""
    return await _run("change", run_change, req)


@app.post("/api/timeseries", response_model=WorkflowResult)
async def timeseries(req: TimeSeriesRequest) -> WorkflowResult:
    """Workflow B: mean backscatter of an area on every available date."""
    return await _run("timeseries", run_timeseries, req)


def _run_motion(req: MotionRequest) -> WorkflowResult:
    """Workflow C lives in an optional module: say so plainly when this build does not have it."""
    try:
        run = getattr(importlib.import_module(MOTION_MODULE), "run_motion", None)
    except ImportError:
        run = None
    if run is None:
        headline = "Ground motion is not supported yet: this server was built without the motion workflow."
        return common.failure("motion", "unsupported", headline, req.model_dump(mode="json"))
    return run(req)


@app.post("/api/motion", response_model=WorkflowResult)
async def motion(req: MotionRequest) -> WorkflowResult:
    """Workflow C: line-of-sight ground motion from a ready-made interferogram pair."""
    return await _run("motion", _run_motion, req)


# ------------------------------------------------------------ investigation


@app.post("/api/investigate")
async def investigate(req: InvestigateRequest) -> StreamingResponse:
    """Question-driven investigation, streamed as server-sent events: step, tool_call, tool_result, done, error.

    The generator is synchronous (workflows and model calls block), so Starlette iterates it in a thread.
    """
    return StreamingResponse(
        agent.sse(agent.investigate(req)),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ------------------------------------------------------- results and files


@app.get("/api/results/{result_id}")
async def result(result_id: str) -> JSONResponse:
    """A stored WorkflowResult, exactly as it was returned when it was computed."""
    stored = provenance.load_result(result_id) if _RESULT_ID.fullmatch(result_id) else None
    if stored is None:
        raise ApiError(404, "not_found", f"No stored result has the id {result_id!r}.")
    return JSONResponse(stored)


@app.get("/api/artifacts/{result_id}/{filename}")
async def artifact(result_id: str, filename: str) -> FileResponse:
    """A PNG, GeoTIFF, CSV or JSON file produced by a workflow."""
    media_type = _CONTENT_TYPES.get(Path(filename).suffix.lower())
    missing = ApiError(404, "not_found", "No such file.")
    well_formed = _RESULT_ID.fullmatch(result_id) and _FILENAME.fullmatch(filename) and ".." not in filename
    if media_type is None or not well_formed:
        raise missing
    root = config.artifacts_dir().resolve()
    path = (root / result_id / filename).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise missing
    # a result id is never reused, so its files never change
    return FileResponse(path, media_type=media_type, headers={"Cache-Control": "public, max-age=86400, immutable"})

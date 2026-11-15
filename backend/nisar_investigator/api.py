"""HTTP API. Start it with:  backend/.venv/bin/uvicorn nisar_investigator.api:app --port 8000

Every endpoint answers in JSON. The three workflow endpoints always answer with a WorkflowResult and HTTP 200:
whether the analysis worked is in its `status` field ("ok", "unsupported" or "error") with the reason in
`summary.headline`. Other problems answer with {"error": <code>, "message": <plain sentence>}.
"""

from __future__ import annotations

import datetime
import importlib
import importlib.util
import os
import re
import threading
import time
from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path

import requests
from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import __version__, agent, catalog, config, gcov, plain, provenance, radar_tiles, remote
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


@asynccontextmanager
async def _lifespan(_: FastAPI):
    """Start the file-reader processes while the server comes up, so the first analysis does not wait for them."""
    threading.Thread(target=gcov.warm_readers, daemon=True).start()
    yield


app = FastAPI(
    title="Aletheia API",
    version=__version__,
    description="Radar-backed answers from NISAR data, with receipts.",
    lifespan=_lifespan,
)


def _resolve_likely(found: Coverage) -> None:
    """Log in to the archive and resolve the links of the files an analysis here would read first.

    A few one-byte requests, made while the person is still choosing what to ask; they take the login
    (the slowest single step of a first read) out of the analysis that follows. Never raises.
    """
    try:
        urls: list[str] = []
        backscatter = [s for s in found.stacks if s.product == "GCOV"]
        if backscatter:
            best = max(backscatter, key=lambda s: len(s.dates))
            mine = [g for g in found.products.get("GCOV", []) if (g.track, g.frame, g.direction) == (best.track, best.frame, best.direction)]
            urls += [g.url for g in sorted(mine, key=lambda g: g.date or "")[-2:]]
        pairs = sorted(found.products.get("GUNW", []), key=lambda g: g.secondary_date or "")
        urls += [g.url for g in pairs[-2:]]
        remote.resolve_many(urls)
    except Exception:  # noqa: BLE001 - a convenience only
        pass


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


# -------------------------------------------------------------- fair use
#
# A public server spends its owner's NASA data allowance and processor time on every analysis. Each address
# may start a limited number per minute; reading results, tiles and coverage is not limited. The count is
# kept per server instance, which is enough to stop one visitor from hammering it.

_ANALYSES = ("/api/change", "/api/timeseries", "/api/motion", "/api/investigate")
_started: dict[str, list[float]] = {}
_started_guard = threading.Lock()


@app.middleware("http")
async def _fair_use(request: Request, call_next):
    limit = config.RATE_LIMIT_PER_MINUTE
    if limit > 0 and request.method == "POST" and request.url.path in _ANALYSES:
        forwarded = request.headers.get("x-forwarded-for", "")
        who = forwarded.split(",")[0].strip() or (request.client.host if request.client else "unknown")
        now = time.time()
        with _started_guard:
            recent = [t for t in _started.get(who, []) if now - t < 60.0]
            allowed = len(recent) < limit
            if allowed:
                recent.append(now)
            _started[who] = recent
            if len(_started) > 5000:  # forget addresses that have gone quiet
                for key in [k for k, v in _started.items() if not v or now - v[-1] > 60.0]:
                    del _started[key]
        if not allowed:
            return _error(429, "too_many_requests", "Too many analyses were started from this address in the last minute. Wait a moment and try again.")
    return await call_next(request)


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
            "available": await run_in_threadpool(_investigator_available),
        },
    }


_model_check: dict = {"at": 0.0, "ok": False}


def _investigator_available() -> bool:
    """Whether questions in plain language can be answered here: a hosted model is configured, or the local
    one answers. Asked of the local model at most twice a minute."""
    if config.agent_provider() != "ollama":
        return True
    if time.time() - _model_check["at"] > 30:
        try:
            ok = requests.get(f"{config.OLLAMA_HOST}/api/version", timeout=0.6).status_code == 200
        except requests.RequestException:
            ok = False
        _model_check.update(at=time.time(), ok=ok)
    return bool(_model_check["ok"])


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
        found = await run_in_threadpool(lambda: catalog.coverage(**where))
        threading.Thread(target=_resolve_likely, args=(found,), daemon=True).start()
        return found
    except requests.RequestException:
        raise ApiError(
            502, "catalogue_unavailable", "NASA's catalogue (CMR) could not be reached. Try again in a moment."
        ) from None


# ----------------------------------------------------------------- workflows


async def _run(workflow: str, run: Callable[[BaseModel], WorkflowResult], req: BaseModel) -> WorkflowResult:
    """Run a blocking workflow off the event loop. Whatever happens, the client gets a WorkflowResult."""
    try:
        return plain.annotate(await run_in_threadpool(run, req))
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


# ------------------------------------------------------- radar picture tiles


@app.get("/api/tiles/radar/{z}/{x}/{y}")
def radar_tile(z: int, x: int, y: int, end: str | None = None, days: int = 12) -> Response:
    """One square of the radar picture of the Earth: `days` daily NASA pictures up to `end`, merged and cached.

    A plain (not async) handler: it runs in the server's thread pool, and blocks only on a first fetch.
    """
    try:
        last = datetime.date.fromisoformat(end) if end else radar_tiles.default_end()
        picture = radar_tiles.tile(z, x, y, last, days)
    except (ValueError, radar_tiles.TileError):
        raise ApiError(404, "no_tile", "No such radar picture tile.") from None
    headers = {"Cache-Control": radar_tiles.cache_control(last, picture.complete)}
    return Response(content=picture.data, media_type=picture.media_type, headers=headers)


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


_replays: dict[str, threading.Lock] = {}
_replays_guard = threading.Lock()


def _materialise(result_id: str, token: str | None) -> dict | None:
    """The stored result. When this server instance does not have it (a fresh instance keeps nothing from
    earlier ones) and the caller sent the result's replay token, the result is computed again under the same
    id first, which also puts its pictures and files back."""
    stored = provenance.load_result(result_id)
    replay = provenance.read_replay(token) if (stored is None and token) else None
    if replay is None:
        return stored
    workflow, request = replay
    runners: dict[str, tuple[type[BaseModel], Callable]] = {
        "change": (ChangeRequest, run_change),
        "timeseries": (TimeSeriesRequest, run_timeseries),
        "motion": (MotionRequest, _run_motion),
    }
    if workflow not in runners:
        return None
    model, run = runners[workflow]
    with _replays_guard:
        lock = _replays.setdefault(result_id, threading.Lock())
    with lock:  # several files of one result are usually asked for at once: compute it once
        stored = provenance.load_result(result_id)
        if stored is None:
            try:
                with provenance.reusing_id(result_id):
                    run(model(**{k: v for k, v in request.items() if k in model.model_fields}))
            except Exception as exc:  # noqa: BLE001 - a bad token must not become a server error
                common.log_failure("replay", exc)
            stored = provenance.load_result(result_id)
    return stored


@app.get("/api/results/{result_id}")
async def result(result_id: str, r: str | None = None) -> JSONResponse:
    """A stored WorkflowResult, exactly as it was returned when it was computed."""
    stored = await run_in_threadpool(_materialise, result_id, r) if _RESULT_ID.fullmatch(result_id) else None
    if stored is None:
        raise ApiError(404, "not_found", f"No stored result has the id {result_id!r}.")
    return JSONResponse(stored)


@app.get("/api/results/{result_id}/point")
async def point(
    result_id: str,
    lon: float = Query(..., ge=-180, le=180),
    lat: float = Query(..., ge=-90, le=90),
    r: str | None = None,
) -> dict:
    """What a stored result says at one spot: the values there, and what they mean in plain words."""
    if not _RESULT_ID.fullmatch(result_id):
        raise ApiError(404, "not_found", "No such result.")

    def read() -> dict:
        _materialise(result_id, r)
        return plain.read_point(result_id, lon, lat)

    try:
        return await run_in_threadpool(read)
    except plain.PointError as exc:
        raise ApiError(404, "no_reading", str(exc)) from None


@app.get("/api/artifacts/{result_id}/{filename}")
async def artifact(result_id: str, filename: str, r: str | None = None) -> FileResponse:
    """A PNG, GeoTIFF, CSV or JSON file produced by a workflow."""
    media_type = _CONTENT_TYPES.get(Path(filename).suffix.lower())
    missing = ApiError(404, "not_found", "No such file.")
    well_formed = _RESULT_ID.fullmatch(result_id) and _FILENAME.fullmatch(filename) and ".." not in filename
    if media_type is None or not well_formed:
        raise missing
    root = config.artifacts_dir().resolve()
    path = (root / result_id / filename).resolve()
    if not path.is_relative_to(root):
        raise missing
    if not path.is_file() and r:
        await run_in_threadpool(_materialise, result_id, r)
    if not path.is_file():
        raise missing
    # a result id is never reused, so its files never change
    return FileResponse(path, media_type=media_type, headers={"Cache-Control": "public, max-age=86400, immutable"})

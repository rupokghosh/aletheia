"""Receipts: every result records which granules it used, what was done to them and how long it took."""

from __future__ import annotations

import base64
import json
import os
import secrets
import subprocess
import time
import zlib
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path

from . import __version__, config
from .schemas import Granule, Receipt, ReceiptGranule, ReceiptStep, WorkflowResult

_PREFIX = {"change": "chg", "timeseries": "ts", "motion": "mot", "investigation": "inv"}


_reused_id: ContextVar[str | None] = ContextVar("reused_result_id", default=None)


def new_id(kind: str) -> str:
    reused = _reused_id.get()
    if reused:
        return reused
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    return f"{_PREFIX.get(kind, kind)}_{stamp}_{secrets.token_hex(4)}"


@contextmanager
def reusing_id(result_id: str):
    """While this is open, the workflow started in this thread writes its result under an existing id."""
    token = _reused_id.set(result_id)
    try:
        yield
    finally:
        _reused_id.reset(token)


# ------------------------------------------------------------------ replay
#
# A hosted server instance keeps files only on a temporary disk that other instances do not share, so the
# pictures and files of a result cannot be assumed to be there when the browser asks for them a moment
# later. Instead of shared storage, every result carries its own request, packed into a short token that
# also rides on each of its file links. Any instance that lacks the files can then compute the result
# again, under the same id. The token holds the request as it was resolved (the track and polarization
# actually used), so the second computation makes the same choices as the first.

MAX_REPLAY_CHARS = 6000  # longer than this (a very detailed polygon) and the result is simply not replayable


def _replay_request(result: WorkflowResult) -> dict | None:
    if result.status != "ok":
        return None
    request = {k: v for k, v in result.request.items() if k != "resolved"}
    if result.workflow == "change":
        stack = result.stats.get("stack") or {}
        request["track"] = stack.get("track", request.get("track"))
        request["polarization"] = result.stats.get("primary_polarization", request.get("polarization", "auto"))
    elif result.workflow == "motion":
        request.update({k: v for k, v in (result.request.get("resolved") or {}).items() if v is not None})
    return request


def replay_token(workflow: str, request: dict) -> str | None:
    packed = zlib.compress(json.dumps({"w": workflow, "r": request}, separators=(",", ":")).encode(), 9)
    token = base64.urlsafe_b64encode(packed).decode().rstrip("=")
    return token if len(token) <= MAX_REPLAY_CHARS else None


def read_replay(token: str) -> tuple[str, dict] | None:
    """(workflow, request) from a replay token, or None when it is not one."""
    if not token or len(token) > MAX_REPLAY_CHARS:
        return None
    try:
        packed = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
        spec = json.loads(zlib.decompress(packed))
        workflow, request = spec["w"], spec["r"]
    except (ValueError, KeyError, TypeError, zlib.error):
        return None
    return (workflow, request) if workflow in _PREFIX and isinstance(request, dict) else None


def artifact_path(result_id: str, filename: str) -> Path:
    path = config.artifacts_dir() / result_id
    path.mkdir(parents=True, exist_ok=True)
    return path / filename


def artifact_url(result_id: str, filename: str) -> str:
    return f"/api/artifacts/{result_id}/{filename}"


def _commit() -> str:
    hosted = os.environ.get("VERCEL_GIT_COMMIT_SHA", "")
    if hosted:
        return hosted[:7]
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=config.BACKEND_DIR,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return out.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


class Recorder:
    """Collects the receipt while a workflow runs.

    with rec.step("read_window", rows=[0, 720]):
        ...
    """

    def __init__(self) -> None:
        self.granules: list[ReceiptGranule] = []
        self.steps: list[ReceiptStep] = []

    def use(self, granule: Granule) -> None:
        if any(g.granule_id == granule.granule_id for g in self.granules):
            return
        self.granules.append(
            ReceiptGranule(
                granule_id=granule.granule_id,
                url=granule.url,
                tier=granule.tier,
                product=granule.product,
                date=granule.date,
                reference_date=granule.reference_date,
                secondary_date=granule.secondary_date,
                track=granule.track,
                frame=granule.frame,
                direction=granule.direction,
                polarizations=granule.polarizations,
            )
        )

    @contextmanager
    def step(self, name: str, **params):
        entry = ReceiptStep(name=name, params=dict(params))
        t0 = time.time()
        try:
            yield entry  # the caller may add to entry.params while the step runs
        finally:
            entry.seconds = round(time.time() - t0, 2)
            self.steps.append(entry)

    def note(self, name: str, **params) -> None:
        self.steps.append(ReceiptStep(name=name, params=dict(params)))

    def receipt(self, reproduce: str = "") -> Receipt:
        return Receipt(
            granules=self.granules,
            steps=self.steps,
            software={"name": "aletheia", "version": __version__, "commit": _commit()},
            generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            reproduce=reproduce,
        )


def save_result(result: WorkflowResult) -> Path:
    """Persist the full result next to its artifacts so it can be re-served and cited later.

    Before saving, the result is given its replay token, and the token is added to each of its file links.
    """
    request = _replay_request(result)
    token = replay_token(result.workflow, request) if request is not None else None
    if token and result.replay is None:
        result.replay = token
        for item in [*result.layers, *result.downloads]:
            if item.url.startswith("/api/artifacts/") and "?" not in item.url:
                item.url = f"{item.url}?r={token}"
    path = artifact_path(result.id, "result.json")
    path.write_text(json.dumps(result.model_dump(mode="json"), indent=2))
    return path


def load_result(result_id: str) -> dict | None:
    path = config.artifacts_dir() / result_id / "result.json"
    return json.loads(path.read_text()) if path.exists() else None

"""Receipts: every result records which granules it used, what was done to them and how long it took."""

from __future__ import annotations

import json
import secrets
import subprocess
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from . import __version__, config
from .schemas import Granule, Receipt, ReceiptGranule, ReceiptStep, WorkflowResult

_PREFIX = {"change": "chg", "timeseries": "ts", "motion": "mot", "investigation": "inv"}


def new_id(kind: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    return f"{_PREFIX.get(kind, kind)}_{stamp}_{secrets.token_hex(4)}"


def artifact_path(result_id: str, filename: str) -> Path:
    path = config.artifacts_dir() / result_id
    path.mkdir(parents=True, exist_ok=True)
    return path / filename


def artifact_url(result_id: str, filename: str) -> str:
    return f"/api/artifacts/{result_id}/{filename}"


def _commit() -> str:
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
            software={"name": "nisar-investigator", "version": __version__, "commit": _commit()},
            generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            reproduce=reproduce,
        )


def save_result(result: WorkflowResult) -> Path:
    """Persist the full result next to its artifacts so it can be re-served and cited later."""
    path = artifact_path(result.id, "result.json")
    path.write_text(json.dumps(result.model_dump(mode="json"), indent=2))
    return path


def load_result(result_id: str) -> dict | None:
    path = config.artifacts_dir() / result_id / "result.json"
    return json.loads(path.read_text()) if path.exists() else None

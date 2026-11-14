"""Helpers shared by the backscatter workflows: request checks, stack grouping, coverage, failures, wording."""

from __future__ import annotations

import logging
import traceback
from collections import defaultdict
from datetime import date

import numpy as np
import requests
from PIL import Image, ImageDraw
from pyproj import Transformer

from .. import config, gcov, provenance
from ..remote import RemoteAccessError
from ..schemas import BBox, Caveat, Granule, Summary, WorkflowResult

log = logging.getLogger(__name__)

# A date is used only if valid radar samples cover at least this fraction of the requested area.
MIN_COVERAGE = 0.9
MAX_WORKERS = 6
NOMINAL_PIXEL_M = 10.0  # GCOV frequency A posting

StackKey = tuple[int, str, int]  # track, direction, frame

_TIER_TEXT = {
    "beta": "beta-tier (uncalibrated: brightness levels are not yet tied to an absolute reference)",
    "provisional": "provisional-tier (calibrated, but values may change after reprocessing)",
    "validated": "validated-tier",
}


class RequestProblem(ValueError):
    """The request cannot be run as given. `status` is the WorkflowResult status to report."""

    def __init__(self, message: str, status: str = "error", stats: dict | None = None):
        super().__init__(message)
        self.status = status
        self.stats = stats or {}


# ------------------------------------------------------------------ requests


def parse_date(text: str, field: str) -> date:
    try:
        return date.fromisoformat(text)
    except (TypeError, ValueError):
        raise RequestProblem(f"{field} must be a date written as YYYY-MM-DD, got {text!r}.") from None


def approx_pixels(bbox: BBox) -> float:
    """Roughly how many 10 m pixels a lon/lat box holds (the exact count depends on the granule's grid)."""
    west, south, east, north = bbox
    width_m = (east - west) * 111_320 * float(np.cos(np.radians((south + north) / 2)))
    height_m = (north - south) * 110_574
    return max(width_m * height_m / NOMINAL_PIXEL_M**2, 1.0)


def check_bbox(bbox: BBox) -> None:
    """Reject boxes that are malformed or would need more pixels than one request may read."""
    west, south, east, north = bbox
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        raise RequestProblem(
            "bbox must be [west, south, east, north] in degrees, with west < east and south < north."
        )
    pixels = approx_pixels(bbox)
    if pixels > config.MAX_WINDOW_PIXELS:
        km2_per_pixel = NOMINAL_PIXEL_M**2 / 1e6
        raise RequestProblem(
            f"The area is too large: about {pixels * km2_per_pixel:,.0f} km2, which needs {pixels / 1e6:.0f} million "
            f"pixels per date. The limit is {config.MAX_WINDOW_PIXELS / 1e6:.0f} million "
            f"(about {config.MAX_WINDOW_PIXELS * km2_per_pixel:,.0f} km2). Draw a smaller area.",
            status="unsupported",
        )


# -------------------------------------------------------------------- stacks


def group_stacks(granules: list[Granule]) -> dict[StackKey, list[Granule]]:
    """Granules whose pixel grids line up (same track, direction and frame), each group sorted by time."""
    groups: dict[StackKey, list[Granule]] = defaultdict(list)
    for g in granules:
        groups[(g.track, g.direction, g.frame)].append(g)
    return {key: sorted(items, key=lambda g: g.start_time or "") for key, items in sorted(groups.items())}


def stack_name(key: StackKey) -> str:
    track, direction, _ = key
    return f"track {track} ({direction})"


def footprint_fraction(footprint: list[tuple[float, float]], bbox: BBox, n: int = 200) -> float:
    """Approximate fraction of a lon/lat box that lies inside a granule footprint (1.0 if it is unknown)."""
    if len(footprint) < 3:
        return 1.0
    west, south, east, north = bbox
    img = Image.new("L", (n, n), 0)
    ring = [((x - west) / (east - west) * n, (north - y) / (north - south) * n) for x, y in footprint]
    ImageDraw.Draw(img).polygon(ring, fill=1)
    return float(np.asarray(img).mean())


# ------------------------------------------------------------------ coverage


def expected_pixels(bbox: BBox, cut: gcov.Cutout) -> int:
    """Pixels a full window for this box holds on the cutout's grid (the same envelope gcov reads)."""
    west, south, east, north = bbox
    tr = Transformer.from_crs("EPSG:4326", f"EPSG:{cut.epsg}", always_xy=True)
    xs, ys = tr.transform([west, east, west, east], [south, south, north, north])
    dx, dy = cut.pixel_size
    return max(int((max(xs) - min(xs)) / dx) * int((max(ys) - min(ys)) / dy), 1)


def coverage(valid: np.ndarray, expected: float) -> float:
    """Fraction of the requested area that carries valid samples."""
    return min(float(np.count_nonzero(valid)) / max(expected, 1.0), 1.0)


# ------------------------------------------------------------------ failures


def explain_read_error(exc: Exception) -> tuple[str, str]:
    """(status, plain sentence) for something gcov.read_windows returned instead of a cutout.

    Only messages written by this package are passed on: third-party exception text can carry URLs.
    """
    if isinstance(exc, gcov.WindowTooLarge):
        return "unsupported", f"The area is too large: {exc}"
    if isinstance(exc, gcov.OutsideFrame):
        return "unsupported", "The area lies outside the part of the track that this acquisition imaged."
    if isinstance(exc, RemoteAccessError):
        return "error", f"The NISAR archive could not be read: {exc}"
    return "error", f"The granule could not be read ({type(exc).__name__})."


def explain_search_error(exc: Exception) -> str:
    if isinstance(exc, requests.RequestException):
        return "NASA's catalogue (CMR) could not be reached. Check the connection and try again."
    return f"The catalogue search failed ({type(exc).__name__})."


def log_failure(workflow: str, exc: Exception) -> None:
    """Log where an unexpected failure happened, without the exception text (it may quote a signed link)."""
    frames = "".join(traceback.format_tb(exc.__traceback__))
    log.error("%s workflow failed with %s\n%s", workflow, type(exc).__name__, frames)


def failure(
    workflow: str,
    status: str,
    headline: str,
    request: dict,
    recorder: provenance.Recorder | None = None,
    stats: dict | None = None,
) -> WorkflowResult:
    """A result that carries no measurement, only the reason there is none."""
    return WorkflowResult(
        id=provenance.new_id(workflow),
        workflow=workflow,  # type: ignore[arg-type]
        status=status,  # type: ignore[arg-type]
        request=request,
        summary=Summary(headline=headline),
        stats=stats or {},
        receipt=(recorder or provenance.Recorder()).receipt(),
    )


# ------------------------------------------------------------------- wording


def pretty_date(iso: str) -> str:
    """'2026-06-19' -> '19 June 2026'."""
    d = date.fromisoformat(iso)
    return f"{d.day} {d:%B %Y}"


def pretty_span(first: str, last: str) -> str:
    """'19 June and 17 October 2026', repeating the year only when it differs."""
    a, b = date.fromisoformat(first), date.fromisoformat(last)
    start = f"{a.day} {a:%B}" if a.year == b.year else pretty_date(first)
    return f"{start} and {pretty_date(last)}"


def join_words(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def co_pol(polarizations: list[str]) -> str | None:
    """The like-polarized channel, which carries the most signal over most surfaces."""
    return next((p for p in ("HH", "VV") if p in polarizations), None)


def tier_caveats(granules: list[Granule]) -> list[Caveat]:
    """One caveat per calibration tier in use, naming the dates it applies to."""
    by_tier: dict[str, list[str]] = defaultdict(list)
    for g in granules:
        if g.date:
            by_tier[g.tier].append(g.date)
    out = []
    for tier in ("beta", "provisional", "validated"):
        dates = sorted(set(by_tier.get(tier, [])))
        if not dates:
            continue
        which = join_words(dates) if len(dates) <= 4 else f"{len(dates)} dates from {dates[0]} to {dates[-1]}"
        verb = "is" if len(dates) == 1 else "are"
        out.append(Caveat(code=f"tier_{tier}", text=f"{which} {verb} {_TIER_TEXT[tier]}."))
    if "beta" in by_tier and len(by_tier) > 1:
        out.append(
            Caveat(
                code="tier_mixed",
                text="Differences between uncalibrated (beta) and calibrated dates can come from calibration "
                "rather than from the ground.",
            )
        )
    return out

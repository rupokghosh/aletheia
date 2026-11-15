"""The radar picture of the Earth as one cached tile layer.

NASA GIBS publishes a picture of each day's NISAR passes. A full view of the planet needs 12 days of them,
and GIBS marks every response "do not cache", so a browser stacking 12 daily layers refetches twelve images
per map square on every move. Here the 12 days are merged into one tile, kept on disk, and served with
cache headers, so each square is fetched from NASA once.

Upstream is the GIBS WMS endpoint. Its WMTS endpoint for this layer was found to return blank tiles
intermittently (the same tile came back empty in about half of repeated requests), so it is not used.

What makes a new square slow is the size of NASA's answer, not the wait for it: a 512-pixel PNG of real
radar data is about 600 KB, and a screen of new squares needs dozens of them. So the colours are asked
for as JPEG (about a tenth of the bytes) and the outline of where there is data comes from a small PNG
of the same square.
"""

from __future__ import annotations

import io
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import NamedTuple

import requests
from PIL import Image
from requests.adapters import HTTPAdapter

from . import config

LAYER = "NISAR_L2_Geocoded_Polarimetric_Covariance"
FIRST_DAY = date(2025, 10, 29)
# 512-pixel squares: a screen needs a quarter as many as with 256-pixel ones. Zoom 12 at this size is
# the full resolution of the NASA picture (about 19 m per pixel at the equator).
MAX_ZOOM = 12
MAX_DAYS = 16
TILE = 512
# Which days NISAR passed over a region is remembered per square at this zoom (about 300 km across),
# so squares inside it ask NASA only for the days that have a picture there: usually 2 to 4 of the 12.
FLAG_ZOOM = 7
FLAG_PIXELS = 256
# The side of the small PNG that says where a day's picture has data. Pictures this small or smaller
# are asked for as PNG outright.
MASK_PIXELS = 128
# GIBS keeps filling in a day's picture for about two weeks; older pictures no longer change.
SETTLED_AFTER_DAYS = 14
UNSETTLED_TTL_SECONDS = 6 * 3600

_WMS = (
    "https://gibs.earthdata.nasa.gov/wms/epsg3857/best/wms.cgi?SERVICE=WMS&REQUEST=GetMap&VERSION=1.3.0"
    f"&LAYERS={LAYER}&STYLES=&CRS=EPSG:3857&BGCOLOR=0x000000"
    "&FORMAT={format}&TRANSPARENT={transparent}&WIDTH={size}&HEIGHT={size}&TIME={day}&BBOX={bbox}"
)
_HALF_WORLD = 20037508.342789244

_session = requests.Session()
# NASA answers one request in about half a second and many at once just as fast, so a screen of new
# squares (a dozen squares, up to 12 days each) is asked for all together.
_session.mount("https://", HTTPAdapter(pool_connections=4, pool_maxsize=128))
_fetchers = ThreadPoolExecutor(max_workers=96, thread_name_prefix="gibs")
_mask_fetchers = ThreadPoolExecutor(max_workers=96, thread_name_prefix="gibs-mask")  # never submits work itself
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


class TileError(ValueError):
    """The tile address or the dates are not valid."""


class UpstreamError(RuntimeError):
    """NASA did not answer, so whether there is a picture is not known."""


class Tile(NamedTuple):
    data: bytes
    media_type: str
    complete: bool  # False when a day could not be fetched: the picture may have a gap and is not kept


def _blank() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGBA", (1, 1), (0, 0, 0, 0)).save(buffer, "PNG")
    return buffer.getvalue()


BLANK_PNG = _blank()


def _bbox(z: int, x: int, y: int) -> str:
    size = 2 * _HALF_WORLD / (2**z)
    west, north = -_HALF_WORLD + x * size, _HALF_WORLD - y * size
    return f"{west},{north - size},{west + size},{north}"


def _days(end: date, days: int) -> list[date]:
    """The days stacked into one picture, oldest first so the most recent pass ends up on top."""
    return [d for d in (end - timedelta(days=i) for i in range(days - 1, -1, -1)) if d >= FIRST_DAY]


def _today() -> date:
    return datetime.now(timezone.utc).date()  # GIBS days are UTC days


def is_settled(end: date) -> bool:
    return (_today() - end).days >= SETTLED_AFTER_DAYS


def _get(day: date, bbox: str, size: int, jpeg: bool = False) -> Image.Image | None:
    """One picture from NASA, or None when the day or the square is outside what the layer holds.

    Raises UpstreamError when NASA did not answer, so that a failed request is never remembered as
    "no picture here".
    """
    url = _WMS.format(
        day=day.isoformat(), bbox=bbox, size=size,
        format="image/jpeg" if jpeg else "image/png", transparent="false" if jpeg else "true",
    )
    for _ in range(3):
        try:
            r = _session.get(url, timeout=(10, 40))
        except requests.RequestException:
            continue
        if r.status_code == 200 and r.headers.get("content-type", "").startswith("image"):
            image = Image.open(io.BytesIO(r.content))
            image.load()
            return image
        if 400 <= r.status_code < 500 and r.status_code != 429:
            return None
    raise UpstreamError(f"no answer from NASA GIBS for {day.isoformat()}")


def _fetch_day(day: date, bbox: str, size: int = TILE) -> Image.Image | None:
    """One day's picture for a map square, or None when NISAR did not pass there that day.
    Raises UpstreamError when NASA did not answer."""
    if size <= MASK_PIXELS * 2:
        small = _get(day, bbox, size)
        small = small.convert("RGBA") if small is not None else None
        return small if small is not None and small.getextrema()[3][1] > 0 else None

    outline = _mask_fetchers.submit(_get, day, bbox, MASK_PIXELS)  # asked for at the same time as the colours
    colours = _get(day, bbox, size, jpeg=True)
    mask = outline.result()
    if mask is None or colours is None:
        return None
    alpha = mask.convert("RGBA").getchannel("A")
    if alpha.getextrema()[1] == 0:
        return None
    if alpha.getextrema()[0] == 255:
        alpha = Image.new("L", (size, size), 255)
    else:
        # Enlarged, then kept only where it is fully inside the data: the edge moves in by a few pixels,
        # which also hides the smear JPEG leaves where a picture ends.
        alpha = alpha.resize((size, size), Image.BILINEAR).point(lambda a: 255 if a >= 250 else 0)
    picture = colours.convert("RGB")
    picture.putalpha(alpha)
    return picture


def _attempt(day: date, bbox: str, size: int = TILE) -> tuple[Image.Image | None, bool]:
    """(picture or None, whether NASA answered)."""
    try:
        return _fetch_day(day, bbox, size), True
    except UpstreamError:
        return None, False


def _path(z: int, x: int, y: int, end: date, days: int) -> Path:
    return config.cache_dir() / "radar_tiles" / str(TILE) / f"{end.isoformat()}_{days}" / str(z) / str(x) / f"{y}.webp"


def _days_with_a_pass(z: int, x: int, y: int, days: list[date]) -> list[date]:
    """The days worth asking NASA about for a square deeper than FLAG_ZOOM: those on which its
    surrounding region has any picture at all. Learned once per region and day, then kept on disk.
    Days whose picture may still be filling in are always asked about."""
    if z <= FLAG_ZOOM:
        return days
    shift = z - FLAG_ZOOM
    fx, fy = x >> shift, y >> shift
    path = config.cache_dir() / "radar_tiles" / "passes" / str(FLAG_ZOOM) / str(fx) / f"{fy}.json"
    with _lock(str(path)):
        known: dict[str, bool] = json.loads(path.read_text()) if path.exists() else {}
        settled = [d for d in days if is_settled(d)]
        missing = [d for d in settled if d.isoformat() not in known]
        if missing:
            bbox = _bbox(FLAG_ZOOM, fx, fy)
            answers = _fetchers.map(lambda d: _attempt(d, bbox, FLAG_PIXELS), missing)
            # A day NASA did not answer for stays unknown, and unknown days are always asked about.
            known.update({d.isoformat(): picture is not None for d, (picture, answered) in zip(missing, answers) if answered})
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(known))
    return [d for d in days if not is_settled(d) or known.get(d.isoformat(), True)]


def _lock(key: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(key, threading.Lock())


def tile(z: int, x: int, y: int, end: date, days: int = 12) -> Tile:
    """The merged picture for one map square. Blank squares are a 1x1 transparent PNG."""
    if not (0 <= z <= MAX_ZOOM and 0 <= x < 2**z and 0 <= y < 2**z):
        raise TileError("no such tile")
    if not (1 <= days <= MAX_DAYS) or end < FIRST_DAY or end > _today():
        raise TileError("dates out of range")

    path = _path(z, x, y, end, days)
    empty = path.with_suffix(".empty")
    settled = is_settled(end)

    def cached() -> Tile | None:
        for candidate in (path, empty):
            if candidate.exists() and (settled or time.time() - candidate.stat().st_mtime < UNSETTLED_TTL_SECONDS):
                return Tile(BLANK_PNG, "image/png", True) if candidate is empty else Tile(candidate.read_bytes(), "image/webp", True)
        return None

    hit = cached()
    if hit:
        return hit
    with _lock(str(path)):  # the same square asked for twice at once is fetched once
        hit = cached()
        if hit:
            return hit
        bbox = _bbox(z, x, y)
        wanted = _days_with_a_pass(z, x, y, _days(end, days))
        answers = list(_fetchers.map(lambda d: _attempt(d, bbox), wanted))
        complete = all(answered for _, answered in answers)  # only a complete picture is kept on disk
        canvas: Image.Image | None = None
        for picture, _ in answers:
            if picture is None:
                continue
            canvas = picture if canvas is None else Image.alpha_composite(canvas, picture)
        if complete:
            path.parent.mkdir(parents=True, exist_ok=True)
        if canvas is None:
            if complete:
                empty.touch()
            return Tile(BLANK_PNG, "image/png", complete)
        buffer = io.BytesIO()
        canvas.save(buffer, "WEBP", quality=84, method=2)  # method 4 takes four times as long for the same size
        data = buffer.getvalue()
        if complete:
            temporary = path.with_suffix(".tmp")
            temporary.write_bytes(data)
            temporary.replace(path)
        return Tile(data, "image/webp", complete)


def cache_control(end: date, complete: bool = True) -> str:
    if not complete:
        return "no-store"  # a day was missing: let the browser ask again
    return "public, max-age=2592000, immutable" if is_settled(end) else "public, max-age=3600"


def default_end() -> date:
    """The last day of the picture the map opens on: at least two weeks old, so the 12-day sweep is
    complete, and snapped to a 7-day grid so the cached tiles stay valid for a week. The web app computes
    the same day (latestCompleteDay in web/src/lib/store.tsx)."""
    day = _today().toordinal() - date(1970, 1, 1).toordinal() - SETTLED_AFTER_DAYS
    return date(1970, 1, 1) + timedelta(days=day - day % 7)


def tiles_for_bbox(bbox: tuple[float, float, float, float], zoom: int) -> list[tuple[int, int, int]]:
    """Map squares covering a lon/lat box at one zoom level."""
    import math

    def col(lon: float) -> int:
        return min(2**zoom - 1, max(0, int((lon + 180.0) / 360.0 * 2**zoom)))

    def row(lat: float) -> int:
        lat = max(-85.0, min(85.0, lat))
        return min(2**zoom - 1, max(0, int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * 2**zoom)))

    west, south, east, north = bbox
    return [(zoom, x, y) for x in range(col(west), col(east) + 1) for y in range(row(north), row(south) + 1)]


def prewarm(squares: list[tuple[int, int, int]], end: date | None = None, days: int = 12, workers: int = 6) -> dict:
    """Fetch and cache a list of map squares. Returns how many had a picture."""
    end = end or default_end()
    t0 = time.time()

    def one(square: tuple[int, int, int]) -> bool:
        return tile(*square, end, days).media_type == "image/webp"

    with ThreadPoolExecutor(max_workers=workers) as pool:
        filled = sum(pool.map(one, squares))
    return {"squares": len(squares), "with_picture": filled, "seconds": round(time.time() - t0, 1)}

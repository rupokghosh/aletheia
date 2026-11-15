"""Windowed reads of NISAR L2 GUNW (geocoded unwrapped interferogram) grids.

Layout verified on real granules (product specification version 1.5.0, product version 1.0.11) with
``scripts/explore_gunw.py``:

    /science/LSAR/identification/                       lookDirection, orbitPassDirection, zero-Doppler times ...
    /science/LSAR/GUNW/grids/frequencyA/
        centerFrequency                                 scalar float64, hertz (1.239e9 for the 40 MHz mode)
        unwrappedInterferogram/
            mask                                        uint32 (rows, cols), _FillValue 255
            HH/                                         (or VV)
                unwrappedPhase                          float32, radians, _FillValue NaN
                coherenceMagnitude                      float32, 0..1, _FillValue NaN
                connectedComponents                     uint16, 0 = not reliably unwrapped, _FillValue 65535
                ionospherePhaseScreen                   float32, radians, _FillValue NaN
                ionospherePhaseScreenUncertainty        float32, radians, _FillValue NaN
                xCoordinates, yCoordinates              float64 pixel centres (m), y descending (north-up)
                xCoordinateSpacing, yCoordinateSpacing  80.0, -80.0
                projection                              uint32 EPSG code (also attribute epsg_code)
        wrappedInterferogram/HH/                        complex64 at 20 m posting (not read here)
        pixelOffsets/HH/                                slantRangeOffset, alongTrackOffset (m) at 80 m
    /science/LSAR/GUNW/metadata/radarGrid/              3-D cubes (20 heights, 500 m posting): incidenceAngle,
                                                        losUnitVectorX/Y (target to sensor, east/north), baselines,
                                                        troposphere and solid-earth-tide phase screens
    /science/LSAR/GUNW/metadata/orbit/temporalBaseline  uint16, days

All 2-D rasters are (4464, 4500)-ish, chunked 512 x 512, gzip level 1 with shuffle. Note that h5py's
``dataset.fillvalue`` is 0 for these datasets: the real no-data marker is the ``_FillValue`` attribute.
"""

from __future__ import annotations

import hashlib
import json
import time
import zlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import h5py
import numpy as np
import requests
from pyproj import Transformer

from . import config
from .gcov import OutsideFrame, WindowTooLarge  # same errors for every product, so callers catch one set
from .remote import RemoteAccessError, RemoteGranule, _resolve, data_session
from .schemas import Granule

__all__ = ["GunwCutout", "OutsideFrame", "WindowTooLarge", "read_window", "valid_sample_mask", "water_mask"]

GRID_PATH = "/science/LSAR/GUNW/grids/frequency{freq}"
ID_PATH = "/science/LSAR/identification"
CUBE_PATH = "/science/LSAR/GUNW/metadata/radarGrid"
META_PATH = "/science/LSAR/GUNW/metadata"

SPEED_OF_LIGHT = 299_792_458.0  # m/s

DEFAULT_LAYERS = (
    "unwrappedPhase",
    "coherenceMagnitude",
    "connectedComponents",
    "ionospherePhaseScreen",
    "ionospherePhaseScreenUncertainty",
)
PREFETCH_WORKERS = 16  # measured: 16 concurrent range requests read a window about a third faster than 8
CC_FILL = 65535  # connectedComponents no-data marker; 0 means "not part of any reliably unwrapped region"
MASK_FILL = 255

# At 80 m posting a whole frame is about 20 M pixels. 9 M pixels is a 240 km square: more than one request needs.
MAX_WINDOW_PIXELS = min(config.MAX_WINDOW_PIXELS, 9_000_000)


@dataclass
class GunwCutout:
    """A window of one GUNW pair. Arrays are (rows, cols), north-up.

    Float layers hold NaN where there is no data. ``connectedComponents`` keeps its integer codes
    (0 = unreliable, 65535 = no data) and ``mask`` keeps the raw NISAR bit field (see ``valid_sample_mask``).
    """

    granule_id: str
    layers: dict[str, np.ndarray]
    x: np.ndarray  # pixel-centre eastings (m)
    y: np.ndarray  # pixel-centre northings (m), descending
    epsg: int
    rows: tuple[int, int]
    cols: tuple[int, int]
    polarization: str
    center_frequency_hz: float
    look_direction: str = ""  # "Left" or "Right"
    pass_direction: str = ""  # "Ascending" or "Descending"
    reference_start: str = ""  # zero-Doppler start time of the earlier acquisition (UTC)
    secondary_start: str = ""
    temporal_baseline_days: int | None = None
    looks: tuple[int, int] | None = None  # (range, azimuth) looks of the unwrapped interferogram
    incidence_deg: float | None = None  # angle between line of sight and vertical at the window centre
    los_enu: tuple[float, float, float] | None = None  # unit vector from the ground to the satellite (east, north, up)
    seconds: float = 0.0
    io: dict = field(default_factory=dict)
    from_cache: bool = False
    # what the first read from NASA's archive cost (megabytes, requests, seconds, file_gb)
    first_read: dict = field(default_factory=dict)

    @property
    def wavelength_m(self) -> float:
        return SPEED_OF_LIGHT / self.center_frequency_hz

    @property
    def shape(self) -> tuple[int, int]:
        return (len(self.y), len(self.x))

    @property
    def pixel_size(self) -> tuple[float, float]:
        dx = float(abs(self.x[1] - self.x[0])) if len(self.x) > 1 else 80.0
        dy = float(abs(self.y[1] - self.y[0])) if len(self.y) > 1 else 80.0
        return dx, dy

    @property
    def pixel_area_km2(self) -> float:
        dx, dy = self.pixel_size
        return dx * dy / 1e6

    def corners_lonlat(self) -> list[tuple[float, float]]:
        """Outer image corners as (lon, lat): top-left, top-right, bottom-right, bottom-left."""
        dx, dy = self.pixel_size
        west, east = float(self.x.min()) - dx / 2, float(self.x.max()) + dx / 2
        south, north = float(self.y.min()) - dy / 2, float(self.y.max()) + dy / 2
        tr = Transformer.from_crs(f"EPSG:{self.epsg}", "EPSG:4326", always_xy=True)
        xs, ys = tr.transform([west, east, east, west], [north, north, south, south])
        return [(round(float(a), 6), round(float(b), 6)) for a, b in zip(xs, ys)]

    def geotransform(self) -> tuple[float, float, float, float, float, float]:
        """GDAL-style affine (x origin, dx, 0, y origin, 0, -dy) for the top-left pixel corner."""
        dx, dy = self.pixel_size
        return (float(self.x.min()) - dx / 2, dx, 0.0, float(self.y.max()) + dy / 2, 0.0, -dy)


# ------------------------------------------------------------------ mask bits


def valid_sample_mask(mask: np.ndarray) -> np.ndarray:
    """True where both acquisitions contributed a valid radar sample.

    Bits 0-7 of the NISAR mask hold a three-digit decimal code: hundreds = water flag, tens = sub-swath number
    in the reference image, units = sub-swath number in the secondary image. A zero sub-swath digit means that
    image had no valid sample there. 255 is the no-data marker. (Source: the dataset's own description.)
    """
    code = np.asarray(mask).astype(np.uint32) & 0xFF
    return (code != MASK_FILL) & ((code // 10) % 10 > 0) & (code % 10 > 0)


def water_mask(mask: np.ndarray) -> np.ndarray:
    """True where the NISAR water mask (hundreds digit of bits 0-7) flags open water."""
    code = np.asarray(mask).astype(np.uint32) & 0xFF
    return (code != MASK_FILL) & (code // 100 == 1)


# ------------------------------------------------------------------- helpers


def _window(x: np.ndarray, y: np.ndarray, epsg: int, bbox: tuple[float, float, float, float], max_pixels: int):
    """Rows and columns of the pixel centres inside a lon/lat box, clipped to the grid."""
    west, south, east, north = bbox
    tr = Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True)
    xs, ys = tr.transform([west, east, west, east], [south, south, north, north])
    cols = np.where((x >= min(xs)) & (x <= max(xs)))[0]
    rows = np.where((y >= min(ys)) & (y <= max(ys)))[0]
    if len(cols) == 0 or len(rows) == 0:
        raise OutsideFrame("the requested box is outside this granule")
    r0, r1, c0, c1 = int(rows.min()), int(rows.max()) + 1, int(cols.min()), int(cols.max()) + 1
    if (r1 - r0) * (c1 - c0) > max_pixels:
        raise WindowTooLarge(
            f"the box needs {(r1 - r0) * (c1 - c0):,} pixels at 80 m; the limit is {max_pixels:,}. Draw a smaller area."
        )
    return r0, r1, c0, c1


def _chunk_ranges(dset, r0: int, r1: int, c0: int, c1: int, lead: tuple[int, ...] = ()) -> list[tuple[int, int]]:
    """Byte ranges of the stored chunks covering a 2-D window (``lead`` indexes any leading dimensions)."""
    if not dset.chunks:
        return []
    ch_r, ch_c = dset.chunks[-2:]
    ranges = []
    for cr in range((r0 // ch_r) * ch_r, r1, ch_r):
        for cc in range((c0 // ch_c) * ch_c, c1, ch_c):
            try:
                info = dset.id.get_chunk_info_by_coord(lead + (cr, cc))
            except Exception:  # noqa: BLE001 - older HDF5 builds: fall back to sequential reads
                return []
            if info.byte_offset is not None and info.size:
                ranges.append((int(info.byte_offset), int(info.size)))
    return ranges


def _batches(ranges: dict[str, list[tuple[int, int]]]) -> list[list[str]]:
    """Group datasets so that each group's chunks fit in the block cache and can be fetched concurrently.

    A small window is one group (everything in parallel). A large one would overflow the cache, and whatever
    does not fit is then read by h5py one block at a time, so it is fetched layer by layer instead.
    """
    budget = max(config.MAX_CACHED_BLOCKS - 8, 1)  # leave room for metadata pages and the geometry cubes
    groups: list[list[str]] = [[]]
    used = 0
    for name, items in ranges.items():
        blocks = {
            index
            for offset, length in items
            for index in range(offset // config.BLOCK_SIZE, (offset + length - 1) // config.BLOCK_SIZE + 1)
        }
        if groups[-1] and used + len(blocks) > budget:
            groups.append([])
            used = 0
        groups[-1].append(name)
        used += len(blocks)
    return groups


def _text(value) -> str:
    if isinstance(value, np.ndarray):
        value = value.ravel()[0] if value.size else b""
    return value.decode(errors="replace") if isinstance(value, bytes) else str(value)


def _fill_value(dset):
    """The CF ``_FillValue`` attribute (h5py's ``fillvalue`` property is 0 for NISAR rasters)."""
    if "_FillValue" not in dset.attrs:
        return None
    value = dset.attrs["_FillValue"]
    return value.ravel()[0] if isinstance(value, np.ndarray) else value


def _cache_path(granule_id: str, bbox, layers: tuple[str, ...], pol: str, freq: str):
    key = f"GUNW|{granule_id}|{freq}|{pol}|{','.join(f'{v:.5f}' for v in bbox)}|{','.join(layers)}"
    digest = hashlib.sha1(key.encode()).hexdigest()[:20]
    path = config.cache_dir() / "windows"
    path.mkdir(parents=True, exist_ok=True)
    return path / f"gunw_{digest}.npz"


def _from_cache(path, granule_id: str) -> GunwCutout:
    z = np.load(path)
    meta = json.loads(str(z["meta"]))
    return GunwCutout(
        granule_id=granule_id,
        layers={k[2:]: z[k] for k in z.files if k.startswith("L_")},
        x=z["x"],
        y=z["y"],
        epsg=int(z["epsg"]),
        rows=tuple(int(v) for v in z["rows"]),
        cols=tuple(int(v) for v in z["cols"]),
        polarization=meta["polarization"],
        center_frequency_hz=float(meta["center_frequency_hz"]),
        look_direction=meta["look_direction"],
        pass_direction=meta["pass_direction"],
        reference_start=meta["reference_start"],
        secondary_start=meta["secondary_start"],
        temporal_baseline_days=meta["temporal_baseline_days"],
        looks=tuple(meta["looks"]) if meta["looks"] else None,
        incidence_deg=meta["incidence_deg"],
        los_enu=tuple(meta["los_enu"]) if meta["los_enu"] else None,
        from_cache=True,
        first_read=json.loads(str(z["first_read"])) if "first_read" in z.files else {},
    )


@dataclass
class _GeometryPoint:
    """Where to sample the radar-grid cubes: height level k, row i, column j."""

    cube: object  # h5py.Group
    k: int
    i: int
    j: int

    NAMES = ("incidenceAngle", "losUnitVectorX", "losUnitVectorY")

    @staticmethod
    def values(inc: float, east: float, north: float):
        """(incidence_deg, (east, north, up)) from the three cube samples; the vector points ground to satellite."""
        if not all(np.isfinite(v) for v in (inc, east, north)):
            return None, None
        up = float(np.sqrt(max(0.0, 1.0 - east**2 - north**2)))
        return round(float(inc), 2), (round(float(east), 4), round(float(north), 4), round(up, 4))


def _look_geometry(h5, x_mid: float, y_mid: float) -> _GeometryPoint | None:
    """Locate the cube sample nearest to a map position, at the height level closest to the terrain."""
    if CUBE_PATH not in h5:
        return None
    cube = h5[CUBE_PATH]
    needed = _GeometryPoint.NAMES + ("xCoordinates", "yCoordinates", "heightAboveEllipsoid")
    if any(name not in cube for name in needed):
        return None
    cx, cy, heights = cube["xCoordinates"][:], cube["yCoordinates"][:], cube["heightAboveEllipsoid"][:]
    # The cubes are sampled at fixed heights; take the level closest to the frame's typical terrain height.
    terrain = 0.0
    ref_height = f"{META_PATH}/processingInformation/parameters/reference/referenceTerrainHeight"
    if ref_height in h5:
        values = h5[ref_height][:]
        values = values[np.isfinite(values)]
        if values.size:
            terrain = float(np.median(values))
    return _GeometryPoint(
        cube=cube,
        k=int(np.argmin(np.abs(heights - terrain))),
        i=int(np.argmin(np.abs(cy - y_mid))),
        j=int(np.argmin(np.abs(cx - x_mid))),
    )


# ------------------------------------------------- exact-range chunk reads
#
# RangeFile serves h5py in whole 4 MiB blocks, so every 512 x 512 chunk (0.01 to 0.8 MB compressed) costs at
# least one block: a 120 x 80 km window was measured at 197 MB of blocks for 30 MB of chunks. The functions
# below ask the archive for exactly the bytes of each chunk and undo the two HDF5 filters NISAR uses (byte
# shuffle, then deflate) themselves. Anything unexpected falls back to the block path through h5py.

_MERGE_GAP = 256 * 1024  # neighbouring chunks closer than this in the file are fetched in one request


def _decodable(dset) -> bool:
    """True if the chunks of this dataset can be decoded here: little-endian numbers, shuffle and/or deflate."""
    plist = dset.id.get_create_plist()
    filters = [plist.get_filter(n)[0] for n in range(plist.get_nfilters())]
    little = dset.dtype.itemsize == 1 or dset.id.get_type().get_order() == h5py.h5t.ORDER_LE
    allowed = ([], [h5py.h5z.FILTER_DEFLATE], [h5py.h5z.FILTER_SHUFFLE, h5py.h5z.FILTER_DEFLATE])
    return bool(dset.chunks) and dset.dtype.kind in "fiu" and little and filters in allowed


def _decode_chunk(blob: bytes, dset) -> np.ndarray:
    """One stored chunk -> array of the dataset's chunk shape (reverses deflate, then the byte shuffle)."""
    plist = dset.id.get_create_plist()
    filters = [plist.get_filter(n)[0] for n in range(plist.get_nfilters())]
    data = zlib.decompress(blob) if h5py.h5z.FILTER_DEFLATE in filters else blob
    dtype = dset.dtype.newbyteorder("<")
    count = int(np.prod(dset.chunks))
    if len(data) != count * dtype.itemsize:
        raise ValueError("chunk has an unexpected size")
    if h5py.h5z.FILTER_SHUFFLE in filters and dtype.itemsize > 1:
        # shuffle stores all first bytes, then all second bytes, ...: put each value's bytes back together
        data = np.frombuffer(data, dtype=np.uint8).reshape(dtype.itemsize, count).T.tobytes()
    return np.frombuffer(data, dtype=dtype).reshape(dset.chunks)


def _chunk_refs(dset, r0: int, r1: int, c0: int, c1: int, lead: tuple[int, ...] = ()):
    """(chunk coordinate, byte offset, byte size) of the chunks covering a window; size 0 = never written."""
    ch_r, ch_c = dset.chunks[-2:]
    refs = []
    for cr in range((r0 // ch_r) * ch_r, r1, ch_r):
        for cc in range((c0 // ch_c) * ch_c, c1, ch_c):
            info = dset.id.get_chunk_info_by_coord(lead + (cr, cc))
            if info.filter_mask:
                raise ValueError("chunk was written with a filter skipped")
            refs.append((lead + (cr, cc), int(info.byte_offset or 0), int(info.size or 0)))
    return refs


def _merge_ranges(ranges: list[tuple[int, int]], gap: int = _MERGE_GAP) -> list[tuple[int, int]]:
    """Sorted (offset, length) spans with near neighbours joined, to save requests."""
    spans: list[list[int]] = []
    for offset, length in sorted(set(ranges)):
        if spans and offset <= spans[-1][0] + spans[-1][1] + gap:
            spans[-1][1] = max(spans[-1][1], offset + length - spans[-1][0])
        else:
            spans.append([offset, length])
    return [(a, b) for a, b in spans]


def _fetch_exact(raw, ranges: list[tuple[int, int]], workers: int = PREFETCH_WORKERS):
    """Fetch byte ranges of the granule concurrently. Returns ({(offset, length): bytes}, io statistics).

    Uses the signed link the RangeFile already resolved; it is never logged or returned.
    """
    spans = _merge_ranges(ranges)
    session = data_session()  # shared and kept open: no new connections per granule
    seconds = [0.0]

    def get(span: tuple[int, int]) -> bytes:
        offset, length = span
        header = {"Range": f"bytes={offset}-{offset + length - 1}"}
        for attempt in range(3):
            t0 = time.time()
            try:
                r = session.get(raw._link.url, headers=header, timeout=(20, 180))  # noqa: SLF001
            except requests.RequestException:
                if attempt == 2:
                    raise RemoteAccessError("network error while reading the granule") from None
                time.sleep(0.5 * (attempt + 1))
                continue
            if r.status_code == 206 and len(r.content) == length:
                seconds[0] += time.time() - t0  # approximate under threads: used for reporting only
                return r.content
            if r.status_code in (401, 403):  # signed link expired: resolve again and retry
                raw._link = _resolve(raw.data_url, force=True)  # noqa: SLF001
                continue
            if attempt == 2:
                raise RemoteAccessError(f"unexpected response while reading the granule (HTTP {r.status_code})")
            time.sleep(0.5 * (attempt + 1))
        raise RemoteAccessError("could not read the granule")

    if len(spans) > 1:
        with ThreadPoolExecutor(max_workers=min(workers, len(spans))) as pool:
            blobs = list(pool.map(get, spans))
    else:
        blobs = [get(span) for span in spans]
    out: dict[tuple[int, int], bytes] = {}
    for offset, length in set(ranges):
        for (start, size), blob in zip(spans, blobs):
            if start <= offset and offset + length <= start + size:
                out[(offset, length)] = blob[offset - start : offset - start + length]
                break
    stats = {"requests": len(spans), "bytes": sum(len(b) for b in blobs), "network_seconds": seconds[0]}
    return out, stats


def _read_exact(raw, datasets: dict, window: tuple[int, int, int, int], geometry: _GeometryPoint | None):
    """Read a window of several 2-D datasets, and the geometry sample, with exact-range chunk requests."""
    r0, r1, c0, c1 = window
    if not all(_decodable(d) and d.ndim == 2 for d in datasets.values()):
        raise ValueError("a layer uses a storage layout this reader does not decode")
    refs = {name: _chunk_refs(dset, r0, r1, c0, c1) for name, dset in datasets.items()}
    cube_sets = {}
    if geometry is not None:
        cube_sets = {name: geometry.cube[name] for name in geometry.NAMES}
        if not all(_decodable(d) and d.ndim == 3 for d in cube_sets.values()):
            raise ValueError("the geometry cubes use a storage layout this reader does not decode")
        for name, dset in cube_sets.items():
            refs[f"cube:{name}"] = _chunk_refs(dset, geometry.i, geometry.i + 1, geometry.j, geometry.j + 1, (geometry.k,))
    blobs, stats = _fetch_exact(raw, [(o, s) for items in refs.values() for _, o, s in items if s])

    arrays: dict[str, np.ndarray] = {}
    for name, dset in datasets.items():
        ch_r, ch_c = dset.chunks
        out = np.full((r1 - r0, c1 - c0), dset.fillvalue, dtype=dset.dtype)  # unwritten chunks read as the fill
        for (cr, cc), offset, size in refs[name]:
            if not size:
                continue
            block = _decode_chunk(blobs[(offset, size)], dset)
            rs, re, cs, ce = max(cr, r0), min(cr + ch_r, r1), max(cc, c0), min(cc + ch_c, c1)
            out[rs - r0 : re - r0, cs - c0 : ce - c0] = block[rs - cr : re - cr, cs - cc : ce - cc]
        arrays[name] = out

    look = (None, None)
    if geometry is not None:
        samples = []
        for name, dset in cube_sets.items():
            (coord, offset, size), = refs[f"cube:{name}"]
            if not size:
                samples.append(float("nan"))
                continue
            block = _decode_chunk(blobs[(offset, size)], dset)
            samples.append(float(block[0, geometry.i - coord[1], geometry.j - coord[2]]))
        look = geometry.values(*samples)
    return arrays, look, stats


def _read_blocks(raw, datasets: dict, window: tuple[int, int, int, int], geometry: _GeometryPoint | None):
    """The same read through h5py and RangeFile's 4 MiB block cache (slower: whole blocks are transferred)."""
    r0, r1, c0, c1 = window
    ranges = {name: _chunk_ranges(dset, r0, r1, c0, c1) for name, dset in datasets.items()}
    arrays: dict[str, np.ndarray] = {}
    look = (None, None)
    first = True
    for batch in _batches(ranges):
        wanted_ranges = [r for name in batch for r in ranges[name]]
        if first and geometry is not None:
            for name in geometry.NAMES:
                wanted_ranges += _chunk_ranges(
                    geometry.cube[name], geometry.i, geometry.i + 1, geometry.j, geometry.j + 1, lead=(geometry.k,)
                )
        raw.prefetch(wanted_ranges, workers=PREFETCH_WORKERS)
        if first and geometry is not None:
            look = geometry.values(
                *(float(geometry.cube[name][geometry.k, geometry.i, geometry.j]) for name in geometry.NAMES)
            )
        first = False
        for name in batch:
            arrays[name] = datasets[name][r0:r1, c0:c1]
    return arrays, look


# -------------------------------------------------------------------- reader


def read_window(
    granule: Granule,
    bbox: tuple[float, float, float, float],
    *,
    polarization: str | None = None,
    freq: str = "A",
    layers: tuple[str, ...] = DEFAULT_LAYERS,
    with_mask: bool = True,
    use_cache: bool = True,
    max_pixels: int = MAX_WINDOW_PIXELS,
    exact_ranges: bool = True,
) -> GunwCutout:
    """Read the pixels of one GUNW pair that fall inside a lon/lat box (80 m posting).

    Only the stored chunks that cover the window are transferred, requested concurrently
    (``exact_ranges=False`` forces the slower path through h5py's 4 MiB blocks, which is also the fallback).
    Layers the granule does not carry are skipped silently; check ``cutout.layers``. ``polarization=None``
    takes the first one the file lists.
    """
    pol_key = polarization or "auto"
    wanted = tuple(layers) + (("mask",) if with_mask else ())
    cache = _cache_path(granule.granule_id, bbox, wanted, pol_key, freq)
    if use_cache and cache.exists():
        return _from_cache(cache, granule.granule_id)

    t0 = time.time()
    with RemoteGranule(granule.url) as rg:
        h5 = rg.h5
        grid = h5[GRID_PATH.format(freq=freq)]
        unw = grid["unwrappedInterferogram"]
        available = [name for name in unw if name in ("HH", "VV", "HV", "VH")]
        pol = polarization or (available[0] if available else "HH")
        if pol not in unw:
            raise KeyError(f"this pair has no {pol} interferogram (available: {', '.join(available) or 'none'})")
        group = unw[pol]

        x = group["xCoordinates"][:]
        y = group["yCoordinates"][:]
        proj = group["projection"]
        epsg = int(_text(proj.attrs["epsg_code"])) if "epsg_code" in proj.attrs else int(proj[()])
        r0, r1, c0, c1 = window = _window(x, y, epsg, bbox, max_pixels)

        datasets = {name: group[name] for name in layers if name in group}
        if with_mask and "mask" in unw:
            datasets["mask"] = unw["mask"]
        geometry = _look_geometry(h5, float(x[(c0 + c1 - 1) // 2]), float(y[(r0 + r1 - 1) // 2]))

        exact_stats = None
        if exact_ranges:
            try:
                arrays, (incidence, los), exact_stats = _read_exact(rg.raw, datasets, window, geometry)
            except RemoteAccessError:
                raise
            except Exception:  # noqa: BLE001 - unexpected storage layout: h5py knows how to read it
                exact_stats = None
        if exact_stats is None:
            arrays, (incidence, los) = _read_blocks(rg.raw, datasets, window, geometry)

        out: dict[str, np.ndarray] = {}
        for name, dset in datasets.items():
            if dset.dtype.kind in "ui":  # connectedComponents, mask: keep the integer codes
                out[name] = arrays[name]
                continue
            arr = arrays[name].astype(np.float32)
            fill = _fill_value(dset)
            if fill is not None and np.isfinite(fill):
                arr[arr == fill] = np.nan
            arr[~np.isfinite(arr)] = np.nan
            out[name] = arr

        ident = h5[ID_PATH]
        baseline_path = f"{META_PATH}/orbit/temporalBaseline"
        params = f"{META_PATH}/processingInformation/parameters/unwrappedInterferogram/frequency{freq}"
        looks = None
        if f"{params}/numberOfRangeLooks" in h5 and f"{params}/numberOfAzimuthLooks" in h5:
            looks = (int(h5[f"{params}/numberOfRangeLooks"][()]), int(h5[f"{params}/numberOfAzimuthLooks"][()]))
        meta = {
            "polarization": pol,
            "center_frequency_hz": float(grid["centerFrequency"][()]),
            "look_direction": _text(ident["lookDirection"][()]) if "lookDirection" in ident else "",
            "pass_direction": _text(ident["orbitPassDirection"][()]) if "orbitPassDirection" in ident else "",
            "reference_start": _text(ident["referenceZeroDopplerStartTime"][()])[:19]
            if "referenceZeroDopplerStartTime" in ident else "",
            "secondary_start": _text(ident["secondaryZeroDopplerStartTime"][()])[:19]
            if "secondaryZeroDopplerStartTime" in ident else "",
            "temporal_baseline_days": int(h5[baseline_path][()]) if baseline_path in h5 else None,
            "looks": looks,
            "incidence_deg": incidence,
            "los_enu": los,
        }
        io_stats = rg.raw.stats()  # metadata pages (and everything, on the block path)
        io_stats["mode"] = "blocks"
        if exact_stats is not None:
            fetched = rg.raw.bytes_fetched + exact_stats["bytes"]
            io_stats = {
                "requests": rg.raw.requests_made + exact_stats["requests"],
                "megabytes": round(fetched / 1e6, 1),
                "fraction_of_file": round(fetched / rg.raw.size, 5) if rg.raw.size else None,
                "network_seconds": round(rg.raw.network_seconds + exact_stats["network_seconds"], 2),
                "mode": "chunks",
            }
        file_gb = round(rg.raw.size / 1e9, 2)

    yw = y[r0:r1]
    if len(yw) > 1 and yw[0] < yw[-1]:  # make north-up
        yw = yw[::-1]
        out = {k: v[::-1] for k, v in out.items()}
    cut = GunwCutout(
        granule_id=granule.granule_id,
        layers=out,
        x=x[c0:c1],
        y=yw,
        epsg=epsg,
        rows=(r0, r1),
        cols=(c0, c1),
        seconds=round(time.time() - t0, 2),
        io=io_stats,
        **meta,
    )
    cut.first_read = {"megabytes": io_stats.get("megabytes", 0.0), "requests": io_stats.get("requests", 0),
                      "seconds": cut.seconds, "file_gb": file_gb}
    if use_cache:
        np.savez_compressed(
            cache,
            x=cut.x,
            y=cut.y,
            epsg=np.int64(epsg),
            rows=np.array(cut.rows),
            cols=np.array(cut.cols),
            first_read=np.array(json.dumps(cut.first_read)),
            meta=np.array(json.dumps(meta)),
            **{f"L_{k}": v for k, v in out.items()},
        )
    return cut

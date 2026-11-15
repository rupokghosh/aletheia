"""Windowed reads of NISAR L2 GCOV (geocoded polarimetric covariance) backscatter grids."""

from __future__ import annotations

import hashlib
import json
import threading
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass, field

import numpy as np
from pyproj import Transformer

from . import config, remote
from .remote import RemoteAccessError, RemoteGranule
from .schemas import Granule

GRID_PATH = "/science/LSAR/GCOV/grids/frequency{freq}"
POL_TO_LAYER = {"HH": "HHHH", "HV": "HVHV", "VH": "VHVH", "VV": "VVVV"}
# Per-pixel validity layer of the product: the sub-swath number (1 to 5) of samples built from fully focused
# radar data, 0 where they are not (swath edges, transmit gaps) and 255 outside the swath. Samples flagged 0
# still carry numbers (down to 1e-14 in power), so they must be masked explicitly.
MASK_LAYER = "mask"
_MASK_INVALID = (0, 255)
# Where every GCOV granule keeps what a read needs first: the superblock and first object headers, and the
# two coordinate arrays at the start of the first data page (traced on several granules). These are fetched
# side by side on opening; the HDF5 library would otherwise ask for them one after another.
_OPENING_OFFSETS = (0, 1024 * 1024, 4 * 1024 * 1024)


class OutsideFrame(ValueError):
    """The requested box does not intersect this granule's grid."""


class WindowTooLarge(ValueError):
    """The requested box needs more pixels than a single request may read."""


@dataclass
class Cutout:
    """A window of one granule. Arrays are (rows, cols), north-up, linear power (gamma0), NaN for no data."""

    granule_id: str
    layers: dict[str, np.ndarray]
    x: np.ndarray  # pixel-centre eastings (m)
    y: np.ndarray  # pixel-centre northings (m), descending
    epsg: int
    rows: tuple[int, int]
    cols: tuple[int, int]
    seconds: float = 0.0
    io: dict = field(default_factory=dict)
    from_cache: bool = False
    # what it took to get this window out of NASA's archive the first time (megabytes, requests, seconds,
    # file_gb); kept with the cached window so a cached result can still say what it cost
    first_read: dict = field(default_factory=dict)

    @property
    def shape(self) -> tuple[int, int]:
        return (len(self.y), len(self.x))

    @property
    def pixel_size(self) -> tuple[float, float]:
        dx = float(abs(self.x[1] - self.x[0])) if len(self.x) > 1 else 10.0
        dy = float(abs(self.y[1] - self.y[0])) if len(self.y) > 1 else 10.0
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


def _window(x: np.ndarray, y: np.ndarray, epsg: int, bbox: tuple[float, float, float, float]):
    west, south, east, north = bbox
    tr = Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True)
    xs, ys = tr.transform([west, east, west, east], [south, south, north, north])
    cols = np.where((x >= min(xs)) & (x <= max(xs)))[0]
    rows = np.where((y >= min(ys)) & (y <= max(ys)))[0]
    if len(cols) == 0 or len(rows) == 0:
        raise OutsideFrame("the requested box is outside this granule")
    r0, r1, c0, c1 = int(rows.min()), int(rows.max()) + 1, int(cols.min()), int(cols.max()) + 1
    if (r1 - r0) * (c1 - c0) > config.MAX_WINDOW_PIXELS:
        raise WindowTooLarge(
            f"the box needs {(r1 - r0) * (c1 - c0):,} pixels; the limit is {config.MAX_WINDOW_PIXELS:,}. "
            "Draw a smaller area."
        )
    return r0, r1, c0, c1


def _chunk_ranges(dset, r0: int, r1: int, c0: int, c1: int) -> list[tuple[int, int]]:
    """Byte ranges of the stored chunks that cover a window, so they can be fetched concurrently."""
    if not dset.chunks:
        return []
    ch_r, ch_c = dset.chunks
    ranges = []
    for cr in range((r0 // ch_r) * ch_r, r1, ch_r):
        for cc in range((c0 // ch_c) * ch_c, c1, ch_c):
            try:
                info = dset.id.get_chunk_info_by_coord((cr, cc))
            except Exception:  # noqa: BLE001 - older HDF5 builds: fall back to sequential reads
                return []
            if info.byte_offset is not None and info.size:
                ranges.append((int(info.byte_offset), int(info.size)))
    return ranges


def _cache_path(granule_id: str, bbox, layers: tuple[str, ...], freq: str):
    # "v2": windows cached before the validity mask was applied must not be reused
    key = f"v2|{granule_id}|{freq}|{','.join(f'{v:.5f}' for v in bbox)}|{','.join(layers)}"
    digest = hashlib.sha1(key.encode()).hexdigest()[:20]
    path = config.cache_dir() / "windows"
    path.mkdir(parents=True, exist_ok=True)
    return path / f"{digest}.npz"


def _read_layers(raw, datasets: dict, window: tuple[int, int, int, int]) -> tuple[dict[str, np.ndarray], dict | None]:
    """The window of each dataset, with the statistics of the exact-range requests (None on the block path).

    The chunks under the window are asked for as exact byte ranges, all at once, and decoded here. Reading
    them through h5py instead costs whole blocks per chunk: measured on a 10 km window, 38 MB for 12 MB of
    chunks. That path remains as the fallback for a storage layout the decoder does not know.
    """
    from . import gunw  # here, not at the top: gunw imports this module

    r0, r1, c0, c1 = window
    try:
        arrays, _, stats = gunw._read_exact(raw, datasets, window, None)  # noqa: SLF001
        return arrays, stats
    except RemoteAccessError:
        raise
    except Exception:  # noqa: BLE001 - unexpected storage layout: h5py knows how to read it
        pass
    ranges: list[tuple[int, int]] = []
    for dset in datasets.values():
        ranges += _chunk_ranges(dset, r0, r1, c0, c1)
    raw.prefetch(ranges)
    return {name: dset[r0:r1, c0:c1] for name, dset in datasets.items()}, None


def read_window(
    granule: Granule,
    bbox: tuple[float, float, float, float],
    polarizations: tuple[str, ...] = ("HH", "HV"),
    *,
    freq: str = "A",
    use_cache: bool = True,
) -> Cutout:
    """Read the pixels of one GCOV granule that fall inside a lon/lat box.

    Only the file's metadata and the chunks under the box are transferred (typically a quarter of one
    percent of the file). Polarizations the granule does not carry are skipped silently; check
    ``cutout.layers``.
    """
    layers = tuple(POL_TO_LAYER[p] for p in polarizations if p in POL_TO_LAYER)
    cache = _cache_path(granule.granule_id, bbox, layers, freq)
    if use_cache and cache.exists():
        z = np.load(cache)
        return Cutout(
            granule_id=granule.granule_id,
            layers={k[2:]: z[k] for k in z.files if k.startswith("L_")},
            x=z["x"],
            y=z["y"],
            epsg=int(z["epsg"]),
            rows=tuple(int(v) for v in z["rows"]),
            cols=tuple(int(v) for v in z["cols"]),
            from_cache=True,
            first_read=json.loads(str(z["first_read"])) if "first_read" in z.files else {},
        )

    t0 = time.time()
    with RemoteGranule(granule.url, warm=_OPENING_OFFSETS) as rg:
        grid = rg.h5[GRID_PATH.format(freq=freq)]
        x = grid["xCoordinates"][:]
        y = grid["yCoordinates"][:]
        proj = grid["projection"]
        epsg = int(proj.attrs["epsg_code"]) if "epsg_code" in proj.attrs else int(proj[()])
        r0, r1, c0, c1 = _window(x, y, epsg, bbox)

        present = [name for name in layers if name in grid]
        has_mask = MASK_LAYER in grid
        wanted = present + ([MASK_LAYER] if has_mask else [])
        arrays, exact = _read_layers(rg.raw, {name: grid[name] for name in wanted}, (r0, r1, c0, c1))

        invalid = np.isin(arrays[MASK_LAYER], _MASK_INVALID) if has_mask else None
        out: dict[str, np.ndarray] = {}
        for name in present:
            arr = arrays[name].astype(np.float32)
            fill = grid[name].fillvalue
            if fill is not None and np.isfinite(fill):
                arr[arr == fill] = np.nan
            arr[~np.isfinite(arr) | (arr <= 0)] = np.nan
            if invalid is not None:
                arr[invalid] = np.nan
            out[name] = arr
        io_stats = rg.raw.stats()  # the metadata blocks (and everything, on the block path)
        if exact is not None:
            fetched = rg.raw.bytes_fetched + exact["bytes"]
            io_stats = {
                "requests": rg.raw.requests_made + exact["requests"],
                "megabytes": round(fetched / 1e6, 1),
                "fraction_of_file": round(fetched / rg.raw.size, 5) if rg.raw.size else None,
                "network_seconds": round(rg.raw.network_seconds + exact["network_seconds"], 2),
            }
        file_gb = round(rg.raw.size / 1e9, 2)

    yw = y[r0:r1]
    if len(yw) > 1 and yw[0] < yw[-1]:  # make north-up
        yw = yw[::-1]
        out = {k: v[::-1] for k, v in out.items()}
    seconds = round(time.time() - t0, 2)
    first_read = {"megabytes": io_stats.get("megabytes", 0.0), "requests": io_stats.get("requests", 0),
                  "seconds": seconds, "file_gb": file_gb}
    cut = Cutout(
        granule_id=granule.granule_id,
        layers=out,
        x=x[c0:c1],
        y=yw,
        epsg=epsg,
        rows=(r0, r1),
        cols=(c0, c1),
        seconds=seconds,
        io=io_stats,
        first_read=first_read,
    )
    if use_cache:
        np.savez_compressed(
            cache,
            x=cut.x,
            y=cut.y,
            epsg=np.int64(epsg),
            rows=np.array(cut.rows),
            cols=np.array(cut.cols),
            first_read=np.array(json.dumps(first_read)),
            **{f"L_{k}": v for k, v in out.items()},
        )
    return cut


def _read_one(args) -> Cutout | Exception:
    granule, bbox, pols, freq, use_cache, signed = args
    try:
        if signed is not None:
            remote.seed_link(granule.url, signed)  # resolved by the calling process: no login here
        return read_window(granule, bbox, pols, freq=freq, use_cache=use_cache)
    except Exception as exc:  # noqa: BLE001 - returned to the caller, one bad date must not sink a series
        return exc


# Reader processes are started once and kept: starting them (and importing numpy, h5py and pyproj in each)
# costs about a second, which used to be paid by every request.
_readers: ProcessPoolExecutor | None = None
_readers_lock = threading.Lock()


def _reader_pool(fresh: bool = False) -> ProcessPoolExecutor:
    global _readers
    with _readers_lock:
        if fresh and _readers is not None:
            _readers.shutdown(wait=False, cancel_futures=True)
            _readers = None
        if _readers is None:
            _readers = ProcessPoolExecutor(max_workers=config.READ_PROCESSES)
        return _readers


def _ready(_: int) -> bool:
    time.sleep(0.25)  # long enough that every process of the pool takes one of these
    return True


def warm_readers() -> None:
    """Start the reader processes ahead of the first request. Safe to call from a background thread."""
    if config.READ_PROCESSES <= 1:
        return
    try:
        list(_reader_pool().map(_ready, range(config.READ_PROCESSES)))
    except (OSError, RuntimeError):
        pass


def read_windows(
    granules: list[Granule],
    bbox: tuple[float, float, float, float],
    polarizations: tuple[str, ...] = ("HH", "HV"),
    *,
    freq: str = "A",
    use_cache: bool = True,
    max_workers: int = 6,
) -> list[Cutout | Exception]:
    """Read the same window from many granules. Uses processes because h5py serialises reads in one process.

    Returns one item per granule, in order: a Cutout, or the exception that granule raised.
    """
    jobs = [(g, bbox, polarizations, freq, use_cache, None) for g in granules]
    # Windows already on disk are loaded here: starting worker processes for them costs seconds, not milliseconds.
    layers = tuple(POL_TO_LAYER[p] for p in polarizations if p in POL_TO_LAYER)
    results: dict[int, Cutout | Exception] = {}
    for i, job in enumerate(jobs):
        if use_cache and _cache_path(job[0].granule_id, bbox, layers, freq).exists():
            results[i] = _read_one(job)
    todo = [i for i in range(len(jobs)) if i not in results]
    if len(todo) <= 1 or max_workers <= 1:
        fetched = [_read_one(jobs[i]) for i in todo]
    elif config.READ_PROCESSES <= 1:
        # No reader processes (a hosted function): a few threads instead. h5py lets one thread at a time read
        # a file's metadata, but the pixel data is fetched outside it, so the downloads still overlap.
        remote.resolve_many([jobs[i][0].url for i in todo])
        with ThreadPoolExecutor(max_workers=min(4, len(todo))) as pool:
            fetched = list(pool.map(_read_one, [jobs[i] for i in todo]))
    else:
        # The login happens here, once and side by side, so that no reader process has to do it.
        links = remote.resolve_many([jobs[i][0].url for i in todo])
        sent = [(*jobs[i][:5], links.get(jobs[i][0].url)) for i in todo]
        try:
            try:
                fetched = list(_reader_pool().map(_read_one, sent))
            except BrokenProcessPool:  # a reader process died: start a new set and try once more
                fetched = list(_reader_pool(fresh=True).map(_read_one, sent))
        except (OSError, RuntimeError):  # environments without process support
            fetched = [_read_one(jobs[i]) for i in todo]
    results.update(zip(todo, fetched))
    return [results[i] for i in range(len(jobs))]

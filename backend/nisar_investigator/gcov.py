"""Windowed reads of NISAR L2 GCOV (geocoded polarimetric covariance) backscatter grids."""

from __future__ import annotations

import hashlib
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field

import numpy as np
from pyproj import Transformer

from . import config
from .remote import RemoteGranule
from .schemas import Granule

GRID_PATH = "/science/LSAR/GCOV/grids/frequency{freq}"
POL_TO_LAYER = {"HH": "HHHH", "HV": "HVHV", "VH": "VHVH", "VV": "VVVV"}


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
    key = f"{granule_id}|{freq}|{','.join(f'{v:.5f}' for v in bbox)}|{','.join(layers)}"
    digest = hashlib.sha1(key.encode()).hexdigest()[:20]
    path = config.cache_dir() / "windows"
    path.mkdir(parents=True, exist_ok=True)
    return path / f"{digest}.npz"


def read_window(
    granule: Granule,
    bbox: tuple[float, float, float, float],
    polarizations: tuple[str, ...] = ("HH", "HV"),
    *,
    freq: str = "A",
    use_cache: bool = True,
) -> Cutout:
    """Read the pixels of one GCOV granule that fall inside a lon/lat box.

    Only the HDF5 pages holding the needed chunks are transferred (typically under 1% of the file).
    Polarizations the granule does not carry are skipped silently; check ``cutout.layers``.
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
        )

    t0 = time.time()
    with RemoteGranule(granule.url) as rg:
        grid = rg.h5[GRID_PATH.format(freq=freq)]
        x = grid["xCoordinates"][:]
        y = grid["yCoordinates"][:]
        proj = grid["projection"]
        epsg = int(proj.attrs["epsg_code"]) if "epsg_code" in proj.attrs else int(proj[()])
        r0, r1, c0, c1 = _window(x, y, epsg, bbox)

        present = [name for name in layers if name in grid]
        ranges: list[tuple[int, int]] = []
        for name in present:
            ranges += _chunk_ranges(grid[name], r0, r1, c0, c1)
        rg.raw.prefetch(ranges)

        out: dict[str, np.ndarray] = {}
        for name in present:
            dset = grid[name]
            arr = dset[r0:r1, c0:c1].astype(np.float32)
            fill = dset.fillvalue
            if fill is not None and np.isfinite(fill):
                arr[arr == fill] = np.nan
            arr[~np.isfinite(arr) | (arr <= 0)] = np.nan
            out[name] = arr
        io_stats = rg.raw.stats()

    yw = y[r0:r1]
    if len(yw) > 1 and yw[0] < yw[-1]:  # make north-up
        yw = yw[::-1]
        out = {k: v[::-1] for k, v in out.items()}
    cut = Cutout(
        granule_id=granule.granule_id,
        layers=out,
        x=x[c0:c1],
        y=yw,
        epsg=epsg,
        rows=(r0, r1),
        cols=(c0, c1),
        seconds=round(time.time() - t0, 2),
        io=io_stats,
    )
    if use_cache:
        np.savez_compressed(
            cache,
            x=cut.x,
            y=cut.y,
            epsg=np.int64(epsg),
            rows=np.array(cut.rows),
            cols=np.array(cut.cols),
            **{f"L_{k}": v for k, v in out.items()},
        )
    return cut


def _read_one(args) -> Cutout | Exception:
    granule, bbox, pols, freq, use_cache = args
    try:
        return read_window(granule, bbox, pols, freq=freq, use_cache=use_cache)
    except Exception as exc:  # noqa: BLE001 - returned to the caller, one bad date must not sink a series
        return exc


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
    jobs = [(g, bbox, polarizations, freq, use_cache) for g in granules]
    if len(jobs) <= 1 or max_workers <= 1:
        return [_read_one(j) for j in jobs]
    try:
        with ProcessPoolExecutor(max_workers=min(max_workers, len(jobs))) as pool:
            return list(pool.map(_read_one, jobs))
    except (OSError, RuntimeError):  # environments without process support
        return [_read_one(j) for j in jobs]

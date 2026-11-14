"""Small, well-defined array operations shared by every workflow."""

from __future__ import annotations

import numpy as np
from scipy import ndimage

# Below this level (dB, gamma0) a pixel is treated as dominated by instrument noise. Measured on NISAR
# 40 MHz dual-pol data over calm water: HV sits near -22 dB and HH near -17 dB. Workflows should prefer
# estimating the floor from the data (see noise_floor_db) and fall back to these.
DEFAULT_NOISE_FLOOR_DB = {"HH": -17.0, "VV": -17.0, "HV": -22.0, "VH": -22.0}


def multilook(power: np.ndarray, size: int = 5) -> np.ndarray:
    """Box average in linear power that ignores no-data pixels.

    scipy's uniform_filter uses a running sum, so a single NaN poisons everything after it on the line.
    Averaging value and validity separately avoids that.
    """
    a = np.asarray(power, dtype=np.float64)
    valid = np.isfinite(a) & (a > 0)
    num = ndimage.uniform_filter(np.where(valid, a, 0.0), size=size, mode="nearest")
    den = ndimage.uniform_filter(valid.astype(np.float64), size=size, mode="nearest")
    with np.errstate(invalid="ignore", divide="ignore"):
        out = num / den
    out[den < 0.2] = np.nan
    return out


def to_db(power: np.ndarray) -> np.ndarray:
    with np.errstate(invalid="ignore", divide="ignore"):
        out = 10.0 * np.log10(np.asarray(power, dtype=np.float64))
    out[~np.isfinite(out)] = np.nan
    return out


def from_db(db: np.ndarray | float) -> np.ndarray | float:
    return 10.0 ** (np.asarray(db, dtype=np.float64) / 10.0)


def mean_db(power: np.ndarray, mask: np.ndarray | None = None) -> tuple[float, float, int]:
    """Mean backscatter of a region, averaged in linear power then expressed in dB.

    Returns (mean_db, spread_db, n_pixels). The spread is the standard deviation, in dB, of 5x5-multilooked
    values inside the region: it describes spatial variability, not measurement error.
    """
    a = np.asarray(power, dtype=np.float64)
    sel = np.isfinite(a) & (a > 0)
    if mask is not None:
        sel &= mask
    n = int(sel.sum())
    if n == 0:
        return float("nan"), float("nan"), 0
    mean = float(10.0 * np.log10(a[sel].mean()))
    smooth = to_db(multilook(a, 5))
    spread = float(np.nanstd(smooth[sel]))
    return mean, spread, n


def noise_floor_db(db: np.ndarray, polarization: str) -> float:
    """Estimate the noise floor as the darkest stable level in the scene (1st percentile + 0.5 dB),
    never lower than 4 dB under the documented default for the polarization."""
    default = DEFAULT_NOISE_FLOOR_DB.get(polarization, -20.0)
    finite = db[np.isfinite(db)]
    if finite.size < 100:
        return default
    estimate = float(np.percentile(finite, 1)) + 0.5
    return float(np.clip(estimate, default - 4.0, default + 2.0))


def polygon_mask(geometry: dict, x: np.ndarray, y: np.ndarray, epsg: int) -> np.ndarray:
    """Rasterise a GeoJSON Polygon (lon/lat) onto a grid of pixel centres. Holes are respected."""
    from PIL import Image, ImageDraw
    from pyproj import Transformer

    tr = Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True)
    dx = float(x[1] - x[0]) if len(x) > 1 else 10.0
    dy = float(y[1] - y[0]) if len(y) > 1 else -10.0  # negative for north-up grids
    img = Image.new("L", (len(x), len(y)), 0)
    draw = ImageDraw.Draw(img)
    for i, ring in enumerate(geometry["coordinates"]):
        px, py = tr.transform([p[0] for p in ring], [p[1] for p in ring])
        cols = (np.asarray(px) - float(x[0])) / dx
        rows = (np.asarray(py) - float(y[0])) / dy
        draw.polygon(list(zip(cols.tolist(), rows.tolist())), fill=1 if i == 0 else 0)
    return np.asarray(img, dtype=bool)


def area_km2(mask: np.ndarray, pixel_area_km2: float) -> float:
    return float(np.count_nonzero(mask)) * pixel_area_km2

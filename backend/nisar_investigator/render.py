"""Turn arrays into things people can open: PNG overlays for the map, GeoTIFF and CSV for download."""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np
from PIL import Image

# Colormaps as control points (position 0..1, r, g, b). Linear interpolation in between.
COLORMAPS: dict[str, list[tuple[float, int, int, int]]] = {
    "grey": [(0.0, 0, 0, 0), (1.0, 255, 255, 255)],
    # diverging, colour-blind safe: blue = decrease, white = no change, red = increase
    "RdBu": [(0.0, 33, 102, 172), (0.25, 103, 169, 207), (0.5, 247, 247, 247), (0.75, 239, 138, 98), (1.0, 178, 24, 43)],
    # sequential, perceptually ordered
    "viridis": [(0.0, 68, 1, 84), (0.25, 59, 82, 139), (0.5, 33, 145, 140), (0.75, 94, 201, 98), (1.0, 253, 231, 37)],
    "magma": [(0.0, 0, 0, 4), (0.25, 81, 18, 124), (0.5, 183, 55, 121), (0.75, 252, 137, 97), (1.0, 252, 253, 191)],
}


def _lut(name: str) -> np.ndarray:
    pts = COLORMAPS[name]
    pos = np.array([p[0] for p in pts])
    out = np.zeros((256, 3), dtype=np.uint8)
    t = np.linspace(0, 1, 256)
    for ch in range(3):
        out[:, ch] = np.interp(t, pos, [p[1 + ch] for p in pts]).round().astype(np.uint8)
    return out


def colorize(
    values: np.ndarray, vmin: float, vmax: float, colormap: str = "grey", alpha: np.ndarray | float = 1.0
) -> np.ndarray:
    """Map a 2-D array to RGBA uint8. NaN becomes fully transparent."""
    v = np.asarray(values, dtype=np.float64)
    finite = np.isfinite(v)
    scaled = np.clip((np.where(finite, v, vmin) - vmin) / max(vmax - vmin, 1e-12), 0, 1)
    rgb = _lut(colormap)[(scaled * 255).round().astype(np.uint8)]
    a = np.broadcast_to(np.asarray(alpha, dtype=np.float64), v.shape)
    rgba = np.dstack([rgb, (np.clip(a, 0, 1) * 255 * finite).round().astype(np.uint8)])
    return rgba


def save_png(path: Path, rgba: np.ndarray) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgba, mode="RGBA").save(path, optimize=True)
    return path


def save_class_png(path: Path, classes: np.ndarray, colors: dict[int, tuple[int, int, int, int]]) -> Path:
    """Categorical overlay. `classes` holds integer codes; codes missing from `colors` are transparent."""
    rgba = np.zeros(classes.shape + (4,), dtype=np.uint8)
    for code, color in colors.items():
        rgba[classes == code] = color
    return save_png(path, rgba)


def save_geotiff(path: Path, values: np.ndarray, geotransform: tuple, epsg: int) -> Path:
    """Write a single-band float32 GeoTIFF (north-up, projected CRS) using only Pillow.

    The georeferencing is carried in the three standard GeoTIFF tags.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    x0, dx, _, y0, _, neg_dy = geotransform
    img = Image.fromarray(np.asarray(values, dtype=np.float32), mode="F")
    tags = {
        33550: (float(dx), float(abs(neg_dy)), 0.0),  # ModelPixelScaleTag
        33922: (0.0, 0.0, 0.0, float(x0), float(y0), 0.0),  # ModelTiepointTag
        # GeoKeyDirectoryTag: version 1.1.0, 3 keys: projected model, pixel-is-area, EPSG code
        34735: (1, 1, 0, 3, 1024, 0, 1, 1, 1025, 0, 1, 1, 3072, 0, 1, int(epsg)),
        42113: "nan",  # GDAL_NODATA
    }
    from PIL.TiffImagePlugin import ImageFileDirectory_v2

    ifd = ImageFileDirectory_v2()
    for tag, value in tags.items():
        ifd[tag] = value
    ifd.tagtype[33550] = 12  # DOUBLE
    ifd.tagtype[33922] = 12
    ifd.tagtype[34735] = 3  # SHORT
    ifd.tagtype[42113] = 2  # ASCII
    img.save(path, format="TIFF", tiffinfo=ifd, compression="tiff_deflate")
    return path


def save_csv(path: Path, header: list[str], rows: list[list]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    return path

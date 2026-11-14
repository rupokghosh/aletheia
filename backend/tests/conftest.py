"""Shared builders for tests that run the workflows on made-up arrays instead of the archive."""

from __future__ import annotations

import numpy as np
import pytest
from pyproj import Transformer

from nisar_investigator import gcov
from nisar_investigator.schemas import Granule

EPSG = 32611
X0, Y0 = 500_000.0, 5_600_000.0  # top-left corner, on the central meridian of UTM zone 11


def make_granule(
    date: str,
    track: int = 77,
    direction: str = "ascending",
    frame: int = 27,
    tier: str = "provisional",
    polarizations: tuple[str, ...] = ("HH", "HV"),
) -> Granule:
    stamp = date.replace("-", "")
    name = (
        f"NISAR_L2_PR_GCOV_001_{track:03d}_{direction[0].upper()}_{frame:03d}_4005_DHDH_A_"
        f"{stamp}T000000_{stamp}T000030_P05023_N_F_J_001"
    )
    return Granule(
        granule_id=name,
        product="GCOV",
        tier=tier,
        url=f"https://example.invalid/{name}.h5",
        track=track,
        frame=frame,
        direction=direction,
        mode="4005",
        polarizations=list(polarizations),
        date=date,
        start_time=f"{date}T00:00:00Z",
    )


def make_cutout(layers: dict[str, np.ndarray], granule_id: str = "granule") -> gcov.Cutout:
    """A cutout on a 10 m grid. Keys are polarizations ("HH"); values are linear power."""
    rows, cols = next(iter(layers.values())).shape
    return gcov.Cutout(
        granule_id=granule_id,
        layers={gcov.POL_TO_LAYER[p]: np.asarray(a, dtype=np.float32) for p, a in layers.items()},
        x=X0 + 5.0 + 10.0 * np.arange(cols),
        y=Y0 - 5.0 - 10.0 * np.arange(rows),
        epsg=EPSG,
        rows=(0, rows),
        cols=(0, cols),
    )


def grid_bbox(rows: int, cols: int) -> tuple[float, float, float, float]:
    """A lon/lat box that fits just inside the grid make_cutout builds for this shape."""
    tr = Transformer.from_crs(f"EPSG:{EPSG}", "EPSG:4326", always_xy=True)
    east, south = X0 + 10.0 * cols, Y0 - 10.0 * rows
    lons, lats = tr.transform([X0, east, east, X0], [Y0, Y0, south, south])
    return (max(lons[0], lons[3]), max(lats[2], lats[3]), min(lons[1], lons[2]), min(lats[0], lats[1]))


def speckle(rng: np.random.Generator, level_db: float, shape: tuple[int, int]) -> np.ndarray:
    """Single-look speckle (exponentially distributed power) around a mean level given in dB."""
    return 10.0 ** (level_db / 10.0) * rng.exponential(1.0, shape)


@pytest.fixture
def cache_dir(tmp_path, monkeypatch):
    """Send artifacts and cached windows to a temporary directory."""
    monkeypatch.setenv("NISAR_CACHE_DIR", str(tmp_path))
    return tmp_path

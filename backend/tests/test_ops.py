"""Array operations shared by the workflows. No network."""

from __future__ import annotations

import numpy as np
import pytest

from nisar_investigator import ops


def test_multilook_ignores_nodata_instead_of_spreading_it():
    power = np.full((40, 40), 2.0)
    power[20, 20] = np.nan
    out = ops.multilook(power, 5)
    assert np.isfinite(out).all()
    assert np.allclose(out, 2.0)


def test_multilook_leaves_nodata_where_too_few_pixels_are_valid():
    power = np.full((40, 40), np.nan)
    power[:, :3] = 1.0
    out = ops.multilook(power, 9)
    assert np.isnan(out[:, 30:]).all()
    assert np.allclose(out[:, 0], 1.0)


def test_multilook_averages_power_not_decibels():
    power = np.tile([0.001, 1.0], (20, 10))  # -30 dB and 0 dB side by side
    centre = ops.multilook(power, 2)[10, 10]
    assert centre == pytest.approx(0.5005)  # the dB average would be 0.0316


def test_db_round_trip_and_invalid_values():
    values = np.array([1.0, 0.1, 0.0, -1.0, np.nan])
    db = ops.to_db(values)
    assert db[:2] == pytest.approx([0.0, -10.0])
    assert np.isnan(db[2:]).all()
    assert ops.from_db(db[:2]) == pytest.approx(values[:2])


def test_mean_db_averages_in_linear_power():
    power = np.concatenate([np.full(500, 1.0), np.full(500, 0.01)]).reshape(20, 50)
    mean, spread, n = ops.mean_db(power)
    assert n == 1000
    assert mean == pytest.approx(10 * np.log10(0.505), abs=1e-6)  # not the -10 dB a dB average gives
    assert spread > 0


def test_mean_db_respects_mask_and_nodata():
    power = np.full((30, 30), 0.1)
    power[:, 15:] = 10.0
    power[0, 0] = np.nan
    mask = np.zeros((30, 30), dtype=bool)
    mask[:, :15] = True
    mean, _, n = ops.mean_db(power, mask)
    assert n == 30 * 15 - 1
    assert mean == pytest.approx(-10.0, abs=1e-6)
    assert ops.mean_db(power, np.zeros((30, 30), dtype=bool))[2] == 0


def test_noise_floor_follows_the_darkest_level_within_limits():
    rng = np.random.default_rng(1)
    scene = rng.normal(-10.0, 0.5, (100, 100))
    scene[:20] = rng.normal(-18.0, 0.2, (20, 100))  # a dark, noise-like population
    floor = ops.noise_floor_db(scene, "HH")
    assert -19.0 < floor < -17.5
    # a scene without any dark surface: the estimate is capped 2 dB above the documented default
    assert ops.noise_floor_db(np.full((50, 50), -5.0), "HH") == ops.DEFAULT_NOISE_FLOOR_DB["HH"] + 2.0
    # an implausibly dark scene: capped 4 dB below it
    assert ops.noise_floor_db(np.full((50, 50), -40.0), "HV") == ops.DEFAULT_NOISE_FLOOR_DB["HV"] - 4.0
    # too few pixels to estimate anything
    assert ops.noise_floor_db(np.full((5, 5), -3.0), "HV") == ops.DEFAULT_NOISE_FLOOR_DB["HV"]


def test_at_noise_floor_flags_the_dark_population_only():
    rng = np.random.default_rng(2)
    scene = rng.normal(-9.0, 0.5, (100, 100))
    scene[:30] = rng.normal(-22.0, 0.3, (30, 100))
    scene[50, 50] = np.nan
    mask, floor = ops.at_noise_floor(scene, "HV")
    assert mask[:30].mean() > 0.98
    assert mask[30:].mean() == 0.0
    assert not mask[50, 50]
    assert floor == ops.noise_floor_db(scene, "HV")


def test_robust_sigma_matches_gaussian_spread_and_ignores_tails():
    rng = np.random.default_rng(3)
    values = rng.normal(0.0, 0.8, 200_000)
    assert ops.robust_sigma(values) == pytest.approx(0.8, rel=0.02)
    values[:4000] = 15.0  # 2% of real change must not inflate the no-change spread
    assert ops.robust_sigma(values) == pytest.approx(0.8, rel=0.05)
    assert np.isnan(ops.robust_sigma(np.array([np.nan])))


def test_disk_is_as_wide_as_asked():
    disk = ops.disk(11)
    assert disk.shape == (11, 11)
    assert disk[5].all() and disk[:, 5].all()
    assert not disk[0, 0] and not disk[-1, -1]
    assert np.array_equal(disk, disk.T)


def test_remove_specks_drops_patches_narrower_than_the_disk():
    mask = np.zeros((80, 80), dtype=bool)
    mask[10:19, 10:19] = True  # 9 x 9: what one strong reflector becomes after a 9 x 9 multilook
    mask[40:70, 30:60] = True  # a real 30 x 30 patch
    out = ops.remove_specks(mask, 11)
    assert not out[10:19, 10:19].any()
    assert out[45:65, 35:55].all()
    assert out.sum() <= mask[40:70, 30:60].sum()
    assert np.array_equal(ops.remove_specks(mask, 1), mask)


def test_polygon_mask_and_area_agree():
    x = 500_005.0 + 10.0 * np.arange(200)
    y = 5_599_995.0 - 10.0 * np.arange(200)
    from pyproj import Transformer

    tr = Transformer.from_crs("EPSG:32611", "EPSG:4326", always_xy=True)
    xs, ys = [500_400.0, 501_400.0, 501_400.0, 500_400.0], [5_599_500.0, 5_599_500.0, 5_598_500.0, 5_598_500.0]
    lons, lats = tr.transform(xs, ys)
    ring = [[lon, lat] for lon, lat in zip(lons, lats)] + [[lons[0], lats[0]]]
    geometry = {"type": "Polygon", "coordinates": [ring]}
    mask = ops.polygon_mask(geometry, x, y, 32611)
    area = ops.polygon_area_m2(geometry, 32611)
    assert area == pytest.approx(1_000_000.0, rel=1e-6)
    assert ops.area_km2(mask, 1e-4) == pytest.approx(1.0, rel=0.03)
    assert mask[100, 90] and not mask[10, 10]


def test_polygon_area_subtracts_holes():
    outer = [[0.0, 0.0], [0.01, 0.0], [0.01, 0.01], [0.0, 0.01], [0.0, 0.0]]
    hole = [[0.0025, 0.0025], [0.0075, 0.0025], [0.0075, 0.0075], [0.0025, 0.0075], [0.0025, 0.0025]]
    whole = ops.polygon_area_m2({"type": "Polygon", "coordinates": [outer]}, 32631)
    holed = ops.polygon_area_m2({"type": "Polygon", "coordinates": [outer, hole]}, 32631)
    assert holed == pytest.approx(0.75 * whole, rel=1e-3)

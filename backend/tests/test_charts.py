"""The numbers behind the small charts: binned and summed from the same arrays as the result."""

from __future__ import annotations

import numpy as np

from nisar_investigator import charts

PIXEL_KM2 = 0.0001  # 10 m pixels


def test_change_distribution_accounts_for_every_measurable_pixel():
    rng = np.random.default_rng(1)
    change = rng.normal(0.0, 1.0, (200, 200))
    change[:20, :20] = 9.0  # beyond the limit: counted in the last bin, not dropped
    measurable = np.ones_like(change, dtype=bool)
    measurable[100:, :] = False
    chart = charts.change_distribution(change, measurable, threshold_db=3.0, limit_db=6.0, pixel_area_km2=PIXEL_KM2)
    data = chart.data
    assert chart.kind == "histogram" and len(data["edges"]) == len(data["area_km2"]) + 1
    assert data["edges"][0] == -6.0 and data["edges"][-1] == 6.0 and data["band"] == [-3.0, 3.0]
    assert sum(data["area_km2"]) == np.float64(measurable.sum() * PIXEL_KM2).round(4)
    assert data["area_km2"][-1] >= 400 * PIXEL_KM2 * 0.99


def test_change_distribution_of_nothing_is_no_chart():
    change = np.full((10, 10), np.nan)
    assert charts.change_distribution(change, np.zeros((10, 10), dtype=bool), 3.0, 6.0, PIXEL_KM2) is None


def test_change_shares_add_up_to_the_analysed_area():
    valid = np.ones((100, 100), dtype=bool)
    valid[:, :10] = False
    up = np.zeros_like(valid); up[:10, 10:30] = True
    down = np.zeros_like(valid); down[50:60, 10:20] = True
    dark = np.zeros_like(valid); dark[90:, 10:] = True
    chart = charts.change_shares(valid, up, down, dark, PIXEL_KM2)
    parts = {p["key"]: p["value"] for p in chart.data["parts"]}
    assert chart.data["total"] == round(9000 * PIXEL_KM2, 2)
    assert parts == {"brighter": 0.02, "darker": 0.01, "steady": 0.78, "cannot_tell": 0.09}
    assert round(sum(parts.values()), 2) == chart.data["total"]


def test_motion_profile_follows_the_direction_of_the_gradient():
    x = 500_000 + 80.0 * np.arange(300)
    y = 1_200_000 - 80.0 * np.arange(200)  # rows run north to south
    northing = np.repeat(y[:, None], 300, axis=1)
    los = (northing - y.min()) / (y.max() - y.min()) * 30.0 - 10.0  # -10 cm in the south, +20 cm in the north
    los[:, :5] = np.nan
    chart = charts.motion_profile(los, x, y, noise_cm=1.0)
    data = chart.data
    assert chart.kind == "profile" and (data["start"], data["end"]) == ("south", "north")
    ys = [v for v in data["y"] if v is not None]
    assert ys[0] < -9 and ys[-1] > 19 and all(b >= a for a, b in zip(ys, ys[1:]))
    assert data["x"][0] < 1 and 14 < data["x"][-1] < 16.5  # 200 rows of 80 m are about 16 km
    assert data["band"] == [-1.0, 1.0]


def test_motion_profile_leaves_gaps_where_there_is_no_data():
    x = 80.0 * np.arange(192)
    y = 80.0 * np.arange(96)[::-1]
    los = np.tile(np.linspace(-5, 5, 192), (96, 1))
    los[:, 60:100] = np.nan  # a band of water down the middle
    chart = charts.motion_profile(los, x, y, noise_cm=1.0)
    assert (chart.data["start"], chart.data["end"]) == ("west", "east")
    assert None in chart.data["y"] and chart.data["y"][0] is not None and chart.data["y"][-1] is not None


def test_motion_charts_need_data():
    empty = np.full((50, 50), np.nan)
    assert charts.motion_profile(empty, np.arange(50.0), np.arange(50.0), 1.0) is None
    assert charts.motion_distribution(empty, 1.0, 10.0, 0.0064) is None


def test_motion_distribution_bands_the_noise():
    los = np.random.default_rng(2).normal(0, 2, (100, 100))
    chart = charts.motion_distribution(los, noise_cm=1.5, limit_cm=10.0, pixel_area_km2=0.0064)
    assert chart.data["band"] == [-1.5, 1.5] and chart.data["unit"] == "cm"
    assert abs(sum(chart.data["area_km2"]) - 10_000 * 0.0064) < 0.01

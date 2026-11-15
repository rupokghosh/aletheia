"""Workflow B: aggregation on made-up arrays, the workflow with the archive stubbed out, and one real run."""

from __future__ import annotations

import csv

import numpy as np
import pytest
from conftest import EPSG, X0, Y0, grid_bbox, make_cutout, make_granule, speckle
from pyproj import Transformer

from nisar_investigator import config, provenance
from nisar_investigator.remote import RemoteAccessError
from nisar_investigator.schemas import Granule, SeriesPoint, TimeSeriesRequest
from nisar_investigator.workflows import timeseries
from nisar_investigator.workflows.timeseries import DateRecord, Skip

SHAPE = (200, 300)


def flat(level_db: float, shape: tuple[int, int] = SHAPE) -> np.ndarray:
    return np.full(shape, 10.0 ** (level_db / 10.0))


def points(values: list[float], tiers: list[str] | None = None) -> list[SeriesPoint]:
    tiers = tiers or ["provisional"] * len(values)
    return [SeriesPoint(date=f"2026-01-{i + 1:02d}", value=v, tier=t) for i, (v, t) in enumerate(zip(values, tiers))]


# -------------------------------------------------------------- aggregation


def test_region_mean_is_averaged_in_linear_power():
    power = flat(-10.0)
    power[:, 150:] = 10.0 ** (-30.0 / 10.0)
    stats = timeseries.region_stats(power, "HH")
    assert stats.n_pixels == 200 * 300
    assert stats.mean_db == pytest.approx(10 * np.log10((0.1 + 0.001) / 2), abs=1e-4)  # -12.97, not -20
    assert stats.spread_db > 5.0  # two very different surfaces: a large spatial spread


def test_region_mask_and_nodata_restrict_the_pixels():
    power = flat(-10.0)
    power[:, 150:] = 10.0 ** (-3.0 / 10.0)
    power[:50] = np.nan
    left = np.zeros(SHAPE, dtype=bool)
    left[:, :100] = True
    stats = timeseries.region_stats(power, "HH", left)
    assert stats.n_pixels == 150 * 100
    assert stats.mean_db == pytest.approx(-10.0, abs=1e-4)
    assert stats.spread_db == pytest.approx(0.0, abs=1e-6)


def test_noise_floor_share_is_measured_inside_the_region():
    rng = np.random.default_rng(0)
    power = speckle(rng, -12.0, SHAPE)
    power[:, :60] = speckle(rng, -23.0, (200, 60))  # 20% of the scene is calm water in HV
    whole = timeseries.region_stats(power, "HV")
    assert whole.floor_fraction == pytest.approx(0.2, abs=0.04)
    land = np.zeros(SHAPE, dtype=bool)
    land[:, 100:] = True
    assert timeseries.region_stats(power, "HV", land).floor_fraction < 0.01


def test_step_summary_finds_the_largest_and_the_typical_step():
    summary = timeseries.step_summary(points([-10.0, -10.2, -8.1, -10.1, -10.3, -10.2]))
    assert summary["largest_step_db"] == pytest.approx(2.1)
    assert (summary["from"], summary["to"]) == ("2026-01-02", "2026-01-03")
    assert summary["typical_step_db"] == pytest.approx(0.2)  # median of 0.2, 2.1, 2.0, 0.2, 0.1
    assert summary["n_steps"] == 5


def test_step_summary_leaves_uncalibrated_dates_out_when_it_can():
    tiers = ["beta", "beta", "provisional", "provisional", "provisional", "validated"]
    summary = timeseries.step_summary(points([-5.0, -14.0, -10.0, -10.4, -10.1, -9.0], tiers))
    assert summary["calibrated_dates_only"] is True
    assert summary["largest_step_db"] == pytest.approx(1.1)  # not the 9 dB jump between two beta dates
    assert summary["n_steps"] == 3
    only_beta = timeseries.step_summary(points([-5.0, -14.0, -10.0], ["beta"] * 3))
    assert only_beta["calibrated_dates_only"] is False and only_beta["largest_step_db"] == pytest.approx(-9.0)


def test_step_summary_needs_two_dates_and_three_steps_for_typical():
    assert timeseries.step_summary(points([-10.0])) is None
    assert timeseries.step_summary([]) is None
    two = timeseries.step_summary(points([-10.0, -9.0]))
    assert two["largest_step_db"] == pytest.approx(1.0) and two["typical_step_db"] is None


def test_examine_measures_a_covered_date_and_explains_the_others():
    bbox = grid_bbox(*SHAPE)
    regions = timeseries._Regions(bbox, None)
    granule = make_granule("2026-07-01")
    good = timeseries.examine(granule, make_cutout({"HH": flat(-9.0), "HV": flat(-17.0)}), regions, ("HH", "HV"), "HH")
    assert isinstance(good, DateRecord)
    assert good.stats["HH"].mean_db == pytest.approx(-9.0, abs=1e-4)
    assert good.stats["HV"].mean_db == pytest.approx(-17.0, abs=1e-4)
    assert good.image.shape == SHAPE and len(good.corners) == 4
    assert good.region_area_km2 == pytest.approx(6.0, rel=0.02)

    partial = flat(-9.0)
    partial[:, 200:] = np.nan  # the swath edge crosses the area: a third of it has no valid samples
    skipped = timeseries.examine(granule, make_cutout({"HH": partial}), regions, ("HH",), "HH")
    assert isinstance(skipped, Skip) and skipped.status is None
    assert skipped.coverage == pytest.approx(2 / 3, abs=0.02)
    assert "cover only 67% of the area" in skipped.reason

    failed = timeseries.examine(granule, RemoteAccessError("network error while reading the granule"), regions, ("HH",), "HH")
    assert isinstance(failed, Skip) and failed.status == "error" and "network error" in failed.reason


def test_large_windows_are_thinned_for_display_only():
    image = timeseries._display_image(np.full((400, 3100), 0.1))
    assert image.shape == (134, 1034) and image.dtype == np.float32
    assert np.allclose(image, -10.0, atol=1e-4)


# ------------------------------------------------- the workflow, archive stubbed

T77 = ["2025-12-09", "2026-06-19", "2026-07-01", "2026-07-13", "2026-07-25", "2026-08-18"]
T77_LEVELS = [-9.0, -10.0, -8.0, -10.2, -10.1, -10.0]
T172 = ["2026-06-26", "2026-07-08", "2026-07-20"]
T5 = ["2026-06-26", "2026-07-08", "2026-07-20", "2026-08-13"]


@pytest.fixture
def archive(monkeypatch, cache_dir):
    """Three stacks: track 77 (one beta date), track 172 (one date unreadable), track 5 (swath misses the area)."""
    granules, cutouts = [], {}
    for day, level in zip(T77, T77_LEVELS):
        g = make_granule(day, track=77, tier="beta" if day < "2026" else "provisional")
        granules.append(g)
        cutouts[g.granule_id] = make_cutout({"HH": flat(level), "HV": flat(level - 7.0)}, g.granule_id)
    for day in T172:
        g = make_granule(day, track=172, direction="descending", frame=63)
        granules.append(g)
        cutouts[g.granule_id] = make_cutout({"HH": flat(-11.0), "HV": flat(-18.0)}, g.granule_id)
    unreadable = next(g for g in granules if g.track == 172 and g.date == "2026-07-08")
    cutouts[unreadable.granule_id] = RemoteAccessError("network error while reading the granule")
    for day in T5:
        g = make_granule(day, track=5)
        granules.append(g)
        cutouts[g.granule_id] = make_cutout({"HH": np.full(SHAPE, np.nan), "HV": np.full(SHAPE, np.nan)}, g.granule_id)
    reads: list[list[tuple[int, str]]] = []

    def search(product, bbox=None, start=None, end=None, **_):
        return [g for g in granules if (not start or g.date >= start) and (not end or g.date <= end)]

    def read_windows(batch, bbox, polarizations=("HH", "HV"), **_):
        reads.append([(g.track, g.date) for g in batch])
        return [cutouts[g.granule_id] for g in batch]

    monkeypatch.setattr(timeseries.catalog, "search", search)
    monkeypatch.setattr(timeseries.gcov, "read_windows", read_windows)
    return reads


def request(**overrides) -> TimeSeriesRequest:
    return TimeSeriesRequest(**{"bbox": grid_bbox(*SHAPE), **overrides})


def test_run_timeseries_keeps_tracks_separate_and_flags_tiers(archive):
    result = timeseries.run_timeseries(request())
    assert result.status == "ok" and result.workflow == "timeseries"
    series = {s.id: s for s in result.series}
    assert set(series) == {"hh_t77_f27", "hv_t77_f27", "hh_t172_f63", "hv_t172_f63"}
    hh = series["hh_t77_f27"]
    assert (hh.track, hh.direction, hh.polarization, hh.unit) == (77, "ascending", "HH", "dB")
    assert [p.date for p in hh.points] == T77
    assert [p.value for p in hh.points] == pytest.approx(T77_LEVELS, abs=0.01)
    assert [p.tier for p in hh.points] == ["beta"] + ["provisional"] * 5  # beta stays in, flagged
    assert all(p.spread is not None and p.granule_id.startswith("NISAR_L2_PR_GCOV") for p in hh.points)
    assert [p.value for p in series["hv_t77_f27"].points] == pytest.approx([v - 7.0 for v in T77_LEVELS], abs=0.01)
    assert [p.date for p in series["hh_t172_f63"].points] == ["2026-06-26", "2026-07-20"]

    codes = {c.code: c.text for c in result.caveats}
    assert "uncalibrated" in codes["tier_beta"] and "2025-12-09" in codes["tier_beta"]
    assert "not directly comparable" in codes["tracks_not_comparable"]
    assert "Track 5 (ascending): 4 dates" in codes["dates_skipped"] and "0% of the area" in codes["dates_skipped"]
    assert "Track 172 (descending): 2026-07-08 not used" in codes["dates_skipped"]
    assert len(result.stats["skipped"]) == 5
    assert len(result.receipt.granules) == 8


def test_a_stack_that_misses_the_area_is_dropped_after_one_read(archive):
    timeseries.run_timeseries(request())
    probes, rest = archive
    assert sorted(probes) == [(5, "2026-08-13"), (77, "2026-08-18"), (172, "2026-07-20")]  # latest date of each stack
    assert not any(track == 5 for track, _ in rest)  # three downloads saved
    assert len(rest) == 7


def test_a_date_in_another_radar_mode_is_still_read_when_its_stack_is_dropped(monkeypatch, cache_dir):
    """The swath differs between radar modes, so one date missing the area says nothing about another mode."""
    narrow = [make_granule(d, track=5) for d in ("2026-07-08", "2026-07-20")]
    wide = make_granule("2026-06-26", track=5)
    wide.mode = "2005"
    other = [make_granule(d, track=77) for d in ("2026-06-19", "2026-07-01")]
    empty, full = np.full(SHAPE, np.nan), flat(-9.0)
    reads: list[str] = []

    def read_windows(batch, *args, **kwargs):
        reads.extend(g.date for g in batch if g.track == 5)
        return [make_cutout({"HH": empty if g in narrow else full}) for g in batch]

    monkeypatch.setattr(timeseries.catalog, "search", lambda product, **_: narrow + [wide] + other)
    monkeypatch.setattr(timeseries.gcov, "read_windows", read_windows)
    result = timeseries.run_timeseries(request(polarizations=["HH"]))
    assert reads == ["2026-07-20", "2026-06-26"]  # the probe, then the one date in the other mode
    assert {s.track: [p.date for p in s.points] for s in result.series} == {
        5: ["2026-06-26"],
        77: ["2026-06-19", "2026-07-01"],
    }
    assert sorted(entry["date"] for entry in result.stats["skipped"]) == ["2026-07-08", "2026-07-20"]


def test_summary_states_the_largest_step_next_to_the_typical_one(archive):
    result = timeseries.run_timeseries(request())
    headline = result.summary.headline
    assert headline.startswith("8 dates on 2 tracks from 9 December 2025 to 18 August 2026.")
    # 2.2 dB against a usual 1.05 dB is under three times the usual change, so the series reads as steady
    assert "stayed steady: the biggest change between two passes was 2.20 dB" in headline
    assert "between 1 July and 13 July 2026 (track 77)" in headline
    assert "usual change of 1.05 dB between passes" in headline  # median of |+2.0|, |-2.2|, |+0.1|, |+0.1|
    metrics = {m.key: m.central for m in result.summary.metrics}
    assert metrics == {"n_dates": 8, "n_tracks": 2, "largest_step_db": -2.2, "typical_step_db": 1.05}
    steps = result.stats["series"]["hh_t77_f27"]["steps"]
    assert steps["calibrated_dates_only"] is True and steps["n_steps"] == 4
    assert any("beta-tier" in note for note in result.uncertainty.notes)
    assert "standard deviation" in result.uncertainty.method
    assert result.uncertainty.noise_floor_fraction is not None


def test_layers_scrub_through_the_best_populated_stack(archive):
    result = timeseries.run_timeseries(request())
    assert [layer.date for layer in result.layers] == T77
    assert all(layer.id == f"hh_{layer.date}" for layer in result.layers)
    assert len({(layer.legend.min, layer.legend.max) for layer in result.layers}) == 1  # one grey scale
    assert [layer.default_visible for layer in result.layers] == [False] * 5 + [True]
    artifacts = config.artifacts_dir() / result.id
    for layer in result.layers:
        assert (artifacts / layer.url.partition("?")[0].rsplit("/", 1)[1]).stat().st_size > 0
    assert result.stats["images"] == {"track": 77, "polarization": "HH", "count": 6}


def test_downloads_hold_the_series_as_csv_and_the_full_result(archive):
    result = timeseries.run_timeseries(request())
    assert [d.format for d in result.downloads] == ["csv", "json"]
    with open(config.artifacts_dir() / result.id / "timeseries.csv", newline="") as f:
        rows = list(csv.reader(f))
    assert rows[0] == ["date", "track", "direction", "polarization", "mean_db", "spread_db", "n_pixels", "tier", "granule_id"]
    assert len(rows) == 1 + 2 * (6 + 2)
    first = dict(zip(rows[0], rows[1]))
    assert (first["date"], first["track"], first["polarization"], first["tier"]) == ("2025-12-09", "77", "HH", "beta")
    assert float(first["mean_db"]) == pytest.approx(-9.0, abs=0.01) and int(first["n_pixels"]) == 200 * 300
    assert provenance.load_result(result.id)["series"][0]["points"][0]["date"] == "2025-12-09"
    compile(result.receipt.reproduce, "<reproduce>", "exec")
    assert "run_timeseries(TimeSeriesRequest(" in result.receipt.reproduce
    steps = {s.name: s for s in result.receipt.steps}
    assert {"search_catalog", "read_and_measure", "render_layers", "write_downloads"} <= set(steps)
    assert steps["read_and_measure"].params["granules_read"] == 9  # the unreadable date returned no window


def test_date_range_and_polarizations_are_honoured(archive):
    result = timeseries.run_timeseries(request(start="2026-07-01", end="2026-07-31", polarizations=["HV"]))
    assert result.status == "ok"
    assert {s.polarization for s in result.series} == {"HV"}
    assert [p.date for p in result.series[0].points] == ["2026-07-01", "2026-07-13", "2026-07-25"]
    assert result.layers[0].id.startswith("hv_")  # no co-pol was asked for: the images show what was
    assert "too few dates" in result.summary.headline  # two steps cannot say what is typical


def test_polygon_restricts_the_pixels(monkeypatch, cache_dir):
    power = flat(-8.0)
    power[:, 150:] = 10.0 ** (-20.0 / 10.0)  # bright west half, dark east half
    granule = make_granule("2026-07-01")
    monkeypatch.setattr(timeseries.catalog, "search", lambda product, **_: [granule])
    monkeypatch.setattr(timeseries.gcov, "read_windows", lambda batch, *a, **k: [make_cutout({"HH": power}) for _ in batch])
    tr = Transformer.from_crs(f"EPSG:{EPSG}", "EPSG:4326", always_xy=True)
    xs = [X0 + 200, X0 + 1200, X0 + 1200, X0 + 200, X0 + 200]
    ys = [Y0 - 300, Y0 - 300, Y0 - 1500, Y0 - 1500, Y0 - 300]
    ring = [list(p) for p in zip(*tr.transform(xs, ys))]
    geometry = {"type": "Polygon", "coordinates": [ring]}

    whole = timeseries.run_timeseries(request(polarizations=["HH"]))
    west = timeseries.run_timeseries(request(polarizations=["HH"], geometry=geometry))
    feature = timeseries.run_timeseries(request(polarizations=["HH"], geometry={"type": "Feature", "geometry": geometry}))
    assert whole.series[0].points[0].value == pytest.approx(-10.74, abs=0.02)
    assert west.series[0].points[0].value == pytest.approx(-8.0, abs=0.01)
    assert feature.series[0].points[0].value == west.series[0].points[0].value
    assert west.stats["region"] == {"kind": "polygon", "area_km2": pytest.approx(1.2, rel=0.01), "pixel_size_m": [10.0, 10.0]}
    assert "One date per track is not enough" in west.summary.headline


def test_images_are_capped_at_thirty(monkeypatch, cache_dir):
    granules = [make_granule(f"2026-{1 + i // 28:02d}-{1 + i % 28:02d}") for i in range(35)]
    monkeypatch.setattr(timeseries.catalog, "search", lambda product, **_: granules)
    monkeypatch.setattr(
        timeseries.gcov, "read_windows", lambda batch, *a, **k: [make_cutout({"HH": flat(-10.0, (40, 60))}) for _ in batch]
    )
    result = timeseries.run_timeseries(TimeSeriesRequest(bbox=grid_bbox(40, 60), polarizations=["HH"]))
    assert len(result.series[0].points) == 35
    assert len(result.layers) == timeseries.MAX_LAYERS == 30
    assert result.layers[-1].date == granules[-1].date  # the most recent dates are the ones kept
    assert any("30 most recent dates" in note for note in result.uncertainty.notes)


def test_bad_requests_are_explained(archive):
    cases = [
        ({"geometry": {"type": "Point", "coordinates": [0, 0]}}, "error", "GeoJSON Polygon"),
        ({"geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}}, "error", "inside bbox"),
        ({"start": "2026-08-01", "end": "2026-07-01"}, "error", "start must not be later"),
        ({"start": "July"}, "error", "YYYY-MM-DD"),
        ({"polarizations": ["XX"]}, "error", "polarizations must be chosen"),
        ({"polarizations": []}, "error", "polarizations must be chosen"),
        ({"polarizations": ["VV"]}, "unsupported", "the data has HH and HV"),
        ({"start": "2030-01-01"}, "unsupported", "no backscatter (GCOV) acquisitions over this area in this date range"),
        ({"bbox": (-121.0, 50.0, -119.0, 51.0)}, "unsupported", "too large"),
    ]
    for overrides, status, text in cases:
        result = timeseries.run_timeseries(request(**overrides))
        assert (result.status, text in result.summary.headline) == (status, True), result.summary.headline
        assert not result.series and not result.layers
    assert archive == []  # none of them downloaded anything


def test_nothing_usable_is_unsupported_and_nothing_readable_is_an_error(monkeypatch, cache_dir):
    granules = [make_granule(d) for d in ("2026-06-19", "2026-07-01")]
    monkeypatch.setattr(timeseries.catalog, "search", lambda product, **_: granules)
    empty = make_cutout({"HH": np.full(SHAPE, np.nan)})
    monkeypatch.setattr(timeseries.gcov, "read_windows", lambda batch, *a, **k: [empty for _ in batch])
    edge = timeseries.run_timeseries(request())
    assert edge.status == "unsupported" and "at least 90% of the area" in edge.summary.headline
    assert len(edge.stats["skipped"]) == 2

    refused = RemoteAccessError("Earthdata Login was refused. Check ~/.netrc or EARTHDATA_TOKEN.")
    monkeypatch.setattr(timeseries.gcov, "read_windows", lambda batch, *a, **k: [refused for _ in batch])
    login = timeseries.run_timeseries(request())
    assert login.status == "error" and "Earthdata Login was refused" in login.summary.headline


def test_unexpected_failure_never_leaks_a_traceback(monkeypatch, cache_dir):
    def broken(*args, **kwargs):
        raise RuntimeError("signed-url-with-token")

    monkeypatch.setattr(timeseries.catalog, "search", lambda product, **_: [make_granule("2026-07-01")])
    monkeypatch.setattr(timeseries.gcov, "read_windows", broken)
    result = timeseries.run_timeseries(request())
    assert result.status == "error" and "RuntimeError" in result.summary.headline
    assert "signed-url-with-token" not in result.model_dump_json()


# ---------------------------------------------------------------- real data


@pytest.mark.network
def test_kamloops_lake_first_of_july_stands_out_on_real_data():
    """On track 77 the 1 July 2026 acquisition is brighter than the dates on either side of it."""
    result = timeseries.run_timeseries(
        TimeSeriesRequest(bbox=(-120.56, 50.675, -120.40, 50.735), start="2026-06-15", end="2026-07-20", polarizations=["HH"])
    )
    assert result.status == "ok", result.summary.headline
    series = {s.track: s for s in result.series}
    assert set(series) == {77, 172}  # tracks 5 and 100 see this box only through the invalid edge of their swath
    values = {p.date: p.value for p in series[77].points}
    assert list(values) == ["2026-06-19", "2026-07-01", "2026-07-13"]
    assert values["2026-07-01"] - values["2026-06-19"] > 1.0
    assert values["2026-07-01"] - values["2026-07-13"] > 1.0
    assert all(p.tier == "provisional" for p in series[77].points)
    skipped_tracks = {entry["track"] for entry in result.stats["skipped"]}
    assert skipped_tracks == {5, 100}


# ------------------------------------------------------------ frames that repeat each other


def _stack_granule(track: int, frame: int, day: str) -> Granule:
    return Granule(
        granule_id=f"G_{track}_{frame}_{day}", product="GCOV", tier="provisional", url="https://example.invalid/x.h5",
        track=track, frame=frame, direction="ascending", mode="4005", polarizations=["HH", "HV"], date=day,
    )


def _probe(granule: Granule, coverage: float) -> timeseries.DateRecord:
    return timeseries.DateRecord(
        granule=granule, stats={}, image=None, corners=[], region_area_km2=100.0, pixel_size_m=(10.0, 10.0), coverage=coverage
    )


def _stacks(spec: dict[tuple[int, int], list[str]]):
    return {(track, "ascending", frame): [_stack_granule(track, frame, d) for d in days] for (track, frame), days in spec.items()}


def test_a_frame_that_repeats_its_neighbour_is_read_once():
    days = ["2026-10-01", "2026-10-13", "2026-10-25"]
    stacks = _stacks({(112, 8): days, (112, 9): days, (11, 40): days})
    probed = {key: [_probe(items[-1], 1.0)] for key, items in stacks.items()}
    repeats = timeseries.duplicate_frames(stacks, probed)
    assert len(repeats) == 1 and repeats[0][0] == 112  # one of the two frames of track 112; track 11 untouched


def test_a_frame_with_a_date_its_neighbour_lacks_is_kept():
    stacks = _stacks({(4, 20): ["2026-10-01", "2026-10-13"], (4, 21): ["2026-10-13", "2026-10-25"]})
    probed = {key: [_probe(items[-1], 1.0)] for key, items in stacks.items()}
    assert timeseries.duplicate_frames(stacks, probed) == []


def test_a_frame_that_covers_only_part_of_the_area_is_not_a_repeat():
    days = ["2026-10-01", "2026-10-13"]
    stacks = _stacks({(112, 8): days, (112, 9): days})
    probed = {(112, "ascending", 8): [_probe(stacks[(112, "ascending", 8)][-1], 1.0)],
              (112, "ascending", 9): [_probe(stacks[(112, "ascending", 9)][-1], 0.9)]}
    assert timeseries.duplicate_frames(stacks, probed) == []


def test_the_frame_with_more_dates_is_the_one_kept():
    stacks = _stacks({(4, 20): ["2026-10-01", "2026-10-13", "2026-10-25"], (4, 21): ["2026-10-13", "2026-10-25"]})
    probed = {key: [_probe(items[-1], 1.0)] for key, items in stacks.items()}
    assert timeseries.duplicate_frames(stacks, probed) == [(4, "ascending", 21)]

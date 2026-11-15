"""Workflow A: change statistics on made-up arrays, the workflow with the archive stubbed out, and one real run."""

from __future__ import annotations

import re

import numpy as np
import pytest
import requests
from conftest import grid_bbox, make_cutout, make_granule, speckle

from nisar_investigator import config, provenance
from nisar_investigator.remote import RemoteAccessError
from nisar_investigator.schemas import ChangeRequest
from nisar_investigator.workflows import change
from nisar_investigator.workflows.common import RequestProblem

SHAPE = (300, 400)
PIXEL_KM2 = 1e-4
BRIGHTER = (slice(40, 100), slice(50, 110))  # 60 x 60 pixels = 0.36 km2
DARKER = (slice(180, 230), slice(250, 300))  # 50 x 50 pixels = 0.25 km2
WATER = (slice(0, 300), slice(340, 400))  # at the noise floor on both dates


def scene_pair(seed: int = 0, shift_db: float = 1.0, level_db: float = -10.0, floor_db: float = -20.0):
    """Two speckled dates of one scene: a whole-scene shift, one patch +8 dB, one patch -8 dB, calm water."""
    rng = np.random.default_rng(seed)
    before_db = np.full(SHAPE, level_db)
    after_db = np.full(SHAPE, level_db + shift_db)
    after_db[BRIGHTER] += 8.0
    after_db[DARKER] -= 8.0
    before_db[WATER] = floor_db
    after_db[WATER] = floor_db
    before = speckle(rng, 0.0, SHAPE) * 10 ** (before_db / 10)
    after = speckle(rng, 0.0, SHAPE) * 10 ** (after_db / 10)
    return before, after


def area(mask: np.ndarray) -> float:
    return float(mask.sum()) * PIXEL_KM2


# ------------------------------------------------------------- statistics


def test_scene_shift_and_spread_are_estimated_from_unchanged_pixels():
    before, after = scene_pair(shift_db=1.0)
    result = change.analyse_pair(before, after, "HH")
    assert result.shift_db == pytest.approx(1.0, abs=0.1)
    assert 0.3 < result.sigma_db < 1.2  # 81 single looks per date: about 0.7 dB
    unchanged = result.change_db[110:170, 0:330]
    assert abs(np.median(unchanged)) < 0.2  # the shift is gone from the change map


def test_known_patches_are_recovered_within_the_reported_range():
    before, after = scene_pair()
    result = change.analyse_pair(before, after, "HH")
    for masks, patch, true_km2 in ((result.increased, BRIGHTER, 0.36), (result.decreased, DARKER, 0.25)):
        low, central, high = (area(masks[level]) for level in ("strict", "central", "lenient"))
        assert low <= central <= high
        assert 0.75 * true_km2 < central < 1.4 * true_km2
        inside = np.zeros(SHAPE, dtype=bool)
        inside[patch] = True
        grown = np.zeros(SHAPE, dtype=bool)  # the multilook blurs each edge by a few pixels
        grown[patch[0].start - 6 : patch[0].stop + 6, patch[1].start - 6 : patch[1].stop + 6] = True
        assert not (masks["central"] & ~grown).any()
        assert (masks["central"] & inside).sum() > 0.7 * inside.sum()


def test_thresholds_are_k_sigma_but_never_under_two_db():
    before, after = scene_pair()
    result = change.analyse_pair(before, after, "HH")
    for level, k in change.K_LEVELS.items():
        assert result.thresholds_db[level] == pytest.approx(max(k * result.sigma_db, change.MIN_CHANGE_DB))
    assert result.thresholds_db["lenient"] <= result.thresholds_db["central"] <= result.thresholds_db["strict"]
    assert result.thresholds_db["lenient"] >= 2.0


def test_unnormalised_change_keeps_the_scene_shift():
    before, after = scene_pair(shift_db=3.0)
    normalised = change.analyse_pair(before, after, "HH")
    raw = change.analyse_pair(before, after, "HH", normalise=False)
    assert raw.shift_db == pytest.approx(normalised.shift_db)
    assert np.nanmedian(raw.change_db[120:170, 20:200]) == pytest.approx(3.0, abs=0.15)
    # a 3 dB shift of everything is not a change of 12 km2 of ground: only the normalised result says so
    assert area(normalised.increased["central"]) < 0.6
    assert area(raw.increased["central"]) > 5.0


def test_pixels_at_the_noise_floor_on_both_dates_cannot_tell():
    rng = np.random.default_rng(5)
    before = speckle(rng, -10.0, SHAPE)
    after = speckle(rng, -10.0, SHAPE)
    before[WATER] = speckle(rng, -24.0, (300, 60))  # dark on both dates, 3 dB apart (wind): not a change of surface
    after[WATER] = speckle(rng, -21.0, (300, 60))
    result = change.analyse_pair(before, after, "HV")
    water = np.zeros(SHAPE, dtype=bool)
    water[WATER] = True
    assert result.cannot_tell[:, 350:395].mean() > 0.95
    assert result.cannot_tell[~water].mean() < 0.01
    assert result.cannot_tell_fraction == pytest.approx(0.15, abs=0.03)
    for level in change.K_LEVELS:
        assert not (result.increased[level] & result.cannot_tell).any()
    assert area(result.increased["lenient"]) < 0.05


def test_floor_on_one_date_only_still_counts_as_change():
    rng = np.random.default_rng(6)
    before = speckle(rng, -10.0, SHAPE)
    after = speckle(rng, -10.0, SHAPE)
    before[WATER] = speckle(rng, -22.0, (300, 60))
    after[WATER] = speckle(rng, -22.0, (300, 60))
    before[BRIGHTER] = speckle(rng, -22.0, (60, 60))  # water before, land after (a sandbar emerging)
    result = change.analyse_pair(before, after, "HV")
    assert not result.cannot_tell[55:85, 65:95].any()
    assert area(result.increased["central"]) == pytest.approx(0.36, rel=0.4)


def test_a_single_strong_reflector_is_not_an_area_of_change():
    rng = np.random.default_rng(7)
    before = speckle(rng, -10.0, SHAPE)
    after = before.copy()  # identical dates, except for one pixel
    after[150, 200] = 500.0
    with_removal = change.analyse_pair(before, after, "HH")
    without = change.analyse_pair(before, after, "HH", speck_diameter=1)
    assert area(without.increased["central"]) == pytest.approx(81 * PIXEL_KM2)  # the 9 x 9 multilook footprint
    assert area(with_removal.increased["lenient"]) == 0.0


def test_nodata_is_excluded_and_does_not_leak_through_the_multilook():
    before, after = scene_pair()
    before[:, :30] = np.nan
    result = change.analyse_pair(before, after, "HH")
    assert not result.valid[:, :30].any()
    assert np.isnan(result.change_db[:, :30]).all()
    assert not result.increased["lenient"][:, :30].any()
    assert result.valid[:, 30:].all()


def test_all_nodata_gives_no_measurement_instead_of_an_error():
    empty = np.full(SHAPE, np.nan)
    result = change.analyse_pair(empty, empty, "HH")
    assert not result.valid.any()
    assert not result.increased["lenient"].any()
    assert np.isnan(result.sigma_db)


# ------------------------------------------------------------ choosing dates


def catalogue() -> list:
    return (
        [make_granule(d, track=77) for d in ("2026-06-19", "2026-07-01", "2026-10-17")]
        + [make_granule(d, track=172, direction="descending", frame=63) for d in ("2026-06-26", "2026-10-12")]
        + [make_granule(d, track=5) for d in ("2026-06-26", "2026-10-12")]
    )


def test_select_pair_finds_the_stack_with_both_dates():
    key, before, after, others = change.select_pair(catalogue(), "2026-06-19", "2026-10-17", None, (0, 0, 1, 1))
    assert key == (77, "ascending", 27)
    assert (before.date, after.date) == ("2026-06-19", "2026-10-17")
    assert others == []


def test_select_pair_honours_track_and_reports_alternatives():
    key, *_, others = change.select_pair(catalogue(), "2026-06-26", "2026-10-12", None, (0, 0, 1, 1))
    assert key[0] == 5 and [k[0] for k in others] == [172]
    key, *_ = change.select_pair(catalogue(), "2026-06-26", "2026-10-12", 172, (0, 0, 1, 1))
    assert key == (172, "descending", 63)


def test_select_pair_prefers_the_footprint_that_covers_the_box():
    granules = catalogue()
    for g in granules:
        if g.track == 5:  # track 5 only reaches the western half of the box
            g.footprint = [(-1.0, -1.0), (0.5, -1.0), (0.5, 2.0), (-1.0, 2.0)]
    key, *_ = change.select_pair(granules, "2026-06-26", "2026-10-12", None, (0, 0, 1, 1))
    assert key[0] == 172


def test_select_pair_explains_dates_from_different_tracks():
    with pytest.raises(RequestProblem) as info:
        change.select_pair(catalogue(), "2026-06-19", "2026-10-12", None, (0, 0, 1, 1))
    problem = info.value
    assert problem.status == "unsupported"
    assert "No single track has both 2026-06-19 and 2026-10-12" in str(problem)
    assert "track 77 (ascending): 2026-06-19 and 2026-10-17" in str(problem)
    assert "track 172 (descending): 2026-06-26 and 2026-10-12" in str(problem)
    by_track = {entry["track"]: entry["dates"] for entry in problem.stats["valid_dates_by_track"]}
    assert by_track[77] == ["2026-06-19", "2026-07-01", "2026-10-17"]


def test_select_pair_explains_a_track_that_does_not_pass_here():
    with pytest.raises(RequestProblem) as info:
        change.select_pair(catalogue(), "2026-06-19", "2026-10-17", 33, (0, 0, 1, 1))
    assert info.value.status == "unsupported"
    assert "Track 33 has no backscatter acquisitions" in str(info.value)
    assert "5, 77 and 172" in str(info.value)


# ------------------------------------------------- the workflow, archive stubbed


@pytest.fixture
def archive(monkeypatch, cache_dir):
    """Stub the catalogue and the reader with a made-up pair on track 77. Returns the calls made to the reader."""
    before, after = scene_pair()
    hv_before, hv_after = scene_pair(seed=1, shift_db=0.0, level_db=-16.0, floor_db=-23.0)
    cutouts = {
        "2026-06-19": make_cutout({"HH": before, "HV": hv_before}),
        "2026-10-17": make_cutout({"HH": after, "HV": hv_after}),
    }
    calls: list[list[str]] = []

    def read_windows(granules, bbox, polarizations=("HH", "HV"), **_):
        calls.append([g.date for g in granules])
        return [cutouts[g.date] for g in granules]

    monkeypatch.setattr(change.catalog, "search", lambda product, **_: catalogue())
    monkeypatch.setattr(change.gcov, "read_windows", read_windows)
    return calls


def request(**overrides) -> ChangeRequest:
    fields = {"bbox": grid_bbox(*SHAPE), "date_before": "2026-06-19", "date_after": "2026-10-17"}
    return ChangeRequest(**{**fields, **overrides})


def test_run_change_reports_ranges_layers_downloads_and_a_receipt(archive):
    result = change.run_change(request())
    assert result.status == "ok" and result.workflow == "change"
    assert archive == [["2026-06-19", "2026-10-17"]]

    assert re.search(r"rose over \d+\.\d\d to \d+\.\d\d km2 and fell over \d+\.\d\d to \d+\.\d\d km2 of the 12 km2 area", result.summary.headline)
    assert "between 19 June and 17 October 2026" in result.summary.headline
    metrics = {m.key: m for m in result.summary.metrics}
    for key, true_km2 in (("increased_area_km2", 0.36), ("decreased_area_km2", 0.25)):
        m = metrics[key]
        assert m.low <= m.central <= m.high and m.unit == "km2"  # never a single unqualified area
        assert 0.75 * true_km2 < m.central < 1.4 * true_km2
    assert metrics["scene_shift_db"].central == pytest.approx(1.0, abs=0.1)
    assert {"increased_area_km2_hv", "decreased_area_km2_hv"} <= set(metrics)

    assert result.stats["primary_polarization"] == "HH"
    assert result.stats["stack"] == {"track": 77, "direction": "ascending", "frame": 27}
    assert result.stats["window"]["shape"] == list(SHAPE)
    assert result.stats["window"]["pixel_size_m"] == [10.0, 10.0]
    for pol in ("HH", "HV"):
        s = result.stats["polarizations"][pol]
        assert {"mean_db_before", "mean_db_after", "scene_shift_db", "sigma_db", "thresholds_db"} <= set(s)
        assert s["increased"]["mean_db_after"] > s["increased"]["mean_db_before"]
        assert s["decreased"]["mean_db_after"] < s["decreased"]["mean_db_before"]
        assert 0.1 < s["noise_floor_fraction"]["both"] < 0.2  # the water strip is 15% of the scene

    assert [layer.id for layer in result.layers[:4]] == ["before", "after", "change_db", "change_classes"]
    assert [layer.default_visible for layer in result.layers].count(True) == 1
    by_id = {layer.id: layer for layer in result.layers}
    assert by_id["change_db"].default_visible
    assert (by_id["before"].date, by_id["after"].date) == ("2026-06-19", "2026-10-17")
    assert by_id["before"].legend.min == by_id["after"].legend.min
    assert by_id["change_db"].legend.colormap == "RdBu"
    assert by_id["change_db"].legend.min == -by_id["change_db"].legend.max
    assert by_id["change_classes"].legend.type == "categorical" and len(by_id["change_classes"].legend.classes) == 3
    assert all(len(layer.corners) == 4 for layer in result.layers)

    formats = [d.format for d in result.downloads]
    assert formats.count("geotiff") == 6 and {"csv", "json", "png"} <= set(formats)
    artifacts = config.artifacts_dir() / result.id
    for url in [layer.url for layer in result.layers] + [d.url for d in result.downloads]:
        assert url.startswith(f"/api/artifacts/{result.id}/")
        link, _, token = url.partition("?r=")
        assert token == result.replay  # every file link carries the request, so any server can rebuild the file
        assert (artifacts / link.rsplit("/", 1)[1]).stat().st_size > 0
    assert provenance.load_result(result.id)["id"] == result.id
    workflow, replayed = provenance.read_replay(result.replay)
    assert workflow == "change" and replayed["date_before"] == result.request["date_before"]
    assert isinstance(replayed["track"], int) and replayed["polarization"] in ("HH", "VV")  # the choices made, not "auto"

    assert [g.date for g in result.receipt.granules] == ["2026-06-19", "2026-10-17"]
    steps = {s.name: s for s in result.receipt.steps}
    assert {"search_catalog", "select_stack", "read_windows", "detect_change", "write_artifacts"} <= set(steps)
    assert steps["detect_change"].params["multilook"] == 9 and steps["detect_change"].seconds is not None
    compile(result.receipt.reproduce, "<reproduce>", "exec")
    assert "run_change(ChangeRequest(" in result.receipt.reproduce and "track=77" in result.receipt.reproduce
    assert 'if __name__ == "__main__":' in result.receipt.reproduce


def test_run_change_states_uncertainty_and_caveats(archive):
    result = change.run_change(request())
    uncertainty = result.uncertainty
    assert "1.4826" in uncertainty.method and "9x9" in uncertainty.method
    assert 0.1 < uncertainty.noise_floor_fraction < 0.2
    parameters = [s.parameter for s in uncertainty.sensitivity]
    assert "increase: scene shift" in parameters and "decrease: speck removal" in parameters
    unshifted = next(s for s in uncertainty.sensitivity if s.parameter == "increase: scene shift")
    assert unshifted.value == "not subtracted" and unshifted.unit == "km2"
    assert any(note.startswith("HH:") and "noise floor" in note for note in uncertainty.notes)
    codes = [c.code for c in result.caveats]
    assert {"tier_provisional", "water_wind", "terrain", "not_land_cover"} <= set(codes)


def test_a_polarization_mostly_at_the_noise_floor_is_flagged(monkeypatch, cache_dir):
    rng = np.random.default_rng(3)
    before, after = scene_pair()
    dark = {d: speckle(rng, -23.0, SHAPE) for d in ("before", "after")}  # HV sees noise almost everywhere
    for image in dark.values():
        image[:, :80] = speckle(rng, -14.0, (300, 80))
    cutouts = {
        "2026-06-19": make_cutout({"HH": before, "HV": dark["before"]}),
        "2026-10-17": make_cutout({"HH": after, "HV": dark["after"]}),
    }
    monkeypatch.setattr(change.catalog, "search", lambda product, **_: catalogue())
    monkeypatch.setattr(change.gcov, "read_windows", lambda granules, *a, **k: [cutouts[g.date] for g in granules])
    result = change.run_change(request())
    assert result.status == "ok"
    assert result.stats["polarizations"]["HV"]["informative"] is False
    assert result.stats["polarizations"]["HH"]["informative"] is True
    assert any("HV is not informative here" in note for note in result.uncertainty.notes)


def test_explicit_polarization_becomes_primary(archive):
    result = change.run_change(request(polarization="HV"))
    assert result.status == "ok"
    assert result.stats["primary_polarization"] == "HV"
    assert result.layers[0].title.startswith("HV before")
    missing = change.run_change(request(polarization="VV"))
    assert missing.status == "unsupported" and "VV is not available" in missing.summary.headline


def test_dates_from_different_tracks_are_unsupported_with_valid_pairs(archive):
    result = change.run_change(request(date_after="2026-10-12"))
    assert result.status == "unsupported"
    assert "Closest pairs that can be compared" in result.summary.headline
    assert result.stats["valid_dates_by_track"]
    assert archive == []  # nothing was downloaded
    assert not result.layers and result.uncertainty is None


def test_bad_requests_are_explained_without_touching_the_archive(monkeypatch, cache_dir):
    def unreachable(*args, **kwargs):
        raise AssertionError("the catalogue must not be queried for a request that cannot run")

    monkeypatch.setattr(change.catalog, "search", unreachable)
    swapped = change.run_change(request(date_before="2026-10-17", date_after="2026-06-19"))
    assert swapped.status == "error" and "date_before must be earlier" in swapped.summary.headline
    malformed = change.run_change(request(date_before="19 June"))
    assert malformed.status == "error" and "YYYY-MM-DD" in malformed.summary.headline
    inverted = change.run_change(request(bbox=(10.0, 5.0, 9.0, 6.0)))
    assert inverted.status == "error" and "west < east" in inverted.summary.headline
    huge = change.run_change(request(bbox=(-121.0, 50.0, -119.0, 51.0)))
    assert huge.status == "unsupported" and "too large" in huge.summary.headline


def test_no_coverage_is_unsupported(monkeypatch, cache_dir):
    monkeypatch.setattr(change.catalog, "search", lambda product, **_: [])
    result = change.run_change(request())
    assert result.status == "unsupported"
    assert "no backscatter" in result.summary.headline


def test_catalogue_outage_is_an_error_not_a_traceback(monkeypatch, cache_dir):
    def offline(*args, **kwargs):
        raise requests.ConnectionError("https://cmr.earthdata.nasa.gov/search?secret=1")

    monkeypatch.setattr(change.catalog, "search", offline)
    result = change.run_change(request())
    assert result.status == "error"
    assert "could not be reached" in result.summary.headline
    assert "secret" not in result.model_dump_json()


def test_login_failure_is_reported_in_plain_words(monkeypatch, cache_dir):
    refused = RemoteAccessError("Earthdata Login was refused. Check ~/.netrc or EARTHDATA_TOKEN.")
    monkeypatch.setattr(change.catalog, "search", lambda product, **_: catalogue())
    monkeypatch.setattr(change.gcov, "read_windows", lambda granules, *a, **k: [refused for _ in granules])
    result = change.run_change(request())
    assert result.status == "error"
    assert "Earthdata Login was refused" in result.summary.headline
    assert [s.name for s in result.receipt.steps][:2] == ["search_catalog", "select_stack"]


def test_swath_edge_without_valid_samples_is_unsupported(monkeypatch, cache_dir):
    empty = np.full(SHAPE, np.nan)
    cut = make_cutout({"HH": empty, "HV": empty})
    monkeypatch.setattr(change.catalog, "search", lambda product, **_: catalogue())
    monkeypatch.setattr(change.gcov, "read_windows", lambda granules, *a, **k: [cut for _ in granules])
    result = change.run_change(request())
    assert result.status == "unsupported"
    assert "no valid radar samples" in result.summary.headline


def test_unexpected_failure_never_leaks_a_traceback(monkeypatch, cache_dir):
    def broken(*args, **kwargs):
        raise RuntimeError("signed-url-with-token")

    monkeypatch.setattr(change.catalog, "search", lambda product, **_: catalogue())
    monkeypatch.setattr(change.gcov, "read_windows", broken)
    result = change.run_change(request())
    assert result.status == "error"
    assert "RuntimeError" in result.summary.headline
    assert "signed-url-with-token" not in result.model_dump_json()


# ---------------------------------------------------------------- real data


@pytest.mark.network
def test_kamloops_lake_drawdown_on_real_data():
    """Thompson River, British Columbia: the gauge fell 2.97 m between these dates and sandbars emerged."""
    result = change.run_change(
        ChangeRequest(bbox=(-120.56, 50.675, -120.40, 50.735), date_before="2026-06-19", date_after="2026-10-17", track=77)
    )
    assert result.status == "ok", result.summary.headline
    metrics = {m.key: m for m in result.summary.metrics}
    rose = metrics["increased_area_km2"]
    assert rose.low <= rose.central <= rose.high
    assert 0.1 < rose.central < 1.5  # a prototype found 0.2 to 1.1 km2 depending on method
    assert metrics["increase_median_change_db"].central > 3.0
    hh = result.stats["polarizations"]["HH"]
    assert result.stats["primary_polarization"] == "HH"
    assert -19.0 < hh["noise_floor_db"]["before"] < -15.0  # open water in HH
    assert -24.0 < result.stats["polarizations"]["HV"]["noise_floor_db"]["before"] < -21.0
    assert abs(hh["scene_shift_db"]) < 3.0
    assert result.stats["window"]["valid_fraction"] > 0.99

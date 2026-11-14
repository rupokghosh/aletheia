"""Ground-motion workflow: unit tests on synthetic phase fields (no network) and integration tests on real
NISAR GUNW granules (marked `network`; they need an Earthdata login in ~/.netrc)."""

from __future__ import annotations

import numpy as np
import pytest

from nisar_investigator import catalog, gunw
from nisar_investigator.ops import robust_sigma as ops_spread
from nisar_investigator.schemas import Granule, MotionRequest
from nisar_investigator.workflows import motion

WAVELENGTH = 299_792_458.0 / 1.239e9  # NISAR L-band, 40 MHz mode: 24.2 cm
CM_PER_RAD = WAVELENGTH / (4 * np.pi) * 100


def to_phase(los_cm: np.ndarray) -> np.ndarray:
    """Inverse of the conversion under test: displacement toward the satellite (cm) -> unwrapped phase."""
    return -np.asarray(los_cm) / CM_PER_RAD


def smooth_noise(shape: tuple[int, int], sigma_cm: float, seed: int = 0, scale: int = 12) -> np.ndarray:
    """Spatially correlated noise with a given standard deviation, like a turbulent atmosphere."""
    from scipy import ndimage

    rng = np.random.default_rng(seed)
    field = ndimage.gaussian_filter(rng.standard_normal(shape), scale, mode="wrap")
    return field / field.std() * sigma_cm


def coherent(shape: tuple[int, int], value: float = 0.8) -> np.ndarray:
    return np.full(shape, value, dtype=np.float32)


# ------------------------------------------------------------- conversion


def test_positive_phase_is_motion_away_from_the_satellite():
    # one full fringe of positive phase = the range grew by half a wavelength = 12.1 cm away from the satellite
    los = motion.phase_to_los_cm(np.array([2 * np.pi, 0.0, -2 * np.pi]), WAVELENGTH)
    assert los == pytest.approx([-WAVELENGTH * 50, 0.0, WAVELENGTH * 50])
    assert WAVELENGTH * 50 == pytest.approx(12.098, abs=1e-3)


def test_range_increase_of_one_centimetre():
    # phase = 4*pi/wavelength * (R_secondary - R_reference); the ground moving 1 cm away adds 1 cm of range
    phase = 4 * np.pi / WAVELENGTH * 0.01
    assert float(motion.phase_to_los_cm(np.array(phase), WAVELENGTH)) == pytest.approx(-1.0)


def test_subsidence_bowl_comes_out_negative():
    shape = (200, 200)
    yy, xx = np.mgrid[: shape[0], : shape[1]]
    bowl = -15.0 * np.exp(-((yy - 100) ** 2 + (xx - 100) ** 2) / (2 * 15.0**2))  # 15 cm away from the satellite
    res = motion.analyse(to_phase(bowl + smooth_noise(shape, 0.5)), coherent(shape), WAVELENGTH)
    assert res.los_cm[100, 100] == pytest.approx(-15.0, abs=1.5)
    assert res.decision.outcome == "signal"
    assert res.default.peak_to_peak > 6.0


# ---------------------------------------------------------------- masking


def test_mask_bit_field_decoding():
    iono_bit = 1 << 24
    codes = np.array([11, 12, 111, 124, 10, 1, 0, 255, 12 | iono_bit, 124 | iono_bit], dtype=np.uint32)
    assert gunw.valid_sample_mask(codes).tolist() == [True, True, True, True, False, False, False, False, True, True]
    assert gunw.water_mask(codes).tolist() == [False, False, True, True, False, False, False, False, False, True]


def test_low_coherence_bad_components_water_and_gaps_are_masked():
    shape = (40, 50)
    phase = np.zeros(shape)
    coherence = coherent(shape)
    components = np.ones(shape, dtype=np.uint16)
    mask = np.full(shape, 11, dtype=np.uint32)
    coherence[:4] = 0.1  # 10% low coherence
    components[4:8] = 0  # 10% not unwrapped
    components[8:10] = gunw.CC_FILL  # 5% no data
    mask[10:14] = 111  # 10% water
    mask[14:16] = 10  # 5% no valid sample in the secondary image
    phase[16:18] = np.nan  # 5% no phase
    valid = motion.valid_pixels(phase, coherence, components, mask)
    assert not valid[:18].any() and valid[18:].all()

    parts = motion.mask_breakdown(phase, coherence, components, mask, motion.COHERENCE_THRESHOLD)
    assert parts["low_coherence_fraction"] == pytest.approx(0.10)
    assert parts["not_unwrapped_fraction"] == pytest.approx(0.10)
    assert parts["water_fraction"] == pytest.approx(0.10)
    assert parts["no_data_fraction"] == pytest.approx(0.15)
    assert parts["valid_fraction"] == pytest.approx(0.55)
    assert parts["valid_fraction"] + parts["masked_fraction"] == pytest.approx(1.0)
    assert parts["valid_fraction"] == pytest.approx(valid.mean())


def test_coherence_threshold_changes_what_is_kept():
    shape = (10, 10)
    coherence = np.linspace(0, 1, 100, dtype=np.float32).reshape(shape)
    counts = [int(motion.valid_pixels(np.zeros(shape), coherence, threshold=t).sum()) for t in (0.2, 0.3, 0.4)]
    assert counts[0] > counts[1] > counts[2]


def test_masked_pixels_do_not_leak_into_statistics():
    shape = (120, 120)
    los = smooth_noise(shape, 0.6)
    coherence = coherent(shape)
    los[:20] += 500.0  # garbage where coherence is lost
    coherence[:20] = 0.05
    res = motion.analyse(to_phase(los), coherence, WAVELENGTH)
    assert np.isnan(res.los_cm[:20]).all()
    assert res.default.peak_to_peak < 5.0
    assert res.masking["low_coherence_fraction"] == pytest.approx(20 / 120, abs=1e-3)


# ------------------------------------------------------------ referencing


def test_field_is_relative_to_the_window_median():
    shape = (100, 100)
    los = smooth_noise(shape, 1.0, seed=3)
    a = motion.analyse(to_phase(los), coherent(shape), WAVELENGTH)
    b = motion.analyse(to_phase(los + 37.0), coherent(shape), WAVELENGTH)  # the whole window shifted together
    assert float(np.nanmedian(a.los_cm)) == pytest.approx(0.0, abs=1e-9)
    assert np.allclose(a.los_cm, b.los_cm, atol=1e-6)
    assert b.default.reference_offset_cm - a.default.reference_offset_cm == pytest.approx(37.0, abs=1e-6)


def test_reference_to_median_ignores_invalid_pixels():
    los = np.array([[1.0, 2.0, 3.0, 1000.0]])
    valid = np.array([[True, True, True, False]])
    out, offset = motion.reference_to_median(los, valid)
    assert offset == 2.0
    assert out[0, :3].tolist() == [-1.0, 0.0, 1.0] and np.isnan(out[0, 3])


def test_plane_removal_reports_and_removes_a_ramp():
    shape = (80, 100)
    x = np.arange(shape[1]) * 80.0
    y = 5_000_000.0 - np.arange(shape[0]) * 80.0  # north-up: northing falls with the row index
    ramp = 10.0 * (x[None, :] - x[0]) / (x[-1] - x[0]) + 4.0 * (y[:, None] - y[-1]) / (y[0] - y[-1])
    out, info = motion.remove_plane(ramp, np.ones(shape, dtype=bool), x, y)
    assert np.abs(out).max() < 1e-6
    assert info["east_west_cm"] == pytest.approx(10.0, abs=0.01)  # rises toward the east
    assert info["north_south_cm"] == pytest.approx(4.0, abs=0.01)  # rises toward the north


def test_local_spread_sees_only_short_distance_scatter():
    rng = np.random.default_rng(1)
    shape = (256, 256)
    white = rng.standard_normal(shape) * 0.5
    slow = np.linspace(-1.0, 1.0, shape[1])[None, :] * np.ones(shape)  # slowly varying, like atmosphere
    assert ops_spread(white + slow) > 0.6  # the whole-window spread sees the slow part ...
    assert motion.local_spread(white + slow) == pytest.approx(0.5, rel=0.15)  # ... the tile scatter does not
    assert motion.local_spread(np.full((8, 8), 1.0)) is None  # smaller than one tile


# ------------------------------------------------- signal / no-signal decision


def test_pure_noise_is_not_a_signal():
    shape = (300, 300)
    res = motion.analyse(to_phase(smooth_noise(shape, 1.4, seed=5)), coherent(shape), WAVELENGTH)
    assert res.decision.outcome == "no_signal" and not res.decision.detected
    assert res.decision.noise_basis == "measured"
    assert res.decision.noise_cm == pytest.approx(res.default.spread_cm)
    assert res.default.spread_cm == pytest.approx(1.4, rel=0.25)


def test_very_quiet_window_still_gets_the_minimum_noise_level():
    shape = (200, 200)
    res = motion.analyse(to_phase(smooth_noise(shape, 0.2, seed=6)), coherent(shape), WAVELENGTH)
    assert res.decision.outcome == "no_signal"
    assert res.decision.noise_basis == "floor"
    assert res.decision.noise_cm == motion.NOISE_FLOOR_CM


def test_noisy_window_without_signal_reports_its_own_spread():
    shape = (300, 300)
    res = motion.analyse(to_phase(smooth_noise(shape, 3.4, seed=7)), coherent(shape), WAVELENGTH)
    assert res.default.spread_cm > motion.NOISE_CEILING_CM
    assert res.decision.outcome == "no_signal"
    assert res.decision.noise_cm == pytest.approx(res.default.spread_cm)  # not capped: nothing was called motion


def test_window_filling_coseismic_step_is_a_signal():
    shape = (300, 300)
    yy = np.mgrid[: shape[0], : shape[1]][0]
    step = 25.0 * np.arctan((yy - 150) / 20.0) / (np.pi / 2)  # +-25 cm across an east-west fault
    res = motion.analyse(to_phase(step + smooth_noise(shape, 1.0, seed=8)), coherent(shape), WAVELENGTH)
    assert res.decision.outcome == "signal"
    assert res.decision.noise_basis == "ceiling" and res.decision.noise_cm == motion.NOISE_CEILING_CM
    assert 35.0 < res.default.peak_to_peak < 55.0
    kept = [st.peak_to_peak for s, st in res.variants.values() if not s.ramp]
    assert min(kept) > res.decision.threshold_cm  # every processing choice agrees
    # a plane fitted across the fault absorbs part of the step, but what is left is far too spread out for noise
    assert res.variants["ramp_removed"][1].spread_cm > motion.SPREAD_IS_MOTION_CM


def test_pure_ramp_is_reported_as_tilt_not_as_motion():
    shape = (300, 300)
    ramp = np.linspace(-20.0, 20.0, shape[1])[None, :] * np.ones(shape)
    res = motion.analyse(to_phase(ramp + smooth_noise(shape, 0.8, seed=9)), coherent(shape), WAVELENGTH)
    assert res.decision.outcome == "tilt_only" and not res.decision.detected
    assert res.variants["ramp_removed"][1].ramp["east_west_cm"] == pytest.approx(40.0, rel=0.05)
    removed = motion.analyse(to_phase(ramp + smooth_noise(shape, 0.8, seed=9)), coherent(shape), WAVELENGTH, remove_ramp=True)
    assert removed.decision.outcome == "no_signal"


def test_decision_thresholds():
    factor = motion.DETECTION_FACTOR
    assert motion.decide_signal(1.5, [factor * 1.5 - 0.1], None).outcome == "no_signal"
    assert motion.decide_signal(1.5, [factor * 1.5 + 0.1], None).outcome == "signal"
    assert motion.decide_signal(1.5, [30.0, 8.0], None).outcome == "no_signal"  # every choice must agree
    tilt = motion.decide_signal(1.5, [30.0], (5.0, 0.8))  # only the ramp was large
    assert tilt.outcome == "tilt_only" and tilt.noise_cm == motion.NOISE_FLOOR_CM
    assert motion.decide_signal(1.5, [30.0], (25.0, 4.0)).outcome == "signal"
    assert motion.decide_signal(9.0, [40.0], (20.0, 7.5)).outcome == "signal"  # fills the window: spread alone
    assert motion.decide_signal(9.0, [40.0], (20.0, 4.0)).outcome == "tilt_only"
    assert motion.decide_signal(0.2, [5.0], None).outcome == "no_signal"  # 5 cm is below 9 x the 1 cm floor
    assert not motion.decide_signal(1.5, [6.0], None).inconclusive  # an ordinary quiet pair
    assert motion.decide_signal(1.5, [12.0], None).inconclusive  # unusually wide, yet short of the threshold
    capped = motion.decide_signal(12.0, [50.0], (45.0, 9.0))
    assert capped.outcome == "signal" and capped.noise_cm == motion.NOISE_CEILING_CM
    assert capped.threshold_cm == factor * motion.NOISE_CEILING_CM
    assert motion.decide_signal(float("nan"), [0.0], None).outcome == "no_signal"


def test_the_decision_rule_matches_the_real_pairs_it_was_calibrated_on():
    """(spread, smallest range, range and spread after ramp removal) measured on real GUNW pairs."""
    quiet = [  # no earthquake: Kamloops (first three), then the hardest of 27 pairs over northern Venezuela
        (1.18, 6.24, 6.02, 1.24), (2.49, 9.95, 8.97, 1.95), (0.98, 5.34, 3.99, 0.70),
        (1.25, 7.53, 7.51, 1.26), (1.22, 7.23, 6.78, 0.96), (3.15, 12.70, 9.29, 1.50), (4.71, 12.16, 7.68, 1.50),
        (2.71, 15.73, 12.87, 2.82), (3.40, 14.70, 11.49, 1.66), (2.34, 13.47, 11.95, 1.86), (3.33, 12.87, 13.41, 2.58),
    ]
    for spread, smallest, deramped_range, deramped_spread in quiet:
        assert motion.decide_signal(spread, [smallest], (deramped_range, deramped_spread)).outcome == "no_signal"
    coseismic = [(8.14, 59.45, 56.71, 7.26), (7.84, 74.24, 64.87, 10.99)]  # tracks 162 and 54 across 24 June 2026
    for spread, smallest, deramped_range, deramped_spread in coseismic:
        assert motion.decide_signal(spread, [smallest], (deramped_range, deramped_spread)).outcome == "signal"


# -------------------------------------------------------------- ionosphere


def test_ionosphere_screen_is_subtracted_and_reported():
    shape = (200, 200)
    ground = smooth_noise(shape, 0.8, seed=11)
    screen_cm = np.linspace(-6.0, 6.0, shape[0])[:, None] * np.ones(shape)  # ionosphere: 12 cm across the window
    phase = to_phase(ground + screen_cm)
    res = motion.analyse(phase, coherent(shape), WAVELENGTH, ionosphere=to_phase(screen_cm),
                         ionosphere_uncertainty=np.full(shape, 0.5))
    assert res.ionosphere["available"] and res.ionosphere["applied"]
    assert res.ionosphere["range_min_max_cm"] == pytest.approx(12.0, abs=0.1)
    assert res.ionosphere["uncertainty_median_cm"] == pytest.approx(0.5 * CM_PER_RAD, abs=0.01)
    assert res.default.spread_cm == pytest.approx(0.8, rel=0.25)
    assert res.variants["ionosphere_not_applied"][1].spread_cm > 2 * res.default.spread_cm

    raw = motion.analyse(phase, coherent(shape), WAVELENGTH, ionosphere=to_phase(screen_cm), apply_ionosphere=False)
    assert not raw.ionosphere["applied"]
    assert raw.variants["ionosphere_applied"][1].spread_cm == pytest.approx(res.default.spread_cm)


def test_missing_ionosphere_layer_is_handled():
    shape = (100, 100)
    res = motion.analyse(to_phase(smooth_noise(shape, 1.0)), coherent(shape), WAVELENGTH,
                         ionosphere=np.full(shape, np.nan))
    assert res.ionosphere == {"available": False, "applied": False}
    assert "ionosphere_not_applied" not in res.variants and "ionosphere_applied" not in res.variants


# ----------------------------------------------------------- sensitivity


def test_areas_and_variants_cover_every_coherence_threshold():
    shape = (200, 200)
    rng = np.random.default_rng(2)
    coherence = rng.uniform(0.1, 0.9, shape).astype(np.float32)
    res = motion.analyse(to_phase(smooth_noise(shape, 1.2, seed=4)), coherence, WAVELENGTH)
    assert set(res.areas_km2) == {0.2, 0.3, 0.4}
    assert res.areas_km2[0.2][0] >= res.areas_km2[0.3][0] >= res.areas_km2[0.4][0]  # fewer pixels, less area
    assert all(a2 >= a3 for a2, a3 in res.areas_km2.values())
    assert res.masked_by_threshold[0.2] < res.masked_by_threshold[0.3] < res.masked_by_threshold[0.4]
    assert res.variants["coherence_0.3"][1] is res.variants["default"][1]


def test_several_unwrapped_regions_add_a_largest_region_variant():
    shape = (100, 100)
    components = np.ones(shape, dtype=np.uint16)
    components[:, 70:] = 2
    los = smooth_noise(shape, 0.5)
    los[:, 70:] += WAVELENGTH * 50  # the small region is off by one fringe
    res = motion.analyse(to_phase(los), coherent(shape), WAVELENGTH, components=components)
    assert res.n_components == 2
    assert res.variants["largest_component"][1].peak_to_peak < res.default.peak_to_peak - 5.0


# --------------------------------------------------------- pair selection


def _pair(ref: str, sec: str, track: int = 77, frame: int = 27, tier: str = "provisional", box=(-121.0, 50.0, -119.0, 51.5)):
    w, s, e, n = box
    stamp = lambda d: d.replace("-", "") + "T120000"  # noqa: E731
    return Granule(
        granule_id=f"NISAR_L2_PR_GUNW_001_{track:03d}_A_{frame:03d}_002_4000_SH_{stamp(ref)}_{stamp(ref)}_{stamp(sec)}_{stamp(sec)}_P05023_N_F_J_001",
        product="GUNW", tier=tier, url="https://example.invalid/pair.h5", track=track, frame=frame,
        direction="ascending", mode="4000", polarizations=["HH"], reference_date=ref, secondary_date=sec,
        footprint=[(w, s), (e, s), (e, n), (w, n), (w, s)],
    )


BOX = (-120.6, 50.55, -120.05, 50.85)


def test_latest_pair_is_chosen_by_default():
    pairs = [_pair("2026-09-11", "2026-09-23"), _pair("2026-10-05", "2026-10-17"), _pair("2026-09-23", "2026-10-05")]
    chosen, usable = motion.choose_pair(pairs, BOX)
    assert chosen.reference_date == "2026-10-05" and len(usable) == 3


def test_reference_date_and_track_are_respected():
    pairs = [_pair("2026-09-30", "2026-10-12", track=172), _pair("2026-10-05", "2026-10-17"), _pair("2026-09-23", "2026-10-05")]
    assert motion.choose_pair(pairs, BOX, reference_date="2026-09-23")[0].secondary_date == "2026-10-05"
    assert motion.choose_pair(pairs, BOX, track=172)[0].reference_date == "2026-09-30"
    assert motion.choose_pair(pairs, BOX, reference_date="2026-10-05", track=172)[0] is None
    assert motion.choose_pair(pairs, BOX, reference_date="2026-11-01")[0] is None


def test_frame_that_covers_the_box_beats_a_newer_sliver():
    covering = _pair("2026-09-23", "2026-10-05", frame=27)
    sliver = _pair("2026-10-05", "2026-10-17", frame=26, box=(-121.0, 50.0, -119.0, 50.6))  # touches the south edge
    chosen, offered = motion.choose_pair([covering, sliver], BOX)
    assert chosen.frame == 27 and [g.frame for g, _ in offered] == [27]  # the sliver is not even offered
    assert motion.choose_pair([covering, sliver], BOX, reference_date="2026-10-05")[0].frame == 26  # unless asked for
    same_day = _pair("2026-09-23", "2026-10-05", frame=26, box=(-121.0, 50.0, -119.0, 50.6))
    assert motion.choose_pair([same_day, covering], BOX, reference_date="2026-09-23")[0].frame == 27


def test_shorter_pair_wins_when_two_share_a_reference_date():
    pairs = [_pair("2026-07-25", "2026-08-18"), _pair("2026-07-25", "2026-08-06")]
    assert motion.choose_pair(pairs, BOX)[0].secondary_date == "2026-08-06"


def test_headline_when_no_pair_matches_lists_what_exists():
    pairs = [_pair("2026-09-23", "2026-10-05"), _pair("2026-10-05", "2026-10-17")]
    _, usable = motion.choose_pair(pairs, BOX, reference_date="2026-11-01")
    text = motion._no_pair_headline(usable, "2026-11-01", None)
    assert "1 November 2026" in text and "stop on 17 October 2026" in text and "track 77" in text
    assert "no ready-made" in motion._no_pair_headline([], None, None)


# ---------------------------------------------------------------- wording


def test_date_span_wording():
    assert motion._span("2026-10-05", "2026-10-17") == "5 and 17 October 2026"
    assert motion._span("2026-06-25", "2026-07-07") == "25 June and 7 July 2026"
    assert motion._span("2025-12-28", "2026-01-09") == "28 December 2025 and 9 January 2026"


def test_number_wording_and_colour_limits():
    assert motion._range_text(38.2, 45.7) == "38 to 46 cm"
    assert motion._range_text(6.02, 7.51) == "6.0 to 7.5 cm"
    assert motion._range_text(12.2, 12.4) == "about 12 cm"
    assert motion._nice_limit(4.2) == 5.0 and motion._nice_limit(36.0) == 40.0
    assert motion._bearing(0.61, 0.13) == "east-north-east" and motion._bearing(-0.6, 0.1) == "west"


# ------------------------------------------------------------------ reader


def test_window_rows_and_cols_from_a_lonlat_box():
    x = 200_000.0 + np.arange(1000) * 80.0  # UTM zone 11N
    y = 5_700_000.0 - np.arange(900) * 80.0
    from pyproj import Transformer

    lon, lat = Transformer.from_crs("EPSG:32611", "EPSG:4326", always_xy=True).transform(
        [x[100], x[300]], [y[500], y[200]]
    )
    r0, r1, c0, c1 = gunw._window(x, y, 32611, (lon[0], lat[0], lon[1], lat[1]), 10_000_000)
    # the window is the envelope of the box in the grid's projection, which is slightly rotated against lon/lat
    assert r0 <= 200 and r1 >= 501 and c0 <= 100 and c1 >= 301
    assert 200 - r0 <= 25 and r1 - 501 <= 25 and 100 - c0 <= 25 and c1 - 301 <= 25
    with pytest.raises(gunw.OutsideFrame):
        gunw._window(x, y, 32611, (10.0, 10.0, 10.1, 10.1), 10_000_000)
    with pytest.raises(gunw.WindowTooLarge):
        gunw._window(x, y, 32611, (lon[0], lat[0], lon[1], lat[1]), 1000)


def test_batches_keep_small_windows_together_and_split_large_ones():
    from nisar_investigator import config

    block = config.BLOCK_SIZE
    small = {name: [(i * block, 100)] for i, name in enumerate("abcdef")}
    assert gunw._batches(small) == [list("abcdef")]
    per_layer = config.MAX_CACHED_BLOCKS // 2
    large = {name: [((k * per_layer + j) * block, 100) for j in range(per_layer)] for k, name in enumerate("abc")}
    groups = gunw._batches(large)
    assert len(groups) >= 2 and [n for g in groups for n in g] == list("abc")
    assert gunw._batches({}) == [[]]


def test_chunks_are_decoded_like_h5py_reads_them(tmp_path):
    """The exact-range reader undoes shuffle + deflate itself; it must agree with h5py bit for bit."""
    import h5py

    rng = np.random.default_rng(0)
    data = {
        "phase": rng.standard_normal((100, 130)).astype(np.float32),
        "components": rng.integers(0, 4, (100, 130)).astype(np.uint16),
        "mask": rng.integers(0, 2**25, (100, 130)).astype(np.uint32),
        "cube": rng.standard_normal((3, 100, 130)),
    }
    with h5py.File(tmp_path / "chunks.h5", "w") as f:
        for name, values in data.items():
            chunks = (64, 64) if values.ndim == 2 else (1, 64, 64)
            f.create_dataset(name, data=values, chunks=chunks, compression="gzip", compression_opts=1, shuffle=True)
        f.create_dataset("plain", data=data["phase"], chunks=(64, 64))
        f.create_dataset("lzf", data=data["phase"], chunks=(64, 64), compression="lzf")
    with h5py.File(tmp_path / "chunks.h5", "r") as f:
        for name in ("phase", "components", "mask", "plain"):
            dset = f[name]
            assert gunw._decodable(dset)
            for coord, offset, size in gunw._chunk_refs(dset, 10, 90, 20, 120):
                _, blob = dset.id.read_direct_chunk(coord)
                assert len(blob) == size and offset > 0
                block = gunw._decode_chunk(blob, dset)
                expected = np.zeros(dset.chunks, dtype=dset.dtype)
                part = dset[coord[0] : coord[0] + 64, coord[1] : coord[1] + 64]
                expected[: part.shape[0], : part.shape[1]] = part
                assert np.array_equal(block[: part.shape[0], : part.shape[1]], part)
        cube = f["cube"]
        ((coord, _, _),) = gunw._chunk_refs(cube, 70, 71, 100, 101, lead=(2,))
        assert coord == (2, 64, 64)
        block = gunw._decode_chunk(cube.id.read_direct_chunk(coord)[1], cube)
        assert block[0, 70 - 64, 100 - 64] == data["cube"][2, 70, 100]
        assert not gunw._decodable(f["lzf"])  # unknown filter: the reader falls back to h5py


def test_neighbouring_byte_ranges_are_merged():
    gap = gunw._MERGE_GAP
    assert gunw._merge_ranges([(1000, 10), (0, 100), (1000, 10)]) == [(0, 1010)]
    assert gunw._merge_ranges([(0, 100), (100 + gap + 1, 50)]) == [(0, 100), (100 + gap + 1, 50)]
    assert gunw._merge_ranges([(0, 100), (10, 20)]) == [(0, 100)]
    assert gunw._merge_ranges([]) == []


def _cutout(los_cm: np.ndarray, coherence: np.ndarray | None = None) -> gunw.GunwCutout:
    rows, cols = los_cm.shape
    return gunw.GunwCutout(
        granule_id="synthetic",
        layers={
            "unwrappedPhase": to_phase(los_cm).astype(np.float32),
            "coherenceMagnitude": coherent(los_cm.shape) if coherence is None else coherence,
            "connectedComponents": np.ones(los_cm.shape, dtype=np.uint16),
            "mask": np.full(los_cm.shape, 11, dtype=np.uint32),
        },
        x=244_960.0 + 40.0 + np.arange(cols) * 80.0,
        y=5_639_360.0 - 40.0 - np.arange(rows) * 80.0,
        epsg=32611,
        rows=(0, rows),
        cols=(0, cols),
        polarization="HH",
        center_frequency_hz=1.239e9,
        look_direction="Left",
        pass_direction="Ascending",
        temporal_baseline_days=12,
        looks=(13, 16),
        incidence_deg=40.7,
        los_enu=(0.61, 0.23, 0.76),
    )


def test_cutout_geometry():
    cut = _cutout(np.zeros((30, 40)))
    assert cut.shape == (30, 40) and cut.pixel_size == (80.0, 80.0)
    assert cut.wavelength_m == pytest.approx(WAVELENGTH)
    assert cut.geotransform() == (244_960.0, 80.0, 0.0, 5_639_360.0, 0.0, -80.0)
    (tl_lon, tl_lat), (tr_lon, _), (_, br_lat), (bl_lon, _) = cut.corners_lonlat()
    assert tl_lon < tr_lon and br_lat < tl_lat and abs(bl_lon - tl_lon) < 0.01


# ------------------------------------------- workflow, with the network stubbed


@pytest.fixture
def offline(monkeypatch, tmp_path):
    """Run `run_motion` without the network: a temporary artifact folder and a stubbed catalogue and reader."""
    monkeypatch.setenv("NISAR_CACHE_DIR", str(tmp_path))
    state: dict = {"pairs": [_pair("2026-09-23", "2026-10-05"), _pair("2026-10-05", "2026-10-17")], "cut": None}
    monkeypatch.setattr(catalog, "search", lambda product, **kw: list(state["pairs"]))
    monkeypatch.setattr(gunw, "read_window", lambda granule, bbox, **kw: state["cut"])
    return state, tmp_path


def test_run_motion_noise_case_end_to_end(offline):
    state, tmp_path = offline
    state["cut"] = _cutout(smooth_noise((240, 300), 1.3, seed=21))
    result = motion.run_motion(MotionRequest(bbox=BOX))
    assert result.status == "ok" and result.workflow == "motion"
    assert result.summary.headline.startswith("No ground motion above the ")
    assert result.summary.headline.endswith("cm noise level between 5 and 17 October 2026")
    assert result.stats["detection"]["signal_detected"] is False
    assert result.stats["pair"]["reference_date"] == "2026-10-05"

    for metric in result.summary.metrics:  # ranges, never a bare number
        if metric.low is not None and metric.high is not None:
            assert metric.low <= metric.central <= metric.high, metric.key
    keys = {m.key for m in result.summary.metrics}
    assert {"noise_level_cm", "los_span_p5_p95_cm", "los_peak_to_peak_cm", "area_above_2x_noise_km2",
            "area_above_3x_noise_km2", "masked_percent"} <= keys

    assert [layer.id for layer in result.layers] == ["displacement", "coherence", "fringes"]
    disp = result.layers[0]
    assert disp.legend.colormap == "RdBu" and disp.legend.unit == "cm" and disp.legend.min == -disp.legend.max
    assert len(disp.corners) == 4
    folder = tmp_path / "artifacts" / result.id
    for name in ("displacement.png", "coherence.png", "fringes.png", "displacement_cm.tif", "coherence.tif",
                 "statistics.csv", "result.json"):
        assert (folder / name).stat().st_size > 0, name
    assert {d.format for d in result.downloads} == {"geotiff", "csv", "png", "json"}

    parameters = {s.parameter for s in result.uncertainty.sensitivity}
    assert {"coherence threshold", "planar ramp"} <= parameters
    assert result.uncertainty.noise_floor_fraction == result.stats["masking"]["masked_fraction"]
    assert any("1 to 2 cm of atmospheric noise" in note for note in result.uncertainty.notes)
    assert {c.code for c in result.caveats} >= {"line_of_sight", "relative_motion", "atmosphere", "ionosphere",
                                                "unwrapping", "tier_provisional", "single_pair"}
    assert [s.name for s in result.receipt.steps] == ["search_pairs", "choose_pair", "read_window",
                                                      "phase_to_displacement", "render"]
    assert result.receipt.granules[0].reference_date == "2026-10-05"
    assert result.receipt.granules[0].granule_id in result.receipt.reproduce
    compile(result.receipt.reproduce, "<reproduce>", "exec")  # the snippet is valid Python


def test_run_motion_signal_case_end_to_end(offline):
    state, _ = offline
    shape = (240, 300)
    yy = np.mgrid[: shape[0], : shape[1]][0]
    step = 22.0 * np.arctan((yy - 120) / 15.0) / (np.pi / 2)
    state["cut"] = _cutout(step + smooth_noise(shape, 1.0, seed=22))
    result = motion.run_motion(MotionRequest(bbox=BOX, reference_date="2026-09-23", track=77))
    assert result.status == "ok"
    assert result.summary.headline.startswith("Up to ")
    assert "of line-of-sight motion across the area between 23 September and 5 October 2026" in result.summary.headline
    assert result.stats["detection"]["outcome"] == "signal"
    p2p = next(m for m in result.summary.metrics if m.key == "los_peak_to_peak_cm")
    assert 35.0 < p2p.central < 50.0
    assert result.stats["detection"]["threshold_cm"] < p2p.central and p2p.low <= p2p.central <= p2p.high < 50.0
    assert f"{p2p.low:.0f} to {p2p.high:.0f} cm" in result.summary.headline


def test_run_motion_without_pairs_is_unsupported(offline):
    state, _ = offline
    state["pairs"] = []
    result = motion.run_motion(MotionRequest(bbox=BOX))
    assert result.status == "unsupported" and "no ready-made" in result.summary.headline
    assert result.layers == []


def test_run_motion_unknown_date_lists_available_pairs(offline):
    result = motion.run_motion(MotionRequest(bbox=BOX, reference_date="2026-11-01"))
    assert result.status == "unsupported"
    assert "stop on 17 October 2026" in result.summary.headline
    assert [p["reference_date"] for p in result.stats["available_pairs"]] == ["2026-09-23", "2026-10-05"]


def test_run_motion_rejects_bad_requests(offline):
    assert motion.run_motion(MotionRequest(bbox=(10.0, 5.0, 9.0, 6.0))).status == "error"
    assert motion.run_motion(MotionRequest(bbox=(-125.0, 45.0, -115.0, 55.0))).status == "unsupported"  # too large
    assert motion.run_motion(MotionRequest(bbox=BOX, reference_date="17 October")).status == "error"


def test_run_motion_when_coherence_is_lost_everywhere(offline):
    state, _ = offline
    shape = (100, 120)
    state["cut"] = _cutout(smooth_noise(shape, 1.0), coherence=np.full(shape, 0.05, dtype=np.float32))
    result = motion.run_motion(MotionRequest(bbox=BOX))
    assert result.status == "unsupported"
    assert "could not be measured" in result.summary.headline
    assert [layer.id for layer in result.layers] == ["coherence"]


def test_run_motion_outside_the_frame(offline, monkeypatch):
    def outside(granule, bbox, **kw):
        raise gunw.OutsideFrame("the requested box is outside this granule")

    monkeypatch.setattr(gunw, "read_window", outside)
    result = motion.run_motion(MotionRequest(bbox=BOX))
    assert result.status == "unsupported" and "outside" in result.summary.headline


# ------------------------------------------------- real data (network needed)

KAMLOOPS = (-120.60, 50.55, -120.05, 50.85)  # 35 x 40 km around Kamloops, British Columbia: no motion expected
# 24 June 2026 Venezuela earthquakes (M7.2 and M7.5), track 162 ascending, 13 -> 25 June 2026
VENEZUELA = (-68.45, 10.05, -67.35, 10.75)
VENEZUELA_REFERENCE, VENEZUELA_TRACK = "2026-06-13", 162


@pytest.mark.network
def test_real_layout_of_a_gunw_window():
    pair = [g for g in catalog.search("GUNW", bbox=KAMLOOPS) if g.track == 77 and g.reference_date == "2026-10-05"][-1]
    cut = gunw.read_window(pair, KAMLOOPS)
    assert cut.epsg == 32611 and cut.pixel_size == (80.0, 80.0)
    assert cut.center_frequency_hz == pytest.approx(1.239e9) and cut.wavelength_m == pytest.approx(0.24196, abs=1e-4)
    assert cut.look_direction == "Left" and cut.pass_direction == "Ascending" and cut.temporal_baseline_days == 12
    assert set(gunw.DEFAULT_LAYERS) | {"mask"} <= set(cut.layers)
    assert all(v.shape == cut.shape for v in cut.layers.values())
    assert cut.layers["connectedComponents"].dtype == np.uint16 and cut.layers["mask"].dtype == np.uint32
    assert cut.y[0] > cut.y[-1]  # north-up
    assert 30.0 < cut.incidence_deg < 50.0 and cut.los_enu[0] > 0.4  # left-looking, ascending: satellite to the east
    lons = [c[0] for c in cut.corners_lonlat()]
    assert min(lons) < KAMLOOPS[0] + 0.05 and max(lons) > KAMLOOPS[2] - 0.05


@pytest.mark.network
def test_real_exact_range_read_equals_block_read():
    pair = [g for g in catalog.search("GUNW", bbox=KAMLOOPS) if g.track == 77 and g.reference_date == "2026-10-05"][-1]
    small = (-120.40, 50.62, -120.25, 50.72)
    fast = gunw.read_window(pair, small, use_cache=False)
    slow = gunw.read_window(pair, small, use_cache=False, exact_ranges=False)
    assert fast.io["mode"] == "chunks" and slow.io["mode"] == "blocks"
    assert fast.io["megabytes"] < slow.io["megabytes"]
    assert set(fast.layers) == set(slow.layers)
    for name, values in slow.layers.items():
        assert np.array_equal(fast.layers[name], values, equal_nan=values.dtype.kind == "f"), name
    assert fast.incidence_deg == slow.incidence_deg and fast.los_enu == slow.los_enu


@pytest.mark.network
def test_real_noise_case_kamloops():
    result = motion.run_motion(MotionRequest(bbox=KAMLOOPS, reference_date="2026-10-05", track=77))
    assert result.status == "ok"
    assert result.summary.headline.startswith("No ground motion above the ")
    assert result.stats["detection"]["outcome"] == "no_signal"
    assert 0.5 < result.stats["noise"]["field_spread_cm"] < 3.0
    # subtracting NASA's ionosphere screen must lower the scatter (adding it, the wrong sign, would raise it)
    spreads = {s.value: s.result for s in result.uncertainty.sensitivity
               if s.parameter == "ionosphere correction" and s.unit == "cm robust spread"}
    assert spreads["applied"] < spreads["not applied"]


@pytest.mark.network
def test_real_reproduce_snippet_matches_the_result(capsys):
    result = motion.run_motion(MotionRequest(bbox=KAMLOOPS, reference_date="2026-10-05", track=77))
    snippet = result.receipt.reproduce.split("# or the whole workflow")[0]
    exec(compile(snippet, "<reproduce>", "exec"), {})  # noqa: S102 - our own generated code
    printed = capsys.readouterr().out
    assert f"robust spread {result.stats['noise']['field_spread_cm']:.2f} cm" in printed
    p2p = next(m for m in result.summary.metrics if m.key == "los_peak_to_peak_cm")
    assert f"1st-99th percentile range {p2p.central:.2f} cm" in printed


def _box_median(cut: gunw.GunwCutout, field_cm: np.ndarray, box: tuple[float, float, float, float]) -> float:
    from pyproj import Transformer

    west, south, east, north = box
    xs, ys = Transformer.from_crs("EPSG:4326", f"EPSG:{cut.epsg}", always_xy=True).transform([west, east], [south, north])
    inside = ((cut.x[None, :] >= min(xs)) & (cut.x[None, :] <= max(xs))
              & (cut.y[:, None] >= min(ys)) & (cut.y[:, None] <= max(ys)))
    return float(np.nanmedian(field_cm[inside]))


@pytest.mark.network
def test_real_signal_case_venezuela_earthquakes():
    request = MotionRequest(bbox=VENEZUELA, reference_date=VENEZUELA_REFERENCE, track=VENEZUELA_TRACK)
    result = motion.run_motion(request)
    assert result.status == "ok"
    assert result.stats["detection"]["outcome"] == "signal"
    assert result.summary.headline.startswith("Up to ")
    assert result.summary.headline.endswith("between 13 and 25 June 2026")
    p2p = next(m for m in result.summary.metrics if m.key == "los_peak_to_peak_cm")
    assert p2p.low > 40.0  # decimetres of coseismic motion under every processing choice
    assert result.stats["ionosphere"]["applied"] and result.stats["ionosphere"]["range_cm"] > 10.0

    # Sign check against the USGS moment tensors (right-lateral slip on east-west planes) with the satellite
    # to the east: north of the on-land rupture the ground moved east = toward the satellite (positive); the
    # coast south of the offshore rupture moved west = away (negative).
    assert result.stats["geometry"]["los_unit_vector_east_north_up"][0] > 0.5
    pair = next(g for g in catalog.search("GUNW", bbox=VENEZUELA) if g.granule_id == result.stats["pair"]["granule_id"])
    cut = gunw.read_window(pair, VENEZUELA)
    los = motion.analyse(
        cut.layers["unwrappedPhase"], cut.layers["coherenceMagnitude"], cut.wavelength_m,
        components=cut.layers["connectedComponents"], mask=cut.layers["mask"],
        ionosphere=cut.layers["ionospherePhaseScreen"], x=cut.x, y=cut.y,
    ).los_cm
    north_of_rupture = _box_median(cut, los, (-68.40, 10.58, -68.25, 10.70))
    south_of_rupture = _box_median(cut, los, (-68.40, 10.32, -68.25, 10.44))
    coast_south_of_offshore_rupture = _box_median(cut, los, (-67.60, 10.50, -67.40, 10.58))
    assert north_of_rupture > 15.0 and coast_south_of_offshore_rupture < -15.0
    assert north_of_rupture - south_of_rupture > 15.0


@pytest.mark.network
def test_real_pair_before_the_earthquakes_shows_no_signal():
    # same place and track, the pair that ends eleven days before the earthquakes
    result = motion.run_motion(MotionRequest(bbox=VENEZUELA, reference_date="2026-06-01", track=VENEZUELA_TRACK))
    assert result.status == "ok"
    assert result.stats["detection"]["outcome"] == "no_signal"
    assert result.summary.headline.startswith("No ground motion above the ")


@pytest.mark.network
def test_real_unsupported_cases():
    no_date = motion.run_motion(MotionRequest(bbox=KAMLOOPS, reference_date="2020-01-01"))
    assert no_date.status == "unsupported" and no_date.stats["available_pairs"]
    ocean = motion.run_motion(MotionRequest(bbox=(-140.0, -50.0, -139.5, -49.5)))  # open South Pacific
    assert ocean.status == "unsupported"

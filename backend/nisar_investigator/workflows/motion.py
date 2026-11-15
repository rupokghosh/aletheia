"""Workflow C: ground motion along the radar line of sight from one of NASA's ready-made NISAR GUNW pairs.

Sign convention (checked, because a wrong sign turns uplift into subsidence)
----------------------------------------------------------------------------
NISAR interferograms are formed by ISCE3 as  reference x conj(secondary), with the reference being the
EARLIER acquisition, and a radar echo carries the phase -4*pi*R/wavelength. The unwrapped phase is therefore
+4*pi/wavelength * (R_secondary - R_reference): POSITIVE PHASE = THE RANGE GREW = THE GROUND MOVED AWAY FROM
THE SATELLITE. This workflow reports displacement as positive TOWARD the satellite, so

    los_cm = -wavelength / (4*pi) * unwrappedPhase * 100

Sources:
- NISAR L2 GUNW product specification, JPL D-102272 Rev E, section 2.2 (linked from the ASF NISAR Data User
  Guide, https://nisar-docs.asf.alaska.edu/gunw/). It defines the layers and states that the ionosphere screen
  and the troposphere / solid-earth-tide corrections are provided but NOT applied to the unwrapped phase. It
  does not spell out the phase sign, so the sign rests on the two items below and on the data checks.
- ARIA-tools README, "Standardized Date and Phase Convention": NISAR GUNW uses the opposite date order and
  phase sign from the ARIA convention (in which positive means toward the sensor).
- MintPy FAQ, "sign convention of the line-of-sight data": for date1_date2 interferograms with date1 earlier
  (the ISCE convention), positive phase is motion away from the satellite.
- Check against independent seismology (tests/test_motion.py::test_real_signal_case_venezuela_earthquakes).
  The USGS moment tensors of the 24 June 2026 Venezuela earthquakes (M7.5 us6000t7zp: strike 86, dip 74,
  rake -176; M7.2 us6000t7zc: strike 270, dip 74, rake -169) are right-lateral slip on east-west planes, so
  ground north of the rupture moved east and ground south of it moved west. On track 162 the satellite is to
  the east-north-east (line-of-sight east component +0.63), so north must come out positive (toward) and
  south negative (away). With the sign above the pair of 13 -> 25 June gives +30 cm north of the on-land
  rupture and -37 cm on the coast south of the offshore rupture. The opposite sign would make both
  earthquakes left-lateral.
- Check against known subsidence: the mean of five 12-day pairs over Mexico City (track 19, August to October
  2026) shows the former lake bed and the Chalco-Tlahuac belt, which sink by tens of centimetres a year,
  as negative (about -1 cm per pair). Sinking ground moves away from any satellite, so negative = away.
- Check of the ionosphere sign: subtracting NASA's screen lowered the robust scatter on 13 of 17 pairs over
  Kamloops (median 1.9 -> 1.1 cm) and on 26 of 27 quiet pairs over northern Venezuela (median 5.9 -> 2.0 cm,
  with screens of up to 100 cm across the window).

Honesty rules of this workflow
------------------------------
- Motion is relative: the median of the usable pixels in the window is set to zero.
- Every headline number is a range over the processing choices (coherence threshold, ionosphere correction,
  ramp removal), never a bare value.
- "Signal" is declared only when the displacement range clearly exceeds what noise alone produces.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date

import numpy as np

from .. import catalog, charts, gunw, ops, provenance, render
from ..remote import RemoteAccessError
from ..schemas import (
    BBox,
    Caveat,
    Download,
    Granule,
    Layer,
    Legend,
    Metric,
    MotionRequest,
    Sensitivity,
    Summary,
    Uncertainty,
    WorkflowResult,
)
from . import common

# ---------------------------------------------------------------- constants

COHERENCE_THRESHOLD = 0.3  # pixels with lower interferometric coherence are masked
COHERENCE_SENSITIVITY = (0.2, 0.3, 0.4)  # thresholds reported side by side
# NASA ships its ionosphere estimate as a separate layer and leaves the unwrapped phase uncorrected. At L-band
# the ionosphere is the largest error source (30 cm across one frame was measured over Venezuela), so it is
# subtracted by default; the result without it is always reported next to it.
APPLY_IONOSPHERE = True
REMOVE_RAMP = False  # a fitted plane can swallow real motion, so it is off unless asked for

# One 12-day pair typically carries 1 to 2 cm of atmospheric noise (spread across tens of kilometres).
TYPICAL_ATMOSPHERE_CM = (1.0, 2.0)
NOISE_FLOOR_CM = 1.0  # the noise level is never taken to be smaller than this, however quiet the window looks
NOISE_CEILING_CM = 2.5  # ... and a spread larger than this is not allowed to pass itself off as noise
# "Clearly exceeds the noise" means the 1st-to-99th percentile range is beyond DETECTION_FACTOR x the noise
# level. For normally distributed noise that ratio is 4.65. The factor and the ceiling were calibrated on 44
# real pairs that span no earthquake: 17 over Kamloops (June to October 2026) and 27 over northern Venezuela
# (April to October 2026, a far harder tropical case with up to 100 cm of ionosphere across the window).
# Their range-to-spread ratio ran from 2.6 to 6.9 (with and without a ramp removed) and their largest range
# was 15.9 cm, so 9 x a noise level of at most 2.5 cm (22.5 cm) leaves a margin of at least 30 % on every one
# of them. A factor of 6 was tried first and called one quiet pair a signal. The two pairs that do span the
# 24 June 2026 Venezuela earthquakes reach 59 and 74 cm.
DETECTION_FACTOR = 9.0
# A deformation field that fills the window (the two sides of a fault) has a flat distribution: a huge spread
# but a modest range-to-spread ratio. After ramp removal the 44 quiet pairs never had a spread above 2.8 cm,
# so a ramp-removed spread beyond twice the ceiling is accepted as motion on its own.
SPREAD_IS_MOTION_CM = 2.0 * NOISE_CEILING_CM
GAUSSIAN_P1_P99 = 4.65
NOISE_ONLY_RATIO_RANGE = (2.6, 6.9)  # measured on the 44 quiet pairs above
CHANCE_ABOVE_2X = 0.0455  # fraction of pure-noise pixels beyond 2 x the spread
CHANCE_ABOVE_3X = 0.0027

MIN_VALID_PIXELS = 400  # 2.6 km2 at 80 m: below this no statistic is meaningful
MIN_VALID_FRACTION = 0.02
LOCAL_TILE = 32  # pixels (2.6 km): tile size for the small-scale scatter estimate
NOMINAL_PIXEL_M = 80.0
MIN_COVERAGE_RATIO = 0.9  # a pair must cover at least this share of what the best-covering pair covers

SIGN_CONVENTION = (
    "Positive values mean the ground moved toward the satellite (for example uplift); negative values mean it "
    "moved away from the satellite (for example subsidence)."
)

_TIER_TEXT = {
    "beta": "This pair is beta-tier: NASA has not yet validated its phase calibration, so treat values as preliminary.",
    "provisional": "This pair is provisional-tier: calibrated, but values may change after NASA reprocesses it.",
    "validated": "This pair is validated-tier.",
}


# ----------------------------------------------------------- pure functions


def phase_to_los_cm(phase_rad: np.ndarray, wavelength_m: float) -> np.ndarray:
    """Unwrapped phase (radians) to line-of-sight displacement in centimetres, positive toward the satellite."""
    return -wavelength_m / (4.0 * np.pi) * np.asarray(phase_rad, dtype=np.float64) * 100.0


def usable_base(phase: np.ndarray, components: np.ndarray | None, mask: np.ndarray | None) -> np.ndarray:
    """Pixels that carry a reliably unwrapped phase over land, before any coherence threshold."""
    ok = np.isfinite(phase)
    if components is not None:
        ok &= (components != 0) & (components != gunw.CC_FILL)  # 0 = not unwrapped reliably, 65535 = no data
    if mask is not None:
        ok &= gunw.valid_sample_mask(mask) & ~gunw.water_mask(mask)
    return ok


def valid_pixels(
    phase: np.ndarray,
    coherence: np.ndarray,
    components: np.ndarray | None = None,
    mask: np.ndarray | None = None,
    *,
    threshold: float = COHERENCE_THRESHOLD,
) -> np.ndarray:
    """Boolean mask of pixels used for statistics: unwrapped, on land, coherence at or above the threshold."""
    with np.errstate(invalid="ignore"):
        return usable_base(phase, components, mask) & (coherence >= threshold)


def mask_breakdown(
    phase: np.ndarray,
    coherence: np.ndarray,
    components: np.ndarray | None,
    mask: np.ndarray | None,
    threshold: float,
) -> dict[str, float]:
    """Why pixels were dropped, as exclusive fractions of the window (first matching reason wins)."""
    n = float(phase.size) or 1.0
    no_data = ~np.isfinite(phase)
    if components is not None:
        no_data |= components == gunw.CC_FILL
    if mask is not None:
        no_data |= ~gunw.valid_sample_mask(mask)
    water = ~no_data & (gunw.water_mask(mask) if mask is not None else False)
    seen = no_data | water
    not_unwrapped = ~seen & ((components == 0) if components is not None else False)
    seen |= not_unwrapped
    with np.errstate(invalid="ignore"):
        low_coherence = ~seen & ~(coherence >= threshold)
    seen |= low_coherence
    return {
        "valid_fraction": round(float((~seen).sum()) / n, 4),
        "masked_fraction": round(float(seen.sum()) / n, 4),
        "no_data_fraction": round(float(no_data.sum()) / n, 4),
        "water_fraction": round(float(water.sum()) / n, 4),
        "not_unwrapped_fraction": round(float(not_unwrapped.sum()) / n, 4),
        "low_coherence_fraction": round(float(low_coherence.sum()) / n, 4),
    }


def reference_to_median(los_cm: np.ndarray, valid: np.ndarray) -> tuple[np.ndarray, float]:
    """Subtract the median of the valid pixels. Returns (field with NaN outside `valid`, the median removed)."""
    if not valid.any():
        return np.full(los_cm.shape, np.nan), float("nan")
    offset = float(np.median(los_cm[valid]))
    return np.where(valid, los_cm - offset, np.nan), offset


def remove_plane(
    values: np.ndarray, valid: np.ndarray, x: np.ndarray, y: np.ndarray, max_points: int = 250_000
) -> tuple[np.ndarray, dict[str, float]]:
    """Least-squares plane through the valid pixels, subtracted everywhere.

    `x`, `y` are pixel-centre coordinates in metres. The returned dictionary gives the size of the plane across
    the window: positive `east_west_cm` means values rise toward the east, positive `north_south_cm` toward
    the north.
    """
    rows, cols = np.nonzero(valid)
    if rows.size < 3:
        return values.copy(), {"east_west_cm": 0.0, "north_south_cm": 0.0}
    step = max(1, rows.size // max_points)
    rows, cols = rows[::step], cols[::step]
    xk = (np.asarray(x, dtype=np.float64) - float(np.mean(x))) / 1000.0
    yk = (np.asarray(y, dtype=np.float64) - float(np.mean(y))) / 1000.0
    design = np.column_stack([np.ones(rows.size), xk[cols], yk[rows]])
    coef, *_ = np.linalg.lstsq(design, values[rows, cols].astype(np.float64), rcond=None)
    plane = coef[0] + coef[1] * xk[None, :] + coef[2] * yk[:, None]
    width_km = float(xk.max() - xk.min()) if xk.size > 1 else 0.0
    height_km = float(yk.max() - yk.min()) if yk.size > 1 else 0.0
    return values - plane, {
        "east_west_cm": round(float(coef[1]) * width_km, 2),
        "north_south_cm": round(float(coef[2]) * height_km, 2),
        "east_west_cm_per_km": round(float(coef[1]), 4),
        "north_south_cm_per_km": round(float(coef[2]), 4),
    }


def local_spread(field_cm: np.ndarray, tile: int = LOCAL_TILE) -> float | None:
    """Typical scatter inside small tiles (median of the per-tile 1.4826 x MAD).

    This is the short-distance part of the noise (decorrelation, small-scale turbulence). It is always smaller
    than the noise across a whole window, which also holds the slowly varying atmosphere.
    """
    rows, cols = (field_cm.shape[0] // tile) * tile, (field_cm.shape[1] // tile) * tile
    if rows == 0 or cols == 0:
        return None
    blocks = field_cm[:rows, :cols].reshape(rows // tile, tile, cols // tile, tile).swapaxes(1, 2)
    blocks = blocks.reshape(-1, tile * tile)
    enough = np.isfinite(blocks).sum(axis=1) >= tile * tile // 2
    if not enough.any():
        return None
    blocks = blocks[enough]
    centre = np.nanmedian(blocks, axis=1, keepdims=True)
    return float(np.median(1.4826 * np.nanmedian(np.abs(blocks - centre), axis=1)))


@dataclass(frozen=True)
class Settings:
    """One combination of processing choices."""

    coherence_threshold: float
    ionosphere: bool
    ramp: bool
    largest_component: bool = False


@dataclass
class FieldStats:
    """Statistics of one referenced displacement field (cm)."""

    n_valid: int
    valid_fraction: float
    reference_offset_cm: float
    spread_cm: float  # 1.4826 x MAD
    p1: float
    p5: float
    p95: float
    p99: float
    ramp: dict[str, float] | None = None

    @property
    def span_p5_p95(self) -> float:
        return self.p95 - self.p5

    @property
    def peak_to_peak(self) -> float:
        """Robust peak-to-peak: 1st to 99th percentile, so that a few bad pixels cannot set it."""
        return self.p99 - self.p1


@dataclass
class Decision:
    outcome: str  # "signal", "tilt_only" or "no_signal"
    noise_cm: float  # the noise level used for the decision and for the area metrics
    noise_basis: str  # "measured", "floor" or "ceiling"
    spread_cm: float  # robust spread of the default field
    threshold_cm: float
    peak_to_peak_min_cm: float  # smallest robust range over the processing choices (ramp setting as requested)
    peak_to_peak_other_ramp_cm: float | None  # the range with the opposite ramp setting
    inconclusive: bool = False  # no signal declared, yet the range is larger than any quiet pair showed

    @property
    def detected(self) -> bool:
        return self.outcome == "signal"


def detection_threshold_cm(spread_cm: float) -> float:
    """Range a field must exceed to count as motion: DETECTION_FACTOR x its spread, the spread being kept
    inside [NOISE_FLOOR_CM, NOISE_CEILING_CM]."""
    return DETECTION_FACTOR * float(np.clip(spread_cm, NOISE_FLOOR_CM, NOISE_CEILING_CM))


def decide_signal(
    spread_cm: float, peak_to_peak_cm: list[float], deramped: tuple[float, float] | None
) -> Decision:
    """Signal / no signal from the robust spread of the field and its robust range under each processing choice.

    `deramped` is (range, spread) of the field after a planar ramp was removed, or None if the field itself
    already had its ramp removed.

    - The noise level is the spread of the field, kept inside [NOISE_FLOOR_CM, NOISE_CEILING_CM]: a quiet
      window is not allowed to claim less noise than a 12-day pair typically has, and a spread too large to be
      atmosphere is not allowed to hide a signal by calling itself noise.
    - "Signal" needs the 1st-to-99th percentile range to exceed DETECTION_FACTOR x noise for EVERY processing
      choice, and the ramp-removed field still to stand out: its range passes the same test against its own
      spread, or its spread alone exceeds SPREAD_IS_MOTION_CM. If only the ramp makes the range large the
      outcome is "tilt_only": one pair cannot tell a tilt from an orbit or atmosphere artefact.
    """
    if not np.isfinite(spread_cm):
        return Decision("no_signal", NOISE_FLOOR_CM, "floor", float("nan"), DETECTION_FACTOR * NOISE_FLOOR_CM, 0.0, None)
    noise = float(np.clip(spread_cm, NOISE_FLOOR_CM, NOISE_CEILING_CM))
    basis = "floor" if spread_cm < NOISE_FLOOR_CM else "ceiling" if spread_cm > NOISE_CEILING_CM else "measured"
    threshold = detection_threshold_cm(spread_cm)
    smallest = float(min(peak_to_peak_cm))
    if smallest <= threshold:
        outcome = "no_signal"
    elif (
        deramped is not None
        and deramped[0] <= detection_threshold_cm(deramped[1])
        and deramped[1] <= SPREAD_IS_MOTION_CM
    ):
        outcome = "tilt_only"
    else:
        outcome = "signal"
    if outcome == "tilt_only":
        # the tilt is set aside: what remains is judged against the scatter of the ramp-removed field
        noise, basis = max(float(deramped[1]), NOISE_FLOOR_CM), "measured"
    elif outcome == "no_signal" and basis == "ceiling":
        noise, basis = float(spread_cm), "measured"  # nothing was attributed to motion: report the spread itself
    inconclusive = outcome == "no_signal" and smallest > NOISE_ONLY_RATIO_RANGE[1] * max(float(spread_cm), NOISE_FLOOR_CM)
    return Decision(
        outcome, noise, basis, float(spread_cm), threshold, smallest, deramped[0] if deramped else None, inconclusive
    )


@dataclass
class Analysis:
    """Everything computed from one window, before it is turned into pictures and words."""

    los_cm: np.ndarray  # default field: referenced, NaN where masked
    settings: Settings
    variants: dict[str, tuple[Settings, FieldStats]]  # ordered; "default" first
    labels: dict[str, str]
    decision: Decision
    masking: dict[str, float]
    masked_by_threshold: dict[float, float]
    areas_km2: dict[float, tuple[float, float]]  # coherence threshold -> (area beyond 2x noise, beyond 3x noise)
    ionosphere: dict
    local_noise_cm: float | None
    decorrelation_noise_cm: float | None
    n_components: int
    median_coherence: float | None
    extremes_cm: tuple[float, float] = (float("nan"), float("nan"))  # min, max of the default field
    seconds: float = 0.0
    notes: list[str] = field(default_factory=list)

    @property
    def default(self) -> FieldStats:
        return self.variants["default"][1]


def analyse(
    phase: np.ndarray,
    coherence: np.ndarray,
    wavelength_m: float,
    *,
    components: np.ndarray | None = None,
    mask: np.ndarray | None = None,
    ionosphere: np.ndarray | None = None,
    ionosphere_uncertainty: np.ndarray | None = None,
    x: np.ndarray | None = None,
    y: np.ndarray | None = None,
    pixel_area_km2: float = NOMINAL_PIXEL_M**2 / 1e6,
    looks: int | None = None,
    coherence_threshold: float = COHERENCE_THRESHOLD,
    apply_ionosphere: bool = APPLY_IONOSPHERE,
    remove_ramp: bool = REMOVE_RAMP,
) -> Analysis:
    """Phase to referenced line-of-sight displacement, with every sensitivity variant and the signal decision.

    Pure numpy: no network, no files. Arrays are (rows, cols), north-up.
    """
    t0 = time.time()
    phase = np.asarray(phase, dtype=np.float64)
    coherence = np.asarray(coherence, dtype=np.float64)
    x = np.arange(phase.shape[1]) * NOMINAL_PIXEL_M if x is None else np.asarray(x, dtype=np.float64)
    y = -np.arange(phase.shape[0]) * NOMINAL_PIXEL_M if y is None else np.asarray(y, dtype=np.float64)

    los_raw = phase_to_los_cm(phase, wavelength_m)
    base = usable_base(phase, components, mask)
    iono_cm = None
    if ionosphere is not None:
        candidate = phase_to_los_cm(ionosphere, wavelength_m)
        if base.any() and np.isfinite(candidate[base]).mean() >= 0.5:
            iono_cm = candidate
    use_iono = bool(apply_ionosphere and iono_cm is not None)

    labels_present: np.ndarray = np.array([], dtype=np.int64)
    largest_label = None
    if components is not None and base.any():
        labels_present, counts = np.unique(components[base], return_counts=True)
        largest_label = int(labels_present[np.argmax(counts)])

    def build(s: Settings) -> tuple[np.ndarray, FieldStats]:
        los = los_raw - iono_cm if (s.ionosphere and iono_cm is not None) else los_raw
        with np.errstate(invalid="ignore"):
            valid = base & (coherence >= s.coherence_threshold) & np.isfinite(los)
        if s.largest_component and largest_label is not None:
            valid &= components == largest_label
        ramp = None
        if s.ramp:
            los, ramp = remove_plane(los, valid, x, y)
        referenced, offset = reference_to_median(los, valid)
        values = referenced[valid]
        if values.size == 0:
            nan = float("nan")
            return referenced, FieldStats(0, 0.0, nan, nan, nan, nan, nan, nan, ramp)
        p1, p5, p95, p99 = (float(v) for v in np.percentile(values, [1, 5, 95, 99]))
        stats = FieldStats(
            n_valid=int(values.size),
            valid_fraction=float(values.size) / float(phase.size),
            reference_offset_cm=offset,
            spread_cm=ops.robust_sigma(values),
            p1=p1,
            p5=p5,
            p95=p95,
            p99=p99,
            ramp=ramp,
        )
        return referenced, stats

    default = Settings(coherence_threshold, use_iono, remove_ramp)
    variants: dict[str, tuple[Settings, FieldStats]] = {}
    labels: dict[str, str] = {}
    fields: dict[str, np.ndarray] = {}

    def add(key: str, label: str, s: Settings, keep: bool = False) -> None:
        referenced, stats = build(s)
        variants[key], labels[key] = (s, stats), label
        if keep:
            fields[key] = referenced

    add("default", "default settings", default, keep=True)
    thresholds = sorted(set(COHERENCE_SENSITIVITY) | {coherence_threshold})
    for thr in thresholds:
        key = f"coherence_{thr:g}"
        if thr == coherence_threshold:
            variants[key], labels[key], fields[key] = variants["default"], f"coherence >= {thr:g}", fields["default"]
        else:
            add(key, f"coherence >= {thr:g}", Settings(thr, use_iono, remove_ramp), keep=True)
    if iono_cm is not None:
        add(
            "ionosphere_applied" if not use_iono else "ionosphere_not_applied",
            "ionosphere correction applied" if not use_iono else "ionosphere correction not applied",
            Settings(coherence_threshold, not use_iono, remove_ramp),
        )
    add(
        "ramp_removed" if not remove_ramp else "ramp_kept",
        "planar ramp removed" if not remove_ramp else "planar ramp kept",
        Settings(coherence_threshold, use_iono, not remove_ramp),
    )
    if labels_present.size > 1:
        add(
            "largest_component",
            "largest unwrapped region only",
            Settings(coherence_threshold, use_iono, remove_ramp, largest_component=True),
        )

    los_cm = fields["default"]
    stats0 = variants["default"][1]
    same_ramp = [st.peak_to_peak for s, st in variants.values() if s.ramp == remove_ramp and st.n_valid]
    other_ramp = [st for s, st in variants.values() if s.ramp != remove_ramp and st.n_valid]
    deramped = None
    if not remove_ramp and other_ramp:
        deramped = (float(other_ramp[0].peak_to_peak), float(other_ramp[0].spread_cm))
    decision = decide_signal(stats0.spread_cm, same_ramp or [0.0], deramped)
    if remove_ramp and other_ramp:
        decision.peak_to_peak_other_ramp_cm = float(other_ramp[0].peak_to_peak)

    areas: dict[float, tuple[float, float]] = {}
    masked_by_threshold: dict[float, float] = {}
    for thr in thresholds:
        f = fields[f"coherence_{thr:g}"]
        with np.errstate(invalid="ignore"):
            areas[thr] = (
                ops.area_km2(np.abs(f) > 2 * decision.noise_cm, pixel_area_km2),
                ops.area_km2(np.abs(f) > 3 * decision.noise_cm, pixel_area_km2),
            )
        masked_by_threshold[thr] = round(1.0 - variants[f"coherence_{thr:g}"][1].valid_fraction, 4)

    valid0 = np.isfinite(los_cm)
    iono_info: dict = {"available": iono_cm is not None, "applied": use_iono}
    if iono_cm is not None and valid0.any():
        screen = iono_cm[valid0]
        screen = screen[np.isfinite(screen)]
        q = np.percentile(screen, [0, 1, 5, 95, 99, 100])
        iono_info.update(
            range_cm=round(float(q[4] - q[1]), 2),  # 1st to 99th percentile across the usable pixels
            range_p5_p95_cm=round(float(q[3] - q[2]), 2),
            range_min_max_cm=round(float(q[5] - q[0]), 2),
        )
        if ionosphere_uncertainty is not None:
            unc = np.abs(phase_to_los_cm(ionosphere_uncertainty, wavelength_m))[valid0]
            unc = unc[np.isfinite(unc)]
            if unc.size:
                iono_info["uncertainty_median_cm"] = round(float(np.median(unc)), 2)

    decorrelation = None
    median_coherence = None
    if valid0.any():
        gamma = np.clip(coherence[valid0], 1e-3, 0.9999)
        median_coherence = round(float(np.median(gamma)), 3)
        if looks:
            # Cramer-Rao bound on the phase standard deviation of a multilooked interferogram
            sigma_phase = np.sqrt((1.0 - gamma**2) / (2.0 * looks * gamma**2))
            decorrelation = round(float(np.median(sigma_phase)) * wavelength_m / (4.0 * np.pi) * 100.0, 3)

    local = local_spread(los_cm)
    return Analysis(
        los_cm=los_cm,
        settings=default,
        variants=variants,
        labels=labels,
        decision=decision,
        masking=mask_breakdown(phase, coherence, components, mask, coherence_threshold),
        masked_by_threshold=masked_by_threshold,
        areas_km2=areas,
        ionosphere=iono_info,
        local_noise_cm=round(local, 3) if local is not None else None,
        decorrelation_noise_cm=decorrelation,
        n_components=int(labels_present.size),
        median_coherence=median_coherence,
        extremes_cm=(float(np.nanmin(los_cm)), float(np.nanmax(los_cm))) if valid0.any() else (float("nan"),) * 2,
        seconds=round(time.time() - t0, 2),
    )


# ------------------------------------------------------------ pair selection


def _days(pair: Granule) -> int:
    return (date.fromisoformat(pair.secondary_date) - date.fromisoformat(pair.reference_date)).days


def _pair_dict(pair: Granule, coverage: float | None = None) -> dict:
    out = {
        "reference_date": pair.reference_date,
        "secondary_date": pair.secondary_date,
        "days": _days(pair),
        "track": pair.track,
        "direction": pair.direction,
        "frame": pair.frame,
        "tier": pair.tier,
    }
    if coverage is not None:
        out["coverage_of_area"] = round(coverage, 3)
    return out


def choose_pair(
    pairs: list[Granule], bbox: BBox, reference_date: str | None = None, track: int | None = None
) -> tuple[Granule | None, list[tuple[Granule, float]]]:
    """Pick the pair to analyse. Returns (pair or None, the pairs worth offering with the share of the box each covers).

    Pairs worth offering are those that cover the box about as well as the best-covering pair does: frames that
    only clip a corner are left out of the list and of the default choice. A requested reference date or track
    is honoured even for such a frame. Among the candidates the latest reference date wins, then the shortest
    time span, the larger coverage and the better calibration tier.
    """
    overlapping = [(g, common.footprint_fraction(g.footprint, bbox)) for g in pairs if g.reference_date and g.secondary_date]
    overlapping = [(g, c) for g, c in overlapping if c > 0]
    overlapping.sort(key=lambda gc: (gc[0].reference_date, gc[0].secondary_date, gc[0].track, gc[0].frame))

    def well_covering(items: list[tuple[Granule, float]]) -> list[tuple[Granule, float]]:
        best = max((c for _, c in items), default=0.0)
        return [(g, c) for g, c in items if c >= MIN_COVERAGE_RATIO * best]

    offered = well_covering(overlapping)
    if reference_date is None and track is None:
        candidates = offered
    else:
        candidates = well_covering([
            (g, c) for g, c in overlapping
            if (track is None or g.track == track) and (reference_date is None or g.reference_date == reference_date)
        ])
    if not candidates:
        return None, offered
    chosen = max(candidates, key=lambda gc: (gc[0].reference_date, -_days(gc[0]), gc[1], -catalog.TIER_RANK[gc[0].tier]))
    return chosen[0], offered


def _no_pair_headline(usable: list[tuple[Granule, float]], reference_date: str | None, track: int | None) -> str:
    if not usable:
        return (
            "NASA has no ready-made ground-motion products (GUNW interferogram pairs) for this place yet, "
            "so motion cannot be measured here."
        )
    first = min(g.reference_date for g, _ in usable)
    last = max(usable, key=lambda gc: (gc[0].secondary_date, gc[0].reference_date))[0]
    tracks = sorted({g.track for g, _ in usable})
    have = (
        f"NASA's motion products for this place start on {common.pretty_date(first)} and stop on "
        f"{common.pretty_date(last.secondary_date)} ({len(usable)} pairs on "
        f"track{'s' if len(tracks) > 1 else ''} {common.join_words([str(t) for t in tracks])}); the most recent pair "
        f"runs from {common.pretty_date(last.reference_date)} to {common.pretty_date(last.secondary_date)} "
        f"on track {last.track}."
    )
    if reference_date is not None:
        on_track = f" on track {track}" if track is not None else ""
        return f"There is no motion pair that starts on {common.pretty_date(reference_date)}{on_track}. {have}"
    return f"There is no motion pair on track {track}. {have}"


# ----------------------------------------------------------------- wording


def _span(first: str, last: str) -> str:
    """'5 and 17 October 2026', falling back to the longer form when the month or year differs."""
    a, b = date.fromisoformat(first), date.fromisoformat(last)
    if (a.year, a.month) == (b.year, b.month):
        return f"{a.day} and {b.day} {b:%B %Y}"
    return common.pretty_span(first, last)


def _cm(value: float) -> str:
    """Centimetres for a sentence: whole numbers from 10 cm up, one decimal below."""
    return f"{value:.0f}" if abs(value) >= 9.95 else f"{value:.1f}"


def _range_text(low: float, high: float) -> str:
    a, b = _cm(low), _cm(high)
    return f"about {a} cm" if a == b else f"{a} to {b} cm"


_COMPASS = (
    "north", "north-north-east", "north-east", "east-north-east", "east", "east-south-east", "south-east",
    "south-south-east", "south", "south-south-west", "south-west", "west-south-west", "west",
    "west-north-west", "north-west", "north-north-west",
)


def _bearing(east: float, north: float) -> str:
    angle = float(np.degrees(np.arctan2(east, north))) % 360.0
    return _COMPASS[int((angle + 11.25) // 22.5) % 16]


def _nice_limit(value: float) -> float:
    """Round a colour-scale limit up to a tidy number."""
    for step in (2, 3, 5, 8, 10, 15, 20, 30, 40, 50, 75, 100, 150, 200, 300, 500):
        if value <= step:
            return float(step)
    return float(np.ceil(value / 100.0) * 100.0)


def _check_bbox(bbox: BBox) -> None:
    west, south, east, north = bbox
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        raise common.RequestProblem(
            "bbox must be [west, south, east, north] in degrees, with west < east and south < north."
        )
    width_m = (east - west) * 111_320 * float(np.cos(np.radians((south + north) / 2)))
    height_m = (north - south) * 110_574
    pixels = width_m * height_m / NOMINAL_PIXEL_M**2
    if pixels > gunw.MAX_WINDOW_PIXELS:
        raise common.RequestProblem(
            f"The area is too large for one motion request: about {width_m * height_m / 1e6:,.0f} km2. The limit is "
            f"about {gunw.MAX_WINDOW_PIXELS * NOMINAL_PIXEL_M**2 / 1e6:,.0f} km2. Draw a smaller area.",
            status="unsupported",
        )


def _reproduce(pair: Granule, bbox: BBox, s: Settings) -> str:
    phase = 'cut.layers["unwrappedPhase"]'
    if s.ionosphere:
        phase += ' - cut.layers["ionospherePhaseScreen"]  # NASA\'s ionosphere estimate, subtracted'
    ramp_import = "from nisar_investigator.workflows.motion import remove_plane\n" if s.ramp else ""
    ramp = "los_cm, ramp = remove_plane(los_cm, ok, cut.x, cut.y)\n" if s.ramp else ""
    return (
        "# pip install -e backend/   (needs an Earthdata Login in ~/.netrc)\n"
        "import numpy as np\n"
        "from nisar_investigator import catalog, gunw\n"
        f"{ramp_import}"
        "\n"
        f"bbox = {tuple(round(float(v), 6) for v in bbox)!r}  # west, south, east, north\n"
        f'granule_id = "{pair.granule_id}"\n'
        'pair = next(g for g in catalog.search("GUNW", bbox=bbox) if g.granule_id == granule_id)\n'
        "cut = gunw.read_window(pair, bbox)  # reads only this window over HTTPS\n"
        "\n"
        f"phase = {phase}\n"
        "los_cm = -cut.wavelength_m / (4 * np.pi) * phase * 100  # positive = toward the satellite\n"
        'cc, mask = cut.layers["connectedComponents"], cut.layers["mask"]\n'
        f'ok = (np.isfinite(los_cm) & (cut.layers["coherenceMagnitude"] >= {s.coherence_threshold:g})\n'
        "      & (cc != 0) & (cc != gunw.CC_FILL) & gunw.valid_sample_mask(mask) & ~gunw.water_mask(mask))\n"
        f"{ramp}"
        "los_cm = np.where(ok, los_cm - np.median(los_cm[ok]), np.nan)  # relative to the window median\n"
        "\n"
        "p1, p5, p95, p99 = np.nanpercentile(los_cm, [1, 5, 95, 99])\n"
        "spread = 1.4826 * np.nanmedian(np.abs(los_cm - np.nanmedian(los_cm)))\n"
        'print(f"robust spread {spread:.2f} cm, 5th-95th percentile span {p95 - p5:.2f} cm, "\n'
        '      f"1st-99th percentile range {p99 - p1:.2f} cm, usable pixels {ok.mean():.1%}")\n'
        "\n"
        "# or the whole workflow, with sensitivity analysis, maps and receipt:\n"
        "from nisar_investigator.schemas import MotionRequest\n"
        "from nisar_investigator.workflows.motion import run_motion\n"
        f'result = run_motion(MotionRequest(bbox=bbox, reference_date="{pair.reference_date}", track={pair.track}))\n'
        "print(result.summary.headline)\n"
    )


def _sensitivity(res: Analysis) -> list[Sensitivity]:
    """The headline range under each processing choice, one row per choice."""
    d0 = res.default
    sensitivity: list[Sensitivity] = []
    for thr in sorted(res.areas_km2):
        st = res.variants[f"coherence_{thr:g}"][1]
        sensitivity.append(Sensitivity(parameter="coherence threshold", value=thr, result=round(st.peak_to_peak, 2),
                                       unit="cm range (1st to 99th percentile)"))
    for thr in sorted(res.areas_km2):
        sensitivity.append(Sensitivity(parameter="coherence threshold", value=thr,
                                       result=round(res.areas_km2[thr][1], 1), unit="km2 beyond 3 x noise"))
    pairs_of_choices = [("ionosphere correction", "ionosphere_applied", "ionosphere_not_applied", "applied", "not applied",
                         res.settings.ionosphere),
                        ("planar ramp", "ramp_removed", "ramp_kept", "removed", "kept", res.settings.ramp)]
    for parameter, key_on, key_off, word_on, word_off, default_on in pairs_of_choices:
        other_key = key_off if default_on else key_on
        if other_key not in res.variants:
            continue
        on = d0 if default_on else res.variants[other_key][1]
        off = res.variants[other_key][1] if default_on else d0
        for word, st in ((word_on, on), (word_off, off)):
            sensitivity.append(Sensitivity(parameter=parameter, value=word, result=round(st.peak_to_peak, 2),
                                           unit="cm range (1st to 99th percentile)"))
            sensitivity.append(Sensitivity(parameter=parameter, value=word, result=round(st.spread_cm, 2),
                                           unit="cm robust spread"))
    if "largest_component" in res.variants:
        st = res.variants["largest_component"][1]
        sensitivity.append(Sensitivity(parameter="unwrapped regions used", value="largest only",
                                       result=round(st.peak_to_peak, 2), unit="cm range (1st to 99th percentile)"))
    return sensitivity


def _caveats(pair: Granule, geometry: dict, wavelength: float, ionosphere_applied: bool) -> list[Caveat]:
    """What a reader must keep in mind, in plain words."""
    look = ""
    if "incidence_deg" in geometry:
        e, n, u = geometry["los_unit_vector_east_north_up"]
        look = (
            f" The radar looked down at {geometry['incidence_deg']:.0f} degrees from vertical with the satellite to "
            f"the {geometry['satellite_is_to_the']}: one centimetre here is {u:.2f} x upward + {e:+.2f} x eastward "
            f"+ {n:+.2f} x northward motion."
        )
    caveats = [
        Caveat(code="line_of_sight",
               text="This is motion along the radar's slanted line of sight, not vertical motion and not full 3-D "
                    "motion. Horizontal and vertical movement are mixed together." + look),
        Caveat(code="relative_motion",
               text="Values are relative to the median of the usable pixels in the drawn area, not to a stable "
                    "reference point. If the whole area moved together, that shared motion is invisible here."),
        Caveat(code="atmosphere",
               text="Water vapour in the atmosphere delays the radar signal differently on the two dates and "
                    "typically adds 1 to 2 cm of smooth, false motion to a single pair. No atmospheric "
                    "(troposphere) correction was applied."),
        Caveat(code="ionosphere",
               text="NISAR's L-band radar is strongly affected by the ionosphere. "
                    + ("NASA's ionosphere estimate was subtracted, but that estimate has its own error and is "
                       "interpolated across gaps." if ionosphere_applied else
                       "No ionosphere correction was applied, so smooth patterns of several centimetres can be "
                       "ionosphere rather than ground motion.")),
        Caveat(code="unwrapping",
               text=f"Turning fringes into continuous motion (phase unwrapping) can slip by whole fringes of "
                    f"{wavelength * 50:.1f} cm across gaps of low coherence such as water, forest, steep slopes or "
                    f"a fault rupture. Sharp steps of about that size should be treated as suspect."),
        Caveat(code=f"tier_{pair.tier}", text=_TIER_TEXT[pair.tier]),
        Caveat(code="single_pair",
               text=f"The pair spans only {_days(pair)} days ({common.pretty_date(pair.reference_date)} to "
                    f"{common.pretty_date(pair.secondary_date)}). It shows what moved between those two passes and "
                    f"cannot show slow motion, timing within the interval, or whether motion continued afterwards."),
    ]
    return caveats


def _notes(
    res: Analysis,
    *,
    threshold: float,
    want_ramp: bool,
    spreads_cm: tuple[float, float],
    valid_area: float,
    wavelength: float,
    looks: int | None,
    coverage: float,
) -> list[str]:
    """Uncertainty notes: how the numbers were obtained and how far they can be trusted, in plain words."""
    d0, decision, iono = res.default, res.decision, res.ionosphere
    sigma_low, sigma_high = spreads_cm
    notes = [
        f"Displacement is measured along the radar line of sight and is relative: the median of the usable "
        f"pixels in the window ({d0.reference_offset_cm:+.1f} cm before referencing) was set to zero. {SIGN_CONVENTION}",
        f"Empirical noise level: the robust spread of the motion field (1.4826 x median absolute deviation) is "
        f"{d0.spread_cm:.2f} cm, and {sigma_low:.2f} to {sigma_high:.2f} cm across the processing choices.",
        f"A single 12-day pair typically carries about {TYPICAL_ATMOSPHERE_CM[0]:.0f} to "
        f"{TYPICAL_ATMOSPHERE_CM[1]:.0f} cm of atmospheric noise, so smaller signals cannot be trusted. The noise "
        f"level is therefore never taken below {NOISE_FLOOR_CM:.0f} cm.",
        f"Decision rule: motion is reported only if the 1st-to-99th percentile range exceeds "
        f"{DETECTION_FACTOR:.0f} x the noise level ({decision.threshold_cm:.1f} cm here) for every processing choice "
        f"and the field still stands out after a planar ramp is removed (same test, or a spread above "
        f"{SPREAD_IS_MOTION_CM:g} cm). Ideal noise gives "
        f"{GAUSSIAN_P1_P99} x; 44 real NISAR pairs without an earthquake gave {NOISE_ONLY_RATIO_RANGE[0]} to "
        f"{NOISE_ONLY_RATIO_RANGE[1]} x. Smallest range found: {decision.peak_to_peak_min_cm:.1f} cm"
        + (f"; after ramp removal: {decision.peak_to_peak_other_ramp_cm:.1f} cm." if not want_ramp and
           decision.peak_to_peak_other_ramp_cm is not None else "."),
        f"{res.masking['masked_fraction']:.0%} of the window was masked: "
        f"{res.masking['low_coherence_fraction']:.0%} coherence below {threshold:g}, "
        f"{res.masking['water_fraction']:.0%} water, {res.masking['not_unwrapped_fraction']:.0%} not reliably "
        f"unwrapped, {res.masking['no_data_fraction']:.0%} no data.",
    ]
    if decision.noise_basis == "ceiling":
        notes.append(
            f"The field's spread ({d0.spread_cm:.1f} cm) is far larger than atmosphere can explain, so it is "
            f"attributed to motion and the noise level is set to {NOISE_CEILING_CM:g} cm, the largest value this "
            f"workflow accepts as atmosphere, rather than measured."
            + (f" Scatter over short distances (2.6 km tiles) is {res.local_noise_cm:.2f} cm." if res.local_noise_cm else "")
        )
    elif res.local_noise_cm is not None:
        notes.append(
            f"Scatter over short distances (2.6 km tiles) is {res.local_noise_cm:.2f} cm; the rest of the noise "
            f"varies slowly across the window, as atmosphere does."
        )
    if decision.inconclusive:
        notes.append(
            f"Inconclusive: the range is {decision.peak_to_peak_min_cm / max(d0.spread_cm, NOISE_FLOOR_CM):.1f} x the "
            f"spread, more than any of the 44 quiet pairs showed but short of the {DETECTION_FACTOR:.0f} x needed to "
            f"call it motion. A second pair over the same dates (another track) could settle it."
        )
    if decision.outcome != "signal":
        share3 = res.areas_km2[threshold][1] / valid_area if valid_area else 0.0
        notes.append(
            f"{share3:.1%} of the usable area lies beyond 3 x the noise level; pure noise would put about "
            f"{CHANCE_ABOVE_3X:.1%} there, and about {CHANCE_ABOVE_2X:.1%} beyond 2 x. Areas close to these "
            f"shares are not evidence of motion."
        )
    if iono.get("range_cm") is not None:
        other = res.variants.get("ionosphere_not_applied" if iono["applied"] else "ionosphere_applied")
        unc = f" NASA's own uncertainty for that estimate is {iono['uncertainty_median_cm']:.1f} cm (median)." \
            if iono.get("uncertainty_median_cm") is not None else ""
        if iono["applied"]:
            notes.append(
                f"Ionosphere: NASA's ionosphere phase screen spans {iono['range_cm']:.1f} cm across the usable "
                f"area. NASA ships it as a separate layer and does not apply it; here it WAS subtracted. Without "
                f"it the robust spread would be {other[1].spread_cm:.2f} cm instead of {d0.spread_cm:.2f} cm." + unc
            )
        else:
            notes.append(
                f"Ionosphere: NASA's ionosphere phase screen spans {iono['range_cm']:.1f} cm across the usable "
                f"area. It was NOT subtracted, so up to that much of the pattern may be ionosphere rather than "
                f"ground motion. With it subtracted the robust spread would be {other[1].spread_cm:.2f} cm "
                f"instead of {d0.spread_cm:.2f} cm." + unc
            )
    else:
        notes.append(
            "Ionosphere: this pair carries no usable ionosphere estimate, so nothing was corrected. At L-band the "
            "ionosphere can add a smooth pattern of several centimetres or more."
        )
    ramp_stats = res.variants.get("ramp_removed" if not want_ramp else "default")
    if ramp_stats and ramp_stats[1].ramp:
        r = ramp_stats[1].ramp
        notes.append(
            f"Planar ramp: a best-fit plane changes by {r['east_west_cm']:+.1f} cm from west to east and "
            f"{r['north_south_cm']:+.1f} cm from south to north across the window. It was "
            f"{'removed' if want_ramp else 'kept (a ramp can be real motion)'}."
        )
    if res.n_components > 1:
        notes.append(
            f"The window holds {res.n_components} separately unwrapped regions. Offsets between them can be wrong "
            f"by multiples of {wavelength * 50:.1f} cm (half a wavelength); the result for the largest region alone "
            f"is listed in the sensitivity table."
        )
    if res.decorrelation_noise_cm is not None:
        notes.append(
            f"Noise from loss of coherence alone is about {res.decorrelation_noise_cm:.2f} cm per pixel "
            f"(median coherence {res.median_coherence}, {looks} looks): the noise here is mostly atmospheric, "
            f"not instrumental."
        )
    if coverage < 0.98:
        notes.append(f"The chosen pair covers about {coverage:.0%} of the requested area; the rest is outside its frame.")
    return notes


# ---------------------------------------------------------------- workflow


def run_motion(
    req: MotionRequest,
    *,
    coherence_threshold: float | None = None,
    remove_ramp: bool | None = None,
    apply_ionosphere: bool | None = None,
    use_cache: bool = True,
) -> WorkflowResult:
    """Line-of-sight ground motion for a box from one NISAR GUNW pair, with noise level, ranges and receipt.

    The keyword options are not part of the v1 request contract; if `MotionRequest` later gains optional fields
    with the same names they are honoured too.
    """
    t_start = time.time()

    def option(name: str, explicit, default):
        if explicit is not None:
            return explicit
        value = getattr(req, name, None)
        return default if value is None else value

    threshold = float(option("coherence_threshold", coherence_threshold, COHERENCE_THRESHOLD))
    want_ramp = bool(option("remove_ramp", remove_ramp, REMOVE_RAMP))
    want_iono = bool(option("apply_ionosphere", apply_ionosphere, APPLY_IONOSPHERE))
    request = req.model_dump(mode="json")
    rec = provenance.Recorder()

    try:
        _check_bbox(req.bbox)
        if req.reference_date is not None:
            common.parse_date(req.reference_date, "reference_date")
    except common.RequestProblem as problem:
        return common.failure("motion", problem.status, str(problem), request, rec, problem.stats)

    # 1. which pairs exist here
    try:
        with rec.step("search_pairs", product="GUNW", bbox=list(req.bbox)) as step:
            pairs = catalog.search("GUNW", bbox=req.bbox)
            step.params["pairs_found"] = len(pairs)
    except Exception as exc:  # noqa: BLE001 - the catalogue is a network service: report, do not crash
        common.log_failure("motion", exc)
        return common.failure("motion", "error", common.explain_search_error(exc), request, rec)

    pair, usable = choose_pair(pairs, req.bbox, req.reference_date, req.track)
    available = [_pair_dict(g, c) for g, c in usable]
    if pair is None:
        headline = _no_pair_headline(usable, req.reference_date, req.track)
        return common.failure("motion", "unsupported", headline, request, rec, {"available_pairs": available})
    coverage = common.footprint_fraction(pair.footprint, req.bbox)
    rec.note(
        "choose_pair",
        rule="requested reference date and track" if req.reference_date else "most recent pair covering the area",
        granule_id=pair.granule_id,
        reference_date=pair.reference_date,
        secondary_date=pair.secondary_date,
        track=pair.track,
        frame=pair.frame,
        coverage_of_area=round(coverage, 3),
        candidates=len(usable),
    )
    rec.use(pair)

    # 2. read the window
    try:
        with rec.step("read_window", product="GUNW", posting_m=NOMINAL_PIXEL_M, layers=list(gunw.DEFAULT_LAYERS) + ["mask"]) as step:
            cut = gunw.read_window(pair, req.bbox, use_cache=use_cache)
            step.params.update(rows=list(cut.rows), cols=list(cut.cols), from_cache=cut.from_cache, io=cut.io)
    except (gunw.OutsideFrame, gunw.WindowTooLarge, RemoteAccessError) as exc:
        status, sentence = common.explain_read_error(exc)
        return common.failure("motion", status, sentence, request, rec, {"available_pairs": available})
    except Exception as exc:  # noqa: BLE001 - message may quote a signed link: log the type only
        common.log_failure("motion", exc)
        status, sentence = common.explain_read_error(exc)
        return common.failure("motion", status, sentence, request, rec, {"available_pairs": available})
    if "unwrappedPhase" not in cut.layers or "coherenceMagnitude" not in cut.layers:
        return common.failure(
            "motion", "error", "This pair does not carry an unwrapped phase and coherence layer.", request, rec
        )

    # 3. phase -> displacement, masks, reference, sensitivity, decision
    wavelength = cut.wavelength_m
    with rec.step(
        "phase_to_displacement",
        formula="los_cm = -wavelength / (4*pi) * unwrappedPhase * 100",
        wavelength_m=round(wavelength, 6),
        center_frequency_hz=cut.center_frequency_hz,
        cm_per_radian=round(-wavelength / (4 * np.pi) * 100, 4),
        sign="positive = toward the satellite",
        coherence_threshold=threshold,
        ionosphere_correction_requested=want_iono,
        ramp_removal=want_ramp,
        reference="median of the usable pixels in the window",
        sensitivity_coherence_thresholds=list(COHERENCE_SENSITIVITY),
    ) as step:
        looks = cut.looks[0] * cut.looks[1] if cut.looks else None
        res = analyse(
            cut.layers["unwrappedPhase"],
            cut.layers["coherenceMagnitude"],
            wavelength,
            components=cut.layers.get("connectedComponents"),
            mask=cut.layers.get("mask"),
            ionosphere=cut.layers.get("ionospherePhaseScreen"),
            ionosphere_uncertainty=cut.layers.get("ionospherePhaseScreenUncertainty"),
            x=cut.x,
            y=cut.y,
            pixel_area_km2=cut.pixel_area_km2,
            looks=looks,
            coherence_threshold=threshold,
            apply_ionosphere=want_iono,
            remove_ramp=want_ramp,
        )
        step.params.update(
            ionosphere_correction_applied=res.ionosphere["applied"],
            usable_pixels=res.default.n_valid,
            usable_fraction=round(res.default.valid_fraction, 4),
            median_removed_cm=round(res.default.reference_offset_cm, 3) if res.default.n_valid else None,
        )

    d0, decision = res.default, res.decision
    window_area = cut.shape[0] * cut.shape[1] * cut.pixel_area_km2
    pair_info = _pair_dict(pair, coverage) | {"granule_id": pair.granule_id, "polarization": cut.polarization}
    geometry: dict = {
        "wavelength_cm": round(wavelength * 100, 2),
        "cm_per_fringe": round(wavelength * 50, 2),
        "look_direction": cut.look_direction.lower(),
        "pass_direction": cut.pass_direction.lower() or pair.direction,
    }
    if cut.incidence_deg is not None and cut.los_enu is not None:
        geometry.update(
            incidence_deg=round(cut.incidence_deg, 1),
            los_unit_vector_east_north_up=[round(v, 3) for v in cut.los_enu],
            satellite_is_to_the=_bearing(cut.los_enu[0], cut.los_enu[1]),
        )
    base_stats: dict = {
        "pair": pair_info,
        "sign_convention": SIGN_CONVENTION,
        "geometry": geometry,
        "window": {
            "shape": list(cut.shape),
            "rows": list(cut.rows),
            "cols": list(cut.cols),
            "pixel_m": cut.pixel_size[0],
            "area_km2": round(window_area, 1),
            "epsg": cut.epsg,
        },
        "masking": res.masking | {"coherence_threshold": threshold, "median_coherence_of_usable": res.median_coherence},
        "available_pairs": available[-12:],
        "timing": {"read_seconds": cut.seconds, "from_cache": cut.from_cache, "io": cut.io},
    }
    span_text = _span(pair.reference_date, pair.secondary_date)

    result_id = provenance.new_id("motion")
    corners = cut.corners_lonlat()
    coherence_layer_path = provenance.artifact_path(result_id, "coherence.png")
    render.save_png(coherence_layer_path, render.colorize(cut.layers["coherenceMagnitude"], 0.0, 1.0, "grey"))
    coherence_layer = Layer(
        id="coherence",
        title="Coherence (0 = signal lost, 1 = stable surface)",
        url=provenance.artifact_url(result_id, "coherence.png"),
        corners=corners,
        legend=Legend(type="continuous", unit="", min=0.0, max=1.0, colormap="grey"),
        default_visible=False,
        date=pair.secondary_date,
    )

    if d0.n_valid < MIN_VALID_PIXELS or d0.valid_fraction < MIN_VALID_FRACTION:
        headline = (
            f"Ground motion could not be measured here between {span_text}: only "
            f"{d0.valid_fraction:.0%} of the area kept a usable radar signal "
            f"({res.masking['low_coherence_fraction']:.0%} lost coherence, "
            f"{res.masking['water_fraction']:.0%} is water, "
            f"{res.masking['no_data_fraction'] + res.masking['not_unwrapped_fraction']:.0%} has no unwrapped phase)."
        )
        result = WorkflowResult(
            id=result_id,
            workflow="motion",
            status="unsupported",
            request=request,
            summary=Summary(headline=headline),
            layers=[coherence_layer.model_copy(update={"default_visible": True})],
            stats=base_stats,
            caveats=[Caveat(code=f"tier_{pair.tier}", text=_TIER_TEXT[pair.tier])],
            receipt=rec.receipt(_reproduce(pair, req.bbox, res.settings)),
        )
        provenance.save_result(result)
        return result

    # 4. pictures and files
    with rec.step("render", layers=["displacement", "coherence", "fringes"]) as step:
        los = res.los_cm
        limit = _nice_limit(max(float(np.nanpercentile(np.abs(los), 99.5)), 3.0 * NOISE_FLOOR_CM))
        render.save_png(provenance.artifact_path(result_id, "displacement.png"), render.colorize(los, -limit, limit, "RdBu"))
        half_wave = wavelength * 50.0  # cm of line-of-sight motion per fringe
        render.save_png(
            provenance.artifact_path(result_id, "fringes.png"),
            render.colorize(np.mod(los, half_wave), 0.0, half_wave, "cyclic"),
        )
        gt = cut.geotransform()
        render.save_geotiff(provenance.artifact_path(result_id, "displacement_cm.tif"), los, gt, cut.epsg)
        render.save_geotiff(
            provenance.artifact_path(result_id, "coherence.tif"), cut.layers["coherenceMagnitude"], gt, cut.epsg
        )
        step.params.update(displacement_limits_cm=[-limit, limit], fringe_cycle_cm=round(half_wave, 2))

    layers = [
        Layer(
            id="displacement",
            title="Line-of-sight motion (cm; red = toward the satellite, blue = away)",
            url=provenance.artifact_url(result_id, "displacement.png"),
            corners=corners,
            legend=Legend(type="continuous", unit="cm", min=-limit, max=limit, colormap="RdBu"),
            default_visible=True,
            date=pair.secondary_date,
        ),
        coherence_layer,
        Layer(
            id="fringes",
            title=f"Motion rewrapped into fringes (one colour cycle = {half_wave:.1f} cm)",
            url=provenance.artifact_url(result_id, "fringes.png"),
            corners=corners,
            legend=Legend(type="continuous", unit="cm", min=0.0, max=round(half_wave, 2), colormap="cyclic"),
            default_visible=False,
            date=pair.secondary_date,
        ),
    ]

    # 5. numbers as ranges
    stats_all = [st for _, st in res.variants.values() if st.n_valid]

    def spread_of(values: list[float]) -> tuple[float, float]:
        return round(min(values), 2), round(max(values), 2)

    p2p_low, p2p_high = spread_of([st.peak_to_peak for st in stats_all])
    span_low, span_high = spread_of([st.span_p5_p95 for st in stats_all])
    sigma_low, sigma_high = spread_of([st.spread_cm for st in stats_all])
    toward_low, toward_high = spread_of([st.p99 for st in stats_all])
    away_low, away_high = spread_of([-st.p1 for st in stats_all])
    area2 = [a for a, _ in res.areas_km2.values()]
    area3 = [b for _, b in res.areas_km2.values()]
    masked = list(res.masked_by_threshold.values())
    valid_area = d0.n_valid * cut.pixel_area_km2
    noise = round(decision.noise_cm, 2)

    noise_label = {
        "measured": "Noise level (robust spread of the motion field)",
        "floor": "Noise level (minimum assumed for one 12-day pair; the field itself is quieter)",
        "ceiling": "Noise level (largest value accepted as atmosphere, assumed; the field is dominated by motion)",
    }[decision.noise_basis]
    metrics = [
        Metric(key="noise_level_cm", label=noise_label, unit="cm", central=noise,
               low=min(noise, sigma_low) if decision.noise_basis == "measured" else None,
               high=max(noise, sigma_high) if decision.noise_basis == "measured" else None),
        Metric(key="field_spread_cm", label="Robust spread of the motion field (1.4826 x MAD)", unit="cm",
               central=round(d0.spread_cm, 2), low=sigma_low, high=sigma_high),
        Metric(key="los_span_p5_p95_cm", label="Line-of-sight motion span, 5th to 95th percentile", unit="cm",
               central=round(d0.span_p5_p95, 2), low=span_low, high=span_high),
        Metric(key="los_peak_to_peak_cm", label="Line-of-sight motion range, 1st to 99th percentile", unit="cm",
               central=round(d0.peak_to_peak, 2), low=p2p_low, high=p2p_high),
        Metric(key="max_toward_satellite_cm", label="Largest motion toward the satellite (99th percentile)",
               unit="cm", central=round(d0.p99, 2), low=toward_low, high=toward_high),
        Metric(key="max_away_from_satellite_cm", label="Largest motion away from the satellite (1st percentile)",
               unit="cm", central=round(-d0.p1, 2), low=away_low, high=away_high),
        Metric(key="area_above_2x_noise_km2", label=f"Area that moved more than 2 x the noise level ({_cm(2 * noise)} cm)",
               unit="km2", central=round(res.areas_km2[threshold][0], 1), low=round(min(area2), 1), high=round(max(area2), 1)),
        Metric(key="area_above_3x_noise_km2", label=f"Area that moved more than 3 x the noise level ({_cm(3 * noise)} cm)",
               unit="km2", central=round(res.areas_km2[threshold][1], 1), low=round(min(area3), 1), high=round(max(area3), 1)),
        Metric(key="masked_percent", label="Share of the area masked out (water, lost coherence, not unwrapped)",
               unit="%", central=round(100 * res.masking["masked_fraction"], 1),
               low=round(100 * min(masked), 1), high=round(100 * max(masked), 1)),
    ]
    if res.ionosphere.get("range_cm") is not None:
        metrics.append(
            Metric(key="ionosphere_range_cm", label="Range of NASA's ionosphere estimate across the area",
                   unit="cm", central=res.ionosphere["range_cm"], low=res.ionosphere["range_p5_p95_cm"],
                   high=res.ionosphere["range_min_max_cm"])
        )

    if decision.outcome == "signal":
        headline = (
            f"Up to {_range_text(p2p_low, p2p_high)} of line-of-sight motion across the area between {span_text}"
        )
    elif decision.outcome == "tilt_only":
        ramp = res.variants["ramp_removed"][1].ramp or {}
        tilt = float(np.hypot(ramp.get("east_west_cm", 0.0), ramp.get("north_south_cm", 0.0)))
        headline = (
            f"A steady tilt of about {_cm(tilt)} cm across the area between {span_text}, which one 12-day pair "
            f"cannot tell apart from an atmospheric or orbit effect; no localised ground motion above the "
            f"{_cm(noise)} cm noise level"
        )
    else:
        clearly = "clearly " if decision.inconclusive else ""
        headline = f"No ground motion {clearly}above the {_cm(noise)} cm noise level between {span_text}"

    # 6. uncertainty
    sensitivity = _sensitivity(res)

    notes = _notes(
        res, threshold=threshold, want_ramp=want_ramp, spreads_cm=(sigma_low, sigma_high), valid_area=valid_area,
        wavelength=wavelength, looks=looks, coverage=coverage,
    )
    iono = res.ionosphere
    ramp_stats = res.variants.get("ramp_removed" if not want_ramp else "default")

    method = (
        f"NASA GUNW unwrapped phase ({cut.polarization}, 80 m) converted to line-of-sight displacement with the "
        f"{wavelength * 100:.1f} cm wavelength read from the file"
        + (", NASA's ionosphere phase screen subtracted" if iono["applied"] else "")
        + f", masked where coherence is below {threshold:g}, over water or not reliably unwrapped"
        + (", best-fit plane removed" if want_ramp else "")
        + ", referenced to the window median. Noise level from the robust spread (1.4826 x MAD); ranges from "
        "repeating the analysis with coherence thresholds 0.2 / 0.3 / 0.4, with and without the ionosphere "
        "correction, and with and without a planar ramp."
    )
    uncertainty = Uncertainty(
        method=method,
        sensitivity=sensitivity,
        noise_floor_fraction=res.masking["masked_fraction"],
        notes=notes,
    )

    # 7. caveats
    caveats = _caveats(pair, geometry, wavelength, iono["applied"])

    # 8. statistics table and result
    header = ["variant", "coherence_threshold", "ionosphere_applied", "ramp_removed", "largest_region_only",
              "usable_fraction", "median_removed_cm", "robust_spread_cm", "p1_cm", "p5_cm", "p95_cm", "p99_cm",
              "span_p5_p95_cm", "range_p1_p99_cm"]
    rows, variant_stats = [], []
    for key, (s, st) in res.variants.items():
        if key == f"coherence_{threshold:g}":
            continue  # identical to "default"
        rows.append([res.labels[key], s.coherence_threshold, s.ionosphere, s.ramp, s.largest_component,
                     round(st.valid_fraction, 4), round(st.reference_offset_cm, 3), round(st.spread_cm, 3),
                     round(st.p1, 3), round(st.p5, 3), round(st.p95, 3), round(st.p99, 3),
                     round(st.span_p5_p95, 3), round(st.peak_to_peak, 3)])
        variant_stats.append({"variant": res.labels[key], "robust_spread_cm": round(st.spread_cm, 2),
                              "span_p5_p95_cm": round(st.span_p5_p95, 2), "range_p1_p99_cm": round(st.peak_to_peak, 2),
                              "usable_fraction": round(st.valid_fraction, 3)})
    render.save_csv(provenance.artifact_path(result_id, "statistics.csv"), header, rows)

    stats = base_stats | {
        "displacement_cm": {"p1": round(d0.p1, 2), "p5": round(d0.p5, 2), "p95": round(d0.p95, 2), "p99": round(d0.p99, 2),
                            "min": round(res.extremes_cm[0], 2), "max": round(res.extremes_cm[1], 2),
                            "median_removed": round(d0.reference_offset_cm, 2)},
        "noise": {
            "noise_level_cm": noise,
            "noise_level_basis": decision.noise_basis,
            "field_spread_cm": round(d0.spread_cm, 2),
            "short_distance_scatter_cm": res.local_noise_cm,
            "decorrelation_noise_cm": res.decorrelation_noise_cm,
            "typical_atmosphere_cm": list(TYPICAL_ATMOSPHERE_CM),
            "chance_fraction_beyond_2x": CHANCE_ABOVE_2X,
            "chance_fraction_beyond_3x": CHANCE_ABOVE_3X,
        },
        "detection": {
            "outcome": decision.outcome,
            "signal_detected": decision.detected,
            "inconclusive": decision.inconclusive,
            "threshold_cm": round(decision.threshold_cm, 2),
            "smallest_range_cm": round(decision.peak_to_peak_min_cm, 2),
            "range_after_ramp_removal_cm": round(decision.peak_to_peak_other_ramp_cm, 2)
            if (not want_ramp and decision.peak_to_peak_other_ramp_cm is not None) else None,
            "rule": f"range (1st to 99th percentile) > {DETECTION_FACTOR:g} x noise level for every processing "
                    f"choice, and again after planar ramp removal (or a ramp-removed spread above "
                    f"{SPREAD_IS_MOTION_CM:g} cm); noise level kept between {NOISE_FLOOR_CM:g} and "
                    f"{NOISE_CEILING_CM:g} cm",
        },
        "ionosphere": iono,
        "ramp": {"removed": want_ramp} | (ramp_stats[1].ramp if ramp_stats and ramp_stats[1].ramp else {}),
        "unwrapped_regions": res.n_components,
        "usable_area_km2": round(valid_area, 1),
        "variants": variant_stats,
    }
    stats["timing"]["analysis_seconds"] = res.seconds
    stats["timing"]["total_seconds"] = round(time.time() - t_start, 2)
    stats["effort"] = common.effort([cut.first_read])

    downloads = [
        Download(label="Line-of-sight motion in cm (GeoTIFF)", url=provenance.artifact_url(result_id, "displacement_cm.tif"), format="geotiff"),
        Download(label="Coherence (GeoTIFF)", url=provenance.artifact_url(result_id, "coherence.tif"), format="geotiff"),
        Download(label="Statistics for every processing choice (CSV)", url=provenance.artifact_url(result_id, "statistics.csv"), format="csv"),
        Download(label="Motion map (PNG)", url=provenance.artifact_url(result_id, "displacement.png"), format="png"),
        Download(label="Full result with receipt (JSON)", url=provenance.artifact_url(result_id, "result.json"), format="json"),
    ]
    result = WorkflowResult(
        id=result_id,
        workflow="motion",
        status="ok",
        request=request | {"resolved": {"coherence_threshold": threshold, "remove_ramp": want_ramp,
                                        "apply_ionosphere": res.settings.ionosphere,
                                        "reference_date": pair.reference_date, "track": pair.track}},
        summary=Summary(headline=headline, metrics=metrics),
        layers=layers,
        charts=[
            c
            for c in (
                charts.motion_profile(res.los_cm, cut.x, cut.y, decision.noise_cm),
                charts.motion_distribution(res.los_cm, decision.noise_cm, limit, cut.pixel_area_km2),
            )
            if c is not None
        ],
        stats=stats,
        uncertainty=uncertainty,
        caveats=caveats,
        receipt=rec.receipt(_reproduce(pair, req.bbox, res.settings)),
        downloads=downloads,
    )
    provenance.save_result(result)
    return result

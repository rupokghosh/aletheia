"""Numbers for the small charts shown with a result. Every chart is computed from the same arrays as the
result's maps and figures; nothing here is drawn, only binned and summed.

A chart is a `schemas.Chart`: a kind the interface knows how to draw, a title, one sentence on how to read
it, and its data.

  histogram  data = {unit, edges[n+1], area_km2[n], band[2], band_label, low_label, high_label}
             Area per bin of the measured quantity. `band` is the span inside which a value cannot be told
             from no change (plus and minus the threshold or the noise level).
  shares     data = {unit, total, parts[{key, label, value}]}
             How the analysed area divides into classes.
  profile    data = {unit, x_unit, x[n], y[n], low[n], high[n], band[2], band_label, start, end}
             The typical value across the area along one compass direction, with the spread across it.
"""

from __future__ import annotations

import warnings

import numpy as np

from .schemas import Chart

HISTOGRAM_BINS = 48
PROFILE_POINTS = 96


def _histogram(values: np.ndarray, limit: float, pixel_area_km2: float) -> tuple[list[float], list[float]]:
    """Area per bin between -limit and +limit; values beyond the limits are counted in the end bins."""
    edges = np.linspace(-limit, limit, HISTOGRAM_BINS + 1)
    counts, _ = np.histogram(np.clip(values, -limit, limit), bins=edges)
    return [round(float(e), 3) for e in edges], [round(float(c) * pixel_area_km2, 4) for c in counts]


def change_distribution(
    change_db: np.ndarray, measurable: np.ndarray, threshold_db: float, limit_db: float, pixel_area_km2: float
) -> Chart | None:
    """How much each part of the area changed, as area per step of change."""
    values = change_db[measurable & np.isfinite(change_db)]
    if values.size == 0:
        return None
    edges, area = _histogram(values, limit_db, pixel_area_km2)
    return Chart(
        id="change_distribution",
        kind="histogram",
        title="How much each part of the area changed",
        description=(
            "Most of the area sits in the middle: no change that can be told from the radar's own speckle. "
            "The coloured tails are the parts that became clearly brighter or darker."
        ),
        data={
            "unit": "dB",
            "edges": edges,
            "area_km2": area,
            "band": [-round(threshold_db, 2), round(threshold_db, 2)],
            "band_label": "no clear change",
            "low_label": "darker",
            "high_label": "brighter",
        },
    )


def change_shares(
    valid: np.ndarray, increased: np.ndarray, decreased: np.ndarray, cannot_tell: np.ndarray, pixel_area_km2: float
) -> Chart | None:
    """The analysed area divided into brighter, darker, no clear change and too dark to judge."""
    total = float(valid.sum()) * pixel_area_km2
    if total <= 0:
        return None
    brighter = float((increased & valid).sum()) * pixel_area_km2
    darker = float((decreased & valid).sum()) * pixel_area_km2
    dark = float((cannot_tell & valid & ~increased & ~decreased).sum()) * pixel_area_km2
    steady = max(total - brighter - darker - dark, 0.0)
    parts = [
        ("brighter", "Brighter", brighter),
        ("darker", "Darker", darker),
        ("steady", "No clear change", steady),
        ("cannot_tell", "Too dark to judge", dark),
    ]
    return Chart(
        id="change_shares",
        kind="shares",
        title="What happened across the area",
        description="Shares of the analysed area, at the middle threshold.",
        data={"unit": "km2", "total": round(total, 2), "parts": [{"key": k, "label": l, "value": round(v, 2)} for k, l, v in parts]},
    )


def motion_distribution(los_cm: np.ndarray, noise_cm: float, limit_cm: float, pixel_area_km2: float) -> Chart | None:
    """How far each part of the area moved along the radar's line of sight."""
    values = los_cm[np.isfinite(los_cm)]
    if values.size == 0:
        return None
    edges, area = _histogram(values, limit_cm, pixel_area_km2)
    return Chart(
        id="motion_distribution",
        kind="histogram",
        title="How far each part of the area moved",
        description=(
            "Motion along the radar's line of sight, relative to the middle of the area. Values inside the grey "
            "band cannot be told from noise."
        ),
        data={
            "unit": "cm",
            "edges": edges,
            "area_km2": area,
            "band": [-round(noise_cm, 2), round(noise_cm, 2)],
            "band_label": "within the noise",
            "low_label": "away from the satellite",
            "high_label": "toward the satellite",
        },
    )


def motion_profile(los_cm: np.ndarray, x_m: np.ndarray, y_m: np.ndarray, noise_cm: float) -> Chart | None:
    """The typical motion across the area, along the compass direction in which it varies most.

    For west to east, each point is the median of one north-south column of pixels, with the 10th to 90th
    percentile of that column as the spread; south to north likewise with rows. Columns (or rows) with fewer
    than a tenth of their pixels usable are left out.
    """
    if los_cm.ndim != 2 or min(los_cm.shape) < 8 or not np.isfinite(los_cm).any():
        return None

    def along(axis: int):
        usable = np.isfinite(los_cm).mean(axis=axis)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)  # columns with no usable pixel at all
            mid = np.nanmedian(los_cm, axis=axis)
            low, high = np.nanpercentile(los_cm, [10, 90], axis=axis)
        keep = usable >= 0.1
        return np.where(keep, mid, np.nan), np.where(keep, low, np.nan), np.where(keep, high, np.nan)

    west_east, south_north = along(0), along(1)

    def span(profile) -> float:
        finite = profile[0][np.isfinite(profile[0])]
        return float(finite.max() - finite.min()) if finite.size > 1 else 0.0

    eastward = span(west_east) >= span(south_north)
    mid, low, high = west_east if eastward else south_north
    coords = np.asarray(x_m if eastward else y_m, dtype=float)
    if not eastward and coords[0] > coords[-1]:  # rows run north to south: turn them to read south to north
        mid, low, high, coords = mid[::-1], low[::-1], high[::-1], coords[::-1]
    if eastward and coords[0] > coords[-1]:
        mid, low, high, coords = mid[::-1], low[::-1], high[::-1], coords[::-1]
    distance_km = (coords - coords[0]) / 1000.0

    step = max(1, int(np.ceil(len(mid) / PROFILE_POINTS)))
    n = (len(mid) // step) * step
    if n < 4 * step:
        return None

    def thin(values: np.ndarray) -> np.ndarray:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            return np.nanmean(values[:n].reshape(-1, step), axis=1)

    xs, ys, lows, highs = thin(distance_km), thin(mid), thin(low), thin(high)
    ok = np.isfinite(ys)
    if ok.sum() < 4:
        return None

    def numbers(values: np.ndarray) -> list[float | None]:
        return [round(float(v), 3) if np.isfinite(v) else None for v in values]

    start, end = ("west", "east") if eastward else ("south", "north")
    return Chart(
        id="motion_profile",
        kind="profile",
        title=f"Motion across the area, {start} to {end}",
        description=(
            f"The typical motion along a line from {start} to {end}, with the spread across the area in grey. "
            "A steady slope or a step is a pattern; scatter inside the noise band is not."
        ),
        data={
            "unit": "cm",
            "x_unit": "km",
            "x": numbers(xs),
            "y": numbers(ys),
            "low": numbers(lows),
            "high": numbers(highs),
            "band": [-round(noise_cm, 2), round(noise_cm, 2)],
            "band_label": "within the noise",
            "start": start,
            "end": end,
        },
    )

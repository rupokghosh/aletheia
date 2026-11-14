"""Workflow A: change in radar backscatter between two dates of one stack (requirement R3).

The two acquisitions share a pixel grid, so the comparison is per pixel: multilook in linear power, convert to
dB, subtract. Whole-scene level shifts (calibration, moisture, wind) are removed with the median change, the
no-change spread is estimated robustly, and the changed area is reported as a range across three thresholds.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date

import numpy as np

from .. import catalog, gcov, ops, provenance, render
from ..schemas import (
    Caveat,
    ChangeRequest,
    Download,
    Granule,
    Layer,
    Legend,
    Metric,
    Sensitivity,
    Summary,
    Uncertainty,
    WorkflowResult,
)
from . import common
from .common import RequestProblem, StackKey

MULTILOOK = 9  # box size in pixels (90 m on the 10 m grid)
# A pixel counts as changed when |change| is at least K x sigma and at least MIN_CHANGE_DB.
K_LEVELS: dict[str, float] = {"lenient": 2.0, "central": 3.0, "strict": 4.0}
MIN_CHANGE_DB = 2.0
# Changed patches must hold a disk this much wider than the multilook box: one strong reflector that changes
# is smeared by the box into a square of exactly MULTILOOK pixels, which is not an area of change.
SPECK_MARGIN = 2
# A polarization is called not informative when more than this share of the area is at the noise floor on both dates.
UNINFORMATIVE_FRACTION = 0.5
SENSITIVITY_MULTILOOKS = (5, 13)

_CLASS_COLORS: dict[int, tuple[int, int, int, int]] = {
    1: (178, 24, 43, 255),  # brighter: the red end of RdBu
    2: (33, 102, 172, 255),  # darker: the blue end
    3: (128, 128, 128, 170),  # at the noise floor on both dates
}


@dataclass
class PairAnalysis:
    """Per-pixel change of one polarization. Arrays are multilooked and share the cutout's shape."""

    polarization: str
    before_db: np.ndarray
    after_db: np.ndarray
    change_db: np.ndarray  # after minus before; the scene shift is removed unless normalise=False
    valid: np.ndarray  # valid radar samples on both dates
    cannot_tell: np.ndarray  # at the noise floor on both dates
    floor_db: tuple[float, float]  # before, after
    floor_fraction: tuple[float, float]  # share of valid pixels at the floor: before, after
    shift_db: float  # median change of measurable pixels
    sigma_db: float  # robust no-change spread
    thresholds_db: dict[str, float]
    increased: dict[str, np.ndarray]  # level -> mask
    decreased: dict[str, np.ndarray]

    @property
    def measurable(self) -> np.ndarray:
        return self.valid & ~self.cannot_tell

    @property
    def cannot_tell_fraction(self) -> float:
        n = int(self.valid.sum())
        return float(self.cannot_tell.sum()) / n if n else float("nan")


def analyse_pair(
    before: np.ndarray,
    after: np.ndarray,
    polarization: str,
    *,
    multilook: int = MULTILOOK,
    normalise: bool = True,
    speck_diameter: int | None = None,
    levels: tuple[str, ...] = tuple(K_LEVELS),
) -> PairAnalysis:
    """Change statistics for two co-registered linear-power images (NaN = no data)."""
    if speck_diameter is None:
        speck_diameter = multilook + SPECK_MARGIN
    valid = np.isfinite(before) & np.isfinite(after)
    before_db = ops.to_db(ops.multilook(before, multilook))
    after_db = ops.to_db(ops.multilook(after, multilook))
    valid &= np.isfinite(before_db) & np.isfinite(after_db)
    before_db[~valid] = np.nan  # multilooking spreads values into no-data pixels: take them out again
    after_db[~valid] = np.nan

    floor_before, floor_before_db = ops.at_noise_floor(before_db, polarization)
    floor_after, floor_after_db = ops.at_noise_floor(after_db, polarization)
    cannot_tell = floor_before & floor_after
    measurable = valid & ~cannot_tell
    n_valid = max(int(valid.sum()), 1)

    raw = after_db - before_db
    shift = float(np.median(raw[measurable])) if measurable.any() else float("nan")
    sigma = ops.robust_sigma(raw[measurable])
    change = raw - shift if normalise else raw

    thresholds: dict[str, float] = {}
    increased: dict[str, np.ndarray] = {}
    decreased: dict[str, np.ndarray] = {}
    comparable = np.where(measurable, change, 0.0)
    for level in levels:
        threshold = max(K_LEVELS[level] * sigma, MIN_CHANGE_DB) if np.isfinite(sigma) else float("nan")
        thresholds[level] = threshold
        increased[level] = ops.remove_specks(comparable >= threshold, speck_diameter)
        decreased[level] = ops.remove_specks(comparable <= -threshold, speck_diameter)

    return PairAnalysis(
        polarization=polarization,
        before_db=before_db,
        after_db=after_db,
        change_db=change,
        valid=valid,
        cannot_tell=cannot_tell,
        floor_db=(floor_before_db, floor_after_db),
        floor_fraction=(float(floor_before.sum()) / n_valid, float(floor_after.sum()) / n_valid),
        shift_db=shift,
        sigma_db=sigma,
        thresholds_db=thresholds,
        increased=increased,
        decreased=decreased,
    )


# ------------------------------------------------------------ choosing dates


def _by_date(items: list[Granule]) -> dict[str, Granule]:
    """One granule per date, the best calibrated if a date appears twice."""
    out: dict[str, Granule] = {}
    for g in items:
        if g.date and (g.date not in out or catalog.TIER_RANK[g.tier] < catalog.TIER_RANK[out[g.date].tier]):
            out[g.date] = g
    return out


def _closest_pair(dates: list[str], before: str, after: str) -> tuple[str, str] | None:
    """The two dates of a stack nearest to the requested ones."""
    if len(dates) < 2:
        return None

    def nearest(target: str, pool: list[str]) -> str:
        return min(pool, key=lambda d: abs((date.fromisoformat(d) - date.fromisoformat(target)).days))

    first = nearest(before, dates)
    second = nearest(after, [d for d in dates if d != first])
    return (first, second) if first < second else (second, first)


def select_pair(
    granules: list[Granule], date_before: str, date_after: str, track: int | None, bbox
) -> tuple[StackKey, Granule, Granule, list[StackKey]]:
    """The stack holding both dates. Returns (stack, before, after, other stacks that also hold both).

    Raises RequestProblem("unsupported") with the pairs that would work when no stack has both dates.
    """
    stacks = {key: _by_date(items) for key, items in common.group_stacks(granules).items()}
    wanted = {key: dates for key, dates in stacks.items() if track is None or key[0] == track}
    available = [
        {"track": key[0], "direction": key[1], "frame": key[2], "dates": sorted(dates)} for key, dates in stacks.items()
    ]
    if not wanted:
        tracks = common.join_words([str(t) for t in sorted({key[0] for key in stacks})])
        raise RequestProblem(
            f"Track {track} has no backscatter acquisitions over this area. Tracks that do: {tracks}.",
            "unsupported",
            {"valid_dates_by_track": available},
        )

    candidates = [key for key, dates in wanted.items() if date_before in dates and date_after in dates]
    if not candidates:
        pairs = []
        for key, dates in wanted.items():
            pair = _closest_pair(sorted(dates), date_before, date_after)
            pairs.append(f"{common.stack_name(key)}: " + (f"{pair[0]} and {pair[1]}" if pair else "one date only"))
        where = f"Track {track} does not have" if track is not None else "No single track has"
        raise RequestProblem(
            f"{where} both {date_before} and {date_after} here. Two dates can only be compared pixel by pixel when "
            f"they come from the same track and frame. Closest pairs that can be compared: {'; '.join(pairs)}.",
            "unsupported",
            {"valid_dates_by_track": available},
        )

    def footprint_cover(key: StackKey) -> float:
        return min(common.footprint_fraction(wanted[key][d].footprint, bbox) for d in (date_before, date_after))

    candidates.sort(key=lambda key: (-footprint_cover(key), key))
    chosen = candidates[0]
    return chosen, wanted[chosen][date_before], wanted[chosen][date_after], candidates[1:]


# ----------------------------------------------------------------- numbers


def _r(value: float, digits: int = 2) -> float | None:
    return round(float(value), digits) if np.isfinite(value) else None


def _areas(analysis: PairAnalysis, direction: str, pixel_area_km2: float) -> dict[str, float]:
    """Changed area in km2 as low (strict), central and high (lenient)."""
    masks = analysis.increased if direction == "increased" else analysis.decreased
    return {
        name: round(ops.area_km2(masks[level], pixel_area_km2), 2)
        for name, level in (("low", "strict"), ("central", "central"), ("high", "lenient"))
    }


def _polarization_stats(analysis: PairAnalysis, before: np.ndarray, after: np.ndarray, pixel_area_km2: float) -> dict:
    out: dict = {
        "mean_db_before": _r(ops.mean_db(before, analysis.valid)[0]),
        "mean_db_after": _r(ops.mean_db(after, analysis.valid)[0]),
        "scene_shift_db": _r(analysis.shift_db),
        "sigma_db": _r(analysis.sigma_db),
        "thresholds_db": {level: _r(v) for level, v in analysis.thresholds_db.items()},
        "noise_floor_db": {"before": _r(analysis.floor_db[0]), "after": _r(analysis.floor_db[1])},
        "noise_floor_fraction": {
            "before": _r(analysis.floor_fraction[0], 3),
            "after": _r(analysis.floor_fraction[1], 3),
            "both": _r(analysis.cannot_tell_fraction, 3),
        },
        "informative": bool(analysis.cannot_tell_fraction <= UNINFORMATIVE_FRACTION),
    }
    for direction, masks in (("increased", analysis.increased), ("decreased", analysis.decreased)):
        mask = masks["central"]
        out[direction] = {
            "area_km2": _areas(analysis, direction, pixel_area_km2),
            "mean_db_before": _r(ops.mean_db(before, mask)[0]),
            "mean_db_after": _r(ops.mean_db(after, mask)[0]),
            # the means are averages in linear power, which a few very bright reflectors can dominate;
            # the median of the per-pixel change is the typical change inside the class
            "median_change_db": _r(np.median(analysis.change_db[mask])) if mask.any() else None,
        }
    return out


def _sensitivity(
    analysis: PairAnalysis, before: np.ndarray, after: np.ndarray, pixel_area_km2: float, pool: ThreadPoolExecutor
) -> list[Sensitivity]:
    """How the central areas of the primary polarization move when one processing choice is changed."""
    pol = analysis.polarization
    out: list[Sensitivity] = []

    def add(parameter: str, value: float | str, variant: PairAnalysis, level: str = "central") -> None:
        for direction, masks in (("increase", variant.increased), ("decrease", variant.decreased)):
            out.append(
                Sensitivity(
                    parameter=f"{direction}: {parameter}",
                    value=value,
                    result=round(ops.area_km2(masks[level], pixel_area_km2), 2),
                    unit="km2",
                )
            )

    for level in ("strict", "central", "lenient"):
        add(f"{level} threshold (dB)", round(analysis.thresholds_db[level], 2), analysis, level)
    variants: list[tuple[str, float | str, dict]] = [("scene shift", "not subtracted", {"normalise": False})]
    variants += [("multilook box (pixels)", size, {"multilook": size}) for size in SENSITIVITY_MULTILOOKS]
    variants.append(("speck removal", "off", {"speck_diameter": 1}))
    reruns = pool.map(lambda v: analyse_pair(before, after, pol, levels=("central",), **v[2]), variants)
    for (parameter, value, _), variant in zip(variants, reruns):
        add(parameter, value, variant)
    return out


def _area_range(areas: dict[str, float]) -> str:
    digits = 2 if areas["high"] < 10 else 1 if areas["high"] < 100 else 0
    return f"{areas['low']:.{digits}f} to {areas['high']:.{digits}f} km2"


def _percent(fraction: float) -> str:
    return f"{100 * fraction:.0f}%"


# ---------------------------------------------------------------- artifacts


def _grey_range(analysis: PairAnalysis) -> tuple[float, float]:
    """One grey scale for both dates (2nd to 98th percentile, rounded outwards to 0.5 dB)."""
    pooled = np.concatenate([analysis.before_db[analysis.valid], analysis.after_db[analysis.valid]])
    low, high = np.percentile(pooled, [2, 98])
    return float(np.floor(low * 2) / 2), float(np.ceil(high * 2) / 2)


def _layers(
    result_id: str, analysis: PairAnalysis, cut: gcov.Cutout, dates: tuple[str, str], primary: bool
) -> list[Layer]:
    pol = analysis.polarization
    suffix = "" if primary else f"_{pol.lower()}"
    corners = cut.corners_lonlat()
    out: list[Layer] = []

    low, high = _grey_range(analysis)
    for name, values, day in (("before", analysis.before_db, dates[0]), ("after", analysis.after_db, dates[1])):
        filename = f"{name}{suffix}.png"
        render.save_grey_png(provenance.artifact_path(result_id, filename), values, low, high)
        out.append(
            Layer(
                id=f"{name}{suffix}",
                title=f"{pol} {name}, {common.pretty_date(day)} (dB)",
                url=provenance.artifact_url(result_id, filename),
                corners=corners,
                legend=Legend(type="continuous", unit="dB", min=low, max=high, colormap="grey"),
                date=day,
            )
        )

    central = analysis.thresholds_db["central"]
    limit = float(np.clip(np.ceil(2 * central), 4, 12))  # symmetric, with the central threshold at half scale
    filename = f"change_db{suffix}.png"
    # Change below 1 dB is transparent and fades in up to the lenient threshold, so speckle does not read as
    # change. Pixels at the noise floor on both dates cannot be judged and are left clear.
    lenient = analysis.thresholds_db["lenient"]
    with np.errstate(invalid="ignore"):
        strength = np.clip((np.abs(analysis.change_db) - 1.0) / max(lenient - 1.0, 0.5), 0.0, 1.0)
    strength = np.where(analysis.cannot_tell | ~np.isfinite(analysis.change_db), 0.0, strength)
    render.save_png(
        provenance.artifact_path(result_id, filename),
        render.colorize(analysis.change_db, -limit, limit, "RdBu", alpha=strength),
    )
    out.append(
        Layer(
            id=f"change_db{suffix}",
            title=f"{pol} change, after minus before (dB)",
            url=provenance.artifact_url(result_id, filename),
            corners=corners,
            legend=Legend(type="continuous", unit="dB", min=-limit, max=limit, colormap="RdBu"),
            default_visible=primary,
        )
    )

    classes = np.zeros(cut.shape, dtype=np.uint8)
    classes[analysis.cannot_tell] = 3
    classes[analysis.increased["central"]] = 1
    classes[analysis.decreased["central"]] = 2
    filename = f"change_classes{suffix}.png"
    render.save_class_png(provenance.artifact_path(result_id, filename), classes, _CLASS_COLORS)
    labels = {
        1: f"Brighter by at least {central:.1f} dB",
        2: f"Darker by at least {central:.1f} dB",
        3: "At the noise floor on both dates (cannot tell)",
    }
    out.append(
        Layer(
            id=f"change_classes{suffix}",
            title=f"{pol} change classes (central threshold)",
            url=provenance.artifact_url(result_id, filename),
            corners=corners,
            legend=Legend(
                type="categorical",
                classes=[{"label": labels[c], "color": render.hex_color(_CLASS_COLORS[c])} for c in (1, 2, 3)],
            ),
        )
    )
    return out


def _geotiffs(
    result_id: str, analysis: PairAnalysis, cut: gcov.Cutout, dates: tuple[str, str], primary: bool
) -> list[Download]:
    pol = analysis.polarization
    suffix = "" if primary else f"_{pol.lower()}"
    out = []
    for name, values, label in (
        ("before_db", analysis.before_db, f"{pol} before, {dates[0]} (dB, GeoTIFF)"),
        ("after_db", analysis.after_db, f"{pol} after, {dates[1]} (dB, GeoTIFF)"),
        ("change_db", analysis.change_db, f"{pol} change, scene shift removed (dB, GeoTIFF)"),
    ):
        filename = f"{name}{suffix}.tif"
        render.save_geotiff(provenance.artifact_path(result_id, filename), values, cut.geotransform(), cut.epsg)
        out.append(Download(label=label, url=provenance.artifact_url(result_id, filename), format="geotiff"))
    return out


def _csv_rows(stats: dict) -> list[list]:
    rows: list[list] = []
    for pol, s in stats.items():
        rows += [
            [pol, "mean_db", "whole area", "before", s["mean_db_before"], "dB"],
            [pol, "mean_db", "whole area", "after", s["mean_db_after"], "dB"],
            [pol, "scene_shift_removed", "whole area", "", s["scene_shift_db"], "dB"],
            [pol, "no_change_sigma", "whole area", "", s["sigma_db"], "dB"],
        ]
        rows += [[pol, "threshold", "whole area", level, v, "dB"] for level, v in s["thresholds_db"].items()]
        rows += [[pol, "noise_floor", "whole area", when, v, "dB"] for when, v in s["noise_floor_db"].items()]
        rows += [
            [pol, "noise_floor_fraction", "whole area", when, v, "fraction"]
            for when, v in s["noise_floor_fraction"].items()
        ]
        for direction in ("increased", "decreased"):
            rows += [[pol, "area", direction, bound, v, "km2"] for bound, v in s[direction]["area_km2"].items()]
            rows += [
                [pol, "mean_db", direction, "before", s[direction]["mean_db_before"], "dB"],
                [pol, "mean_db", direction, "after", s[direction]["mean_db_after"], "dB"],
                [pol, "median_change", direction, "", s[direction]["median_change_db"], "dB"],
            ]
    return rows


_REPRODUCE = '''\
# Needs: pip install -e backend/  and an Earthdata Login in ~/.netrc (or EARTHDATA_TOKEN).
# Reads the best calibration tier available when it runs. This result used:
{granules}
from nisar_investigator.schemas import ChangeRequest
from nisar_investigator.workflows.change import run_change

if __name__ == "__main__":  # required: the reader starts worker processes
    result = run_change(ChangeRequest(
        bbox={bbox}, date_before="{before}", date_after="{after}", track={track}, polarization="{pol}",
    ))
    print(result.summary.headline)
    for m in result.summary.metrics:
        print(m.key, m.low, m.central, m.high, m.unit)
'''


# --------------------------------------------------------------- the workflow


def run_change(req: ChangeRequest) -> WorkflowResult:
    """Run workflow A. Never raises: problems come back as a result with status 'unsupported' or 'error'."""
    request = req.model_dump(mode="json")
    rec = provenance.Recorder()
    try:
        return _run(req, request, rec)
    except RequestProblem as problem:
        return common.failure("change", problem.status, str(problem), request, rec, problem.stats)
    except Exception as exc:  # noqa: BLE001 - the interface must get a readable result, never a traceback
        common.log_failure("change", exc)
        headline = f"The change analysis failed unexpectedly ({type(exc).__name__}). Nothing was measured."
        return common.failure("change", "error", headline, request, rec)


def _run(req: ChangeRequest, request: dict, rec: provenance.Recorder) -> WorkflowResult:
    bbox = req.bbox
    common.check_bbox(bbox)
    if common.parse_date(req.date_before, "date_before") >= common.parse_date(req.date_after, "date_after"):
        raise RequestProblem("date_before must be earlier than date_after.")

    with rec.step("search_catalog", product="GCOV", bbox=list(bbox)) as step:
        try:
            granules = catalog.search("GCOV", bbox=bbox)
        except Exception as exc:  # noqa: BLE001
            raise RequestProblem(common.explain_search_error(exc)) from None
        step.params["granules_found"] = len(granules)
    if not granules:
        raise RequestProblem("NISAR has no backscatter (GCOV) acquisitions over this area yet.", "unsupported")

    key, g_before, g_after, alternatives = select_pair(granules, req.date_before, req.date_after, req.track, bbox)
    track, direction, frame = key
    rec.note(
        "select_stack",
        track=track,
        direction=direction,
        frame=frame,
        other_tracks_with_both_dates=[k[0] for k in alternatives],
    )
    available = [p for p in gcov.POL_TO_LAYER if p in g_before.polarizations and p in g_after.polarizations]
    primary = common.co_pol(available) if req.polarization == "auto" else req.polarization
    if primary not in available:
        have = common.join_words(available) or "no polarization shared by both dates"
        raise RequestProblem(
            f"{req.polarization} is not available for these dates on {common.stack_name(key)}; it has {have}.",
            "unsupported",
        )

    with rec.step("read_windows", polarizations=available) as step:
        cuts = gcov.read_windows([g_before, g_after], bbox, tuple(available), max_workers=common.MAX_WORKERS)
        for cut in cuts:
            if isinstance(cut, Exception):
                status, reason = common.explain_read_error(cut)
                raise RequestProblem(reason, status)
        before, after = cuts
        step.params.update(
            rows=list(before.rows),
            cols=list(before.cols),
            epsg=before.epsg,
            megabytes_transferred=round(sum(c.io.get("megabytes", 0.0) for c in cuts), 1),
            from_cache=[c.from_cache for c in cuts],
        )
    rec.use(g_before)
    rec.use(g_after)
    if (before.rows, before.cols, before.epsg) != (after.rows, after.cols, after.epsg):
        raise RequestProblem(
            "The two acquisitions are not on the same pixel grid, so they cannot be compared.", "unsupported"
        )

    pixel_area = before.pixel_area_km2
    present = [p for p in available if gcov.POL_TO_LAYER[p] in before.layers and gcov.POL_TO_LAYER[p] in after.layers]
    if primary not in present:
        raise RequestProblem(f"{primary} could not be read for both dates.", "unsupported")
    power = {p: (before.layers[gcov.POL_TO_LAYER[p]], after.layers[gcov.POL_TO_LAYER[p]]) for p in present}

    speck_diameter = MULTILOOK + SPECK_MARGIN
    # threads help here: numpy, scipy and the image writers release the interpreter lock while they work
    with ThreadPoolExecutor(max_workers=common.MAX_WORKERS) as pool, rec.step(
        "detect_change",
        multilook=MULTILOOK,
        sigma_estimator="1.4826 x median absolute deviation of the change",
        k_sigma=K_LEVELS,
        minimum_change_db=MIN_CHANGE_DB,
        speck_removal=f"binary opening with a disk {speck_diameter} pixels across",
        noise_margin_db=ops.NOISE_MARGIN_DB,
    ):
        analyses = dict(zip(present, pool.map(lambda p: analyse_pair(*power[p], p), present)))
        main = analyses[primary]
        cover = common.coverage(main.valid, common.expected_pixels(bbox, before))
        if not main.valid.any():
            raise RequestProblem(
                f"{common.stack_name(key)} has no valid radar samples inside the area on both dates: the area lies "
                "at the edge of this track's swath. Try another track.",
                "unsupported",
            )
        if not main.measurable.any():
            raise RequestProblem(
                "The whole area is at the radar noise floor on both dates (for example open water), so change "
                "cannot be measured here.",
                "unsupported",
            )
        stats = dict(zip(present, pool.map(lambda p: _polarization_stats(analyses[p], *power[p], pixel_area), present)))
        sensitivity = _sensitivity(main, *power[primary], pixel_area, pool)

    result_id = provenance.new_id("change")
    dates = (req.date_before, req.date_after)
    ordered = [primary] + [p for p in present if p != primary]
    with ThreadPoolExecutor(max_workers=common.MAX_WORKERS) as pool, rec.step(
        "write_artifacts", formats=["PNG", "GeoTIFF", "CSV", "JSON"], polarizations=ordered
    ):
        tiffs = [pool.submit(_geotiffs, result_id, analyses[p], before, dates, p == primary) for p in ordered]
        pngs = [pool.submit(_layers, result_id, analyses[p], before, dates, p == primary) for p in ordered]
        layers = [layer for job in pngs for layer in job.result()]
        downloads = [d for job in tiffs for d in job.result()]
        render.save_csv(
            provenance.artifact_path(result_id, "statistics.csv"),
            ["polarization", "quantity", "region", "level", "value", "unit"],
            _csv_rows(stats),
        )
        downloads += [
            Download(label=label, url=provenance.artifact_url(result_id, filename), format=kind)
            for label, filename, kind in (
                ("Change map (PNG)", "change_db.png", "png"),
                ("Statistics (CSV)", "statistics.csv", "csv"),
                ("Full result with receipt (JSON)", "result.json", "json"),
            )
        ]

    area = round(ops.area_km2(main.valid, pixel_area), 2)
    increased, decreased = stats[primary]["increased"], stats[primary]["decreased"]
    headline = (
        f"Radar brightness rose over {_area_range(increased['area_km2'])} and fell over "
        f"{_area_range(decreased['area_km2'])} of the {area:.0f} km2 area between "
        f"{common.pretty_span(*dates)}."
    )
    rose, fell = f"Area where radar brightness rose ({primary})", f"Area where radar brightness fell ({primary})"
    single_values = [
        ("analysed_area_km2", "Area analysed", "km2", area),
        (
            "cannot_tell_percent",
            f"Share of the area at the noise floor on both dates ({primary})",
            "%",
            _r(100 * main.cannot_tell_fraction, 1),
        ),
        ("increase_median_change_db", "Typical (median) change where it rose", "dB", increased["median_change_db"]),
        ("decrease_median_change_db", "Typical (median) change where it fell", "dB", decreased["median_change_db"]),
        ("scene_shift_db", "Scene-wide shift removed before comparing", "dB", _r(main.shift_db)),
    ]
    metrics = [
        Metric(key="increased_area_km2", label=rose, unit="km2", **increased["area_km2"]),
        Metric(key="decreased_area_km2", label=fell, unit="km2", **decreased["area_km2"]),
        *(Metric(key=key, label=label, unit=unit, central=value) for key, label, unit, value in single_values),
    ]
    for p in ordered[1:]:
        for change_class, word in (("increased", "rose"), ("decreased", "fell")):
            metrics.append(
                Metric(
                    key=f"{change_class}_area_km2_{p.lower()}",
                    label=f"Area where radar brightness {word} ({p})",
                    unit="km2",
                    **stats[p][change_class]["area_km2"],
                )
            )

    notes = [
        "Each area is a range, not one value: low uses the strict threshold (4 sigma), central 3 sigma and high "
        "the lenient one (2 sigma). The sensitivity list shows how other processing choices move the central value.",
    ]
    for p in ordered:
        a = analyses[p]
        note = (
            f"{p}: {_percent(a.floor_fraction[0])} of the area is at or below the noise floor on {dates[0]}, "
            f"{_percent(a.floor_fraction[1])} on {dates[1]} and {_percent(a.cannot_tell_fraction)} on both."
        )
        if not stats[p]["informative"]:
            note += f" {p} is not informative here: most of the area cannot be told apart from instrument noise."
        notes.append(note)
    notes += [
        "The noise floor is estimated from the darkest part of each image, not from the instrument's noise record. "
        "Pixels at the floor on only one date are kept; their change is a lower bound.",
        f"Changed patches narrower than about {speck_diameter * before.pixel_size[0]:.0f} m are not counted, so thin "
        "features such as narrow channels or roads are under-represented.",
    ]
    if alternatives:
        others = common.join_words([str(k[0]) for k in alternatives])
        notes.append(f"Track {others} also has both dates; track {track} was used. Pass track to choose another.")

    caveats = common.tier_caveats([g_before, g_after])
    if cover < common.MIN_COVERAGE:
        caveats.append(
            Caveat(
                code="partial_coverage",
                text=f"Valid radar samples cover only {_percent(cover)} of the requested area on this track; "
                "the areas refer to that part.",
            )
        )
    caveats += [
        Caveat(
            code="water_wind",
            text="Wind roughens open water and changes its brightness from one pass to the next. A change over "
            "water is not by itself a change of the surface.",
        ),
        Caveat(
            code="terrain",
            text="On steep slopes the radar image is distorted (layover) or blind (shadow); changes there are "
            "unreliable.",
        ),
        Caveat(
            code="not_land_cover",
            text="A change in radar brightness means the surface scatters the signal differently (water level, "
            "moisture, roughness, vegetation, structures). It is not by itself a land-cover label.",
        ),
    ]

    uncertainty = Uncertainty(
        method=(
            f"Per-pixel change in dB (after minus before) after {MULTILOOK}x{MULTILOOK} multilook in linear power, "
            f"minus the median change of all measurable pixels ({main.shift_db:+.2f} dB for {primary}). The no-change "
            f"spread sigma ({main.sigma_db:.2f} dB) is 1.4826 x the median absolute deviation of the change. A pixel counts "
            f"as changed when its change is at least k x sigma and at least {MIN_CHANGE_DB:.0f} dB, for k = 2, 3 "
            f"and 4; patches that cannot hold a disk {speck_diameter} pixels across are removed. Pixels within "
            f"{ops.NOISE_MARGIN_DB} dB of the estimated noise floor on both dates are excluded as 'cannot tell'."
        ),
        sensitivity=sensitivity,
        noise_floor_fraction=_r(main.cannot_tell_fraction, 3),
        notes=notes,
    )

    reproduce = _REPRODUCE.format(
        granules="\n".join(f"#   {g.granule_id} ({g.tier})" for g in (g_before, g_after)),
        bbox=tuple(bbox),
        before=req.date_before,
        after=req.date_after,
        track=track,
        pol=primary,
    )
    result = WorkflowResult(
        id=result_id,
        workflow="change",
        request=request,
        summary=Summary(headline=headline, metrics=metrics),
        layers=layers,
        stats={
            "primary_polarization": primary,
            "stack": {"track": track, "direction": direction, "frame": frame},
            "window": {
                "shape": list(before.shape),
                "pixel_size_m": list(before.pixel_size),
                "epsg": before.epsg,
                "multilook": MULTILOOK,
                "analysed_area_km2": area,
                "valid_fraction": _r(cover, 3),
            },
            "polarizations": stats,
        },
        uncertainty=uncertainty,
        caveats=caveats,
        receipt=rec.receipt(reproduce),
        downloads=downloads,
    )
    provenance.save_result(result)
    return result

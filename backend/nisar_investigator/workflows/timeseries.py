"""Workflow B: mean radar backscatter of an area on every available date (requirement R4).

Every date is read from the archive in parallel. Each track keeps its own series, because the same surface
looks different from different directions. A date enters a series only if valid radar samples cover the area.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import numpy as np

from .. import catalog, gcov, ops, provenance, render
from ..schemas import (
    Caveat,
    Download,
    Granule,
    Layer,
    Legend,
    Metric,
    Series,
    SeriesPoint,
    Summary,
    TimeSeriesRequest,
    Uncertainty,
    WorkflowResult,
)
from . import common
from .common import RequestProblem, StackKey

MAX_LAYERS = 30  # images offered for scrubbing through time
DISPLAY_MULTILOOK = 3  # light smoothing for the images only; the statistics use every pixel
MAX_IMAGE_SIDE = 1500  # larger windows are thinned for display
# Dates are read in batches sized so that the raw windows held in memory at once stay under this.
MEMORY_BUDGET_BYTES = 1_500_000_000
NOISE_MULTILOOK = 9  # the noise-floor share is judged on the same 9x9 multilook as the change workflow
# Dates of one stack acquired in the same radar mode see the area through the same swath. When the first date
# read from a stack is this far under the coverage requirement, its other dates in that mode are not downloaded.
STACK_SKIP_COVERAGE = common.MIN_COVERAGE - 0.1
UNINFORMATIVE_FRACTION = 0.5
MIN_STEPS_FOR_TYPICAL = 3


@dataclass
class RegionStats:
    """One polarization of one date, inside the requested area."""

    mean_db: float  # average in linear power, expressed in dB
    spread_db: float  # standard deviation of 5x5-multilooked dB values: spatial variety, not error
    n_pixels: int
    floor_fraction: float  # share of the area's pixels at the noise floor


@dataclass
class DateRecord:
    """What is kept of one usable date once its window has been measured."""

    granule: Granule
    stats: dict[str, RegionStats]  # polarization -> statistics
    image: np.ndarray | None  # dB picture of the displayed polarization, NaN where there is no data
    corners: list[tuple[float, float]]
    region_area_km2: float
    pixel_size_m: tuple[float, float]


@dataclass
class Skip:
    """Why a date is left out. `status` is set when the date could not be read at all."""

    reason: str
    coverage: float | None = None
    status: str | None = None


def region_stats(power: np.ndarray, polarization: str, region: np.ndarray | None = None) -> RegionStats:
    """Aggregate one linear-power image (NaN = no data) over a region (None = the whole image)."""
    mean, spread, n = ops.mean_db(power, region)
    at_floor, _ = ops.at_noise_floor(ops.to_db(ops.multilook(power, NOISE_MULTILOOK)), polarization)
    selected = np.isfinite(power) if region is None else np.isfinite(power) & region
    fraction = float((at_floor & selected).sum()) / n if n else float("nan")
    return RegionStats(mean_db=mean, spread_db=spread, n_pixels=n, floor_fraction=fraction)


def step_summary(points: list[SeriesPoint]) -> dict | None:
    """Largest and typical change between consecutive dates of one series.

    Steps that touch a beta-tier (uncalibrated) date are left out when calibrated dates exist, because such a
    step can be a calibration difference. Returns None when fewer than two usable dates remain.
    """
    measured = [p for p in points if p.value is not None]
    calibrated = [p for p in measured if p.tier != "beta"]
    usable = calibrated if len(calibrated) >= 2 else measured
    if len(usable) < 2:
        return None
    steps = [(round(b.value - a.value, 2), a.date, b.date) for a, b in zip(usable, usable[1:])]
    largest = max(steps, key=lambda s: abs(s[0]))
    sizes = [abs(s[0]) for s in steps]
    return {
        "largest_step_db": largest[0],
        "from": largest[1],
        "to": largest[2],
        "typical_step_db": round(float(np.median(sizes)), 2) if len(steps) >= MIN_STEPS_FOR_TYPICAL else None,
        "n_steps": len(steps),
        "calibrated_dates_only": usable is calibrated,
    }


# ------------------------------------------------------------------ request


def _polygon(geometry: dict | None, bbox) -> dict | None:
    """The GeoJSON Polygon of the request (a Feature wrapper is accepted), checked against the box."""
    if geometry is None:
        return None
    if geometry.get("type") == "Feature":
        geometry = geometry.get("geometry") or {}
    rings = geometry.get("coordinates")
    try:
        ok = geometry.get("type") == "Polygon" and all(len(ring) >= 3 for ring in rings) and len(rings) >= 1
        points = [(float(p[0]), float(p[1])) for ring in rings for p in ring] if ok else []
    except (TypeError, ValueError, IndexError):
        ok, points = False, []
    if not ok:
        raise RequestProblem("geometry must be a GeoJSON Polygon with coordinates as [longitude, latitude] pairs.")
    west, south, east, north = bbox
    slack = 1e-6
    if any(not (west - slack <= x <= east + slack and south - slack <= y <= north + slack) for x, y in points):
        raise RequestProblem("geometry must lie inside bbox.")
    return {"type": "Polygon", "coordinates": rings}


class _Regions:
    """The requested area on each pixel grid: a mask (None = the whole window) and the pixels it should hold."""

    def __init__(self, bbox, polygon: dict | None):
        self.bbox = bbox
        self.polygon = polygon
        self._cache: dict[tuple, tuple[np.ndarray | None, float]] = {}

    def on(self, cut: gcov.Cutout) -> tuple[np.ndarray | None, float]:
        key = (cut.epsg, cut.rows, cut.cols)
        if key not in self._cache:
            if self.polygon is None:
                self._cache[key] = (None, float(common.expected_pixels(self.bbox, cut)))
            else:
                mask = ops.polygon_mask(self.polygon, cut.x, cut.y, cut.epsg)
                expected = ops.polygon_area_m2(self.polygon, cut.epsg) / (cut.pixel_area_km2 * 1e6)
                self._cache[key] = (mask, expected)
        return self._cache[key]

    def coverage(self, cut: gcov.Cutout) -> float:
        """Share of the requested area that carries valid samples on this date."""
        if not cut.layers:
            return 0.0
        mask, expected = self.on(cut)
        valid = np.isfinite(next(iter(cut.layers.values())))
        return common.coverage(valid if mask is None else valid & mask, expected)


# ---------------------------------------------------------------- measuring


def _display_image(power: np.ndarray) -> np.ndarray:
    """Lightly multilooked dB picture, thinned so that neither side exceeds MAX_IMAGE_SIDE."""
    step = int(np.ceil(max(power.shape) / MAX_IMAGE_SIDE))
    image = ops.to_db(ops.multilook(power, max(DISPLAY_MULTILOOK, step)))
    image[~np.isfinite(power)] = np.nan  # keep no-data transparent
    return image[::step, ::step].astype(np.float32)


def examine(
    granule: Granule,
    cut: gcov.Cutout | Exception,
    regions: _Regions,
    polarizations: tuple[str, ...],
    shown: str,
) -> DateRecord | Skip:
    """Measure one date, or say why it cannot be used."""
    if isinstance(cut, Exception):
        status, reason = common.explain_read_error(cut)
        return Skip(reason=reason.rstrip("."), status=status)
    cover = regions.coverage(cut)
    if cover < common.MIN_COVERAGE:
        return Skip(reason=f"valid radar samples cover only {_percent(cover)} of the area", coverage=cover)
    region, expected = regions.on(cut)
    layers = {p: cut.layers[gcov.POL_TO_LAYER[p]] for p in polarizations if gcov.POL_TO_LAYER[p] in cut.layers}
    return DateRecord(
        granule=granule,
        stats={p: region_stats(power, p, region) for p, power in layers.items()},
        image=_display_image(layers[shown]) if shown in layers else None,
        corners=cut.corners_lonlat(),
        region_area_km2=expected * cut.pixel_area_km2,
        pixel_size_m=cut.pixel_size,
    )


# ---------------------------------------------------------------- wording


def _r(value: float | None, digits: int = 2) -> float | None:
    return round(float(value), digits) if value is not None and np.isfinite(value) else None


def _percent(fraction: float) -> str:
    return f"{100 * fraction:.0f}%"


def _series_id(key: StackKey, pol: str) -> str:
    return f"{pol.lower()}_t{key[0]}_f{key[2]}"


def _skipped_caveat(skipped: list[dict]) -> Caveat:
    """One sentence per track about the dates that were left out, and why."""
    by_stack: dict[str, list[dict]] = {}
    for item in skipped:
        by_stack.setdefault(item["stack"], []).append(item)
    parts = []
    for name, items in by_stack.items():
        dates = sorted(i["date"] for i in items)
        which = common.join_words(dates) if len(dates) <= 3 else f"{len(dates)} dates from {dates[0]} to {dates[-1]}"
        reasons = sorted({i["reason"] for i in items})
        parts.append(f"{name[0].upper()}{name[1:]}: {which} not used, because {'; '.join(reasons)}.")
    return Caveat(code="dates_skipped", text="Some acquisitions were left out. " + " ".join(parts))


_REPRODUCE = '''\
# Needs: pip install -e backend/  and an Earthdata Login in ~/.netrc (or EARTHDATA_TOKEN).
# Reads the best calibration tier available when it runs; the receipt lists the {n} granules this result used.
from nisar_investigator.schemas import TimeSeriesRequest
from nisar_investigator.workflows.timeseries import run_timeseries

if __name__ == "__main__":  # required: the reader starts worker processes
    result = run_timeseries(TimeSeriesRequest(
        bbox={bbox}, geometry={geometry}, start={start}, end={end}, polarizations={polarizations},
    ))
    print(result.summary.headline)
    for series in result.series:
        for p in series.points:
            print(series.label, p.date, p.value, p.spread, p.tier)
'''


# --------------------------------------------------------------- the workflow


def run_timeseries(req: TimeSeriesRequest) -> WorkflowResult:
    """Run workflow B. Never raises: problems come back as a result with status 'unsupported' or 'error'."""
    request = req.model_dump(mode="json")
    rec = provenance.Recorder()
    try:
        return _run(req, request, rec)
    except RequestProblem as problem:
        return common.failure("timeseries", problem.status, str(problem), request, rec, problem.stats)
    except Exception as exc:  # noqa: BLE001 - the interface must get a readable result, never a traceback
        common.log_failure("timeseries", exc)
        headline = f"The time series failed unexpectedly ({type(exc).__name__}). Nothing was measured."
        return common.failure("timeseries", "error", headline, request, rec)


def _run(req: TimeSeriesRequest, request: dict, rec: provenance.Recorder) -> WorkflowResult:
    bbox = req.bbox
    common.check_bbox(bbox)
    start = common.parse_date(req.start, "start") if req.start else None
    end = common.parse_date(req.end, "end") if req.end else None
    if start and end and start > end:
        raise RequestProblem("start must not be later than end.")
    polarizations = tuple(dict.fromkeys(req.polarizations))
    unknown = [p for p in polarizations if p not in gcov.POL_TO_LAYER]
    if unknown or not polarizations:
        raise RequestProblem(f"polarizations must be chosen from {common.join_words(list(gcov.POL_TO_LAYER))}.")
    polygon = _polygon(req.geometry, bbox)
    regions = _Regions(bbox, polygon)

    with rec.step("search_catalog", product="GCOV", bbox=list(bbox), start=req.start, end=req.end) as step:
        try:
            granules = catalog.search("GCOV", bbox=bbox, start=req.start, end=req.end)
        except Exception as exc:  # noqa: BLE001
            raise RequestProblem(common.explain_search_error(exc)) from None
        step.params["granules_found"] = len(granules)
    if not granules:
        when = " in this date range" if (start or end) else " yet"
        raise RequestProblem(f"NISAR has no backscatter (GCOV) acquisitions over this area{when}.", "unsupported")
    stacks = common.group_stacks(granules)
    carried = sorted({p for g in granules for p in g.polarizations})
    if not set(polarizations) & set(carried):
        raise RequestProblem(
            f"None of the requested polarizations ({common.join_words(list(polarizations))}) is acquired here; "
            f"the data has {common.join_words(carried)}.",
            "unsupported",
        )

    shown = common.co_pol([p for p in polarizations if p in carried]) or next(p for p in polarizations if p in carried)
    bytes_per_date = common.approx_pixels(bbox) * 4 * len(polarizations)
    batch_size = max(common.MAX_WORKERS, int(MEMORY_BUDGET_BYTES // bytes_per_date))

    records: dict[StackKey, list[DateRecord]] = {}
    skipped: dict[str, dict] = {}  # by granule id
    failures: list[Skip] = []
    io = dict.fromkeys(("granules_read", "from_cache"), 0)
    io.update(megabytes_transferred=0.0, read_seconds=0.0, measure_seconds=0.0)

    def skip(key: StackKey, granule: Granule, reason: str) -> None:
        skipped[granule.granule_id] = {
            "date": granule.date,
            "stack": common.stack_name(key),
            "track": key[0],
            "direction": key[1],
            "reason": reason,
        }

    def handle(batch: list[tuple[StackKey, Granule]]) -> list[DateRecord | Skip]:
        """Read and measure one batch of dates, then let go of the raw windows."""
        t0 = time.time()
        cuts = gcov.read_windows([g for _, g in batch], bbox, polarizations, max_workers=common.MAX_WORKERS)
        t1 = time.time()
        with ThreadPoolExecutor(max_workers=common.MAX_WORKERS) as pool:
            jobs = [(granule, cut, regions, polarizations, shown) for (_, granule), cut in zip(batch, cuts)]
            outcomes = list(pool.map(lambda job: examine(*job), jobs))
        for (key, granule), cut, outcome in zip(batch, cuts, outcomes):
            if isinstance(cut, gcov.Cutout):
                io["granules_read"] += 1
                io["from_cache"] += int(cut.from_cache)
                io["megabytes_transferred"] += cut.io.get("megabytes", 0.0)
            if isinstance(outcome, DateRecord):
                records.setdefault(key, []).append(outcome)
                continue
            skip(key, granule, outcome.reason)
            if outcome.status:
                failures.append(outcome)
        io["read_seconds"] += t1 - t0
        io["measure_seconds"] += time.time() - t1
        return outcomes

    with rec.step(
        "read_and_measure",
        polarizations=list(polarizations),
        workers=common.MAX_WORKERS,
        statistic="mean in linear power, expressed in dB",
        spread="standard deviation of 5x5-multilooked dB values inside the area",
        region="polygon" if polygon else "bbox",
        minimum_coverage=common.MIN_COVERAGE,
    ) as step:
        queue = [(key, g) for key, items in stacks.items() for g in items]
        if len(stacks) > 1:
            # The most recent date of each stack is read first (see STACK_SKIP_COVERAGE).
            probes = [(key, items[-1]) for key, items in stacks.items()]
            for (key, probe), outcome in zip(probes, handle(probes)):
                misses = isinstance(outcome, Skip) and outcome.coverage is not None
                if misses and outcome.coverage < STACK_SKIP_COVERAGE:
                    reason = (
                        f"valid radar samples cover only {_percent(outcome.coverage)} of the area on this track, "
                        f"measured on {probe.date} (its other dates share the same swath and were not read)"
                    )
                    for g in stacks[key]:
                        if g.mode == probe.mode:
                            skip(key, g, reason)
            done = {g.granule_id for _, g in probes} | set(skipped)
            queue = [(key, g) for key, g in queue if g.granule_id not in done]
        for i in range(0, len(queue), batch_size):
            handle(queue[i : i + batch_size])
        step.params.update({k: round(v, 1) if isinstance(v, float) else v for k, v in io.items()})

    if not records:
        if failures and len(failures) == len(skipped):  # nothing could be read at all: report the cause itself
            status = "error" if any(f.status == "error" for f in failures) else "unsupported"
            raise RequestProblem(failures[0].reason + ".", status, {"skipped": list(skipped.values())})
        raise RequestProblem(
            f"None of the {len(granules)} acquisitions has valid radar samples over at least "
            f"{_percent(common.MIN_COVERAGE)} of the area: it lies at the edge of every track that passes here. "
            "Try a smaller or shifted area.",
            "unsupported",
            {"skipped": list(skipped.values())},
        )
    for items in records.values():
        items.sort(key=lambda r: r.granule.start_time or "")
        for record in items:
            rec.use(record.granule)

    # ---- series, one per stack and polarization
    series: list[Series] = []
    series_stats: dict[str, dict] = {}
    floor_fractions: dict[str, float] = {}
    csv_rows: list[list] = []
    for key, items in records.items():
        track, direction, _ = key
        for p in polarizations:
            measured = [(r.granule, r.stats[p]) for r in items if p in r.stats and r.stats[p].n_pixels]
            if not measured:
                continue
            points = [
                SeriesPoint(
                    date=g.date or "", value=_r(s.mean_db), spread=_r(s.spread_db), tier=g.tier, granule_id=g.granule_id
                )
                for g, s in measured
            ]
            sid = _series_id(key, p)
            series.append(
                Series(
                    id=sid,
                    label=f"{p} mean, track {track} {direction}",
                    unit="dB",
                    track=track,
                    direction=direction,
                    polarization=p,
                    points=points,
                )
            )
            values = [pt.value for pt in points if pt.value is not None]
            floor_fractions[sid] = float(np.mean([s.floor_fraction for _, s in measured]))
            series_stats[sid] = {
                "track": track,
                "direction": direction,
                "polarization": p,
                "n_dates": len(points),
                "mean_db": _r(float(np.mean(values))),
                "min_db": min(values),
                "max_db": max(values),
                "mean_noise_floor_fraction": _r(floor_fractions[sid], 3),
                "steps": step_summary(points),
            }
            csv_rows += [
                [g.date, track, direction, p, _r(s.mean_db), _r(s.spread_db), s.n_pixels, g.tier, g.granule_id]
                for g, s in measured
            ]

    # ---- images of the best-populated stack, for scrubbing through time
    result_id = provenance.new_id("timeseries")
    best = max(records, key=lambda key: (sum(r.image is not None for r in records[key]), len(records[key]), -key[0]))
    frames = [r for r in records[best] if r.image is not None][-MAX_LAYERS:]
    layers: list[Layer] = []
    if frames:
        with rec.step(
            "render_layers", format="PNG", polarization=shown, multilook=DISPLAY_MULTILOOK, images=len(frames)
        ):
            sample = np.concatenate([r.image[::4, ::4].ravel() for r in frames])
            low, high = np.nanpercentile(sample, [2, 98])  # one grey scale for every date
            low, high = float(np.floor(low * 2) / 2), float(np.ceil(high * 2) / 2)

            def draw(record: DateRecord) -> Layer:
                day = record.granule.date or ""
                filename = f"{shown.lower()}_{day}.png"
                render.save_grey_png(provenance.artifact_path(result_id, filename), record.image, low, high)
                return Layer(
                    id=f"{shown.lower()}_{day}",
                    title=f"{shown}, {common.pretty_date(day)} (dB)",
                    url=provenance.artifact_url(result_id, filename),
                    corners=record.corners,
                    legend=Legend(type="continuous", unit="dB", min=low, max=high, colormap="grey"),
                    date=day,
                )

            with ThreadPoolExecutor(max_workers=common.MAX_WORKERS) as pool:
                layers = list(pool.map(draw, frames))
        layers[-1].default_visible = True

    # ---- summary
    used = [r.granule for items in records.values() for r in items]
    days = sorted({g.date for g in used if g.date})
    main_pol = shown
    candidates = [
        (sid, s["steps"]) for sid, s in series_stats.items() if s["polarization"] == main_pol and s["steps"] is not None
    ]
    n_tracks = len(records)
    first_day, last_day = common.pretty_date(days[0]), common.pretty_date(days[-1])
    headline = (
        f"{len(days)} {'date' if len(days) == 1 else 'dates'} on {n_tracks} {'track' if n_tracks == 1 else 'tracks'}"
        + (f" from {first_day} to {last_day}." if len(days) > 1 else f": {first_day}.")
    )
    metrics = [
        Metric(key="n_dates", label="Dates used", unit="dates", central=len(days)),
        Metric(key="n_tracks", label="Tracks", unit="tracks", central=n_tracks),
    ]
    notes: list[str] = []
    if candidates:
        sid, steps = max(candidates, key=lambda c: abs(c[1]["largest_step_db"]))
        track = series_stats[sid]["track"]
        step = steps["largest_step_db"]
        verb = "rose" if step > 0 else "fell"
        usual = steps["typical_step_db"]
        if usual is not None and abs(step) >= 3 * max(usual, 0.05):
            headline += (
                f" Radar brightness was steady apart from one change: it {verb} by {abs(step):.2f} dB between "
                f"{common.pretty_span(steps['from'], steps['to'])} (track {track})"
            )
        else:
            headline += (
                f" Radar brightness stayed steady: the biggest change between two passes was {abs(step):.2f} dB, "
                f"between {common.pretty_span(steps['from'], steps['to'])} (track {track})"
            )
        metrics.append(
            Metric(
                key="largest_step_db",
                label=f"Largest step between consecutive dates ({main_pol}, track {track}, "
                f"{steps['from']} to {steps['to']})",
                unit="dB",
                central=steps["largest_step_db"],
            )
        )
        if steps["typical_step_db"] is not None:
            headline += f", against a usual change of {steps['typical_step_db']:.2f} dB between passes."
            metrics.append(
                Metric(
                    key="typical_step_db",
                    label=f"Typical (median) change between consecutive dates ({main_pol}, track {track})",
                    unit="dB",
                    central=steps["typical_step_db"],
                )
            )
        else:
            headline += "; there are too few dates to say what a typical change is."
        if steps["calibrated_dates_only"] and any(g.tier == "beta" for g in used):
            notes.append(
                "Steps to or from beta-tier (uncalibrated) dates are left out of the largest and typical step."
            )
    else:
        headline += " One date per track is not enough to measure change over time."

    notes.append(
        "The mean includes pixels at the noise floor. Where a large share of the area is at the floor, the mean "
        "is held up by instrument noise and under-states real change."
    )
    for sid, fraction in floor_fractions.items():
        s = series_stats[sid]
        note = (
            f"{s['polarization']} on track {s['track']}: on average {_percent(fraction)} of the area is at the "
            "noise floor."
        )
        if fraction > UNINFORMATIVE_FRACTION:
            note += f" {s['polarization']} is not informative here."
        notes.append(note)
    if len(records[best]) > len(frames) > 0:
        notes.append(f"Images are provided for the {len(frames)} most recent dates of track {best[0]} only.")

    main_floor = floor_fractions.get(_series_id(best, main_pol))
    uncertainty = Uncertainty(
        method=(
            "Each point is the mean backscatter of the area on one date, averaged in linear power and expressed in "
            "dB. Spread is the standard deviation, in dB, of 5x5-multilooked pixel values inside the area: it says "
            "how varied the surface is, not how uncertain the mean is. Typical date-to-date change is the median "
            "absolute difference between consecutive dates of one track. The noise-floor share is the fraction of "
            f"the area within {ops.NOISE_MARGIN_DB} dB of the darkest level in the scene after "
            f"{NOISE_MULTILOOK}x{NOISE_MULTILOOK} multilook, averaged over dates."
        ),
        noise_floor_fraction=_r(main_floor, 3),
        notes=notes,
    )

    caveats = common.tier_caveats(used)
    if n_tracks > 1:
        caveats.append(
            Caveat(
                code="tracks_not_comparable",
                text="Each track looks at the area from a different direction and angle, so absolute levels of "
                "different tracks are not directly comparable. Compare dates within one track.",
            )
        )
    if skipped:
        caveats.append(_skipped_caveat(list(skipped.values())))
    caveats += [
        Caveat(
            code="weather",
            text="Rain, snow, freezing, soil moisture and wind over water change radar brightness within days. "
            "A step in the series is not by itself a lasting change of the surface.",
        ),
        Caveat(
            code="not_land_cover",
            text="Mean brightness describes how the area scatters the radar signal; it is not a land-cover label.",
        ),
    ]

    with rec.step("write_downloads", formats=["CSV", "JSON"]):
        render.save_csv(
            provenance.artifact_path(result_id, "timeseries.csv"),
            ["date", "track", "direction", "polarization", "mean_db", "spread_db", "n_pixels", "tier", "granule_id"],
            sorted(csv_rows, key=lambda row: (row[1], row[3], row[0])),
        )
        downloads = [
            Download(label=label, url=provenance.artifact_url(result_id, filename), format=kind)
            for label, filename, kind in (
                ("Time series (CSV)", "timeseries.csv", "csv"),
                ("Full result with receipt (JSON)", "result.json", "json"),
            )
        ]

    reference = records[best][0]
    reproduce = _REPRODUCE.format(
        n=len(used),
        bbox=tuple(bbox),
        geometry=repr(polygon),
        start=repr(req.start),
        end=repr(req.end),
        polarizations=list(polarizations),
    )
    result = WorkflowResult(
        id=result_id,
        workflow="timeseries",
        request=request,
        summary=Summary(headline=headline, metrics=metrics),
        layers=layers,
        series=series,
        stats={
            "dates": {"count": len(days), "first": days[0], "last": days[-1]},
            "tracks": [
                {"track": k[0], "direction": k[1], "frame": k[2], "dates_used": len(v)} for k, v in records.items()
            ],
            "region": {
                "kind": "polygon" if polygon else "bbox",
                "area_km2": round(reference.region_area_km2, 2),
                "pixel_size_m": list(reference.pixel_size_m),
            },
            "series": series_stats,
            "skipped": list(skipped.values()),
            "images": {"track": best[0], "polarization": shown, "count": len(layers)},
        },
        uncertainty=uncertainty,
        caveats=caveats,
        receipt=rec.receipt(reproduce),
        downloads=downloads,
    )
    provenance.save_result(result)
    return result

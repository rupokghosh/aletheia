"""Plain-language presentation of results: what each map layer shows, and what a value at one spot means.

Everything here is deterministic text built from computed values. Nothing is inferred by a language model.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image
from pyproj import Transformer

from . import config, gcov, provenance
from .schemas import Granule, WorkflowResult
from .workflows import common

_BRIGHTNESS = (
    "How strongly the ground reflected the radar on this date. Dark: smooth surfaces such as calm water, "
    "roads or flat bare ground. Bright: rough or tall things such as forest, buildings or flooded vegetation."
)
_HV_NOTE = " This is the radar's second channel (HV), which responds mostly to vegetation."


def _date_from_id(layer_id: str) -> str:
    return layer_id.rsplit("_", 1)[-1]


def annotate(result: WorkflowResult) -> WorkflowResult:
    """Give every layer a plain title, a description of its colours, and captions for its legend."""
    for layer in result.layers:
        if layer.technical_title:  # already annotated
            continue
        layer.technical_title = layer.title
        hv = layer.id.endswith("_hv") or layer.id.startswith("hv_")
        base = layer.id[:-3] if layer.id.endswith("_hv") else layer.id
        legend = layer.legend

        if base in ("before", "after") or (layer.date and base[:3] in ("hh_", "hv_", "vv_", "vh_")):
            day = layer.date or _date_from_id(layer.id)
            layer.title = f"Radar image, {common.pretty_date(day)}"
            layer.description = _BRIGHTNESS
            if legend:
                legend.min_label, legend.max_label = "dark: smooth, calm water", "bright: rough, forest, buildings"
        elif base == "change_db":
            layer.title = "Where it changed, and how much"
            layer.description = (
                "Red: the ground reflects more radar than before, for example where water receded and left wet "
                "ground, or where forest was flooded. Blue: it reflects less, for example new open water or "
                "vegetation that was removed. White: no real change."
            )
            if legend:
                legend.min_label, legend.max_label = "darker than before", "brighter than before"
        elif base == "change_classes":
            layer.title = "Clear changes only"
            layer.description = (
                "Only the places where the change is larger than the measurement noise. "
                "Grey marks places too dark on both dates for the radar to tell."
            )
            if legend and len(legend.classes) == 3:
                for cls, label in zip(legend.classes, ("Clearly brighter", "Clearly darker", "Too dark to tell")):
                    cls["detail"], cls["label"] = cls["label"], label
        elif base == "displacement":
            layer.title = "Ground movement"
            layer.description = (
                "How far the ground moved toward or away from the satellite between the two passes, in "
                "centimetres. Red: toward the satellite. Blue: away from it. Gaps: water, or places where the "
                "radar lost track of the surface."
            )
            if legend:
                legend.min_label, legend.max_label = "away from the satellite", "toward the satellite"
        elif base == "coherence":
            layer.title = "How trustworthy each spot is"
            layer.description = (
                "White: the surface stayed stable between the two passes, so the movement measured there can "
                "be trusted. Black: the signal was lost, as over water, dense vegetation or snow."
            )
            layer.group = "advanced"
            if legend:
                legend.min_label, legend.max_label = "signal lost", "stable surface"
        elif base == "fringes":
            layer.title = "Movement as contour bands"
            layer.description = (
                f"Each full colour cycle is {legend.max if legend and legend.max else 12.1:g} cm of movement, "
                "like contour lines on a hiking map. Tight bands mean the ground moved a lot over a short distance."
            )
            layer.group = "advanced"
        if hv:
            layer.group = "advanced"
            layer.title += " (vegetation channel)"
            layer.description = (layer.description or "") + _HV_NOTE
    return result


def annotate_dict(result: dict) -> dict:
    """The same for a stored result (a dict). Anything that is not a WorkflowResult is returned unchanged."""
    if not isinstance(result, dict) or "layers" not in result or "workflow" not in result:
        return result
    return annotate(WorkflowResult.model_validate(result)).model_dump(mode="json")


# ------------------------------------------------------------------ reading one spot


class PointError(ValueError):
    """The spot cannot be read (unknown result, outside the area)."""


@lru_cache(maxsize=24)
def _geotiff(path: str):
    """A GeoTIFF written by render.save_geotiff: (array, x0, y0, dx, dy, epsg)."""
    with Image.open(path) as im:
        scale, tie, keys = im.tag_v2[33550], im.tag_v2[33922], im.tag_v2[34735]
        array = np.asarray(im, dtype=np.float32)
    epsg = next(int(keys[i + 3]) for i in range(4, len(keys), 4) if keys[i] == 3072)
    return array, float(tie[3]), float(tie[4]), float(scale[0]), float(scale[1]), epsg


def _sample(result_id: str, filename: str, lon: float, lat: float) -> float | None:
    path = config.artifacts_dir() / result_id / filename
    if not path.exists():
        return None
    array, x0, y0, dx, dy, epsg = _geotiff(str(path))
    x, y = Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True).transform(lon, lat)
    col, row = int((x - x0) // dx), int((y0 - y) // dy)
    if not (0 <= row < array.shape[0] and 0 <= col < array.shape[1]):
        raise PointError("That spot is outside the analysed area.")
    value = float(array[row, col])
    return value if np.isfinite(value) else None


def brightness_words(db: float, floor: float | None) -> str:
    if floor is not None and db <= floor + 1.5:
        return "as dark as the radar can measure, typical of calm water or very smooth ground"
    if db < -13:
        return "dark, typical of smooth or sparsely covered ground"
    if db < -7:
        return "medium, typical of fields, shrubs or rough ground"
    if db < -2:
        return "bright, typical of forest or rough terrain"
    return "very bright, typical of buildings, steep slopes facing the radar or flooded vegetation"


def _change_reading(result: dict, lon: float, lat: float) -> dict:
    rid = result["id"]
    pol = result["stats"].get("primary_polarization", "HH")
    stats = result["stats"]["polarizations"][pol]
    before, after, change = (_sample(rid, f, lon, lat) for f in ("before_db.tif", "after_db.tif", "change_db.tif"))
    d0, d1 = result["request"]["date_before"], result["request"]["date_after"]
    day0, day1 = common.pretty_date(d0), common.pretty_date(d1)
    if before is None or after is None or change is None:
        return {"readings": [], "sentence": "There is no valid radar measurement at this spot."}
    floors = stats.get("noise_floor_db", {})
    central = stats["thresholds_db"]["central"]
    lenient = stats["thresholds_db"]["lenient"]
    dark_both = before <= floors.get("before", -99) + 1.5 and after <= floors.get("after", -99) + 1.5
    readings = [
        {"label": f"Radar brightness on {day0}", "value": round(before, 1), "unit": "dB", "note": brightness_words(before, floors.get("before"))},
        {"label": f"Radar brightness on {day1}", "value": round(after, 1), "unit": "dB", "note": brightness_words(after, floors.get("after"))},
        {"label": "Change", "value": round(change, 1), "unit": "dB", "note": ""},
    ]
    causes: list[str] = []
    if dark_both:
        verdict = "too dark on both dates for the radar to tell whether anything changed"
    elif abs(change) < lenient:
        verdict = f"no real change (within the {lenient:g} dB the method can resolve)"
    else:
        strength = "a clear change" if abs(change) >= central else "a possible change, close to the noise"
        direction = "brighter" if change > 0 else "darker"
        verdict = f"{direction} by {abs(change):.1f} dB, {strength}"
        if change > 0:
            causes = (["water receded and exposed ground", "wind roughened open water"]
                      if before <= floors.get("before", -99) + 1.5
                      else ["standing water under vegetation", "wetter soil", "new structures"])
        else:
            causes = (["new open water over ground that was dry", "a surface that became very smooth"]
                      if after <= floors.get("after", -99) + 1.5
                      else ["vegetation removed or burned", "drying soil", "flood water draining from under vegetation"])
    readings[2]["note"] = verdict
    sentence = f"Between {day0} and {day1} this spot went from {before:.1f} to {after:.1f} dB: {verdict}."
    out = {"readings": readings, "sentence": sentence}
    if causes:
        out["common_causes"] = causes
        out["causes_note"] = "Common causes of a change like this. They are possibilities to check, not a diagnosis."
    return out


def _motion_reading(result: dict, lon: float, lat: float) -> dict:
    rid = result["id"]
    moved = _sample(rid, "displacement_cm.tif", lon, lat)
    coherence = _sample(rid, "coherence.tif", lon, lat)
    pair, noise = result["stats"]["pair"], result["stats"]["noise"]["noise_level_cm"]
    span = common.pretty_span(pair["reference_date"], pair["secondary_date"])
    readings = []
    if coherence is not None:
        readings.append({"label": "Signal stability (0 to 1)", "value": round(coherence, 2), "unit": "",
                         "note": "stable enough to trust" if coherence >= 0.3 else "too unstable to trust"})
    if moved is None:
        return {"readings": readings, "sentence": "No reliable movement measurement at this spot: it is water, or the radar lost track of the surface between the two passes."}
    direction = "toward" if moved > 0 else "away from"
    if abs(moved) < 2 * noise:
        verdict = f"within the noise ({noise:g} cm), so no movement can be claimed here"
    else:
        verdict = f"well above the {noise:g} cm noise level"
    readings.insert(0, {"label": "Movement along the radar's line of sight", "value": round(moved, 1), "unit": "cm", "note": f"{direction} the satellite"})
    sentence = (f"Between {span} this spot moved {abs(moved):.1f} cm {direction} the satellite, relative to the "
                f"middle of the area: {verdict}.")
    return {"readings": readings, "sentence": sentence}


def _series_reading(result: dict, lon: float, lat: float) -> dict:
    bbox = tuple(result["request"]["bbox"])
    pols = tuple(result["request"].get("polarizations") or ("HH", "HV"))
    layers = tuple(gcov.POL_TO_LAYER[p] for p in pols if p in gcov.POL_TO_LAYER)
    series: dict[tuple, list] = {}
    for g in result["receipt"]["granules"]:
        if g.get("product") != "GCOV" or not gcov._cache_path(g["granule_id"], bbox, layers, "A").exists():
            continue
        granule = Granule(granule_id=g["granule_id"], product="GCOV", tier=g["tier"], url=g["url"], track=g["track"],
                          frame=g["frame"], direction=g["direction"], mode="", polarizations=g.get("polarizations", []), date=g.get("date"))
        cut = gcov.read_window(granule, bbox, pols)
        x, y = Transformer.from_crs("EPSG:4326", f"EPSG:{cut.epsg}", always_xy=True).transform(lon, lat)
        dx, dy = cut.pixel_size
        col, row = int(round((x - cut.x[0]) / dx)), int(round((cut.y[0] - y) / dy))
        if not (2 <= row < cut.shape[0] - 2 and 2 <= col < cut.shape[1] - 2):
            continue
        for pol in pols:
            arr = cut.layers.get(gcov.POL_TO_LAYER[pol])
            if arr is None:
                continue
            patch = arr[row - 2: row + 3, col - 2: col + 3]
            if np.isfinite(patch).sum() < 5:
                continue
            value = float(10 * np.log10(np.nanmean(patch)))
            series.setdefault((g["track"], g["direction"], pol), []).append({"date": g["date"], "value": round(value, 2), "tier": g["tier"]})
    out_series = [
        {"id": f"point_{pol.lower()}_{track}", "label": f"{pol} at this spot, track {track}", "unit": "dB", "track": track,
         "direction": direction, "polarization": pol, "points": sorted(points, key=lambda p: p["date"])}
        for (track, direction, pol), points in sorted(series.items()) if len(points) >= 2
    ]
    if not out_series:
        return {"readings": [], "series": [], "sentence": "No radar history could be read at this spot."}
    main = max((s for s in out_series if s["polarization"] in ("HH", "VV")), key=lambda s: len(s["points"]), default=out_series[0])
    values = [p["value"] for p in main["points"]]
    steps = [(abs(b["value"] - a["value"]), a, b) for a, b in zip(main["points"], main["points"][1:])]
    biggest = max(steps, key=lambda s: s[0])
    sentence = (
        f"Over {len(values)} dates this spot ranged from {min(values):.1f} to {max(values):.1f} dB "
        f"({brightness_words(float(np.median(values)), None)}). The largest jump between consecutive dates was "
        f"{biggest[2]['value'] - biggest[1]['value']:+.1f} dB, from {common.pretty_date(biggest[1]['date'])} "
        f"to {common.pretty_date(biggest[2]['date'])}."
    )
    return {"readings": [], "series": out_series, "sentence": sentence}


def read_point(result_id: str, lon: float, lat: float) -> dict:
    """What the data says at one spot of a stored result, in numbers and in words."""
    result = provenance.load_result(result_id)
    if result is None or result.get("status") != "ok":
        raise PointError("That result is not available.")
    reader = {"change": _change_reading, "motion": _motion_reading, "timeseries": _series_reading}[result["workflow"]]
    return {"result_id": result_id, "workflow": result["workflow"], "lon": round(lon, 5), "lat": round(lat, 5), **reader(result, lon, lat)}

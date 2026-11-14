"""Plain-language layer captions and reading one spot of a stored change result."""

import json

import numpy as np
import pytest
from pyproj import Transformer

from nisar_investigator import plain, provenance, render
from nisar_investigator.schemas import Layer, Legend, Summary, WorkflowResult

CORNERS = [(-120.56, 50.735), (-120.40, 50.735), (-120.40, 50.675), (-120.56, 50.675)]
EPSG = 32611
X0, Y0, PIXEL = 500_000.0, 5_620_000.0, 10.0


def _layer(layer_id: str, title: str, legend: Legend, date: str | None = None) -> Layer:
    return Layer(id=layer_id, title=title, url=f"/api/artifacts/x/{layer_id}.png", corners=CORNERS, legend=legend, date=date)


def test_layers_get_plain_titles_descriptions_and_legend_captions():
    grey = Legend(type="continuous", unit="dB", min=-20, max=0, colormap="grey")
    classes = Legend(type="categorical", classes=[{"label": "Brighter by at least 2.4 dB", "color": "#b2182b"},
                                                  {"label": "Darker by at least 2.4 dB", "color": "#2166ac"},
                                                  {"label": "At the noise floor on both dates (cannot tell)", "color": "#808080"}])
    result = WorkflowResult(
        id="chg_test", workflow="change", summary=Summary(headline="x"),
        layers=[
            _layer("before", "HH before, 19 June 2026 (dB)", grey.model_copy(), "2026-06-19"),
            _layer("change_db", "HH change, after minus before (dB)", Legend(type="continuous", unit="dB", min=-6, max=6, colormap="RdBu")),
            _layer("change_classes", "HH change classes (central threshold)", classes),
            _layer("change_db_hv", "HV change, after minus before (dB)", Legend(type="continuous", unit="dB", min=-4, max=4, colormap="RdBu")),
        ],
    )
    out = {layer.id: layer for layer in plain.annotate(result).layers}
    assert out["before"].title == "Radar image, 19 June 2026"
    assert out["before"].technical_title == "HH before, 19 June 2026 (dB)"
    assert "calm water" in out["before"].description and out["before"].legend.max_label.startswith("bright")
    assert out["change_db"].title == "Where it changed, and how much" and out["change_db"].group == "main"
    assert out["change_db"].legend.min_label == "darker than before"
    assert [c["label"] for c in out["change_classes"].legend.classes] == ["Clearly brighter", "Clearly darker", "Too dark to tell"]
    assert out["change_classes"].legend.classes[0]["detail"] == "Brighter by at least 2.4 dB"
    assert out["change_db_hv"].group == "advanced" and "vegetation" in out["change_db_hv"].title
    # annotating twice changes nothing
    again = plain.annotate(result)
    assert again.layers[0].title == "Radar image, 19 June 2026"


@pytest.fixture
def stored_change(tmp_path, monkeypatch):
    """A change result on disk: water that stayed dark, a bar that brightened by 6 dB, and unchanged land."""
    monkeypatch.setenv("NISAR_CACHE_DIR", str(tmp_path))
    rid = "chg_spot"
    before = np.full((100, 100), -10.0, dtype=np.float32)
    after = before.copy()
    before[:, :30], after[:, :30] = -18.0, -18.2  # open water on both dates
    before[40:60, 40:60], after[40:60, 40:60] = -17.5, -11.5  # emerged bar
    transform = (X0, PIXEL, 0.0, Y0, 0.0, -PIXEL)
    for name, values in (("before_db", before), ("after_db", after), ("change_db", after - before)):
        render.save_geotiff(provenance.artifact_path(rid, f"{name}.tif"), values, transform, EPSG)
    result = {
        "id": rid, "workflow": "change", "status": "ok",
        "request": {"bbox": [0, 0, 1, 1], "date_before": "2026-06-19", "date_after": "2026-10-17"},
        "stats": {"primary_polarization": "HH", "polarizations": {"HH": {
            "thresholds_db": {"lenient": 2.0, "central": 2.9, "strict": 3.9},
            "noise_floor_db": {"before": -17.5, "after": -17.4}}}},
    }
    provenance.artifact_path(rid, "result.json").write_text(json.dumps(result))
    plain._geotiff.cache_clear()
    return rid


def _lonlat(col: float, row: float) -> tuple[float, float]:
    tr = Transformer.from_crs(f"EPSG:{EPSG}", "EPSG:4326", always_xy=True)
    return tr.transform(X0 + (col + 0.5) * PIXEL, Y0 - (row + 0.5) * PIXEL)


def test_a_brightened_spot_is_read_with_values_and_common_causes(stored_change):
    lon, lat = _lonlat(50, 50)
    reading = plain.read_point(stored_change, lon, lat)
    values = {r["label"]: r["value"] for r in reading["readings"]}
    assert values == {"Radar brightness on 19 June 2026": -17.5, "Radar brightness on 17 October 2026": -11.5, "Change": 6.0}
    assert "brighter by 6.0 dB, a clear change" in reading["sentence"]
    assert "water receded and exposed ground" in reading["common_causes"]


def test_unchanged_land_and_dark_water_are_described_honestly(stored_change):
    land = plain.read_point(stored_change, *_lonlat(80, 80))
    assert "no real change" in land["sentence"] and "common_causes" not in land
    water = plain.read_point(stored_change, *_lonlat(10, 50))
    assert "too dark on both dates" in water["sentence"]


def test_a_spot_outside_the_area_is_refused(stored_change):
    with pytest.raises(plain.PointError):
        plain.read_point(stored_change, *_lonlat(500, 500))
    with pytest.raises(plain.PointError):
        plain.read_point("chg_missing", 0.0, 0.0)

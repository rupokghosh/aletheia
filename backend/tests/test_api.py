"""The HTTP API with the workflows stubbed out, plus one real catalogue query."""

from __future__ import annotations

import json
import types

import pytest
import requests
from fastapi.testclient import TestClient

from nisar_investigator import api, config
from nisar_investigator.schemas import Coverage, Summary, WorkflowResult

BBOX = [-120.56, 50.675, -120.40, 50.735]


@pytest.fixture
def client(cache_dir):
    return TestClient(api.app, raise_server_exceptions=False)


def canned(workflow: str, status: str = "ok") -> WorkflowResult:
    return WorkflowResult(id=f"{workflow}_test_1", workflow=workflow, status=status, summary=Summary(headline=f"{workflow} ran"))


def test_health(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok" and body["version"]
    assert body["workflows"]["change"] is True and body["workflows"]["timeseries"] is True


# ------------------------------------------------------------------ coverage


def test_coverage_by_point_and_by_box(client, monkeypatch):
    seen = []

    def coverage(**where):
        seen.append(where)
        return Coverage(query=where, products={"GCOV": []}, stacks=[], notes=["nothing here"])

    monkeypatch.setattr(api.catalog, "coverage", coverage)
    point = client.get("/api/coverage", params={"lon": -120.33, "lat": 50.67})
    assert point.status_code == 200 and point.json()["notes"] == ["nothing here"]
    box = client.get("/api/coverage", params={"bbox": "-120.56,50.675,-120.40,50.735"})
    assert box.status_code == 200
    assert seen == [{"lon": -120.33, "lat": 50.67}, {"bbox": (-120.56, 50.675, -120.40, 50.735)}]


@pytest.mark.parametrize(
    "params, text",
    [
        ({}, "Give either lon and lat, or bbox"),
        ({"lon": 10}, "Give either lon and lat, or bbox"),
        ({"bbox": "1,2,3"}, "four numbers"),
        ({"bbox": "a,b,c,d"}, "four numbers"),
        ({"bbox": "10,5,9,6"}, "west < east"),
        ({"lon": 500, "lat": 1}, "lon"),
        ({"lon": "east", "lat": 1}, "lon"),
    ],
)
def test_coverage_rejects_bad_input_in_plain_words(client, monkeypatch, params, text):
    monkeypatch.setattr(api.catalog, "coverage", lambda **_: pytest.fail("the catalogue must not be queried"))
    response = client.get("/api/coverage", params=params)
    assert response.status_code == 422
    body = response.json()
    assert body["error"] == "invalid_request" and text in body["message"]


def test_coverage_reports_a_catalogue_outage(client, monkeypatch):
    def offline(**_):
        raise requests.ConnectionError("https://cmr.earthdata.nasa.gov/?secret=1")

    monkeypatch.setattr(api.catalog, "coverage", offline)
    response = client.get("/api/coverage", params={"lon": 0, "lat": 0})
    assert response.status_code == 502
    assert response.json()["error"] == "catalogue_unavailable" and "secret" not in response.text


# ----------------------------------------------------------------- workflows


def test_change_passes_the_request_through(client, monkeypatch):
    seen = []
    monkeypatch.setattr(api, "run_change", lambda req: seen.append(req) or canned("change"))
    body = {"bbox": BBOX, "date_before": "2026-06-19", "date_after": "2026-10-17", "track": 77}
    response = client.post("/api/change", json=body)
    assert response.status_code == 200
    assert response.json()["id"] == "change_test_1" and response.json()["status"] == "ok"
    assert seen[0].bbox == tuple(BBOX) and seen[0].track == 77 and seen[0].polarization == "auto"


def test_timeseries_passes_the_request_through(client, monkeypatch):
    seen = []
    monkeypatch.setattr(api, "run_timeseries", lambda req: seen.append(req) or canned("timeseries"))
    response = client.post("/api/timeseries", json={"bbox": BBOX, "start": "2026-06-01"})
    assert response.status_code == 200 and response.json()["workflow"] == "timeseries"
    assert seen[0].start == "2026-06-01" and seen[0].polarizations == ["HH", "HV"] and seen[0].geometry is None


def test_unsupported_is_a_result_not_an_http_error(client, monkeypatch):
    monkeypatch.setattr(api, "run_change", lambda req: canned("change", "unsupported"))
    response = client.post("/api/change", json={"bbox": BBOX, "date_before": "2026-06-19", "date_after": "2026-06-21"})
    assert response.status_code == 200 and response.json()["status"] == "unsupported"


@pytest.mark.parametrize(
    "path, body, field",
    [
        ("/api/change", {"bbox": BBOX}, "date_before"),
        ("/api/change", {"bbox": [1, 2], "date_before": "a", "date_after": "b"}, "bbox"),
        ("/api/change", {"bbox": BBOX, "date_before": "a", "date_after": "b", "polarization": "XX"}, "polarization"),
        ("/api/timeseries", {}, "bbox"),
        ("/api/timeseries", {"bbox": BBOX, "polarizations": "HH"}, "polarizations"),
        ("/api/motion", {"bbox": "everywhere"}, "bbox"),
    ],
)
def test_invalid_bodies_get_a_readable_message(client, path, body, field):
    response = client.post(path, json=body)
    assert response.status_code == 422
    payload = response.json()
    assert payload["error"] == "invalid_request"
    assert payload["message"].startswith("The request is not valid.") and field in payload["message"]
    assert any(f["field"].startswith(field) for f in payload["fields"])


def test_a_crashing_workflow_still_answers_with_a_result(client, monkeypatch):
    def crash(req):
        raise RuntimeError("signed-url-with-token")

    monkeypatch.setattr(api, "run_timeseries", crash)
    response = client.post("/api/timeseries", json={"bbox": BBOX})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "error" and body["workflow"] == "timeseries"
    assert "RuntimeError" in body["summary"]["headline"]
    assert "signed-url-with-token" not in response.text and "Traceback" not in response.text
    assert body["request"]["bbox"] == BBOX


def test_the_server_stays_responsive_while_a_workflow_runs(client, monkeypatch):
    """Workflows run in a worker thread: one that waits on another request can only finish if that one is served."""
    import threading

    inside, release = threading.Event(), threading.Event()

    def slow(req):
        inside.set()
        assert release.wait(10), "the health check was never answered"
        return canned("change")

    monkeypatch.setattr(api, "run_change", slow)
    body = {"bbox": BBOX, "date_before": "2026-06-19", "date_after": "2026-10-17"}
    answers = {}
    worker = threading.Thread(target=lambda: answers.update(change=client.post("/api/change", json=body)))
    worker.start()
    assert inside.wait(10)
    assert client.get("/api/health").status_code == 200
    release.set()
    worker.join(10)
    assert answers["change"].json()["id"] == "change_test_1"


def test_motion_is_unsupported_when_the_module_is_missing(client, monkeypatch):
    monkeypatch.setattr(api, "MOTION_MODULE", "nisar_investigator.workflows.no_such_module")
    response = client.post("/api/motion", json={"bbox": BBOX})
    assert response.status_code == 200
    body = response.json()
    assert body["workflow"] == "motion" and body["status"] == "unsupported"
    assert "not supported yet" in body["summary"]["headline"]
    assert client.get("/api/health").json()["workflows"]["motion"] is False


def test_motion_is_unsupported_when_run_motion_is_missing(client, monkeypatch):
    monkeypatch.setattr(api.importlib, "import_module", lambda name: types.SimpleNamespace())
    response = client.post("/api/motion", json={"bbox": BBOX, "reference_date": "2026-10-05"})
    assert response.json()["status"] == "unsupported"


def test_motion_runs_when_the_module_provides_it(client, monkeypatch):
    seen = []
    module = types.SimpleNamespace(run_motion=lambda req: seen.append(req) or canned("motion"))
    monkeypatch.setattr(api.importlib, "import_module", lambda name: module)
    response = client.post("/api/motion", json={"bbox": BBOX, "reference_date": "2026-10-05", "track": 77})
    assert response.json()["id"] == "motion_test_1"
    assert seen[0].reference_date == "2026-10-05" and seen[0].track == 77


# ------------------------------------------------------- results and files


@pytest.fixture
def stored(cache_dir):
    folder = config.artifacts_dir() / "chg_20261114_ab12cd34"
    folder.mkdir(parents=True)
    (folder / "result.json").write_text(json.dumps({"id": "chg_20261114_ab12cd34", "status": "ok"}))
    (folder / "change_db.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (folder / "change_db.tif").write_bytes(b"II*\x00")
    (folder / "statistics.csv").write_text("polarization,value\nHH,1\n")
    (folder / "notes.txt").write_text("not served")
    (cache_dir / "secret.json").write_text("{}")
    return "chg_20261114_ab12cd34"


def test_results_are_served_by_id(client, stored):
    assert client.get(f"/api/results/{stored}").json() == {"id": stored, "status": "ok"}
    missing = client.get("/api/results/chg_20261114_00000000")
    assert missing.status_code == 404 and missing.json()["error"] == "not_found"
    assert "chg_20261114_00000000" in missing.json()["message"]


@pytest.mark.parametrize(
    "filename, content_type",
    [
        ("change_db.png", "image/png"),
        ("change_db.tif", "image/tiff"),
        ("statistics.csv", "text/csv; charset=utf-8"),
        ("result.json", "application/json"),
    ],
)
def test_artifacts_are_served_with_their_content_type(client, stored, filename, content_type):
    response = client.get(f"/api/artifacts/{stored}/{filename}")
    assert response.status_code == 200
    assert response.headers["content-type"] == content_type
    assert response.content == (config.artifacts_dir() / stored / filename).read_bytes()
    assert "max-age" in response.headers["cache-control"]


@pytest.mark.parametrize(
    "path",
    [
        "/api/artifacts/{id}/missing.png",
        "/api/artifacts/{id}/notes.txt",  # a type the workflows never produce
        "/api/artifacts/nope/result.json",
        "/api/artifacts/{id}/..%2F..%2Fsecret.json",
        "/api/artifacts/..%2F{id}/result.json",
        "/api/artifacts/%2E%2E/secret.json",
        "/api/artifacts/{id}/%2E%2E%2F%2E%2E%2Fsecret.json",
        "/api/artifacts/{id}/..%5C..%5Csecret.json",
        "/api/artifacts/{id}/.hidden.json",
        "/api/results/..%2F..%2Fsecret",
        "/api/results/%2E%2E",
    ],
)
def test_missing_files_and_path_traversal_are_refused(client, stored, path):
    response = client.get(path.format(id=stored))
    assert response.status_code == 404
    assert response.json()["error"] == "not_found"


def test_artifact_folders_cannot_be_escaped_through_a_link(client, stored, cache_dir):
    (config.artifacts_dir() / stored / "link.json").symlink_to(cache_dir / "secret.json")
    assert client.get(f"/api/artifacts/{stored}/link.json").status_code == 404


# ---------------------------------------------------------------------- CORS


def test_cors_allows_the_local_interface_and_no_one_else(client):
    allowed = client.get("/api/health", headers={"Origin": "http://localhost:3000"})
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:3000"
    stranger = client.get("/api/health", headers={"Origin": "https://example.org"})
    assert "access-control-allow-origin" not in stranger.headers
    preflight = client.options(
        "/api/change", headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "POST"}
    )
    assert preflight.status_code == 200 and "POST" in preflight.headers["access-control-allow-methods"]


def test_cors_origins_come_from_the_environment(monkeypatch):
    monkeypatch.delenv("NISAR_CORS_ORIGINS", raising=False)
    assert api._cors_origins() == ["http://localhost:3000"]
    monkeypatch.setenv("NISAR_CORS_ORIGINS", "https://nisar.example.org/, http://localhost:3000 ,,https://b.example")
    assert api._cors_origins() == ["http://localhost:3000", "https://nisar.example.org", "https://b.example"]


def test_unknown_routes_answer_in_json(client):
    response = client.get("/api/nothing-here")
    assert response.status_code == 404 and response.json()["error"] == "not_found"


# ---------------------------------------------------------------- real data


@pytest.mark.network
def test_coverage_of_kamloops_lake_from_the_real_catalogue():
    response = TestClient(api.app).get("/api/coverage", params={"bbox": "-120.56,50.675,-120.40,50.735"})
    assert response.status_code == 200
    body = response.json()
    assert len(body["products"]["GCOV"]) >= 57
    stack = next(s for s in body["stacks"] if s["product"] == "GCOV" and s["track"] == 77)
    assert {"2026-06-19", "2026-10-17"} <= set(stack["dates"])
    assert stack["polarizations"] == ["HH", "HV"]

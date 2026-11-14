"""Run the showcase investigations through the real pipeline and export them as static files.

Each showcase is an actual output of the investigator: the model that planned and wrote it is recorded in
the file. Artifacts (map layers, CSV, JSON) are copied next to it so the web app can show the investigation
without a backend. GeoTIFF downloads are left out to keep the bundle small; the live API produces them.

Run:  backend/.venv/bin/python backend/scripts/build_showcases.py [--only ID] [--skip-existing]
"""

from __future__ import annotations

import argparse
import json
import shutil
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "web" / "public" / "showcases"  # served as static files by the web app

SHOWCASES = [
    {
        "id": "kamloops-lake",
        "title": "Kamloops Lake through the summer",
        "place_name": "Kamloops Lake, British Columbia",
        "bbox": (-120.56, 50.675, -120.40, 50.735),
        "question": "How did the east end of Kamloops Lake change between June and October 2026, and does the river gauge agree?",
    },
    {
        "id": "venezuela-earthquakes",
        "title": "The June 2026 earthquakes in Venezuela",
        "place_name": "Carabobo coast, Venezuela",
        "bbox": (-68.45, 10.30, -67.95, 10.75),
        "question": "Did the ground move here during the earthquakes of 24 June 2026, and by how much?",
    },
    {
        "id": "choctawhatchee-floodplain",
        "title": "A Florida river floodplain in October",
        "place_name": "Choctawhatchee River floodplain, Florida",
        "bbox": (-86.08, 30.37, -85.84, 30.49),
        "question": "How did this river floodplain change between 27 September and 21 October 2026, and do the river gauges agree?",
    },
]

_KEEP = {".png", ".csv", ".json"}


def _export(showcase: dict, investigation: dict, artifacts_dir: Path) -> dict:
    slug = showcase["id"]
    target = OUT / slug
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)

    def rewrite(url: str) -> str | None:
        """/api/artifacts/<id>/<file> -> /showcases/<slug>/artifacts/<id>/<file>, copying the file."""
        prefix = "/api/artifacts/"
        if not url.startswith(prefix):
            return url
        result_id, filename = url[len(prefix):].split("/", 1)
        if Path(filename).suffix.lower() not in _KEEP:
            return None
        source = artifacts_dir / result_id / filename
        if not source.exists():
            return None
        dest = target / "artifacts" / result_id / filename
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest)
        return f"/showcases/{slug}/artifacts/{result_id}/{filename}"

    from nisar_investigator import plain

    investigation["results"] = {key: plain.annotate_dict(value) for key, value in investigation["results"].items()}
    for result in investigation["results"].values():
        if not isinstance(result, dict):
            continue
        for layer in result.get("layers", []):
            layer["url"] = rewrite(layer["url"]) or layer["url"]
        downloads = []
        for d in result.get("downloads", []):
            url = rewrite(d["url"])
            if url:
                downloads.append({**d, "url": url})
        if "downloads" in result:
            result["downloads"] = downloads

    (target / "investigation.json").write_text(json.dumps(investigation, indent=1))
    report = investigation.get("report") or {}
    return {
        "id": slug,
        "title": showcase["title"],
        "place_name": showcase["place_name"],
        "question": showcase["question"],
        "summary": report.get("answer", ""),
        "file": f"{slug}/investigation.json",
        "model": investigation.get("model"),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def main() -> None:
    from nisar_investigator import agent, config
    from nisar_investigator.schemas import InvestigateRequest

    p = argparse.ArgumentParser()
    p.add_argument("--only")
    p.add_argument("--skip-existing", action="store_true")
    p.add_argument("--refresh", action="store_true", help="re-apply titles and plain layer names to exported showcases, without running anything")
    a = p.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    if a.refresh:
        from nisar_investigator import plain

        entries = {e["id"]: e for e in json.loads((OUT / "index.json").read_text())}
        for showcase in SHOWCASES:
            path = OUT / showcase["id"] / "investigation.json"
            if not path.exists() or showcase["id"] not in entries:
                continue
            investigation = json.loads(path.read_text())
            investigation["results"] = {k: plain.annotate_dict(v) for k, v in investigation["results"].items()}
            path.write_text(json.dumps(investigation, indent=1))
            entries[showcase["id"]].update(title=showcase["title"], place_name=showcase["place_name"])
        (OUT / "index.json").write_text(json.dumps([entries[s["id"]] for s in SHOWCASES if s["id"] in entries], indent=1))
        print("refreshed", list(entries))
        return

    index_path = OUT / "index.json"
    index = {e["id"]: e for e in json.loads(index_path.read_text())} if index_path.exists() else {}

    for showcase in SHOWCASES:
        if a.only and showcase["id"] != a.only:
            continue
        if a.skip_existing and (OUT / showcase["id"] / "investigation.json").exists():
            continue
        print(f"\n=== {showcase['id']}: {showcase['question']}", flush=True)
        t0 = time.time()
        investigation = None
        req = InvestigateRequest(question=showcase["question"], bbox=showcase["bbox"], place_name=showcase["place_name"])
        for ev in agent.investigate(req):
            kind, d = ev["event"], ev["data"]
            if kind == "step" and d.get("status") != "running":
                print(f"  [{time.time() - t0:5.0f}s] {d.get('status', ''):6s} {d['title']}" + (f" -> {d['detail']}" if d.get("detail") else ""), flush=True)
            elif kind == "error":
                print(f"  [{time.time() - t0:5.0f}s] ERROR {d['message']}", flush=True)
            elif kind == "done":
                investigation = d["investigation"]
        if not investigation or not investigation.get("report"):
            print("  no report produced; showcase not exported", flush=True)
            continue
        index[showcase["id"]] = _export(showcase, investigation, config.artifacts_dir())
        index_path.write_text(json.dumps([index[s["id"]] for s in SHOWCASES if s["id"] in index], indent=1))
        report = investigation["report"]
        print(f"  ANSWER: {report['answer']}\n  OBSERVED: {len(report['observed'])}  EXPLANATIONS: {len(report['possible_explanations'])}  "
              f"UNKNOWN: {len(report['unknown'])}  CONFIDENCE: {report['confidence'][:80]}", flush=True)

    size = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file()) / 1e6
    print(f"showcase bundle: {size:.1f} MB in {OUT.relative_to(REPO)}", flush=True)


if __name__ == "__main__":  # required: the workflows read granules in worker processes
    main()

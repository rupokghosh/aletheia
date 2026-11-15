# Spec: requirements and contracts

Name: **Aletheia** (Greek: truth as un-hiddenness). NASA Space Apps Challenge 2026, challenge "Dancing with the SARs".
Build window: Saturday 14 November 9:00 to Sunday 15 November 23:59 local time.

## 1. What it is

A web application where a researcher picks any place on Earth, asks a question in plain language,
and gets a radar-backed answer computed from real NISAR data, with the evidence attached.

One line: *ask a question about any place and get a radar-backed answer with receipts.*

## 2. Users

Primary: researchers who are not SAR specialists (hydrologists, ecologists, geologists, planners, students)
and who today must search an archive, download 2 to 12 GB HDF5 files and write code before seeing anything.

Secondary: educators, journalists and local decision-makers who need the answer and its reliability.

## 3. Requirements

### Must have (submission is not viable without these)

- R1. **Real NISAR data at the core.** Every number shown comes from NISAR L2/L3 products read at request time
  or precomputed from them. No synthetic data anywhere.
- R2. **Coverage check.** For a point or box, list what NISAR has: products, dates, tracks, direction,
  polarizations, calibration tier (beta, provisional, validated), and gaps.
- R3. **Workflow A, change between two dates.** Same track and frame, GCOV backscatter. Output a change map,
  the changed area with a low/central/high range, and per-polarization statistics.
- R4. **Workflow B, time series for an area.** Mean backscatter per date and polarization, per track,
  with spread, for a drawn box or polygon.
- R5. **Receipts on every result.** Source granules with links and tier, processing steps with parameters,
  timings, stated uncertainty, caveats, downloads (PNG, GeoTIFF, CSV, JSON) and a code snippet that reproduces it.
- R6. **Map interface.** Globe or map, place search, draw an area, pick dates from what actually exists,
  see result layers over a base map, compare before and after.
- R7. **Question-driven investigation.** A plain-language question is turned into a visible sequence of steps:
  coverage check, choice of a supported workflow, computed results, then a report that separates
  **observed**, **possible explanations** and **unknown**. The language model never states a number that a
  tool did not compute, and never interprets raw pixels.
- R8. **Honest limits.** Unsupported questions get "not supported yet" with the reason. Pixels at the
  instrument noise floor are labelled as such. Beta-tier data is labelled uncalibrated.
- R9. **Live public link** that opens with no login, plus an open-source repository (Apache 2.0) that cites
  every data source and tool, and discloses AI use.

### Should have

- S1. **Workflow C, ground motion** from NASA's ready-made GUNW pairs where they exist: line-of-sight
  displacement, coherence mask, quality statistics, and plain caveats (atmosphere, reference point).
- S2. **Three precomputed showcase investigations**: Kamloops Lake seasonal drawdown (validated against the
  Water Survey of Canada gauge 08LF023), one storm or flood case, one earthquake case.
- S3. **Context evidence**: USGS earthquake catalogue, river gauge where available, land cover.
- S4. Shareable report page per investigation.

### Will not do in this window

Sonification, S-band, alerts, multi-language, slow subsidence, seasonal trend analysis,
ground-motion time series from raw SLC data, a model that reads radar pictures directly.

## 4. Lessons already learned (design constraints)

- The standard `earthaccess` + `fsspec` route hung for over ten minutes. Resolving the signed download link
  once and then issuing plain HTTP range requests with a 4 MiB block cache read a 75 km2 window from a
  7.8 GB file in about 9 seconds (15 requests, 63 MB).
- GCOV frequency A grids are float32, chunked 512 x 512, gzip, 10 m posting, in UTM. Two dates on the same
  track and frame share an identical pixel grid.
- `scipy.ndimage.uniform_filter` is poisoned by a single NaN. Multilook with a validity weight.
- In dry terrain open water (about -17 dB HH) and smooth dry ground (about -15 to -13 dB HH) are close.
  HV sits at the noise floor (about -22 dB) for both. Independent per-date thresholds are fragile and once
  gave the wrong sign. Per-pixel change relative to stable reference pixels is more robust.
  **Every area must be reported as a range across thresholds, never a single number.**
- Stable water itself shifted by about +1.5 dB between two dates (wind). Normalise change by the median
  shift of a stable reference class.

## 5. Architecture

```
web/       Next.js (App Router, TypeScript). MapLibre GL JS. Talks to the API only.
backend/   Python 3.12+. FastAPI. Package `nisar_investigator`.
           catalog.py    CMR search, granule parsing, tier handling
           remote.py     signed-link resolution + HTTP range file with block cache
           gcov.py       windowed reads of GCOV grids, disk cache
           gunw.py       windowed reads of GUNW grids
           ops.py        multilook, dB, change statistics, noise floor
           workflows/    change.py, timeseries.py, motion.py -> WorkflowResult
           render.py     arrays -> PNG overlay, GeoTIFF, CSV
           provenance.py Receipt
           context.py    USGS earthquakes, river gauges
           agent.py      question -> steps -> report (Claude tool use)
           api.py        FastAPI app
showcases/ precomputed investigations (JSON + images), served statically
docs/      this spec
```

## 6. API contract (v1)

All endpoints are under `/api`. JSON in, JSON out. Coordinates are WGS84 lon/lat. `bbox` is `[west, south, east, north]`.
Dates are `YYYY-MM-DD` (UTC acquisition date).

### GET /api/coverage?lon=&lat=  or  ?bbox=w,s,e,n

```json
{
  "query": {"lon": -120.33, "lat": 50.67},
  "products": {
    "GCOV": [ {"granule_id": "...", "date": "2026-06-19", "start_time": "2026-06-19T12:47:59Z",
               "track": 77, "direction": "ascending", "frame": 27, "mode": "4005",
               "polarizations": ["HH","HV"], "tier": "provisional", "size_gb": 7.3, "url": "https://..."} ],
    "GUNW": [ {"granule_id": "...", "reference_date": "2026-10-05", "secondary_date": "2026-10-17", "...": "..."} ],
    "SME2": []
  },
  "stacks": [ {"track": 77, "direction": "ascending", "frame": 27, "product": "GCOV",
               "dates": ["2026-06-19", "..."], "tiers": {"provisional": 9, "beta": 4}} ],
  "notes": ["No acquisitions between 2026-01-09 and 2026-06-19."]
}
```

### POST /api/change

Request: `{"bbox": [w,s,e,n], "date_before": "2026-06-19", "date_after": "2026-10-17", "track": 77, "polarization": "auto"}`
(`track` optional: the backend picks the stack that has both dates.)

### POST /api/timeseries

Request: `{"bbox": [w,s,e,n], "geometry": null, "start": null, "end": null, "polarizations": ["HH","HV"]}`

### POST /api/motion

Request: `{"bbox": [w,s,e,n], "reference_date": "2026-10-05"}` (optional date: latest pair if omitted)

### POST /api/investigate

Request: `{"question": "...", "bbox": [w,s,e,n], "place_name": "Kamloops Lake"}`.
Response: `text/event-stream`. Events: `step` (a plan step started), `tool_call`, `tool_result` (a WorkflowResult or
coverage object), `text` (report text delta), `done` (final Investigation object), `error`.

### GET /api/artifacts/{result_id}/{filename}

Serves PNG, GeoTIFF, CSV and JSON produced by a workflow.

### WorkflowResult (returned by change, timeseries, motion)

```json
{
  "id": "chg_20261114_ab12cd",
  "workflow": "change",
  "status": "ok",
  "request": {},
  "summary": {
    "headline": "0.2 to 1.1 km2 of the 7.2 km2 water body became land",
    "metrics": [ {"key": "changed_area_km2", "label": "Changed area", "low": 0.2, "central": 0.44, "high": 1.1, "unit": "km2"} ]
  },
  "layers": [
    {"id": "change_db", "title": "HH change (dB)", "kind": "image",
     "url": "/api/artifacts/chg_.../change_db.png",
     "corners": [[lon,lat],[lon,lat],[lon,lat],[lon,lat]],
     "legend": {"type": "continuous", "unit": "dB", "min": -6, "max": 6, "colormap": "RdBu"},
     "default_visible": true}
  ],
  "series": [
    {"id": "hh_mean", "label": "HH mean", "unit": "dB", "track": 77,
     "points": [ {"date": "2026-06-19", "value": -12.9, "spread": 0.4, "tier": "provisional"} ]}
  ],
  "charts": [
    {"id": "change_distribution", "kind": "histogram", "title": "How much each part of the area changed",
     "description": "One or two sentences on how to read it.",
     "data": {"unit": "dB", "edges": [-6.0, -5.75], "area_km2": [0.2], "band": [-2.9, 2.9],
              "band_label": "no clear change", "low_label": "darker", "high_label": "brighter"}}
  ],
  "stats": {},
  "uncertainty": {
    "method": "Per-pixel log-ratio after 9x9 multilook, normalised by the median shift of stable reference pixels.",
    "sensitivity": [ {"parameter": "change threshold (dB)", "value": 2, "result": 0.44, "unit": "km2"} ],
    "noise_floor_fraction": 0.31,
    "notes": ["HV is at the noise floor for 62% of the area and was not used."]
  },
  "caveats": [ {"code": "tier_provisional", "text": "Provisional calibration: values may change after reprocessing."} ],
  "receipt": {
    "granules": [ {"granule_id": "...", "url": "https://...", "tier": "provisional", "date": "2026-06-19",
                   "track": 77, "frame": 27, "direction": "ascending", "polarizations": ["HH","HV"]} ],
    "steps": [ {"name": "read_window", "params": {"rows": [13072, 13792], "cols": [15993, 17153]}, "seconds": 8.9} ],
    "software": {"name": "aletheia", "version": "0.1.0", "commit": "abc1234"},
    "generated_at": "2026-11-14T21:00:00Z",
    "reproduce": "python code as a string"
  },
  "downloads": [ {"label": "Change map (GeoTIFF)", "url": "/api/artifacts/.../change_db.tif", "format": "geotiff"} ]
}
```

`status` is `ok`, `unsupported` (with `summary.headline` explaining why) or `error`.
`corners` are the four image corners in order top-left, top-right, bottom-right, bottom-left, because the grids
are in UTM and are slightly rotated in lon/lat.

### Investigation (final object of /api/investigate, also the showcase file format)

```json
{
  "id": "inv_...", "question": "...", "place_name": "...", "bbox": [w,s,e,n],
  "steps": [ {"title": "Checked what NISAR has here", "detail": "...", "result_ref": "coverage"} ],
  "results": { "coverage": {}, "chg_...": {} },
  "report": {
    "answer": "one or two sentences",
    "observed": ["statements that each cite a result id and metric"],
    "possible_explanations": ["hypotheses, each with what would confirm or rule it out"],
    "unknown": ["what the data cannot tell"],
    "confidence": "low | medium | high, with the reason"
  }
}
```

## 7. Conventions

- Python: type hints, pydantic v2 models in `nisar_investigator/schemas.py` are the source of truth for the contract.
- Earthdata auth: `~/.netrc` locally; `EARTHDATA_TOKEN` (bearer) when set. Never log or return credentials or signed URLs.
- Cache directory: `NISAR_CACHE_DIR` (default `backend/.cache`). Artifacts under `<cache>/artifacts/<result_id>/`.
- Units: backscatter in dB (gamma0), areas in km2, displacement in cm along the radar line of sight.
- Every workflow records its steps and timings into the receipt as it runs.
- Tests that touch the network are marked `@pytest.mark.network`.
- AI assistance: this repository was built with an AI coding agent; this is stated in the README and commit trailers.

# NISAR Investigator (working title)

Ask a question about any place on Earth and get a radar-backed answer with receipts.

Built for the NASA Space Apps Challenge 2026, challenge **Dancing with the SARs**.

## What it does

NISAR images nearly all land and ice every 12 days, and the data is free. Reading it is not easy:
today a researcher searches an archive, downloads 2 to 12 GB HDF5 files and writes code before seeing anything.

This tool lets a researcher pick a place, ask a question in plain language and get:

- what NISAR actually has there (products, dates, tracks, calibration tier, gaps),
- a computed result from real NISAR values (change between two dates, a time series for an area,
  ground motion where NASA's interferograms exist),
- the receipts: source granules, processing steps, stated uncertainty, caveats, downloads and
  code that reproduces every number,
- a short report that separates what was **observed**, what might **explain** it, and what is **unknown**.

It reads only the part of each file it needs: a 75 km2 window comes out of a 7.8 GB granule in about
5 seconds by transferring under 1% of the file.

## Status

Work in progress during the hackathon weekend (14 to 15 November 2026). See `docs/spec.md`.

## Run the backend

```bash
cd backend
python3 -m venv .venv
./.venv/bin/pip install -e ".[dev]"
./.venv/bin/python scripts/smoke.py
```

Reading NISAR data needs a free [Earthdata Login](https://urs.earthdata.nasa.gov/) in `~/.netrc`
(machine `urs.earthdata.nasa.gov`) or an `EARTHDATA_TOKEN` environment variable.

## Data and resources

- **NISAR L2 GCOV, L2 GUNW and L3 SME2** products, NASA-ISRO SAR mission, distributed by the
  Alaska Satellite Facility DAAC (NASA Earthdata).
- **NASA Common Metadata Repository (CMR)** for granule search.
- **NASA GIBS** NISAR backscatter imagery layer for map context.
- Water Survey of Canada real-time hydrometric data (Environment and Climate Change Canada) for validation.

A complete, cited list is maintained in `docs/sources.md` as the project grows.

## Use of AI

This project was built during the hackathon by a human developer working with an AI coding agent
(Claude Code). The AI wrote code under the developer's direction; the project idea, scope and
decisions are the developer's. AI-assisted commits carry a `Co-Authored-By` trailer.
In the running application, a language model selects and explains analyses; it never produces
numbers itself. Every number comes from deterministic code operating on NISAR data.

## License

Apache License 2.0. See `LICENSE`.

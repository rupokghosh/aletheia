# Aletheia

Ask a question about any place on Earth and get a radar-backed answer with receipts.

Built for the NASA Space Apps Challenge 2026, challenge **Dancing with the SARs**.

Live: https://aletheia-five-tawny.vercel.app

Pick a place, ask in plain language or choose an analysis, and Aletheia computes the answer from real
NISAR radar data: what changed between two dates, how a place behaved over time, or whether the ground
moved. Every result comes with its sources, its uncertainty, its caveats and the code to reproduce it.
It reads only the part of each NASA file it needs: about 16 MB of a 7 GB file for a 10 km area.

## Run it

Needs Python 3.12 or newer, Node with pnpm, and a free [Earthdata Login](https://urs.earthdata.nasa.gov/)
in `~/.netrc` (machine `urs.earthdata.nasa.gov`) or an `EARTHDATA_TOKEN` environment variable.

```bash
cd backend
python3 -m venv .venv && ./.venv/bin/pip install -e ".[dev]"
./.venv/bin/uvicorn nisar_investigator.api:app --port 8000
```

```bash
cd web
pnpm install
NEXT_PUBLIC_API_URL=http://localhost:8000 pnpm dev
```

Open http://localhost:3000. The three worked examples open without the backend. Questions in plain
language need a language model: [Ollama](https://ollama.com/) running `qwen3:14b`, or an
`ANTHROPIC_API_KEY` in `backend/.env`.

## Data, references and use of AI

Every data source, service and library is listed in [docs/sources.md](docs/sources.md).

Built during the hackathon by a human developer working with an AI coding agent (Claude Code): the AI
wrote code under the developer's direction, and the idea, scope and decisions are the developer's. In the
app, a language model chooses the analyses and writes the report; every number comes from deterministic
code reading NISAR data, and a report whose figures cannot be traced to a computed result is sent back.

## License

Apache License 2.0. See [LICENSE](LICENSE).

# Web interface

The map and side panel of Aletheia: pick a place, see what NISAR has there, run an analysis
or ask a question, and read the result with its receipt. Next.js (App Router, TypeScript, Tailwind CSS)
and MapLibre GL JS. It talks to the Python API in `../backend` and to nothing else of ours.

## Run it

```bash
cd web
pnpm install
cp .env.example .env.local     # sets NEXT_PUBLIC_API_URL=http://localhost:8000
pnpm dev                       # http://localhost:3000
```

Start the API in another terminal (`backend/.venv/bin/uvicorn nisar_investigator.api:app --port 8000`).
The API allows requests from `http://localhost:3000` by default; other origins go in its
`NISAR_CORS_ORIGINS` variable.

| Command | What it does |
| --- | --- |
| `pnpm dev` | Development server |
| `pnpm build` | Production build (static pages; deploys to Vercel as is) |
| `pnpm lint` | ESLint |
| `pnpm typecheck` | Route types, then `tsc --noEmit` |
| `pnpm demo:artifacts` | Regenerates the sample images in `public/demo-artifacts` |

`pnpm dev` and `pnpm build` first copy MapLibre's worker module into `public/vendor/`
(`scripts/copy-maplibre-worker.mjs`). MapLibre GL JS 6 loads its worker as a separate file that the
bundler does not emit, so the app serves it itself.

## Configuration

| Variable | Meaning |
| --- | --- |
| `NEXT_PUBLIC_API_URL` | Base URL of the API, for example `http://localhost:8000`. No trailing path. |

There are no secrets in the frontend. The base map (OpenFreeMap), place search (Photon) and NASA GIBS
imagery need no key.

## Demo-data mode

The one API client is `src/lib/api.ts`. The switch is at the top of that file:

- `NEXT_PUBLIC_API_URL` unset or empty: the client answers every call from the fixtures in `src/mocks/`.
- Set, but the server does not answer: the client switches to the fixtures and says so, with a
  "Try again" link. The check is a request to `/api/health`.
- Set and reachable: every response is live. An HTTP error from a reachable server is shown as an
  error and is never replaced by a fixture.

Every response carries its source (`live`, `demo` or `showcase`). Anything that is not live is
labelled in the interface: a note at the top of the card and a "Sample data" badge on coverage,
results, investigations and the map layers card. The sample images are procedural pictures with "SAMPLE" stamped
into their pixels. Granule links and downloads are switched off for sample data, because the
granules do not exist.

## Where things are

```
src/lib/config.ts      product name (APP_NAME, the only place it is written), URLs, thresholds
src/lib/types.ts       API types, mirroring backend/nisar_investigator/schemas.py
src/lib/api.ts         API client, demo-data switch, artifact URL resolution
src/lib/store.tsx      application state (one reducer, read with useApp())
src/lib/useActions.ts  network actions: coverage, the three workflows, the investigation stream
src/lib/coverage.ts    what the catalogue has: stacks ranked by coverage, summary sentence, default dates
src/lib/layers.ts      which result layers are on the map: toggles, before/after pair, date slider
src/app/globals.css    design tokens (light theme) and the few shared classes
src/mocks/             fixtures for demo-data mode, and worst-case data for development
src/components/AppShell.tsx        full-bleed map plus one floating card (bottom sheet on a phone)
src/components/panel/SidePanel.tsx the card: header, sample-data note, and one of three views
src/components/panel/HomeView.tsx  start state: tagline, search, "Draw area", worked examples
src/components/panel/AreaView.tsx  area chosen: coverage sentence and details, question box, analyses
src/components/panel/*Form.tsx     the question box and the three analysis forms
src/components/results/            result view: headline, ranges, chart, and the rows that open
src/components/investigate/        steps of an investigation and the four-part report
src/components/map/MapView.tsx     the map; LayersCard.tsx is the floating layer and legend card
public/showcases/      precomputed investigations (index.json plus one Investigation file each)
```

## Showcases

`public/showcases/index.json` is a list of entries:

```json
[
  {
    "id": "kamloops",
    "title": "Kamloops Lake seasonal drawdown",
    "place_name": "Kamloops Lake, British Columbia",
    "question": "How did the lake change between June and October 2026?",
    "summary": "Optional one-line summary.",
    "file": "kamloops/investigation.json"
  }
]
```

`file` is relative to `/showcases/` and holds an `Investigation` object as returned by the `done`
event of `POST /api/investigate`. Layer and download URLs inside it should point at static files
(`/showcases/kamloops/change_db.png`); URLs that start with `/api/` are resolved against the API.
`/?showcase=kamloops` opens an entry directly. `/?bbox=west,south,east,north&place=Name` opens the
workspace with that area chosen.

## Worst-case data (development only)

In `pnpm dev`, `?data=worst` in the address swaps the fixtures for worst-case data, with or without
an API configured (`?data=empty` and `?data=one` are the empty and single-item cases, `?data=demo`
the ordinary fixtures). A small control at the bottom of the screen switches between them. The data
is in `src/mocks/worstCase.ts`: a track with more than 60 dates, no tracks at all, a 180-character
file name, an unsupported result with a long headline, a metric without a range, a series with a
single point, long caveats. None of this exists in a production build.

## Attribution

Base map: OpenFreeMap, © OpenMapTiles, data from OpenStreetMap contributors. Place search: Photon by
komoot. Quick-look imagery: NASA GIBS / ESDIS. Fonts: IBM Plex Sans and IBM Plex Mono (SIL Open Font
License). Data: NASA-ISRO NISAR via the Alaska Satellite Facility; the full list of sources is in
`../README.md`.

"""Ask the published site for the radar-picture tiles a visitor sees first, so the host's network has them
cached: the whole planet at low zoom and the areas of the worked examples down to street level.

A new deployment starts with an empty cache, so run this after every deployment.

Run:  backend/.venv/bin/python backend/scripts/warm_public_tiles.py https://<the site>
"""

from __future__ import annotations

import argparse
import time
from concurrent.futures import ThreadPoolExecutor

import requests

from prewarm_tiles import EXAMPLES

WORLD_ZOOM = 3


def main() -> None:
    from nisar_investigator import radar_tiles

    p = argparse.ArgumentParser()
    p.add_argument("site", help="address of the published site, for example https://example.vercel.app")
    p.add_argument("--end", default=radar_tiles.default_end().isoformat(), help="last day of the picture (the site's default)")
    p.add_argument("--days", type=int, default=12)
    a = p.parse_args()
    base = a.site.rstrip("/")

    squares: list[tuple[int, int, int]] = []
    for z in range(0, WORLD_ZOOM + 1):
        squares += [(z, x, y) for x in range(2**z) for y in range(2**z)]
    for w, s, e, n in EXAMPLES.values():
        for z in range(WORLD_ZOOM + 1, 13):
            margin = 0.6 if z <= 9 else 0.2
            found = radar_tiles.tiles_for_bbox((w - margin, s - margin, e + margin, n + margin), z)
            if len(found) <= 120:
                squares += found
    squares = list(dict.fromkeys(squares))
    session = requests.Session()

    def one(square: tuple[int, int, int]) -> tuple[int, str, float]:
        z, x, y = square
        t0 = time.time()
        try:
            r = session.get(f"{base}/api/tiles/radar/{z}/{x}/{y}?end={a.end}&days={a.days}", timeout=120)
            return r.status_code, r.headers.get("x-vercel-cache", "?"), time.time() - t0
        except requests.RequestException as exc:
            return 0, type(exc).__name__, time.time() - t0

    print(f"{len(squares)} tiles for the {a.days} days up to {a.end}", flush=True)
    t0 = time.time()
    tally: dict[str, int] = {}
    slowest = 0.0
    with ThreadPoolExecutor(max_workers=6) as pool:
        for i, (status, cache, seconds) in enumerate(pool.map(one, squares), 1):
            key = f"{status} {cache}"
            tally[key] = tally.get(key, 0) + 1
            slowest = max(slowest, seconds)
            if i % 50 == 0:
                print(i, tally, f"slowest {slowest:.1f}s", flush=True)
    print("done", tally, f"slowest {slowest:.1f}s", f"total {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()

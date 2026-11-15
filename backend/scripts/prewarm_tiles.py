"""Fetch and cache the radar-picture tiles a visitor sees first: the whole planet at low zoom and the
areas of the worked examples at every zoom down to street level.

Run:  backend/.venv/bin/python backend/scripts/prewarm_tiles.py [--world-zoom 4]
"""

from __future__ import annotations

import argparse

EXAMPLES = {
    "Kamloops Lake": (-120.56, 50.675, -120.40, 50.735),
    "Venezuela coast": (-68.45, 10.30, -67.95, 10.75),
    "Florida floodplain": (-86.08, 30.37, -85.84, 30.49),
}


def main() -> None:
    from nisar_investigator import radar_tiles

    p = argparse.ArgumentParser()
    p.add_argument("--world-zoom", type=int, default=3, help="cache the whole planet up to this zoom level")
    a = p.parse_args()

    for z in range(0, a.world_zoom + 1):
        squares = [(z, x, y) for x in range(2**z) for y in range(2**z)]
        print(f"world, zoom {z}:", radar_tiles.prewarm(squares), flush=True)
    for name, (w, s, e, n) in EXAMPLES.items():
        pad = 0.6  # the area with room to pan around it
        for z in range(a.world_zoom + 1, 13):
            margin = pad if z <= 9 else pad / 3
            squares = radar_tiles.tiles_for_bbox((w - margin, s - margin, e + margin, n + margin), z)
            if len(squares) > 400:
                continue
            print(f"{name}, zoom {z}:", radar_tiles.prewarm(squares), flush=True)


if __name__ == "__main__":
    main()

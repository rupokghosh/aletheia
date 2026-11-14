"""List the stacks over a box and run the change workflow for several date pairs. Used to scout study sites.

Run:  backend/.venv/bin/python backend/scripts/scout_change.py W,S,E,N BEFORE:AFTER[:TRACK] [BEFORE:AFTER[:TRACK] ...]
"""

from __future__ import annotations

import sys
import time


def main() -> None:
    from nisar_investigator import catalog
    from nisar_investigator.schemas import ChangeRequest
    from nisar_investigator.workflows.change import run_change

    bbox = tuple(float(v) for v in sys.argv[1].split(","))
    cov = catalog.coverage(bbox=bbox, products=("GCOV",))
    for s in cov.stacks:
        print(f"track {s.track} {s.direction} frame {s.frame}: {len(s.dates)} dates {s.dates[0]} to {s.dates[-1]} {s.tiers}")
        print("   ", " ".join(d[5:] if d.startswith("2026") else d for d in s.dates))
    wanted = ("increased_area_km2", "decreased_area_km2", "increased_area_km2_hv", "decreased_area_km2_hv",
              "increase_median_change_db", "decrease_median_change_db", "scene_shift_db", "cannot_tell_percent")
    for spec in sys.argv[2:]:
        parts = spec.split(":")
        req = ChangeRequest(bbox=bbox, date_before=parts[0], date_after=parts[1], track=int(parts[2]) if len(parts) > 2 else None)
        t = time.time()
        r = run_change(req)
        print(f"\n{parts[0]} -> {parts[1]}: {r.status} in {time.time() - t:.0f}s  {r.id}\n  {r.summary.headline}")
        for m in r.summary.metrics:
            if m.key in wanted:
                rng = f"{m.low} / {m.central} / {m.high}" if m.low is not None else f"{m.central}"
                print(f"    {m.key:28s} {rng} {m.unit}")


if __name__ == "__main__":
    main()

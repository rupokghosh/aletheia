"""Re-read the demo areas straight from NASA's archive and print what each read cost.

Run:  backend/.venv/bin/python backend/scripts/demo_effort.py
"""

from __future__ import annotations

import time


def main() -> None:
    from nisar_investigator.schemas import ChangeRequest, MotionRequest
    from nisar_investigator.workflows.change import run_change
    from nisar_investigator.workflows.motion import run_motion

    jobs = [
        ("Kamloops Lake change", lambda: run_change(ChangeRequest(bbox=(-120.56, 50.675, -120.40, 50.735), date_before="2026-06-19", date_after="2026-10-17", track=77))),
        ("Florida floodplain change", lambda: run_change(ChangeRequest(bbox=(-86.08, 30.37, -85.84, 30.49), date_before="2026-09-27", date_after="2026-10-21", track=127))),
        ("Venezuela ground movement", lambda: run_motion(MotionRequest(bbox=(-68.45, 10.30, -67.95, 10.75), reference_date="2026-06-13", track=162))),
    ]
    for name, job in jobs:
        t = time.time()
        r = job()
        print(f"{name}: {r.status} in {time.time() - t:.1f}s\n   {r.summary.headline}\n   effort: {r.stats.get('effort')}", flush=True)


if __name__ == "__main__":
    main()

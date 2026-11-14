"""Run one investigation from the command line and print the steps and the report.

Run:  backend/.venv/bin/python backend/scripts/investigate.py "How did this lake change between June and October 2026?"
      [--bbox -120.56,50.675,-120.40,50.735] [--place "Kamloops Lake"]
"""

from __future__ import annotations

import argparse
import time


def main() -> None:
    from nisar_investigator import agent
    from nisar_investigator.schemas import InvestigateRequest

    p = argparse.ArgumentParser()
    p.add_argument("question")
    p.add_argument("--bbox", default="-120.56,50.675,-120.40,50.735")
    p.add_argument("--place", default="Kamloops Lake, British Columbia")
    a = p.parse_args()
    bbox = tuple(float(v) for v in a.bbox.split(","))

    t0 = time.time()
    for ev in agent.investigate(InvestigateRequest(question=a.question, bbox=bbox, place_name=a.place)):
        kind, d = ev["event"], ev["data"]
        stamp = f"[{time.time() - t0:6.1f}s]"
        if kind == "step":
            print(stamp, f"step {d.get('status', ''):8s} {d['title']}" + (f"  ->  {d['detail']}" if d.get("detail") else ""), flush=True)
        elif kind == "tool_call":
            print(stamp, f"     call     {d['name']}({d['input']})"[:240], flush=True)
        elif kind == "error":
            print(stamp, "ERROR", d["message"], flush=True)
        elif kind == "done":
            inv = d["investigation"]
            print(stamp, f"done: {inv['id']}  model: {inv.get('model')}  results: {list(inv['results'])}", flush=True)
            r = inv.get("report")
            if r:
                print("\nANSWER\n ", r["answer"])
                for title, key in (("OBSERVED", "observed"), ("POSSIBLE EXPLANATIONS", "possible_explanations"), ("UNKNOWN", "unknown")):
                    print(f"\n{title}")
                    for item in r[key]:
                        print("  -", item)
                print("\nCONFIDENCE\n ", r["confidence"])


if __name__ == "__main__":  # required: the workflows read granules in worker processes
    main()

"""Smoke test of the data layer on real NISAR data (needs an Earthdata login in ~/.netrc).

Run:  backend/.venv/bin/python backend/scripts/smoke.py
"""

from __future__ import annotations

import time

import numpy as np

from nisar_investigator import catalog, gcov

KAMLOOPS_LAKE = (-120.56, 50.675, -120.40, 50.735)  # west, south, east, north


def main() -> None:
    t = time.time()
    cov = catalog.coverage(lon=-120.33, lat=50.67)
    print(f"coverage in {time.time() - t:.2f}s")
    for s in cov.stacks:
        print(f"  {s.product} track {s.track} {s.direction} frame {s.frame}: {len(s.dates)} dates "
              f"{s.dates[0]} -> {s.dates[-1]} {s.tiers} {s.polarizations}")
    for n in cov.notes:
        print("  note:", n)

    gcovs = [g for g in cov.products["GCOV"] if g.track == 77 and g.tier != "beta"]
    first, last = gcovs[0], gcovs[-1]

    cut = gcov.read_window(first, KAMLOOPS_LAKE, use_cache=False)
    hh = cut.layers["HHHH"]
    print(f"\none window, cold: {cut.seconds}s, shape {cut.shape}, EPSG:{cut.epsg}, io {cut.io}")
    print(f"  HH dB percentiles 1/50/99: {np.nanpercentile(10 * np.log10(hh), [1, 50, 99]).round(1)}")
    print(f"  corners: {cut.corners_lonlat()}")

    t = time.time()
    cuts = gcov.read_windows(gcovs, KAMLOOPS_LAKE, use_cache=False)
    ok = [c for c in cuts if isinstance(c, gcov.Cutout)]
    print(f"\n{len(gcovs)} dates in parallel: {time.time() - t:.1f}s, {len(ok)} ok, "
          f"{sum(c.io['megabytes'] for c in ok):.0f} MB transferred")
    for g, c in zip(gcovs, cuts):
        if isinstance(c, gcov.Cutout):
            print(f"  {g.date} {g.tier:11s} HH median {np.nanmedian(10 * np.log10(c.layers['HHHH'])):6.2f} dB  {c.seconds}s")
        else:
            print(f"  {g.date} FAILED: {c}")
    same_grid = all(c.rows == ok[0].rows and c.cols == ok[0].cols for c in ok)
    print(f"all dates share one pixel grid: {same_grid}; first {first.date}, last {last.date}")


if __name__ == "__main__":
    main()

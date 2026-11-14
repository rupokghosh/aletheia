"""Walk a real NISAR L2 GUNW granule over HTTPS and print its layout (needs an Earthdata login in ~/.netrc).

Run:  backend/.venv/bin/python backend/scripts/explore_gunw.py [lon lat [reference_date]] [--all]

Prints, for every dataset under the GUNW grids and the identification / processing-parameter groups: path,
shape, dtype, chunking, compression, fill value, units and description. Scalars and short vectors are printed
with their values so that the wavelength, look direction and reference terrain height can be found.
`--all` walks the whole file instead of the interesting groups only.
"""

from __future__ import annotations

import sys
import time

import h5py
import numpy as np

from nisar_investigator import catalog
from nisar_investigator.remote import RemoteGranule

INTERESTING = (
    "/science/LSAR/identification",
    "/science/LSAR/GUNW/grids",
    "/science/LSAR/GUNW/metadata/radarGrid",
    "/science/LSAR/GUNW/metadata/processingInformation/parameters",
    "/science/LSAR/GUNW/metadata/orbit",
)


def _text(value) -> str:
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    if isinstance(value, np.ndarray) and value.dtype.kind in "SO":
        return ", ".join(_text(v) for v in value.ravel()[:8])
    if isinstance(value, np.ndarray):
        flat = value.ravel()
        return np.array2string(flat[:6], precision=6) + (" ..." if flat.size > 6 else "")
    return str(value)


def describe(name: str, obj) -> None:
    if isinstance(obj, h5py.Group):
        print(f"\n[{name}]")
        return
    attrs = {k: _text(v) for k, v in obj.attrs.items() if k not in ("DIMENSION_LIST", "REFERENCE_LIST")}
    filters = obj.compression or "none"
    line = f"  {name.rsplit('/', 1)[-1]:38s} shape={obj.shape} dtype={obj.dtype} chunks={obj.chunks} comp={filters}"
    if obj.shape == () or obj.size <= 6:
        try:
            line += f" value={_text(obj[()])}"
        except Exception as exc:  # noqa: BLE001 - exploration script: keep walking
            line += f" value=<{type(exc).__name__}>"
    print(line)
    for key in ("units", "_FillValue", "valid_min", "valid_max", "grid_mapping", "description", "long_name"):
        if key in attrs:
            print(f"      {key}: {attrs[key][:200]}")
    extra = {k: v for k, v in attrs.items() if k not in
             ("units", "_FillValue", "valid_min", "valid_max", "grid_mapping", "description", "long_name",
              "CLASS", "NAME", "_Netcdf4Dimid", "_Netcdf4Coordinates")}
    if extra:
        print(f"      other attrs: { {k: v[:80] for k, v in extra.items()} }")


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    walk_all = "--all" in sys.argv
    lon, lat = (float(args[0]), float(args[1])) if len(args) >= 2 else (-120.33, 50.67)
    ref = args[2] if len(args) >= 3 else None

    pairs = catalog.search("GUNW", lon=lon, lat=lat)
    if ref:
        pairs = [g for g in pairs if g.reference_date == ref]
    if not pairs:
        raise SystemExit("no GUNW pair found")
    g = pairs[-1]
    print(f"granule: {g.granule_id}\n  track {g.track} {g.direction} frame {g.frame}, "
          f"{g.reference_date} -> {g.secondary_date}, tier {g.tier}, {g.size_gb} GB")

    t0 = time.time()
    with RemoteGranule(g.url) as rg:
        print(f"opened in {time.time() - t0:.1f}s; file size {rg.raw.size / 1e9:.2f} GB")
        print("top level:", list(rg.h5["/science/LSAR"].keys()), "| GUNW:", list(rg.h5["/science/LSAR/GUNW"].keys()))
        if walk_all:
            rg.h5.visititems(describe)
        else:
            for root in INTERESTING:
                if root not in rg.h5:
                    print(f"\n[{root}] MISSING")
                    continue
                print(f"\n[{root}]")
                rg.h5[root].visititems(lambda n, o, root=root: describe(f"{root}/{n}", o))
        print(f"\nwalk took {time.time() - t0:.1f}s; io {rg.raw.stats()}")


if __name__ == "__main__":
    main()

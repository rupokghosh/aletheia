"""Search NASA's Common Metadata Repository (CMR) for NISAR granules. No login needed."""

from __future__ import annotations

from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import requests

from .schemas import Coverage, Granule, Stack

CMR_GRANULES = "https://cmr.earthdata.nasa.gov/search/granules.json"

# Collection concept IDs at the Alaska Satellite Facility DAAC, by product and calibration tier.
COLLECTIONS: dict[str, dict[str, str]] = {
    "GCOV": {"validated": "C3622241360-ASF", "provisional": "C2854338529-ASF", "beta": "C3622214170-ASF"},
    "GUNW": {"validated": "C3622247503-ASF", "provisional": "C2854335566-ASF", "beta": "C2850261892-ASF"},
    "GOFF": {"validated": "C3622250865-ASF", "provisional": "C2854341702-ASF", "beta": "C2850263910-ASF"},
    "SME2": {"provisional": "C2854344945-ASF", "beta": "C2850265000-ASF"},
}
TIER_RANK = {"validated": 0, "provisional": 1, "beta": 2}
PAIR_PRODUCTS = {"GUNW", "GOFF"}

# Polarization codes used in NISAR file names (two letters per frequency band).
_POL_CODES = {
    "SH": ["HH"],
    "SV": ["VV"],
    "DH": ["HH", "HV"],
    "DV": ["VV", "VH"],
    "QP": ["HH", "HV", "VH", "VV"],
    "QD": ["HH", "VV"],
    "CL": ["LH", "LV"],
    "CR": ["RH", "RV"],
    "NA": [],
}


def _date(token: str) -> tuple[str, str]:
    """'20260619T124759' -> ('2026-06-19', '2026-06-19T12:47:59Z')."""
    dt = datetime.strptime(token, "%Y%m%dT%H%M%S")
    return dt.strftime("%Y-%m-%d"), dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_granule_id(granule_id: str) -> dict:
    """Decode the fields carried in a NISAR granule name.

    Single-date: NISAR_L2_PR_GCOV_023_077_A_027_4005_DHDH_A_<start>_<end>_P05023_N_F_J_001
    Pair:        NISAR_L2_PR_GUNW_032_077_A_027_033_4000_SH_<refstart>_<refend>_<secstart>_<secend>_P05023_N_F_J_001
    """
    p = granule_id.split("_")
    product = p[3]
    out: dict = {
        "product": product,
        "track": int(p[5]),
        "direction": "ascending" if p[6] == "A" else "descending",
        "frame": int(p[7]),
    }
    if product in PAIR_PRODUCTS:
        out["mode"] = p[9]
        out["polarizations"] = _POL_CODES.get(p[10], [])
        out["reference_date"], out["start_time"] = _date(p[11])
        out["secondary_date"], _ = _date(p[13])
    else:
        out["mode"] = p[8]
        out["polarizations"] = _POL_CODES.get(p[9][:2], [])
        out["date"], out["start_time"] = _date(p[11])
    return out


def _data_url(entry: dict) -> str | None:
    for link in entry.get("links", []):
        href = link.get("href", "")
        if href.startswith("https://") and href.endswith(".h5") and "QA_STATS" not in href:
            return href
    return None


def _footprint(entry: dict) -> list[tuple[float, float]]:
    polys = entry.get("polygons") or []
    if not polys:
        return []
    nums = [float(v) for v in polys[0][0].split()]
    return [(nums[i + 1], nums[i]) for i in range(0, len(nums) - 1, 2)]  # CMR gives lat lon pairs


def _query(product: str, tier: str, params: dict) -> list[Granule]:
    q = dict(params, collection_concept_id=COLLECTIONS[product][tier], page_size=2000, sort_key="start_date")
    r = requests.get(CMR_GRANULES, params=q, timeout=60)
    r.raise_for_status()
    out: list[Granule] = []
    for e in r.json()["feed"]["entry"]:
        url = _data_url(e)
        if not url:
            continue
        try:
            fields = parse_granule_id(e["title"])
        except (IndexError, ValueError):
            continue
        size = e.get("granule_size")
        out.append(
            Granule(
                granule_id=e["title"],
                tier=tier,  # type: ignore[arg-type]
                url=url,
                size_gb=round(float(size) / 1024, 2) if size else None,
                footprint=_footprint(e),
                **fields,
            )
        )
    return out


def search(
    product: str,
    *,
    lon: float | None = None,
    lat: float | None = None,
    bbox: tuple[float, float, float, float] | None = None,
    start: str | None = None,
    end: str | None = None,
) -> list[Granule]:
    """Granules of one product that intersect a point or a box, best calibration tier first per acquisition."""
    if product not in COLLECTIONS:
        raise ValueError(f"unknown product {product!r}")
    params: dict = {}
    if bbox is not None:
        params["bounding_box"] = ",".join(f"{v:.6f}" for v in bbox)
    elif lon is not None and lat is not None:
        params["point"] = f"{lon:.6f},{lat:.6f}"
    else:
        raise ValueError("give a point (lon, lat) or a bbox")
    if start or end:
        params["temporal"] = f"{start + 'T00:00:00Z' if start else ''},{end + 'T23:59:59Z' if end else ''}"

    tiers = list(COLLECTIONS[product])
    with ThreadPoolExecutor(max_workers=len(tiers)) as pool:
        batches = list(pool.map(lambda t: _query(product, t, params), tiers))

    # The same acquisition can exist in more than one tier: keep the best calibrated copy.
    best: dict[tuple, Granule] = {}
    for g in (g for batch in batches for g in batch):
        key = (g.track, g.direction, g.frame, g.start_time, g.secondary_date)
        if key not in best or TIER_RANK[g.tier] < TIER_RANK[best[key].tier]:
            best[key] = g
    return sorted(best.values(), key=lambda g: (g.start_time or "", g.track))


def stacks(granules: list[Granule]) -> list[Stack]:
    """Group granules whose pixel grids line up (same product, track, direction and frame)."""
    groups: dict[tuple, list[Granule]] = defaultdict(list)
    for g in granules:
        groups[(g.product, g.track, g.direction, g.frame)].append(g)
    out = []
    for (product, track, direction, frame), items in sorted(groups.items()):
        tiers: dict[str, int] = defaultdict(int)
        for g in items:
            tiers[g.tier] += 1
        out.append(
            Stack(
                product=product,
                track=track,
                direction=direction,
                frame=frame,
                dates=sorted({g.date or g.reference_date or "" for g in items}),
                tiers=dict(tiers),
                polarizations=sorted({p for g in items for p in g.polarizations}),
            )
        )
    return out


def _gap_notes(granules: list[Granule], min_days: int = 30) -> list[str]:
    dates = sorted({g.date for g in granules if g.date})
    notes = []
    for a, b in zip(dates, dates[1:]):
        days = (datetime.fromisoformat(b) - datetime.fromisoformat(a)).days
        if days >= min_days:
            notes.append(f"No acquisitions between {a} and {b} ({days} days).")
    return notes


def coverage(
    *,
    lon: float | None = None,
    lat: float | None = None,
    bbox: tuple[float, float, float, float] | None = None,
    products: tuple[str, ...] = ("GCOV", "GUNW", "SME2"),
) -> Coverage:
    """Everything NISAR has for a point or a box, grouped into grid-aligned stacks."""
    with ThreadPoolExecutor(max_workers=len(products)) as pool:
        found = dict(zip(products, pool.map(lambda p: search(p, lon=lon, lat=lat, bbox=bbox), products)))
    all_stacks = [s for p in products for s in stacks(found[p])]
    notes = _gap_notes(found.get("GCOV", []))
    if not found.get("GCOV"):
        notes.append("No NISAR backscatter (GCOV) granules intersect this location.")
    if any(g.tier == "beta" for g in found.get("GCOV", [])):
        notes.append("Beta-tier acquisitions are uncalibrated; compare them with later dates only with care.")
    query = {"bbox": list(bbox)} if bbox is not None else {"lon": lon, "lat": lat}
    return Coverage(query=query, products=found, stacks=all_stacks, notes=notes)

"""Independent context evidence, fetched separately from the radar analysis.

Every function returns a plain dict with `available`, `source`, `url` and the facts, and never raises:
missing context must not sink an investigation.
"""

from __future__ import annotations

import csv
import io
import math
from collections import defaultdict
from datetime import datetime, timedelta

import requests

_TIMEOUT = (10, 60)
BBox = tuple[float, float, float, float]


def _centre(bbox: BBox) -> tuple[float, float]:
    return (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2


def _km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(a))


def _unavailable(source: str, reason: str) -> dict:
    return {"available": False, "source": source, "reason": reason}


# ------------------------------------------------------------- earthquakes


def earthquakes(bbox: BBox, start: str, end: str, *, min_magnitude: float = 4.5, radius_km: float = 150) -> dict:
    """Earthquakes near the area from the USGS catalogue (global, no key)."""
    source = "USGS Earthquake Catalog (FDSN event service)"
    lon, lat = _centre(bbox)
    params = {
        "format": "geojson",
        "starttime": start,
        "endtime": (datetime.fromisoformat(end) + timedelta(days=1)).strftime("%Y-%m-%d"),
        "latitude": round(lat, 4),
        "longitude": round(lon, 4),
        "maxradiuskm": radius_km,
        "minmagnitude": min_magnitude,
        "orderby": "magnitude",
        "limit": 20,
    }
    try:
        r = requests.get("https://earthquake.usgs.gov/fdsnws/event/1/query", params=params, timeout=_TIMEOUT)
        r.raise_for_status()
        features = r.json().get("features", [])
    except (requests.RequestException, ValueError) as exc:
        return _unavailable(source, f"request failed ({type(exc).__name__})")
    events = []
    for f in features:
        p, c = f["properties"], f["geometry"]["coordinates"]
        events.append(
            {
                "time_utc": datetime.utcfromtimestamp(p["time"] / 1000).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "magnitude": p.get("mag"),
                "depth_km": round(c[2], 1) if c[2] is not None else None,
                "distance_km": round(_km(lon, lat, c[0], c[1]), 1),
                "place": p.get("place"),
                "url": p.get("url"),
            }
        )
    return {
        "available": True,
        "source": source,
        "url": r.url,
        "search": {"radius_km": radius_km, "min_magnitude": min_magnitude, "start": start, "end": end},
        "count": len(events),
        "events": events,
    }


# ------------------------------------------------------------ river gauges


def _daily_means(rows: list[tuple[str, float]]) -> dict[str, float]:
    by_day: dict[str, list[float]] = defaultdict(list)
    for stamp, value in rows:
        by_day[stamp[:10]].append(value)
    return {day: round(sum(v) / len(v), 3) for day, v in sorted(by_day.items())}


def _canada_gauges(bbox: BBox, start: str, end: str, dates: list[str], pad_deg: float = 0.25) -> dict:
    source = "Water Survey of Canada real-time hydrometric data (Environment and Climate Change Canada)"
    lon, lat = _centre(bbox)
    box = f"{bbox[0] - pad_deg},{bbox[1] - pad_deg},{bbox[2] + pad_deg},{bbox[3] + pad_deg}"
    try:
        r = requests.get(
            "https://api.weather.gc.ca/collections/hydrometric-stations/items",
            params={"f": "json", "bbox": box, "limit": 500},
            timeout=_TIMEOUT,
        )
        r.raise_for_status()
        stations = [
            f
            for f in r.json().get("features", [])
            if f["properties"].get("STATUS_EN") == "Active" and f["properties"].get("REAL_TIME") == 1
        ]
    except (requests.RequestException, ValueError) as exc:
        return _unavailable(source, f"station search failed ({type(exc).__name__})")
    if not stations:
        return _unavailable(source, "no active real-time gauge within about 25 km of the area")
    stations.sort(key=lambda f: _km(lon, lat, *f["geometry"]["coordinates"][:2]))

    gauges = []
    for f in stations[:2]:
        sid, name = f["properties"]["STATION_NUMBER"], f["properties"]["STATION_NAME"]
        slon, slat = f["geometry"]["coordinates"][:2]
        url = (
            "https://wateroffice.ec.gc.ca/services/real_time_data/csv/inline"
            f"?stations[]={sid}&parameters[]=46&start_date={start}%2000:00:00&end_date={end}%2023:59:59"
        )
        try:
            c = requests.get(url, timeout=_TIMEOUT)
            c.raise_for_status()
            rows = []
            for row in csv.reader(io.StringIO(c.text.lstrip("﻿"))):
                if len(row) > 3 and row[0].strip() == sid:
                    try:
                        rows.append((row[1], float(row[3])))
                    except ValueError:
                        continue
        except requests.RequestException:
            continue
        daily = _daily_means(rows)
        if not daily:
            continue
        peak_day = max(daily, key=daily.get)
        low_day = min(daily, key=daily.get)
        gauges.append(
            {
                "station_id": sid,
                "station_name": name,
                "distance_km": round(_km(lon, lat, slon, slat), 1),
                "parameter": "water level",
                "unit": "m (local gauge datum)",
                "quality": "provisional real-time data",
                "level_on_dates": {d: daily[d] for d in dates if d in daily},
                "period_max": {"date": peak_day, "level": daily[peak_day]},
                "period_min": {"date": low_day, "level": daily[low_day]},
                "url": f"https://wateroffice.ec.gc.ca/report/real_time_e.html?stn={sid}",
            }
        )
    if not gauges:
        return _unavailable(source, "gauges were found but returned no water-level data for the period")
    return {"available": True, "source": source, "url": "https://wateroffice.ec.gc.ca/", "gauges": gauges}


def _usa_gauges(bbox: BBox, start: str, end: str, dates: list[str], pad_deg: float = 0.25) -> dict:
    source = "USGS National Water Information System, daily values"
    lon, lat = _centre(bbox)
    params = {
        "format": "json",
        "bBox": f"{bbox[0] - pad_deg:.4f},{bbox[1] - pad_deg:.4f},{bbox[2] + pad_deg:.4f},{bbox[3] + pad_deg:.4f}",
        "parameterCd": "00065",  # gage height, feet
        "startDT": start,
        "endDT": end,
        "siteStatus": "active",
    }
    try:
        r = requests.get("https://waterservices.usgs.gov/nwis/dv/", params=params, timeout=_TIMEOUT)
        r.raise_for_status()
        series = r.json()["value"]["timeSeries"]
    except (requests.RequestException, ValueError, KeyError) as exc:
        return _unavailable(source, f"request failed ({type(exc).__name__})")
    gauges = []
    for ts in series:
        info = ts["sourceInfo"]
        loc = info["geoLocation"]["geogLocation"]
        values = ts["values"][0]["value"] if ts.get("values") else []
        daily = {}
        for v in values:
            try:
                daily[v["dateTime"][:10]] = round(float(v["value"]) * 0.3048, 3)
            except (ValueError, KeyError):
                continue
        if not daily:
            continue
        sid = info["siteCode"][0]["value"]
        peak_day, low_day = max(daily, key=daily.get), min(daily, key=daily.get)
        gauges.append(
            {
                "station_id": sid,
                "station_name": info["siteName"],
                "distance_km": round(_km(lon, lat, loc["longitude"], loc["latitude"]), 1),
                "parameter": "gage height (daily mean)",
                "unit": "m (converted from feet, local gauge datum)",
                "quality": "may include provisional data",
                "level_on_dates": {d: daily[d] for d in dates if d in daily},
                "period_max": {"date": peak_day, "level": daily[peak_day]},
                "period_min": {"date": low_day, "level": daily[low_day]},
                "url": f"https://waterdata.usgs.gov/monitoring-location/{sid}/",
            }
        )
    if not gauges:
        return _unavailable(source, "no active gauge with gage-height data near the area")
    gauges.sort(key=lambda g: g["distance_km"])
    return {"available": True, "source": source, "url": "https://waterdata.usgs.gov/", "gauges": gauges[:2]}


def river_gauges(bbox: BBox, start: str, end: str, dates: list[str] | None = None) -> dict:
    """Water level at the nearest gauges, for Canada and the United States. Elsewhere: not available."""
    lon, lat = _centre(bbox)
    dates = dates or [start, end]
    in_canada = 41.5 < lat < 84 and -141.5 < lon < -52
    in_usa = (24 < lat < 49.5 and -125 < lon < -66) or (51 < lat < 72 and -170 < lon < -129) or (18 < lat < 23 and -161 < lon < -154)
    attempts = []
    if in_canada:
        attempts.append(_canada_gauges)
    if in_usa:
        attempts.append(_usa_gauges)
    if lat >= 49 and in_canada:
        attempts = [_canada_gauges] + [a for a in attempts if a is not _canada_gauges]
    last = _unavailable("river gauges", "river-gauge context is only wired up for Canada and the United States so far")
    for fn in attempts:
        last = fn(bbox, start, end, dates)
        if last.get("available"):
            return last
    return last

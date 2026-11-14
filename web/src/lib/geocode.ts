/** Place search with Photon (komoot), a free geocoder on OpenStreetMap data. */

import { GEOCODER_URL } from "./config";
import type { BBox, LonLat } from "./types";

export interface Place {
  id: string;
  name: string;
  /** region and country, for telling results apart */
  detail: string;
  center: LonLat;
  extent: BBox | null;
}

interface PhotonFeature {
  geometry?: { coordinates?: [number, number] };
  properties?: {
    osm_type?: string;
    osm_id?: number;
    name?: string;
    city?: string;
    county?: string;
    state?: string;
    country?: string;
    /** west, north, east, south */
    extent?: [number, number, number, number];
  };
}

const cache = new Map<string, Place[]>();

/** "50.75, -120.6" (latitude, longitude) is answered locally without a network request. */
function parseCoordinates(query: string): Place | null {
  const match = /^\s*(-?\d+(?:\.\d+)?)\s*[,\s]\s*(-?\d+(?:\.\d+)?)\s*$/.exec(query);
  if (!match) return null;
  const lat = Number(match[1]);
  const lon = Number(match[2]);
  if (Math.abs(lat) > 90 || Math.abs(lon) > 180) return null;
  return {
    id: `coordinates:${lat},${lon}`,
    name: `${lat.toFixed(4)}, ${lon.toFixed(4)}`,
    detail: "Latitude, longitude",
    center: [lon, lat],
    extent: null,
  };
}

function toPlace(feature: PhotonFeature): Place | null {
  const coordinates = feature.geometry?.coordinates;
  const properties = feature.properties;
  if (!coordinates || !properties?.name) return null;
  const detail = [properties.city, properties.state ?? properties.county, properties.country]
    .filter((part, index, parts) => part && part !== properties.name && parts.indexOf(part) === index)
    .join(", ");
  const extent = properties.extent;
  return {
    id: `${properties.osm_type ?? "x"}${properties.osm_id ?? `${coordinates[0]},${coordinates[1]}`}`,
    name: properties.name,
    detail,
    center: [coordinates[0], coordinates[1]],
    extent: extent ? [extent[0], extent[3], extent[2], extent[1]] : null,
  };
}

export async function searchPlaces(query: string, signal?: AbortSignal): Promise<Place[]> {
  const trimmed = query.trim();
  const coordinates = parseCoordinates(trimmed);
  if (coordinates) return [coordinates];
  if (trimmed.length < 3) return [];

  const key = trimmed.toLowerCase();
  const cached = cache.get(key);
  if (cached) return cached;

  const url = `${GEOCODER_URL}?q=${encodeURIComponent(trimmed)}&limit=6&lang=en`;
  const response = await fetch(url, { signal, headers: { Accept: "application/json" } });
  if (!response.ok) throw new Error(`Place search is unavailable (${response.status}).`);
  const body = (await response.json()) as { features?: PhotonFeature[] };
  const seen = new Set<string>();
  const places = (body.features ?? [])
    .map(toPlace)
    .filter((place): place is Place => place !== null && !seen.has(place.id) && Boolean(seen.add(place.id)));
  cache.set(key, places);
  return places;
}

/** A view box for a place: its own extent, or a window of about 20 km around a point. */
export function placeBounds(place: Place): BBox {
  if (place.extent) return place.extent;
  const [lon, lat] = place.center;
  const dLat = 0.09;
  const dLon = dLat / Math.max(0.2, Math.cos((lat * Math.PI) / 180));
  return [lon - dLon, lat - dLat, lon + dLon, lat + dLat];
}

/** A short name for a spot on the map ("Kamloops, British Columbia"), or null when none can be found. */
export async function nearestPlaceName(lon: number, lat: number, signal?: AbortSignal): Promise<string | null> {
  const url = `${GEOCODER_URL.replace(/\/api\/?$/, "")}/reverse?lon=${lon.toFixed(5)}&lat=${lat.toFixed(5)}&lang=en`;
  try {
    const response = await fetch(url, { signal, headers: { Accept: "application/json" } });
    if (!response.ok) return null;
    const body = (await response.json()) as { features?: PhotonFeature[] };
    const properties = body.features?.[0]?.properties;
    if (!properties) return null;
    const place = properties.city ?? properties.name ?? properties.county;
    const region = properties.state ?? properties.country;
    if (!place) return region ?? null;
    return region && region !== place ? `${place}, ${region}` : place;
  } catch {
    return null; // a name is a nicety: the area works without one
  }
}

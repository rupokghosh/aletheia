import type { BBox, LonLat } from "./types";

const EARTH_RADIUS_KM = 6371.0088;
const RAD = Math.PI / 180;

/** Area of a lon/lat rectangle on the sphere, in km². */
export function bboxAreaKm2([west, south, east, north]: BBox): number {
  const dLon = (east - west) * RAD;
  const band = Math.sin(north * RAD) - Math.sin(south * RAD);
  return Math.abs(EARTH_RADIUS_KM * EARTH_RADIUS_KM * dLon * band);
}

/** Orders two corner points into a valid bbox and clamps it to the valid range. */
export function bboxFromCorners(a: LonLat, b: LonLat): BBox {
  const clampLat = (v: number) => Math.max(-85, Math.min(85, v));
  const clampLon = (v: number) => Math.max(-180, Math.min(180, v));
  return [
    clampLon(Math.min(a[0], b[0])),
    clampLat(Math.min(a[1], b[1])),
    clampLon(Math.max(a[0], b[0])),
    clampLat(Math.max(a[1], b[1])),
  ];
}

export function isValidBBox(bbox: BBox): boolean {
  const [west, south, east, north] = bbox;
  return (
    bbox.every((v) => Number.isFinite(v)) &&
    west >= -180 &&
    east <= 180 &&
    south >= -90 &&
    north <= 90 &&
    east > west &&
    north > south
  );
}

/** Closed ring for a bbox, densified along each edge so it follows the globe's curvature. */
export function bboxRing([west, south, east, north]: BBox, segments = 16): LonLat[] {
  const ring: LonLat[] = [];
  const edge = (from: LonLat, to: LonLat) => {
    for (let i = 0; i < segments; i += 1) {
      const t = i / segments;
      ring.push([from[0] + (to[0] - from[0]) * t, from[1] + (to[1] - from[1]) * t]);
    }
  };
  edge([west, north], [east, north]);
  edge([east, north], [east, south]);
  edge([east, south], [west, south]);
  edge([west, south], [west, north]);
  ring.push([west, north]);
  return ring;
}

/** Image corners (top-left, top-right, bottom-right, bottom-left) for a north-up bbox. */
export function bboxCorners([west, south, east, north]: BBox): LonLat[] {
  return [
    [west, north],
    [east, north],
    [east, south],
    [west, south],
  ];
}

/** Smallest bbox that contains a set of points. */
export function boundsOf(points: LonLat[]): BBox | null {
  if (points.length === 0) return null;
  let west = Infinity;
  let south = Infinity;
  let east = -Infinity;
  let north = -Infinity;
  for (const [lon, lat] of points) {
    west = Math.min(west, lon);
    east = Math.max(east, lon);
    south = Math.min(south, lat);
    north = Math.max(north, lat);
  }
  return [west, south, east, north];
}

/**
 * Share of a bbox that lies inside a footprint polygon, 0 to 1. The polygon is clipped to the
 * rectangle edge by edge (Sutherland-Hodgman) and the areas are compared in degrees, which is
 * accurate enough for the few kilometres an area of interest spans.
 */
export function footprintShare(bbox: BBox, footprint: LonLat[]): number | null {
  if (footprint.length < 3) return null;
  const [west, south, east, north] = bbox;
  const edges: Array<{ inside: (p: LonLat) => boolean; cut: (a: LonLat, b: LonLat) => LonLat }> = [
    { inside: (p) => p[0] >= west, cut: (a, b) => [west, a[1] + ((west - a[0]) / (b[0] - a[0])) * (b[1] - a[1])] },
    { inside: (p) => p[0] <= east, cut: (a, b) => [east, a[1] + ((east - a[0]) / (b[0] - a[0])) * (b[1] - a[1])] },
    { inside: (p) => p[1] >= south, cut: (a, b) => [a[0] + ((south - a[1]) / (b[1] - a[1])) * (b[0] - a[0]), south] },
    { inside: (p) => p[1] <= north, cut: (a, b) => [a[0] + ((north - a[1]) / (b[1] - a[1])) * (b[0] - a[0]), north] },
  ];
  let polygon = footprint;
  for (const { inside, cut } of edges) {
    const next: LonLat[] = [];
    polygon.forEach((point, index) => {
      const previous = polygon[(index + polygon.length - 1) % polygon.length];
      if (inside(point)) {
        if (!inside(previous)) next.push(cut(previous, point));
        next.push(point);
      } else if (inside(previous)) {
        next.push(cut(previous, point));
      }
    });
    polygon = next;
    if (polygon.length === 0) return 0;
  }
  const doubled = polygon.reduce((sum, point, index) => {
    const previous = polygon[(index + polygon.length - 1) % polygon.length];
    return sum + previous[0] * point[1] - point[0] * previous[1];
  }, 0);
  const share = Math.abs(doubled) / 2 / ((east - west) * (north - south));
  return Math.min(1, Math.max(0, share));
}

export function bboxKey(bbox: BBox): string {
  return bbox.map((v) => v.toFixed(5)).join(",");
}

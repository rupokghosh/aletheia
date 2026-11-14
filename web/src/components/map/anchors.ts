import type { Map as MapLibreMap } from "maplibre-gl";

/**
 * Two invisible layers that fix the drawing order: base map, context imagery, result layers, labels.
 * Context imagery is inserted before CONTEXT_ANCHOR and result layers before RESULTS_ANCHOR.
 */
export const CONTEXT_ANCHOR = "anchor-context";
export const RESULTS_ANCHOR = "anchor-results";

export function addAnchors(map: MapLibreMap): void {
  // In the base style every label layer comes after the fills and lines, so results go under the first one.
  const firstLabel = map.getStyle().layers.find((layer) => layer.type === "symbol")?.id;
  for (const id of [CONTEXT_ANCHOR, RESULTS_ANCHOR]) {
    map.addLayer({ id, type: "background", layout: { visibility: "none" } }, firstLabel);
  }
}

const removed = new WeakSet<MapLibreMap>();

/** Removes the map and remembers it, so effect clean-ups that run afterwards can skip it. */
export function destroyMap(map: MapLibreMap): void {
  removed.add(map);
  map.remove();
}

export function isAlive(map: MapLibreMap): boolean {
  return !removed.has(map);
}

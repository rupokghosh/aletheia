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

/**
 * The base map draws water in pale grey. NISAR does not image the open ocean, so that grey is what
 * most of the globe would show; a deep blue reads as sea and sits next to the radar picture, whose
 * own water is dark, without a seam.
 */
const SEA = "#17365c";
const SEA_LABEL = "#c9d6ee";

export function colourWater(map: MapLibreMap): void {
  if (map.getLayer("water")) map.setPaintProperty("water", "fill-color", SEA);
  if (map.getLayer("waterway")) map.setPaintProperty("waterway", "line-color", SEA);
  for (const id of ["water_name_point_label", "water_name_line_label", "waterway_line_label"]) {
    if (!map.getLayer(id)) continue;
    map.setPaintProperty(id, "text-color", SEA_LABEL);
    map.setPaintProperty(id, "text-halo-color", "rgba(12, 30, 54, 0.75)");
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

"use client";

import type { CustomLayerInterface, Map as MapLibreMap } from "maplibre-gl";
import { useEffect, useRef } from "react";
import type { MapLayer } from "@/lib/layers";
import { RESULTS_ANCHOR, isAlive } from "./anchors";

const PREFIX = "result-";
const SWIPE_LAYERS = ["swipe-left", "swipe-right", "swipe-off"] as const;

/** Everything that requires layers to be rebuilt. Opacity is applied in place. */
function structureOf(layers: MapLayer[]): string {
  return layers.map((l) => `${l.key}|${l.url}|${l.role}|${l.corners.flat().join(",")}`).join(";");
}

function clear(map: MapLibreMap): void {
  if (!isAlive(map)) return;
  const style = map.getStyle();
  for (const layer of style.layers) {
    if (layer.id.startsWith(PREFIX) || (SWIPE_LAYERS as readonly string[]).includes(layer.id)) map.removeLayer(layer.id);
  }
  for (const id of Object.keys(style.sources)) {
    if (id.startsWith(PREFIX)) map.removeSource(id);
  }
}

/**
 * A layer that draws nothing and only sets the WebGL scissor rectangle. Placed around the
 * "before" and "after" images, it clips each to one side of the swipe line.
 */
function scissorLayer(id: string, apply: (gl: WebGL2RenderingContext) => void): CustomLayerInterface {
  return { id, type: "custom", renderingMode: "2d", render: (gl) => apply(gl) };
}

/**
 * Keeps the image layers of the active result on the map. `layers` is ordered bottom to top.
 * `swipe` is the position of the compare line, 0 to 1 across the map.
 */
export function useResultLayers(map: MapLibreMap | null, layers: MapLayer[], swipe: number): void {
  const swipeRef = useRef(swipe);
  const structure = structureOf(layers);

  useEffect(() => {
    swipeRef.current = swipe;
    map?.triggerRepaint();
  }, [map, swipe]);

  useEffect(() => {
    if (!map) return;
    // Start clean: if an earlier run stopped half way, its layers must not collide with these.
    clear(map);
    const comparing = layers.some((l) => l.role === "before") && layers.some((l) => l.role === "after");
    const splitAt = (gl: WebGL2RenderingContext) => Math.round(swipeRef.current * gl.drawingBufferWidth);

    const addImage = (layer: MapLayer) => {
      const id = `${PREFIX}${layer.key}`;
      const [topLeft, topRight, bottomRight, bottomLeft] = layer.corners;
      map.addSource(id, { type: "image", url: layer.url, coordinates: [topLeft, topRight, bottomRight, bottomLeft] });
      map.addLayer(
        {
          id,
          type: "raster",
          source: id,
          paint: {
            "raster-opacity": layer.opacity,
            "raster-opacity-transition": { duration: 0, delay: 0 },
            "raster-fade-duration": 0,
            "raster-resampling": layer.resampling,
          },
        },
        RESULTS_ANCHOR,
      );
    };

    for (const layer of layers) {
      if (comparing && layer.role === "before") {
        map.addLayer(
          scissorLayer("swipe-left", (gl) => {
            gl.enable(gl.SCISSOR_TEST);
            gl.scissor(0, 0, splitAt(gl), gl.drawingBufferHeight);
          }),
          RESULTS_ANCHOR,
        );
      }
      if (comparing && layer.role === "after") {
        map.addLayer(
          scissorLayer("swipe-right", (gl) => {
            const x = splitAt(gl);
            gl.enable(gl.SCISSOR_TEST);
            gl.scissor(x, 0, gl.drawingBufferWidth - x, gl.drawingBufferHeight);
          }),
          RESULTS_ANCHOR,
        );
      }
      addImage(layer);
      if (comparing && layer.role === "after") {
        map.addLayer(scissorLayer("swipe-off", (gl) => gl.disable(gl.SCISSOR_TEST)), RESULTS_ANCHOR);
      }
    }

    return () => clear(map);
    // `structure` stands in for `layers`: a rebuild is only needed when it changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map, structure]);

  useEffect(() => {
    if (!map) return;
    for (const layer of layers) {
      const id = `${PREFIX}${layer.key}`;
      if (map.getLayer(id)) map.setPaintProperty(id, "raster-opacity", layer.opacity);
    }
  }, [map, layers]);
}

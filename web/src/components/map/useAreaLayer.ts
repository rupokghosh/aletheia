"use client";

import type { GeoJSONSource, Map as MapLibreMap, MapMouseEvent, MapTouchEvent } from "maplibre-gl";
import { useEffect, useState } from "react";
import { bboxAreaKm2, bboxFromCorners, bboxRing } from "@/lib/geo";
import type { BBox, LonLat } from "@/lib/types";
import { isAlive } from "./anchors";

const SOURCE = "aoi";
/** A drag shorter than this many pixels is treated as a click, not a rectangle. */
const MIN_DRAG_PX = 6;

/** GeoJSON accepted by the outline source. */
type AreaData = Parameters<GeoJSONSource["setData"]>[0];

function polygon(bbox: BBox | null): AreaData {
  if (!bbox) return { type: "FeatureCollection", features: [] };
  return {
    type: "FeatureCollection",
    features: [{ type: "Feature", properties: {}, geometry: { type: "Polygon", coordinates: [bboxRing(bbox)] } }],
  };
}

function setArea(map: MapLibreMap, bbox: BBox | null): void {
  map.getSource<GeoJSONSource>(SOURCE)?.setData(polygon(bbox));
}

/** Adds the area-of-interest outline: a black line on a white casing, readable on the map and on result layers. */
export function addAreaLayers(map: MapLibreMap): void {
  map.addSource(SOURCE, { type: "geojson", data: polygon(null) });
  map.addLayer({ id: "aoi-fill", type: "fill", source: SOURCE, paint: { "fill-color": "#191919", "fill-opacity": 0 } });
  map.addLayer({ id: "aoi-casing", type: "line", source: SOURCE, paint: { "line-color": "#ffffff", "line-width": 4.5, "line-opacity": 0.9 } });
  map.addLayer({ id: "aoi-line", type: "line", source: SOURCE, paint: { "line-color": "#191919", "line-width": 2 } });
}

interface AreaLayerOptions {
  bbox: BBox | null;
  drawing: boolean;
  onDrawn: (bbox: BBox) => void;
  onCancel: () => void;
}

/**
 * Keeps the outline in step with the chosen area and runs the rectangle draw tool.
 * Returns the area of the rectangle being dragged, in km², or null when nothing is being drawn.
 */
export function useAreaLayer(map: MapLibreMap | null, { bbox, drawing, onDrawn, onCancel }: AreaLayerOptions): number | null {
  const [draftArea, setDraftArea] = useState<number | null>(null);

  useEffect(() => {
    if (map) setArea(map, bbox);
  }, [map, bbox]);

  useEffect(() => {
    if (!map || !drawing) return;

    const container = map.getCanvasContainer();
    let origin: { lngLat: LonLat; x: number; y: number } | null = null;
    let draft: BBox | null = null;
    let dragged = false;

    container.style.cursor = "crosshair";
    map.dragPan.disable();
    map.boxZoom.disable();
    map.doubleClickZoom.disable();
    map.setPaintProperty("aoi-fill", "fill-opacity", 0.08);

    const begin = (event: MapMouseEvent | MapTouchEvent) => {
      if ("touches" in event.originalEvent && event.originalEvent.touches.length > 1) return;
      event.preventDefault();
      origin = { lngLat: [event.lngLat.lng, event.lngLat.lat], x: event.point.x, y: event.point.y };
      dragged = false;
    };

    const move = (event: MapMouseEvent | MapTouchEvent) => {
      if (!origin) return;
      dragged = Math.hypot(event.point.x - origin.x, event.point.y - origin.y) >= MIN_DRAG_PX;
      if (!dragged) return;
      draft = bboxFromCorners(origin.lngLat, [event.lngLat.lng, event.lngLat.lat]);
      setArea(map, draft);
      setDraftArea(bboxAreaKm2(draft));
    };

    const finish = () => {
      if (!origin) return;
      origin = null;
      if (dragged && draft && draft[2] > draft[0] && draft[3] > draft[1]) onDrawn(draft);
      draft = null;
    };

    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onCancel();
    };

    map.on("mousedown", begin);
    map.on("mousemove", move);
    map.on("touchstart", begin);
    map.on("touchmove", move);
    window.addEventListener("mouseup", finish);
    window.addEventListener("touchend", finish);
    window.addEventListener("keydown", onKey);

    return () => {
      map.off("mousedown", begin);
      map.off("mousemove", move);
      map.off("touchstart", begin);
      map.off("touchmove", move);
      window.removeEventListener("mouseup", finish);
      window.removeEventListener("touchend", finish);
      window.removeEventListener("keydown", onKey);
      setDraftArea(null);
      if (!isAlive(map)) return;
      container.style.cursor = "";
      map.dragPan.enable();
      map.boxZoom.enable();
      map.doubleClickZoom.enable();
      map.setPaintProperty("aoi-fill", "fill-opacity", 0);
      // Drop an unfinished rectangle and show the committed area again.
      setArea(map, bbox);
    };
  }, [map, drawing, bbox, onDrawn, onCancel]);

  return draftArea;
}

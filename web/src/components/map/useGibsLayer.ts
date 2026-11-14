"use client";

import type { Map as MapLibreMap, RasterTileSource } from "maplibre-gl";
import { useEffect } from "react";
import { GIBS } from "@/lib/config";
import { dayNumber, isoFromDayNumber } from "@/lib/format";
import type { GibsState } from "@/lib/store";
import { CONTEXT_ANCHOR, isAlive } from "./anchors";

const ID = "gibs-nisar";

function tileUrl(date: string): string {
  const params = new URLSearchParams({
    SERVICE: "WMS",
    REQUEST: "GetMap",
    VERSION: "1.3.0",
    LAYERS: GIBS.layer,
    STYLES: "",
    FORMAT: "image/png",
    TRANSPARENT: "true",
    CRS: "EPSG:3857",
    WIDTH: "512",
    HEIGHT: "512",
    TIME: date,
  });
  // The bbox token must stay unescaped so MapLibre can substitute it per tile.
  return `${GIBS.wmsUrl}?${params.toString()}&BBOX={bbox-epsg-3857}`;
}

/** The days on show, oldest first, so the most recent pass is drawn on top. */
function daysShown(date: string, days: number): string[] {
  const last = dayNumber(date);
  return Array.from({ length: days }, (_, i) => isoFromDayNumber(last - (days - 1 - i))).filter((d) => d >= GIBS.firstDate);
}

/**
 * NASA GIBS quick-look imagery as an optional raster layer, under the result layers and the labels.
 * NISAR images a few strips of the planet each day and returns to every place after 12 days, so the
 * default view stacks the last 12 daily pictures into one that covers the whole Earth.
 */
export function useGibsLayer(map: MapLibreMap | null, gibs: GibsState): void {
  const { enabled, date, days, opacity } = gibs;

  useEffect(() => {
    if (!map || !enabled) return;
    const shown = daysShown(date, days);
    shown.forEach((day, index) => {
      map.addSource(`${ID}-${index}`, {
        type: "raster",
        tiles: [tileUrl(day)],
        tileSize: 512,
        minzoom: 1,
        maxzoom: 12,
        attribution: index === 0 ? "Radar picture: NASA GIBS / ESDIS" : undefined,
      });
      map.addLayer(
        { id: `${ID}-${index}`, type: "raster", source: `${ID}-${index}`, paint: { "raster-opacity": opacity, "raster-fade-duration": 0 } },
        CONTEXT_ANCHOR,
      );
    });
    return () => {
      if (!isAlive(map)) return;
      shown.forEach((_, index) => {
        if (map.getLayer(`${ID}-${index}`)) map.removeLayer(`${ID}-${index}`);
        if (map.getSource(`${ID}-${index}`)) map.removeSource(`${ID}-${index}`);
      });
    };
    // Date and opacity changes are applied in place by the effects below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map, enabled, days]);

  useEffect(() => {
    if (!map || !enabled) return;
    daysShown(date, days).forEach((day, index) => map.getSource<RasterTileSource>(`${ID}-${index}`)?.setTiles([tileUrl(day)]));
  }, [map, enabled, date, days]);

  useEffect(() => {
    if (!map || !enabled) return;
    for (let index = 0; index < days; index += 1) {
      if (map.getLayer(`${ID}-${index}`)) map.setPaintProperty(`${ID}-${index}`, "raster-opacity", opacity);
    }
  }, [map, enabled, days, opacity]);
}

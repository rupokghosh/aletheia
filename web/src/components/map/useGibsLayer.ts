"use client";

import type { Map as MapLibreMap, RasterTileSource } from "maplibre-gl";
import { useEffect } from "react";
import { GIBS } from "@/lib/config";
import { dayNumber, isoFromDayNumber } from "@/lib/format";
import type { GibsState } from "@/lib/store";
import { CONTEXT_ANCHOR, isAlive } from "./anchors";

const ID = "gibs-nisar";

/** One day straight from NASA GIBS. Used only when there is no API to merge and cache the days. */
function directTileUrl(date: string): string {
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

interface Plan {
  /** one entry per map layer: its tile URL templates (MapLibre spreads tiles across them) and tile size */
  layers: Array<{ urls: string[]; tileSize: number }>;
  maxzoom: number;
}

/**
 * A browser opens at most six connections to one host, so a screen of new tiles waits in line.
 * A local API answers on two names for the same machine, which doubles that. A tile always maps
 * to the same name, so the browser cache still works.
 */
function apiHosts(apiBase: string): string[] {
  try {
    const url = new URL(apiBase);
    if (url.hostname !== "localhost") return [apiBase];
    url.hostname = "127.0.0.1";
    return [apiBase, url.origin];
  } catch {
    return [apiBase];
  }
}

/**
 * With an API, the days are merged into one tile per map square on the server and cached there and
 * in the browser: one layer, one request per square, ever. Without one, the days are stacked here
 * as separate layers straight from NASA, which is slower and cannot be cached.
 */
function plan(date: string, days: number, apiBase: string | null): Plan {
  if (apiBase !== null) {
    // 512-pixel squares: a quarter as many requests per screen as 256-pixel ones.
    const urls = apiHosts(apiBase).map((host) => `${host}/api/tiles/radar/{z}/{x}/{y}?end=${date}&days=${days}`);
    return { layers: [{ urls, tileSize: 512 }], maxzoom: 12 };
  }
  return { layers: daysShown(date, days).map((day) => ({ urls: [directTileUrl(day)], tileSize: 512 })), maxzoom: 12 };
}

/**
 * NASA's picture of what NISAR saw, as an optional raster layer under the result layers and the labels.
 * NISAR images a few strips of the planet each day and returns to every place after 12 days, so the
 * default view shows the last 12 daily pictures together.
 */
export function useGibsLayer(map: MapLibreMap | null, gibs: GibsState, apiBase: string | null): void {
  const { enabled, date, days, opacity } = gibs;
  const count = apiBase !== null ? 1 : days;

  useEffect(() => {
    if (!map || !enabled) return;
    const { layers, maxzoom } = plan(date, days, apiBase);
    layers.forEach((layer, index) => {
      map.addSource(`${ID}-${index}`, {
        type: "raster",
        tiles: layer.urls,
        tileSize: layer.tileSize,
        minzoom: 0,
        maxzoom,
        attribution: index === 0 ? "Radar picture: NASA GIBS / ESDIS" : undefined,
      });
      map.addLayer(
        {
          id: `${ID}-${index}`,
          type: "raster",
          source: `${ID}-${index}`,
          // A short cross-fade as sharper tiles arrive, so zooming does not snap between pictures.
          paint: { "raster-opacity": opacity, "raster-fade-duration": 220 },
        },
        CONTEXT_ANCHOR,
      );
    });
    return () => {
      if (!isAlive(map)) return;
      layers.forEach((_, index) => {
        if (map.getLayer(`${ID}-${index}`)) map.removeLayer(`${ID}-${index}`);
        if (map.getSource(`${ID}-${index}`)) map.removeSource(`${ID}-${index}`);
      });
    };
    // Date and opacity changes are applied in place by the effects below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map, enabled, count, apiBase]);

  useEffect(() => {
    if (!map || !enabled) return;
    plan(date, days, apiBase).layers.forEach((layer, index) => map.getSource<RasterTileSource>(`${ID}-${index}`)?.setTiles(layer.urls));
  }, [map, enabled, date, days, apiBase]);

  useEffect(() => {
    if (!map || !enabled) return;
    for (let index = 0; index < count; index += 1) {
      if (map.getLayer(`${ID}-${index}`)) map.setPaintProperty(`${ID}-${index}`, "raster-opacity", opacity);
    }
  }, [map, enabled, count, opacity]);
}

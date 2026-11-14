"use client";

import type { Map as MapLibreMap, RasterTileSource } from "maplibre-gl";
import { useEffect } from "react";
import { GIBS } from "@/lib/config";
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

/** NASA GIBS quick-look imagery as an optional raster layer, under the result layers and the labels. */
export function useGibsLayer(map: MapLibreMap | null, gibs: GibsState): void {
  const { enabled, date, opacity } = gibs;

  useEffect(() => {
    if (!map || !enabled) return;
    map.addSource(ID, {
      type: "raster",
      tiles: [tileUrl(date)],
      tileSize: 512,
      minzoom: 1,
      maxzoom: 12,
      attribution: "Quick-look imagery: NASA GIBS / ESDIS",
    });
    map.addLayer({ id: ID, type: "raster", source: ID, paint: { "raster-opacity": opacity } }, CONTEXT_ANCHOR);
    return () => {
      if (!isAlive(map)) return;
      if (map.getLayer(ID)) map.removeLayer(ID);
      if (map.getSource(ID)) map.removeSource(ID);
    };
    // Date and opacity changes are applied in place by the effects below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map, enabled]);

  useEffect(() => {
    if (map && enabled) map.getSource<RasterTileSource>(ID)?.setTiles([tileUrl(date)]);
  }, [map, enabled, date]);

  useEffect(() => {
    if (map && enabled && map.getLayer(ID)) map.setPaintProperty(ID, "raster-opacity", opacity);
  }, [map, enabled, opacity]);
}

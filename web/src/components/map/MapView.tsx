"use client";

import "maplibre-gl/dist/maplibre-gl.css";
import {
  AttributionControl,
  Map as MapLibreMap,
  Marker,
  NavigationControl,
  ScaleControl,
  setWorkerUrl,
  type MapMouseEvent,
} from "maplibre-gl";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { readPoint } from "@/lib/api";
import { APP_NAME, BASEMAP_STYLE_URL, LARGE_AREA_KM2 } from "@/lib/config";
import { nearestPlaceName } from "@/lib/geocode";
import { formatArea } from "@/lib/format";
import { activeGroup, layerMode, mapLayersFor } from "@/lib/layers";
import { activeResult, useApp } from "@/lib/store";
import type { BBox } from "@/lib/types";
import { addAnchors, destroyMap } from "./anchors";
import { LayersCard } from "./LayersCard";
import { SpotCard, type SpotState } from "./SpotCard";
import { SwipeHandle } from "./SwipeHandle";
import { addAreaLayers, useAreaLayer } from "./useAreaLayer";
import { useGibsLayer } from "./useGibsLayer";
import { useResultLayers } from "./useResultLayers";

/** MapLibre 6 loads its worker as a separate module; scripts/copy-maplibre-worker.mjs puts it here. */
const WORKER_URL = "/vendor/maplibre-gl-worker.mjs";
const NO_LAYERS: ReturnType<typeof mapLayersFor> = [];
/** Side of the square placed around a clicked spot, in km: big enough to show context, small enough to be fast. */
const PICK_KM = 10;
/** Width of the floating card plus its margins: the map keeps this much clear on a wide screen. */
const CARD_SPACE = 432;

/**
 * The part of the map the card covers, as camera padding: the left on a wide screen, the bottom
 * sheet on a phone. With it, "centred" means centred in the part of the map that can be seen.
 */
function cardPadding(cardOpen: boolean) {
  const wide = window.matchMedia("(min-width: 768px)").matches;
  return {
    top: 0,
    right: 0,
    bottom: cardOpen && !wide ? Math.round(window.innerHeight * 0.5) : 0,
    left: cardOpen && wide ? CARD_SPACE : 0,
  };
}

/** MapLibre GL JS 6 draws with WebGL 2. Checked once so the map area can explain itself when it is missing. */
function webglAvailable(): boolean {
  try {
    return document.createElement("canvas").getContext("webgl2") !== null;
  } catch {
    return false;
  }
}

export default function MapView() {
  const { state, dispatch } = useApp();
  const containerRef = useRef<HTMLDivElement>(null);
  const [map, setMap] = useState<MapLibreMap | null>(null);
  const [supported] = useState(webglAvailable);
  const [tilesReady, setTilesReady] = useState(false);

  useEffect(() => {
    const container = containerRef.current;
    if (!container || !supported) return;
    setWorkerUrl(WORKER_URL);

    let alive = true;
    const instance = new MapLibreMap({
      container,
      style: BASEMAP_STYLE_URL,
      center: [-40, 28],
      zoom: 1.7,
      minZoom: 0.8,
      maxZoom: 16,
      attributionControl: false,
      dragRotate: false,
      pitchWithRotate: false,
      touchPitch: false,
    });

    instance.setPadding(cardPadding(true));
    instance.touchZoomRotate.disableRotation();
    instance.keyboard.disableRotation();
    instance.addControl(new NavigationControl({ showCompass: false }), "top-right");
    instance.addControl(new ScaleControl({ unit: "metric", maxWidth: 120 }), "bottom-right");
    instance.addControl(new AttributionControl({ compact: false }), "bottom-right");
    instance.getCanvas().setAttribute("aria-label", `${APP_NAME} map. Arrow keys pan, plus and minus zoom.`);

    instance.once("style.load", () => {
      if (!alive) return;
      instance.setProjection({ type: "globe" });
      addAnchors(instance);
      addAreaLayers(instance);
      setMap(instance);
    });
    instance.once("idle", () => {
      if (alive) setTilesReady(true);
    });

    // MapLibre only draws inside animation frames, and browsers slow or stop those for a page that is
    // hidden or embedded out of view, which would leave the first, empty frame on screen. While the
    // map still has something to load or is moving, a timer draws it as well.
    const paintWhileHidden = setInterval(() => {
      if (instance.isStyleLoaded() && (document.hidden || !instance.loaded() || instance.isMoving())) instance.redraw();
    }, 400);

    return () => {
      alive = false;
      clearInterval(paintWhileHidden);
      setMap(null);
      destroyMap(instance);
    };
  }, [supported]);

  // ---- area of interest
  const onDrawn = useCallback((bbox: BBox) => dispatch({ type: "area", bbox }), [dispatch]);
  const onCancel = useCallback(() => dispatch({ type: "drawing", drawing: false }), [dispatch]);
  const draftArea = useAreaLayer(map, { bbox: state.bbox, drawing: state.drawing, onDrawn, onCancel });

  // ---- picking a place: before any area exists, a click puts a square around the spot
  const pickable = state.bbox === null && !state.drawing && state.view === "home";
  useEffect(() => {
    if (!map || !pickable) return;
    const canvas = map.getCanvas();
    canvas.style.cursor = "pointer";
    const onClick = (event: MapMouseEvent) => {
      const lon = ((event.lngLat.lng + 540) % 360) - 180;
      const lat = Math.max(-84, Math.min(84, event.lngLat.lat));
      const dLat = PICK_KM / 2 / 111.2;
      const dLon = PICK_KM / 2 / (111.32 * Math.max(0.1, Math.cos((lat * Math.PI) / 180)));
      const bbox: BBox = [lon - dLon, lat - dLat, lon + dLon, lat + dLat];
      dispatch({ type: "area", bbox, placeName: null });
      dispatch({ type: "flyTo", bbox });
      void nearestPlaceName(lon, lat).then((name) => {
        if (name) dispatch({ type: "placeName", placeName: `Near ${name}` });
      });
    };
    map.on("click", onClick);
    return () => {
      map.off("click", onClick);
      canvas.style.cursor = "";
    };
  }, [map, pickable, dispatch]);

  // ---- reference imagery
  useGibsLayer(map, state.gibs);

  // ---- result layers: on the map while a result or the investigation that produced it is being read
  const stored = activeResult(state);
  const display = stored ? state.displays[stored.result.id] : undefined;
  const showResult = stored !== null && display !== undefined && state.view !== "home";
  const layers = useMemo(
    () => (showResult ? mapLayersFor(stored.result, display, stored.source) : NO_LAYERS),
    [showResult, stored, display],
  );
  const group = showResult ? activeGroup(stored.result, display) : [];
  const comparing = showResult && layerMode(stored.result) === "compare" && display.compare;
  useResultLayers(map, layers, display?.swipe ?? 0.5);

  // ---- camera: the area is centred in the part of the map the card does not cover
  const cardOpen = state.panelOpen;
  useEffect(() => {
    if (!map) return;
    const apply = () => map.setPadding(cardPadding(cardOpen));
    apply();
    window.addEventListener("resize", apply);
    return () => window.removeEventListener("resize", apply);
  }, [map, cardOpen]);

  const flyTo = state.flyTo;
  useEffect(() => {
    if (!map || !flyTo) return;
    const [west, south, east, north] = flyTo.bbox;
    const still = document.hidden || window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    map.fitBounds(
      [
        [west, south],
        [east, north],
      ],
      { padding: 56, maxZoom: 13, duration: still ? 0 : 1400 },
    );
  }, [map, flyTo]);

  // ---- reading one spot: click the map while a result is on it
  const [spot, setSpot] = useState<SpotState | null>(null);
  const readableId = showResult && stored.result.status === "ok" && !state.drawing ? stored.result.id : null;
  // A reading belongs to the result it was taken from; switching results hides it without an effect.
  const visibleSpot = spot && spot.resultId === readableId ? spot : null;

  useEffect(() => {
    if (!map || !readableId) return;
    const canvas = map.getCanvas();
    canvas.style.cursor = "crosshair";
    let controller: AbortController | null = null;
    const onClick = (event: MapMouseEvent) => {
      controller?.abort();
      controller = new AbortController();
      const { lng: lon, lat } = event.lngLat;
      const at = { resultId: readableId, lon, lat };
      setSpot({ status: "loading", ...at });
      readPoint(readableId, lon, lat, controller.signal)
        .then((reading) =>
          setSpot(
            reading
              ? { status: "ready", ...at, reading }
              : { status: "error", ...at, message: "Reading a spot needs the live service. This result is sample data." },
          ),
        )
        .catch((error: unknown) => {
          if (error instanceof DOMException && error.name === "AbortError") return;
          const message = error instanceof Error ? error.message : "This spot could not be read.";
          setSpot({ status: "error", ...at, message });
        });
    };
    map.on("click", onClick);
    return () => {
      map.off("click", onClick);
      controller?.abort();
      canvas.style.cursor = "";
    };
  }, [map, readableId]);

  const spotLon = visibleSpot?.lon;
  const spotLat = visibleSpot?.lat;
  useEffect(() => {
    if (!map || spotLon === undefined || spotLat === undefined) return;
    const element = document.createElement("div");
    element.style.cssText =
      "width:16px;height:16px;border-radius:9999px;background:#fff;border:3px solid #191919;box-shadow:0 1px 4px rgba(0,0,0,.35);pointer-events:none";
    const marker = new Marker({ element }).setLngLat([spotLon, spotLat]).addTo(map);
    return () => {
      marker.remove();
    };
  }, [map, spotLon, spotLat]);

  const resultId = stored?.result.id;
  const setSwipe = useCallback(
    (swipe: number) => {
      if (resultId) dispatch({ type: "display", resultId, display: { swipe } });
    },
    [dispatch, resultId],
  );

  return (
    <div className="relative h-full w-full bg-bg">
      {/* MapLibre's stylesheet sets position: relative on this element, so it is sized by height, not by insets. */}
      <div ref={containerRef} className="h-full w-full" />

      {supported ? null : (
        <p className="absolute inset-0 grid place-items-center p-8 text-center text-[15px] text-ink-2 md:pl-[432px]" role="alert">
          The map needs WebGL 2, which this browser or device does not provide. Results, charts and receipts still
          work; enter the area as coordinates.
        </p>
      )}

      {comparing ? (
        <SwipeHandle
          position={display.swipe}
          beforeDate={group[0]?.date ?? null}
          afterDate={group[1]?.date ?? null}
          onChange={setSwipe}
        />
      ) : null}

      {state.drawing || (supported && !tilesReady) ? (
        <p
          className="pointer-events-none absolute top-16 left-3 z-10 w-max max-w-[calc(100%-1.5rem)] rounded-2xl border border-line bg-panel px-4 py-2 text-sm text-ink shadow-card md:top-4 md:left-[calc(50%+216px)] md:max-w-[calc(100%-480px)] md:-translate-x-1/2 md:text-center"
          role="status"
        >
          {!state.drawing ? (
            "Loading map tiles"
          ) : draftArea === null ? (
            "Drag on the map to draw a rectangle. Press Esc to cancel."
          ) : (
            <>
              {formatArea(draftArea)}
              {draftArea > LARGE_AREA_KM2 ? ", a large area: slower to analyse" : null}
            </>
          )}
        </p>
      ) : null}

      {visibleSpot ? (
        <div className="pointer-events-none absolute inset-x-3 top-16 z-20 flex justify-center md:top-auto md:right-auto md:bottom-10 md:left-[444px] md:w-[420px] md:justify-start">
          <SpotCard spot={visibleSpot} onClose={() => setSpot(null)} />
        </div>
      ) : null}

      {/* Under the zoom buttons on a wide screen; in the corner on a phone, where there are none. */}
      <div className="pointer-events-none absolute top-3 right-2.5 z-10 flex max-h-[calc(100%-5rem)] flex-col items-end md:top-[6.25rem] md:max-h-[calc(100%-10rem)]">
        <LayersCard stored={showResult ? stored : null} display={showResult ? display : undefined} layers={layers} />
      </div>
    </div>
  );
}

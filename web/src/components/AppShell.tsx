"use client";

import dynamic from "next/dynamic";
import { useEffect } from "react";
import { APP_NAME } from "@/lib/config";
import { isValidBBox } from "@/lib/geo";
import { AppProvider, useApp } from "@/lib/store";
import type { BBox } from "@/lib/types";
import { useApiCheck, useCoverageLoader } from "@/lib/useActions";
import { DevDataToggle } from "./DevDataToggle";
import { SidePanel } from "./panel/SidePanel";

const MapView = dynamic(() => import("./map/MapView"), {
  ssr: false,
  loading: () => (
    <p className="grid h-full place-items-center text-sm text-ink-3" role="status">
      Loading the map
    </p>
  ),
});

/** A link such as /?bbox=-120.81,50.73,-120.63,50.79&place=Kamloops%20Lake opens with that area chosen. */
function useAreaFromUrl(): void {
  const { dispatch } = useApp();
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const bbox = (params.get("bbox") ?? "").split(",").map(Number) as BBox;
    if (bbox.length !== 4 || !isValidBBox(bbox)) return;
    dispatch({ type: "area", bbox, placeName: params.get("place") });
    dispatch({ type: "flyTo", bbox });
  }, [dispatch]);
}

/** A full-bleed map with one floating card: on a wide screen at the left, on a phone as a bottom sheet. */
function Workspace() {
  const { state, dispatch } = useApp();
  useApiCheck();
  useCoverageLoader();
  useAreaFromUrl();

  return (
    <div className="relative h-dvh overflow-hidden bg-[#fdfcf9]">
      <main className="absolute inset-0" aria-label="Map">
        <MapView />
      </main>

      {state.panelOpen ? (
        <aside
          aria-label={APP_NAME}
          className="absolute inset-x-0 bottom-0 z-20 flex max-h-[62dvh] flex-col overflow-hidden rounded-t-2xl border border-line bg-panel shadow-card md:inset-x-auto md:top-4 md:bottom-auto md:left-4 md:max-h-[calc(100dvh-2rem)] md:w-[460px] md:rounded-2xl"
        >
          <SidePanel />
        </aside>
      ) : (
        <button
          type="button"
          className="press absolute bottom-4 left-4 z-20 rounded-full border border-line bg-panel px-4 py-2.5 text-[15px] text-ink shadow-card hover:bg-raised md:top-4 md:bottom-auto"
          onClick={() => dispatch({ type: "panel", open: true })}
        >
          {APP_NAME}
          <span className="ml-2 text-ink-3">Open</span>
        </button>
      )}

      <DevDataToggle />
    </div>
  );
}

export default function AppShell() {
  return (
    <AppProvider>
      <Workspace />
    </AppProvider>
  );
}

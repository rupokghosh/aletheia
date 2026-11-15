"use client";

import { useEffect, useState } from "react";
import { PlaceSearch } from "@/components/map/PlaceSearch";
import { Button } from "@/components/ui/Button";
import { Notice } from "@/components/ui/Notice";
import { DrawIcon } from "@/components/ui/icons";
import { APP_TAGLINE } from "@/lib/config";
import { plural } from "@/lib/format";
import { loadShowcase, loadShowcaseIndex } from "@/lib/showcases";
import { useApp } from "@/lib/store";
import type { ShowcaseEntry } from "@/lib/types";
import { AreaView } from "./AreaView";
import { CoordinateForm } from "./CoordinateForm";

type IndexState = { status: "loading" } | { status: "ready"; entries: ShowcaseEntry[] } | { status: "error" };

/** Precomputed investigations as plain cards. Says so when there are none. */
function Showcases() {
  const { dispatch } = useApp();
  const [index, setIndex] = useState<IndexState>({ status: "loading" });
  const [opening, setOpening] = useState<string | null>(null);
  const [openError, setOpenError] = useState<string | null>(null);

  const open = async (entry: ShowcaseEntry) => {
    setOpening(entry.id);
    setOpenError(null);
    try {
      dispatch({ type: "investigationOpened", investigation: await loadShowcase(entry), source: "showcase" });
    } catch (error) {
      setOpenError(error instanceof Error ? error.message : "The investigation could not be opened.");
    } finally {
      setOpening(null);
    }
  };

  useEffect(() => {
    const controller = new AbortController();
    loadShowcaseIndex(controller.signal)
      .then(async (entries) => {
        setIndex({ status: "ready", entries });
        // A link such as /?showcase=kamloops opens that investigation directly.
        const wanted = new URLSearchParams(window.location.search).get("showcase");
        const entry = entries.find((item) => item.id === wanted);
        if (entry) {
          const investigation = await loadShowcase(entry, controller.signal);
          dispatch({ type: "investigationOpened", investigation, source: "showcase" });
        }
      })
      .catch((error: unknown) => {
        if (!(error instanceof DOMException && error.name === "AbortError")) setIndex({ status: "error" });
      });
    return () => controller.abort();
  }, [dispatch]);

  return (
    <section aria-labelledby="showcases-title" className="mt-7">
      <h2 id="showcases-title" className="text-[15px] tracking-normal text-ink">
        Worked examples
      </h2>
      <div className="mt-2.5">
        {index.status === "loading" ? (
          <p className="text-sm text-ink-3" role="status">
            Loading
          </p>
        ) : null}
        {index.status === "error" ? <Notice tone="warn">The list of examples could not be loaded.</Notice> : null}
        {index.status === "ready" && index.entries.length === 0 ? (
          <p className="max-w-[65ch] text-sm leading-snug text-ink-3">
            None are published yet. Finished investigations will be listed here, each with its map, results and
            receipt.
          </p>
        ) : null}
        {index.status === "ready" && index.entries.length > 0 ? (
          <ul className="space-y-2.5">
            {index.entries.map((entry) => (
              <li key={entry.id}>
                <button
                  type="button"
                  className="press w-full overflow-hidden rounded-2xl border border-line bg-panel text-left hover:bg-raised disabled:opacity-60"
                  disabled={opening !== null}
                  onClick={() => void open(entry)}
                >
                  {entry.thumbnail ? (
                    // eslint-disable-next-line @next/next/no-img-element -- a small static file; no optimiser needed
                    <img src={entry.thumbnail} alt="" className="aspect-[16/7] w-full border-b border-line object-cover" loading="lazy" />
                  ) : null}
                  <span className="block p-4">
                    <span className="block text-[13px] [overflow-wrap:anywhere] text-ink-3">{entry.place_name}</span>
                    <span className="mt-0.5 block text-[15px] [overflow-wrap:anywhere] text-ink">{entry.title}</span>
                    <span className="mt-1 block text-sm leading-snug [overflow-wrap:anywhere] text-ink-2">{entry.question}</span>
                    {opening === entry.id ? <span className="mt-1.5 block text-[13px] text-ink-3">Opening</span> : null}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        ) : null}
        {openError ? (
          <div className="mt-3">
            <Notice tone="error">{openError}</Notice>
          </div>
        ) : null}
      </div>
    </section>
  );
}

/**
 * The working view. Without an area: what the tool does, a search field, "Draw area" and the
 * worked examples. With one: what NISAR has there, the question box and the analyses.
 */
export function HomeView() {
  const { state, dispatch } = useApp();
  const { bbox, drawing, results, investigation } = state;
  const reading = results.length + (investigation ? 1 : 0);

  return (
    <div className="px-5 pb-6">
      {bbox ? null : <p className="mb-4 max-w-[65ch] text-[17px] leading-snug text-ink">{APP_TAGLINE}</p>}

      <PlaceSearch />
      {bbox ? null : (
        <p className="mt-3 max-w-[65ch] text-[15px] leading-snug text-ink">
          Click anywhere on the map to pick a place, or search for one above.
        </p>
      )}

      {bbox ? (
        <AreaView bbox={bbox} />
      ) : (
        <>
          <details className="mt-2">
            <summary className="w-max text-sm text-ink-2 underline underline-offset-2 hover:text-ink">
              Choose the exact area yourself
            </summary>
            <div className="mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-2">
              <Button variant="secondary" size="sm" aria-pressed={drawing} onClick={() => dispatch({ type: "drawing", drawing: !drawing })}>
                <DrawIcon />
                {drawing ? "Cancel drawing" : "Draw a rectangle"}
              </Button>
              {drawing ? <p className="text-sm text-ink-3">Drag on the map.</p> : null}
            </div>
            <CoordinateForm bbox={null} />
          </details>
          <Showcases />
        </>
      )}

      {reading > 0 ? (
        <button
          type="button"
          className="mt-6 text-sm text-ink underline underline-offset-2"
          onClick={() => dispatch({ type: "view", view: investigation ? state.reading : "results" })}
        >
          Back to {reading === 1 ? "the result" : `the ${plural(reading, "result")}`} from this session
        </button>
      ) : null}
    </div>
  );
}

"use client";

import { useEffect, useRef } from "react";
import { InvestigationView } from "@/components/investigate/InvestigationView";
import { ResultsView } from "@/components/results/ResultsView";
import { ChevronDownIcon } from "@/components/ui/icons";
import { API_BASE, checkApi } from "@/lib/api";
import { APP_NAME } from "@/lib/config";
import { useApp } from "@/lib/store";
import { useApiMode } from "@/lib/useActions";
import { HomeView } from "./HomeView";

/** Says plainly, at the top of the card, that nothing on screen is a live result. */
function DemoNote() {
  const mode = useApiMode();
  if (!mode.demo) return null;
  return (
    <p className="mx-5 mb-1 rounded-xl bg-raised px-3.5 py-2.5 text-sm leading-snug text-ink-2" role="status">
      <span className="mr-2 inline-block size-2 rounded-full bg-purple align-middle" aria-hidden="true" />
      <span className="text-ink">Sample data mode.</span> Nothing shown is a live result.{" "}
      {mode.reason === "unreachable" ? (
        <>
          The API at <span className="[overflow-wrap:anywhere]">{API_BASE}</span> did not answer.{" "}
          <button type="button" className="text-ink underline underline-offset-2" onClick={() => void checkApi()}>
            Try again
          </button>
        </>
      ) : (
        "No API address is set for this site."
      )}
    </p>
  );
}

const ICON_BUTTON = "press grid size-9 place-items-center rounded-full text-ink-2 hover:bg-raised hover:text-ink";

export function SidePanel() {
  const { state, dispatch } = useApp();
  const { view, activeResultId } = state;
  const scrollRef = useRef<HTMLDivElement>(null);

  // A new view or a newly opened result starts at its top.
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: 0 });
  }, [view, activeResultId]);

  return (
    <>
      <header className="flex shrink-0 items-center justify-between gap-2 py-3 pr-3 pl-5">
        <button
          type="button"
          className="flex items-center gap-2 rounded-md text-[19px] tracking-tight text-ink"
          onClick={() => dispatch({ type: "view", view: "home" })}
          aria-label={`${APP_NAME}: back to the start`}
        >
          {/* A disc coming out from behind another: un-hiddenness, which is what the name means. */}
          <svg width="20" height="20" viewBox="0 0 20 20" aria-hidden="true">
            <circle cx="10" cy="10" r="9" fill="var(--ink)" />
            <circle cx="13.2" cy="7.4" r="6.2" fill="var(--panel)" />
            <circle cx="13.2" cy="7.4" r="2.6" fill="var(--blue)" />
          </svg>
          {APP_NAME}
        </button>
        <button type="button" className={ICON_BUTTON} aria-label="Hide this panel" title="Hide this panel" onClick={() => dispatch({ type: "panel", open: false })}>
          <ChevronDownIcon width={18} height={18} className="md:rotate-90" />
        </button>
      </header>

      <div ref={scrollRef} className="scroll-quiet min-h-0 flex-1 overflow-y-auto">
        <DemoNote />
        {view === "home" ? <HomeView /> : null}
        {view === "investigation" ? <InvestigationView /> : null}
        {view === "results" ? <ResultsView /> : null}
        <p className="px-5 pb-4 text-xs text-ink-3">Data: NASA-ISRO NISAR via the Alaska Satellite Facility</p>
      </div>
    </>
  );
}

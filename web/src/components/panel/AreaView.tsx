"use client";

import { useMemo } from "react";
import { Button } from "@/components/ui/Button";
import { Notice } from "@/components/ui/Notice";
import { SourceBadge } from "@/components/ui/SourceBadge";
import { LARGE_AREA_KM2 } from "@/lib/config";
import { stackViews, summarizeCoverage, type StackView } from "@/lib/coverage";
import { formatArea, formatMonthSpan, plural } from "@/lib/format";
import { bboxAreaKm2, bboxKey } from "@/lib/geo";
import { useApp, type AnalysisTab } from "@/lib/store";
import { useActions, useApiMode } from "@/lib/useActions";
import type { BBox, WorkflowKind } from "@/lib/types";
import { AskForm } from "./AskForm";
import { ChangeForm } from "./ChangeForm";
import { CoordinateForm } from "./CoordinateForm";
import { CoverageDetails } from "./CoverageDetails";
import { MotionForm } from "./MotionForm";
import { RunProgress } from "./RunProgress";
import { TimeSeriesForm } from "./TimeSeriesForm";

const ANALYSES: Array<{ id: WorkflowKind; label: string; about: string }> = [
  {
    id: "change",
    label: "See what changed between two dates",
    about: "A map of where the ground looks different to the radar, and how much area changed. Good for floods, water levels, logging and burns.",
  },
  {
    id: "timeseries",
    label: "See how it behaved over time",
    about: "A chart of radar brightness on every date NISAR has here, with the radar picture for each date. Good for seasons, and for finding when something happened.",
  },
  {
    id: "motion",
    label: "See if the ground moved",
    about: "A map of ground movement in centimetres between two passes 12 days apart. Good for earthquakes, volcanoes and fast sinking.",
  },
];

/** The place and its size on one line, with the ways to change it. */
function AreaLine({ bbox }: { bbox: BBox }) {
  const { state, dispatch } = useApp();
  const area = bboxAreaKm2(bbox);
  return (
    <div className="mt-4">
      <p className="text-[17px] leading-snug [overflow-wrap:anywhere] text-ink">
        {state.placeName ? `${state.placeName}, ` : ""}
        {formatArea(area)}
      </p>
      <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-sm">
        <button type="button" className="text-ink-2 underline underline-offset-2 hover:text-ink" aria-pressed={state.drawing} onClick={() => dispatch({ type: "drawing", drawing: !state.drawing })}>
          {state.drawing ? "Cancel drawing" : "Redraw"}
        </button>
        <button type="button" className="text-ink-2 underline underline-offset-2 hover:text-ink" onClick={() => dispatch({ type: "flyTo", bbox })}>
          Zoom to it
        </button>
        <button type="button" className="text-ink-2 underline underline-offset-2 hover:text-ink" onClick={() => dispatch({ type: "clearArea" })}>
          Clear
        </button>
      </div>
      <details className="mt-1">
        <summary className="w-max text-sm text-ink-2 underline underline-offset-2 hover:text-ink">Coordinates</summary>
        <CoordinateForm key={bboxKey(bbox)} bbox={bbox} />
      </details>
      {area > LARGE_AREA_KM2 ? (
        <div className="mt-3">
          <Notice tone="warn">
            This is a large area: above {LARGE_AREA_KM2} km², more of each file has to be read. A smaller rectangle
            around what you care about gives a sharper answer.
          </Notice>
        </div>
      ) : null}
    </div>
  );
}

/** One plain sentence on what NISAR has here, with the per-track detail behind "Details". */
function CoverageLine({ bbox, views }: { bbox: BBox; views: StackView[] }) {
  const { state, dispatch } = useApp();
  const { coverage } = state;

  if (coverage.status === "loading" || coverage.status === "idle") {
    return (
      <div className="mt-5" role="status">
        <p className="text-[15px] text-ink-2">Checking what NISAR has here</p>
        <div className="mt-2.5 h-1 overflow-hidden rounded-full bg-raised-2">
          <div className="sweep h-full w-2/5 rounded-full bg-ink" />
        </div>
      </div>
    );
  }

  if (coverage.status === "error") {
    return (
      <div className="mt-5 space-y-3">
        <Notice tone="error" title="The search of NASA's catalogue failed">
          {coverage.error}
        </Notice>
        <Button size="sm" onClick={() => dispatch({ type: "area", bbox: [...bbox] })}>
          Try again
        </Button>
      </div>
    );
  }

  const summary = summarizeCoverage(views);
  return (
    <div className="mt-5">
      {coverage.source === "demo" ? (
        <div className="mb-2">
          <SourceBadge source={coverage.source} />
        </div>
      ) : null}
      <p className="max-w-[65ch] text-[15px] leading-snug text-ink">
        {summary
          ? `NISAR has ${plural(summary.dates, "usable date")} here, ${formatMonthSpan(summary.first, summary.last)}, on ${plural(summary.tracks, "track")}.`
          : "NISAR has no radar images of this area yet. Not every part of the planet has been processed and released: try a larger rectangle or another place."}
      </p>
      {coverage.data && views.length > 0 ? (
        <details className="mt-1.5">
          <summary className="w-max text-sm text-ink-2 underline underline-offset-2 hover:text-ink">Details</summary>
          <CoverageDetails coverage={coverage.data} views={views} linked={coverage.source !== "demo"} />
        </details>
      ) : null}
    </div>
  );
}

/** With an area chosen: what NISAR has there, the question box, and the three analyses. */
export function AreaView({ bbox }: { bbox: BBox }) {
  const { state, dispatch } = useApp();
  const actions = useActions();
  const mode = useApiMode();
  const { coverage, analysisTab, run } = state;
  const views = useMemo(() => (coverage.data ? stackViews(coverage.data, bbox) : []), [coverage.data, bbox]);
  const ready = coverage.status === "ready" && coverage.data !== null;
  const choose = (tab: AnalysisTab) => dispatch({ type: "analysisTab", tab: tab === analysisTab ? "ask" : tab });
  // What exists here for each choice, so nobody has to open one to find out it is empty.
  const summary = useMemo(() => summarizeCoverage(views), [views]);
  const pairs = useMemo(() => {
    const motion = views.filter((view) => view.isPair && view.stack.product === "GUNW");
    return new Set(motion.flatMap((view) => view.marks.map((mark) => `${view.key}|${mark.date}`))).size;
  }, [views]);
  const available: Record<WorkflowKind, string | null> = {
    change: summary && summary.dates >= 2 ? `${plural(summary.dates, "date")} to choose from` : null,
    timeseries: summary ? `${plural(summary.dates, "date")}, ${formatMonthSpan(summary.first, summary.last)}` : null,
    motion: pairs > 0 ? `${plural(pairs, "pair")} of passes` : null,
  };

  return (
    <>
      <AreaLine bbox={bbox} />
      <CoverageLine bbox={bbox} views={views} />

      <section className="mt-6" aria-label="Analyses">
        <h2 className="text-[15px] tracking-normal text-ink">What do you want to know?</h2>
        <ul className="mt-2.5 space-y-2">
          {ANALYSES.map((item) => {
            const open = item.id === analysisTab;
            return (
              <li key={item.id} className={`rounded-2xl border bg-panel ${open ? "border-line-strong" : "border-line"}`}>
                <button
                  type="button"
                  className="press w-full rounded-2xl p-3.5 text-left hover:bg-raised"
                  aria-expanded={open}
                  onClick={() => choose(item.id)}
                >
                  <span className="block text-[15px] text-ink">{item.label}</span>
                  <span className="mt-0.5 block text-sm leading-snug text-ink-2">{item.about}</span>
                  {ready ? (
                    <span className={`mt-1.5 block text-[13px] ${available[item.id] ? "text-[#007a41]" : "text-ink-3"}`}>
                      {available[item.id] ? `Available here: ${available[item.id]}` : "NISAR has nothing for this here yet"}
                    </span>
                  ) : null}
                </button>
                {open ? (
                  <div className="border-t border-line p-3.5">
                    {!ready ? (
                      <Notice>Dates can be chosen once the search above has finished.</Notice>
                    ) : run.status === "running" ? (
                      <RunProgress description={run.description} demo={mode.demo} onCancel={actions.cancelRun} />
                    ) : (
                      <>
                        {run.status === "error" && run.error ? (
                          <div className="mb-3">
                            <Notice tone="error" title="The analysis did not complete">
                              {run.error}
                            </Notice>
                          </div>
                        ) : null}
                        {item.id === "change" ? <ChangeForm bbox={bbox} views={views} /> : null}
                        {item.id === "timeseries" ? <TimeSeriesForm bbox={bbox} views={views} /> : null}
                        {item.id === "motion" ? <MotionForm bbox={bbox} views={views} /> : null}
                      </>
                    )}
                  </div>
                ) : null}
              </li>
            );
          })}
        </ul>
      </section>

      <section className="mt-6" aria-label="Ask a question">
        <h2 className="text-[15px] tracking-normal text-ink">Or ask in your own words</h2>
        <p className="mt-0.5 mb-2.5 max-w-[65ch] text-sm leading-snug text-ink-2">
          The tool picks the analyses, runs them and writes up what it found, with its sources.
        </p>
        <AskForm bbox={bbox} />
      </section>
    </>
  );
}

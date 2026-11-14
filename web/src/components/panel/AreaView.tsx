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
  { id: "change", label: "Change", about: "Compares two dates and maps what changed between them." },
  { id: "timeseries", label: "Time series", about: "The radar brightness of the whole area on every date." },
  { id: "motion", label: "Ground motion", about: "How far the ground moved towards or away from the satellite between two dates." },
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
            This is a large area. Above {LARGE_AREA_KM2} km² an analysis takes longer, because more of each file is
            read. A smaller rectangle around what you care about is faster and sharper.
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
      {coverage.source && coverage.source !== "live" ? (
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
  const chosen = ANALYSES.find((item) => item.id === analysisTab);
  const choose = (tab: AnalysisTab) => dispatch({ type: "analysisTab", tab: tab === analysisTab ? "ask" : tab });

  return (
    <>
      <AreaLine bbox={bbox} />
      <CoverageLine bbox={bbox} views={views} />

      <div className="mt-6">
        <AskForm bbox={bbox} />
      </div>

      <div className="mt-6">
        <p className="text-sm text-ink-2">or run an analysis</p>
        <div role="group" aria-label="Analyses" className="mt-2 flex flex-wrap gap-2">
          {ANALYSES.map((item) => (
            <Button
              key={item.id}
              size="sm"
              variant={item.id === analysisTab ? "primary" : "secondary"}
              aria-pressed={item.id === analysisTab}
              onClick={() => choose(item.id)}
            >
              {item.label}
            </Button>
          ))}
        </div>

        {chosen ? (
          <div className="mt-4">
            <p className="mb-3 max-w-[65ch] text-sm leading-snug text-ink-2">{chosen.about}</p>
            {!ready ? (
              <Notice>Dates can be chosen once the search above has finished.</Notice>
            ) : run.status === "running" ? (
              <RunProgress description={run.description} startedAt={run.startedAt} demo={mode.demo} onCancel={actions.cancelRun} />
            ) : (
              <>
                {run.status === "error" && run.error ? (
                  <div className="mb-3">
                    <Notice tone="error" title="The analysis did not complete">
                      {run.error}
                    </Notice>
                  </div>
                ) : null}
                {chosen.id === "change" ? <ChangeForm bbox={bbox} views={views} /> : null}
                {chosen.id === "timeseries" ? <TimeSeriesForm bbox={bbox} views={views} /> : null}
                {chosen.id === "motion" ? <MotionForm bbox={bbox} views={views} /> : null}
              </>
            )}
          </div>
        ) : null}
      </div>
    </>
  );
}

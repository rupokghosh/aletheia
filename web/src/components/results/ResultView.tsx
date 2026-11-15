"use client";

import { Button } from "@/components/ui/Button";
import { Disclosure } from "@/components/ui/Disclosure";
import { Notice } from "@/components/ui/Notice";
import { SourceBadge } from "@/components/ui/SourceBadge";
import { TargetIcon } from "@/components/ui/icons";
import { formatSeconds, plural, prettyUnits } from "@/lib/format";
import { boundsOf } from "@/lib/geo";
import { useApp, type StoredResult } from "@/lib/store";
import type { WorkflowKind } from "@/lib/types";
import { Downloads } from "./Downloads";
import { EffortStrip } from "./EffortStrip";
import { MetricRange, SingleValues, splitMetrics } from "./MetricRange";
import { ReceiptSection } from "./ReceiptSection";
import { SeriesChart } from "./SeriesChart";
import { StatsTable } from "./StatsTable";
import { UncertaintySection } from "./UncertaintySection";

export const WORKFLOW_NAMES: Record<WorkflowKind, string> = {
  change: "Change between two dates",
  timeseries: "Time series",
  motion: "Ground motion",
};

function Kicker({ stored }: { stored: StoredResult }) {
  return (
    <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1.5">
      <p className="text-sm text-ink-2">{WORKFLOW_NAMES[stored.result.workflow]}</p>
      <SourceBadge source={stored.source} />
    </div>
  );
}

/** "Not supported yet" is an answer, not a failure: it is stated plainly, with the reason. */
function Unsupported({ stored }: { stored: StoredResult }) {
  const { result } = stored;
  // The heading already says "Not supported yet", so a headline that opens with the same words is trimmed.
  const reason = prettyUnits(result.summary.headline).replace(/^\s*not supported yet[\s:.,-]*/i, "");
  return (
    <div className="px-5 pb-6">
      <Kicker stored={stored} />
      <h2 className="mt-2 text-2xl text-ink">Not supported yet</h2>
      <p className="mt-2.5 max-w-[65ch] text-[15px] leading-snug [overflow-wrap:anywhere] text-ink">
        {reason.charAt(0).toUpperCase() + reason.slice(1)}
      </p>
      {result.caveats.length > 0 ? (
        <ul className="mt-3 max-w-[65ch] space-y-2 text-sm leading-snug [overflow-wrap:anywhere] text-ink-2">
          {result.caveats.map((caveat) => (
            <li key={caveat.code}>{caveat.text}</li>
          ))}
        </ul>
      ) : null}
      <p className="mt-4 max-w-[65ch] text-sm leading-snug text-ink-3">
        Nothing was measured, so there are no numbers, map layers or downloads for this request.
      </p>
    </div>
  );
}

/**
 * One result: the headline sentence, at most two ranges, the chart if there is one, and then rows
 * that open for everything else. Its map layers are controlled from the card on the map.
 */
export function ResultView({ stored }: { stored: StoredResult }) {
  const { dispatch } = useApp();
  const { result, source } = stored;

  if (result.status === "unsupported") return <Unsupported stored={stored} />;

  if (result.status === "error") {
    return (
      <div className="space-y-3 px-5 pb-6">
        <Kicker stored={stored} />
        <Notice tone="error" title="This analysis failed">
          {result.summary.headline}
        </Notice>
      </div>
    );
  }

  const { receipt, uncertainty } = result;
  const { lead, moreRanges, single } = splitMetrics(result.summary.metrics);
  const extent = boundsOf(result.layers.flatMap((layer) => layer.corners));
  const statCount = Object.keys(result.stats).length;
  const moreCount = moreRanges.length + single.length;
  const seconds = receipt.steps.reduce((sum, step) => sum + (step.seconds ?? 0), 0);
  const headline = prettyUnits(result.summary.headline);

  return (
    <article aria-label={`${WORKFLOW_NAMES[result.workflow]} result`} className="px-5 pb-4">
      <Kicker stored={stored} />
      <h2 className={`mt-2 max-w-[65ch] [overflow-wrap:anywhere] text-ink ${headline.length > 160 ? "text-lg leading-snug tracking-tight" : "text-2xl"}`}>
        {headline}
      </h2>
      {source !== "live" ? (
        <div className="mt-3">
          <SourceBadge source={source} detailed />
        </div>
      ) : null}

      <EffortStrip stats={result.stats} />

      {lead.length > 0 ? (
        <div className="mt-6 space-y-5">
          {lead.map((metric) => (
            <MetricRange key={metric.key} metric={metric} />
          ))}
        </div>
      ) : null}

      {result.series.length > 0 ? (
        <div className="mt-6">
          <SeriesChart series={result.series} />
        </div>
      ) : null}

      {extent ? (
        <Button size="sm" className="mt-5" onClick={() => dispatch({ type: "flyTo", bbox: extent })}>
          <TargetIcon />
          Show on the map
        </Button>
      ) : null}

      <div className="mt-6">
        {moreCount > 0 || statCount > 0 ? (
          <Disclosure title="More numbers" summary={moreCount > 0 ? plural(moreCount, "value") : undefined}>
            <div className="space-y-5">
              {moreRanges.map((metric) => (
                <MetricRange key={metric.key} metric={metric} />
              ))}
              {single.length > 0 ? <SingleValues metrics={single} /> : null}
              {statCount > 0 ? (
                <details>
                  <summary className="w-max text-sm text-ink-2 underline underline-offset-2 hover:text-ink">All statistics</summary>
                  <div className="mt-3">
                    <StatsTable stats={result.stats} />
                  </div>
                </details>
              ) : null}
            </div>
          </Disclosure>
        ) : null}

        {uncertainty ? (
          <Disclosure title="How sure is this?">
            <UncertaintySection uncertainty={uncertainty} workflow={result.workflow} />
          </Disclosure>
        ) : null}

        {result.caveats.length > 0 ? (
          <Disclosure title="Caveats" summary={String(result.caveats.length)}>
            <ul className="max-w-[65ch] space-y-3">
              {result.caveats.map((caveat) => (
                <li key={caveat.code} className="text-sm leading-snug [overflow-wrap:anywhere] text-ink">
                  {caveat.text}
                </li>
              ))}
            </ul>
          </Disclosure>
        ) : null}

        <Disclosure
          title="Sources and receipt"
          summary={[plural(receipt.granules.length, "file"), plural(receipt.steps.length, "step"), seconds > 0 ? formatSeconds(seconds) : null]
            .filter(Boolean)
            .join(", ")}
        >
          <ReceiptSection result={result} source={source} />
        </Disclosure>

        {result.downloads.length > 0 ? (
          <Disclosure title="Downloads" summary={String(result.downloads.length)}>
            <Downloads downloads={result.downloads} source={source} />
          </Disclosure>
        ) : null}
      </div>
    </article>
  );
}

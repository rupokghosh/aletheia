"use client";

import { TierBadge, TierMark } from "@/components/ui/Tier";
import { coversArea, type StackView } from "@/lib/coverage";
import { formatDate, plural, shortenMiddle } from "@/lib/format";
import { TIERS, TIER_ORDER } from "@/lib/tiers";
import { useApp } from "@/lib/store";
import type { Coverage, Granule } from "@/lib/types";
import { CoverageTimeline } from "./CoverageTimeline";

/** Products an analysis here can read. Others (soil moisture) are listed with the other tracks. */
const ANALYSED = ["GCOV", "GUNW"];

function granuleDate(granule: Granule): string {
  return granule.reference_date
    ? `${formatDate(granule.reference_date)} to ${formatDate(granule.secondary_date)}`
    : formatDate(granule.date);
}

function GranuleTable({ coverage, linked }: { coverage: Coverage; linked: boolean }) {
  const granules = Object.values(coverage.products)
    .flat()
    .sort((a, b) => (a.start_time ?? "").localeCompare(b.start_time ?? ""));
  return (
    <div className="scroll-quiet mt-2 max-h-72 overflow-auto rounded-xl border border-line" tabIndex={0} role="group" aria-label="Files, scrolls">
      <table className="w-full min-w-[34rem] border-collapse text-left text-[13px]">
        <thead className="sticky top-0 bg-raised text-ink-2">
          <tr>
            {["Date (UTC)", "Product", "Track", "Channels", "Tier", "File"].map((heading) => (
              <th key={heading} scope="col" className="px-2.5 py-2 font-normal whitespace-nowrap">
                {heading}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {granules.map((granule) => (
            <tr key={granule.granule_id} className="border-t border-line text-ink">
              <td className="px-2.5 py-1.5 whitespace-nowrap">{granuleDate(granule)}</td>
              <td className="px-2.5 py-1.5">{granule.product}</td>
              <td className="px-2.5 py-1.5 whitespace-nowrap">
                {granule.track} {granule.direction === "ascending" ? "asc." : "desc."}, frame {granule.frame}
              </td>
              <td className="px-2.5 py-1.5 whitespace-nowrap">{granule.polarizations.join(" ") || "n/a"}</td>
              <td className="px-2.5 py-1.5">
                <TierBadge tier={granule.tier} />
              </td>
              <td className="px-2.5 py-1.5 font-mono text-xs whitespace-nowrap text-ink-2" title={granule.granule_id}>
                {linked ? (
                  <a className="underline underline-offset-2 hover:text-ink" href={granule.url} target="_blank" rel="noreferrer">
                    {shortenMiddle(granule.granule_id, 16, 14)}
                  </a>
                ) : (
                  shortenMiddle(granule.granule_id, 16, 14)
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

interface CoverageDetailsProps {
  coverage: Coverage;
  /** stacks, best first */
  views: StackView[];
  /** false for sample data, whose files do not exist */
  linked: boolean;
}

/**
 * What is behind the one-sentence summary: a timeline per track, the tracks that only clip the
 * area, the calibration tiers, the notes from the catalogue and the list of files.
 */
export function CoverageDetails({ coverage, views, linked }: CoverageDetailsProps) {
  const { state } = useApp();
  const { analysisTab, selection } = state;
  const main = views.filter((view) => ANALYSED.includes(view.stack.product) && coversArea(view));
  const chosenElsewhere = views.find((view) => view.key === selection.stackKey && !main.includes(view));
  const shown = main.length > 0 ? (chosenElsewhere ? [...main, chosenElsewhere] : main) : views;
  const others = views.filter((view) => !shown.includes(view));
  const total = views.reduce((sum, view) => sum + view.marks.length, 0);

  const hint =
    analysisTab === "change"
      ? "Select two dates on one radar-brightness row: the earlier becomes before, the later after."
      : analysisTab === "motion"
        ? "Select a ground-motion pair."
        : null;

  return (
    <div className="mt-3">
      <p className="max-w-[65ch] text-sm leading-snug text-ink-2">
        Each row is one track of the satellite. Dates on the same row line up pixel for pixel, so they can be
        compared directly.
      </p>
      {hint ? <p className="mt-1.5 text-sm text-ink">{hint}</p> : null}

      <div className="mt-3">
        <CoverageTimeline views={shown} />
      </div>

      <ul className="mt-2.5 flex flex-wrap gap-x-4 gap-y-1 text-[13px] text-ink-2" aria-label="Calibration tiers">
        {TIER_ORDER.map((tier) => (
          <li key={tier} className="flex items-center gap-1.5" title={TIERS[tier].meaning}>
            <TierMark tier={tier} />
            {TIERS[tier].label}
          </li>
        ))}
      </ul>

      {coverage.notes.length > 0 ? (
        <ul className="mt-3 max-w-[65ch] space-y-1.5 text-sm leading-snug [overflow-wrap:anywhere] text-ink-2">
          {coverage.notes.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      ) : null}

      {others.length > 0 ? (
        <details className="mt-3">
          <summary className="w-max text-sm text-ink-2 underline underline-offset-2 hover:text-ink">
            Other tracks ({others.length})
          </summary>
          <p className="mt-2 max-w-[65ch] text-sm leading-snug text-ink-2">
            Tracks that only clip the edge of the area, and products no analysis here reads. An analysis on a
            track that clips the area is usually declined.
          </p>
          <div className="mt-2.5">
            <CoverageTimeline views={others} />
          </div>
        </details>
      ) : null}

      <details className="mt-2">
        <summary className="w-max text-sm text-ink-2 underline underline-offset-2 hover:text-ink">
          {total === 1 ? "The file" : `All ${plural(total, "file")}`}
        </summary>
        <GranuleTable coverage={coverage} linked={linked} />
      </details>
    </div>
  );
}

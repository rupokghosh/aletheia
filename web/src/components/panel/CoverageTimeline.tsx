"use client";

import { useEffect, useRef } from "react";
import { TierShape } from "@/components/ui/Tier";
import { PRODUCT_NAMES, coverageSpan, resolveChange, type StackMark, type StackView } from "@/lib/coverage";
import { dayNumber, formatDate, formatPercent, isoFromDayNumber, plural } from "@/lib/format";
import { monthTicks } from "@/lib/scale";
import { TIERS } from "@/lib/tiers";
import { useApp } from "@/lib/store";
import { useElementWidth } from "@/lib/useElementWidth";

const PAD = 22;
const MIN_PX_PER_DAY = 2.2;
const LANE_HEIGHT = 30;

function markLabel(mark: StackMark): string {
  const tier = TIERS[mark.tier].label.toLowerCase();
  return mark.secondaryDate
    ? `Pair ${formatDate(mark.date)} to ${formatDate(mark.secondaryDate)}, ${tier}`
    : `${formatDate(mark.date)}, ${tier}`;
}

/**
 * Tracks as rows on one shared time axis. Position is proportional to time, so gaps in the record
 * show as empty stretches. Marks are buttons only when the open analysis needs a date.
 */
export function CoverageTimeline({ views }: { views: StackView[] }) {
  const { state, dispatch } = useApp();
  const { analysisTab, selection } = state;
  const scrollerRef = useRef<HTMLDivElement>(null);
  const available = useElementWidth(scrollerRef);
  const span = coverageSpan(views);
  // The dates the change form shows, including its defaults before anything has been chosen.
  const change = analysisTab === "change" ? resolveChange(views, selection) : null;

  const days = span ? Math.max(1, span.end - span.start) : 1;
  const pxPerDay = Math.max(MIN_PX_PER_DAY, (available - PAD * 2) / days);
  const width = Math.max(available, days * pxPerDay + PAD * 2);
  const x = (iso: string) => PAD + (dayNumber(iso) - (span?.start ?? 0)) * pxPerDay;

  // Start at the most recent dates.
  useEffect(() => {
    const scroller = scrollerRef.current;
    if (scroller && available > 0) scroller.scrollLeft = scroller.scrollWidth;
  }, [available, views]);

  if (!span) return null;
  const ticks = monthTicks(span.start, span.end);

  return (
    <div
      ref={scrollerRef}
      className="scroll-quiet overflow-x-auto rounded-xl border border-line"
      role="group"
      aria-label={`Timeline of dates, ${formatDate(isoFromDayNumber(span.start))} to ${formatDate(isoFromDayNumber(span.end))}`}
      tabIndex={width > available ? 0 : undefined}
    >
      <div className="relative" style={{ width }}>
        <div className="relative h-7 border-b border-line" aria-hidden="true">
          {ticks.map((tick) => (
            <span
              key={tick.day}
              className="absolute top-0 h-full border-l border-line pt-1.5 pl-1.5 text-[11px] whitespace-nowrap text-ink-3"
              style={{ left: PAD + (tick.day - span.start) * pxPerDay }}
            >
              {tick.label}
            </span>
          ))}
        </div>

        {views.map((view) => {
          const selectable =
            (analysisTab === "change" && view.stack.product === "GCOV") ||
            (analysisTab === "motion" && view.stack.product === "GUNW");
          const inChange = change?.view.key === view.key;
          return (
            <div key={view.key} className="border-b border-line last:border-b-0">
              {/* No wider than the visible part, so it stays fully in view while the dates scroll under it. */}
              <p className="sticky left-0 w-max px-3 pt-2.5 text-[13px] leading-snug" style={{ maxWidth: available || undefined }}>
                <span className="text-ink">
                  Track {view.stack.track}, {view.stack.direction}
                </span>
                <span className="ml-2 text-ink-3">
                  {PRODUCT_NAMES[view.stack.product] ?? view.stack.product}, {plural(view.marks.length, view.isPair ? "pair" : "date")}, frame{" "}
                  {view.stack.frame}
                  {view.stack.polarizations.length > 0 ? `, ${view.stack.polarizations.join(" ")}` : ""}
                </span>
                {view.areaShare !== null && view.areaShare < 0.995 ? (
                  <span className="block text-ink-2" title="The usable part can be smaller: a footprint includes the empty margins of a frame.">
                    Covers {formatPercent(view.areaShare)} of the area at most
                  </span>
                ) : null}
              </p>

              <div className="relative mt-3 mb-2" style={{ height: view.lanes * LANE_HEIGHT }}>
                {ticks.map((tick) => (
                  <span
                    key={tick.day}
                    className="absolute inset-y-0 border-l border-line"
                    style={{ left: PAD + (tick.day - span.start) * pxPerDay }}
                    aria-hidden="true"
                  />
                ))}

                {view.gaps.map((gap) => {
                  const left = x(gap.from) + 10;
                  const gapWidth = x(gap.to) - x(gap.from) - 20;
                  return (
                    <span
                      key={gap.from}
                      className="absolute top-1/2 flex h-5 -translate-y-1/2 items-center justify-center overflow-hidden border-y border-dashed border-line-strong text-[11px] whitespace-nowrap text-ink-3"
                      style={{ left, width: Math.max(0, gapWidth) }}
                      title={`No images between ${formatDate(gap.from)} and ${formatDate(gap.to)}`}
                    >
                      {gapWidth > 110 ? `no images, ${plural(gap.days, "day")}` : gapWidth > 40 ? `${gap.days} d` : ""}
                    </span>
                  );
                })}

                {view.marks.map((mark) => {
                  const top = mark.lane * LANE_HEIGHT;
                  const left = x(mark.date);
                  const isBefore = inChange && change?.before === mark.date;
                  const isAfter = inChange && change?.after === mark.date;
                  const chosen = analysisTab === "change" ? isBefore || isAfter : analysisTab === "motion" && selection.pairId === mark.granule.granule_id;
                  const label = markLabel(mark);
                  const shape = (
                    <svg width="20" height="20" viewBox="-10 -10 20 20" aria-hidden="true" focusable="false">
                      {chosen ? <circle r="9" fill="none" stroke="var(--ink)" strokeWidth="1.75" /> : null}
                      <TierShape tier={mark.tier} r={4.5} />
                    </svg>
                  );
                  return (
                    <span key={mark.granule.granule_id}>
                      {mark.secondaryDate ? (
                        <span
                          className="absolute h-1 rounded-full opacity-50"
                          style={{
                            left,
                            top: top + LANE_HEIGHT / 2 - 2,
                            width: Math.max(2, x(mark.secondaryDate) - left),
                            background: TIERS[mark.tier].color,
                          }}
                          aria-hidden="true"
                        />
                      ) : null}
                      {selectable ? (
                        <button
                          type="button"
                          className="absolute grid -translate-x-1/2 place-items-center rounded-full hover:bg-raised-2"
                          style={{ left, top: top + 1, width: 26, height: LANE_HEIGHT - 2 }}
                          aria-label={`${label}${isBefore ? ", chosen as before" : ""}${isAfter ? ", chosen as after" : ""}`}
                          aria-pressed={chosen}
                          title={label}
                          onClick={() =>
                            analysisTab === "change"
                              ? dispatch({ type: "pickDate", stackKey: view.key, date: mark.date })
                              : dispatch({ type: "select", selection: { pairId: mark.granule.granule_id } })
                          }
                        >
                          {shape}
                        </button>
                      ) : (
                        <span
                          className="absolute grid -translate-x-1/2 place-items-center"
                          style={{ left, top: top + 1, width: 20, height: LANE_HEIGHT - 2 }}
                          title={label}
                          role="img"
                          aria-label={label}
                        >
                          {shape}
                        </span>
                      )}
                      {isBefore || isAfter ? (
                        <span
                          className="pointer-events-none absolute -translate-x-1/2 rounded-full bg-ink px-1.5 text-[10px] leading-4 text-white"
                          style={{ left, top: top - 10 }}
                          aria-hidden="true"
                        >
                          {isBefore ? "Before" : "After"}
                        </span>
                      ) : null}
                    </span>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

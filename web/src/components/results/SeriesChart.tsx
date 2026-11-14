"use client";

import { useMemo, useRef, useState } from "react";
import { dayNumber, decimalsFor, formatDate, formatNumber, formatUnit, shortenMiddle } from "@/lib/format";
import { monthTicks, niceTicks, thin } from "@/lib/scale";
import { TIERS, TIER_ORDER } from "@/lib/tiers";
import type { Series, SeriesPoint, Tier } from "@/lib/types";
import { useElementWidth } from "@/lib/useElementWidth";

const HEIGHT = 264;
const MARGIN = { top: 14, right: 16, bottom: 30, left: 48 };
/** Black and blue first, as thin lines; purple and green for a third and fourth series. Beyond that, dashes. */
const COLORS = ["var(--series-1)", "var(--series-2)", "var(--series-3)", "var(--series-4)"];
const GRID = "rgb(0 0 0 / 0.06)";
const AXIS = "rgb(0 0 0 / 0.16)";
const LABEL = "rgb(25 25 25 / 0.56)";

type Plotted = SeriesPoint & { value: number; day: number };

/** A point marker in the series colour, shaped by calibration tier (same shapes as the timeline). */
function PointMark({ tier, color, r }: { tier: Tier | null; color: string; r: number }) {
  if (tier === "provisional") {
    const d = r * 1.3;
    return <path d={`M0 ${-d}L${d} 0L0 ${d}L${-d} 0Z`} fill={color} stroke="var(--panel)" strokeWidth={1.5} />;
  }
  if (tier === "beta") {
    const d = r * 1.25;
    return (
      <path
        d={`M0 ${-d}L${d} ${d * 0.85}L${-d} ${d * 0.85}Z`}
        fill="var(--panel)"
        stroke={color}
        strokeWidth={1.75}
        strokeLinejoin="round"
      />
    );
  }
  if (tier === "validated") return <circle r={r} fill={color} stroke="var(--panel)" strokeWidth={1.5} />;
  return <rect x={-r * 0.8} y={-r * 0.8} width={r * 1.6} height={r * 1.6} fill={color} stroke="var(--panel)" strokeWidth={1.5} />;
}

/** Splits a series into runs. A run ends at a missing value or at a gap much longer than the usual revisit. */
function runsOf(points: SeriesPoint[]): Plotted[][] {
  const sorted = [...points].sort((a, b) => a.date.localeCompare(b.date));
  const days = sorted.map((point) => dayNumber(point.date));
  const intervals = days.slice(1).map((day, i) => day - days[i]).sort((a, b) => a - b);
  const usual = intervals.length > 0 ? intervals[Math.floor(intervals.length / 2)] : 12;
  const longest = Math.max(36, usual * 2.5);

  const runs: Plotted[][] = [];
  let run: Plotted[] = [];
  sorted.forEach((point, index) => {
    const gap = index > 0 && days[index] - days[index - 1] > longest;
    if ((point.value === null || gap) && run.length > 0) {
      runs.push(run);
      run = [];
    }
    if (point.value !== null) run.push({ ...point, value: point.value, day: days[index] });
  });
  if (run.length > 0) runs.push(run);
  return runs;
}

interface SeriesStyle {
  color: string;
  /** set from the fifth series onwards, where the four colours repeat */
  dash: string | undefined;
}

function Chart({ series, styles }: { series: Series[]; styles: Map<string, SeriesStyle> }) {
  const styleOf = (id: string): SeriesStyle => styles.get(id) ?? { color: COLORS[0], dash: undefined };
  const frameRef = useRef<HTMLDivElement>(null);
  const width = useElementWidth(frameRef);
  const [active, setActive] = useState<number | null>(null);
  const unit = formatUnit(series[0].unit);

  const model = useMemo(() => {
    const plotted = series.map((item) => ({ series: item, runs: runsOf(item.points) }));
    const all = plotted.flatMap((item) => item.runs.flat());
    const days = [...new Set(all.map((point) => point.day))].sort((a, b) => a - b);
    const lows = all.map((point) => point.value - (point.spread ?? 0));
    const highs = all.map((point) => point.value + (point.spread ?? 0));
    return { plotted, days, min: Math.min(...lows), max: Math.max(...highs) };
  }, [series]);

  if (model.days.length === 0) return <p className="text-sm text-ink-3">This series has no values.</p>;

  const innerWidth = Math.max(10, width - MARGIN.left - MARGIN.right);
  const innerHeight = HEIGHT - MARGIN.top - MARGIN.bottom;
  const firstDay = model.days[0];
  const lastDay = model.days[model.days.length - 1];
  const daySpan = Math.max(1, lastDay - firstDay);
  const dayPad = lastDay === firstDay ? 6 : daySpan * 0.03;
  const yPad = (model.max - model.min || 1) * 0.08;
  const yMin = model.min - yPad;
  const yMax = model.max + yPad;

  const x = (day: number) => MARGIN.left + ((day - firstDay + dayPad) / (daySpan + dayPad * 2)) * innerWidth;
  const y = (value: number) => MARGIN.top + (1 - (value - yMin) / (yMax - yMin)) * innerHeight;

  const yTicks = niceTicks(yMin, yMax, 5);
  const yDecimals = Math.min(decimalsFor(yTicks), yTicks.some((tick) => !Number.isInteger(tick)) ? 1 : 0);
  const xTicks = thin(monthTicks(firstDay - dayPad, lastDay + dayPad), Math.max(2, Math.floor(innerWidth / 64)));
  const decimals = 2;

  const nearest = (clientX: number) => {
    const rect = frameRef.current?.getBoundingClientRect();
    if (!rect) return null;
    const px = clientX - rect.left;
    let best = 0;
    model.days.forEach((day, index) => {
      if (Math.abs(x(day) - px) < Math.abs(x(model.days[best]) - px)) best = index;
    });
    return best;
  };

  const onKeyDown = (event: React.KeyboardEvent) => {
    const last = model.days.length - 1;
    const moves: Record<string, number> = {
      ArrowRight: Math.min(last, (active ?? -1) + 1),
      ArrowLeft: Math.max(0, (active ?? last + 1) - 1),
      Home: 0,
      End: last,
    };
    if (event.key in moves) {
      event.preventDefault();
      setActive(moves[event.key]);
    } else if (event.key === "Escape") {
      setActive(null);
    }
  };

  const activeDay = active === null ? null : model.days[active];
  const activeRows =
    activeDay === null
      ? []
      : model.plotted.flatMap((item) => {
          const point = item.series.points.find((p) => dayNumber(p.date) === activeDay);
          return point ? [{ point, label: item.series.label, color: styleOf(item.series.id).color }] : [];
        });
  const tooltipOnLeft = activeDay !== null && x(activeDay) > width / 2;

  return (
    <div>
      {series.length > 1 ? (
        <ul className="mb-2 flex flex-wrap gap-x-4 gap-y-1 text-[13px] text-ink-2" aria-label="Lines">
          {series.map((item) => (
            <li key={item.id} className="flex items-center gap-1.5">
              <svg width="18" height="6" aria-hidden="true">
                <line x1="1" x2="17" y1="3" y2="3" stroke={styleOf(item.id).color} strokeWidth="1.5" strokeLinecap="round" strokeDasharray={styleOf(item.id).dash} />
              </svg>
              {item.label}
            </li>
          ))}
        </ul>
      ) : null}

      <div
        ref={frameRef}
        className="relative rounded-md outline-offset-4"
        role="group"
        tabIndex={0}
        aria-label={`Chart of ${series.map((item) => item.label).join(", ")} in ${unit || "the unit shown"}, ${formatDate(series[0].points[0]?.date)} onwards. Use the left and right arrow keys to read each date, or open the table below.`}
        onPointerMove={(event) => setActive(nearest(event.clientX))}
        onPointerDown={(event) => setActive(nearest(event.clientX))}
        onPointerLeave={(event) => {
          if (event.pointerType === "mouse") setActive(null);
        }}
        onKeyDown={onKeyDown}
        onBlur={() => setActive(null)}
      >
        {width > 0 ? (
          <svg width={width} height={HEIGHT} role="presentation" className="block select-none">
            {yTicks.map((tick) => (
              <g key={tick}>
                <line x1={MARGIN.left} x2={width - MARGIN.right} y1={y(tick)} y2={y(tick)} stroke={GRID} strokeWidth={1} />
                <text x={MARGIN.left - 8} y={y(tick)} textAnchor="end" dominantBaseline="middle" fontSize={11} fill={LABEL}>
                  {formatNumber(tick, yDecimals)}
                </text>
              </g>
            ))}
            <text x={MARGIN.left - 8} y={8} textAnchor="end" fontSize={11} fill={LABEL}>
              {unit}
            </text>
            <line x1={MARGIN.left} x2={width - MARGIN.right} y1={HEIGHT - MARGIN.bottom} y2={HEIGHT - MARGIN.bottom} stroke={AXIS} />
            {xTicks.map((tick) => (
              <g key={tick.day}>
                <line x1={x(tick.day)} x2={x(tick.day)} y1={HEIGHT - MARGIN.bottom} y2={HEIGHT - MARGIN.bottom + 5} stroke={AXIS} />
                <text x={x(tick.day)} y={HEIGHT - 8} textAnchor="middle" fontSize={11} fill={LABEL}>
                  {tick.label}
                </text>
              </g>
            ))}

            {model.plotted.map((item) => {
              const { color, dash } = styleOf(item.series.id);
              return (
                <g key={item.series.id}>
                  {item.runs.map((run) => {
                    const upper = run.map((p) => `${x(p.day)},${y(p.value + (p.spread ?? 0))}`);
                    const lower = [...run].reverse().map((p) => `${x(p.day)},${y(p.value - (p.spread ?? 0))}`);
                    const banded = run.some((p) => p.spread !== null && p.spread > 0);
                    return (
                      <g key={run[0].date}>
                        {banded && run.length > 1 ? (
                          <polygon points={[...upper, ...lower].join(" ")} fill={color} opacity={0.1} />
                        ) : null}
                        {/* A lone point has no band to carry its spread, so it gets an error bar. */}
                        {banded && run.length === 1 ? (
                          <line
                            x1={x(run[0].day)}
                            x2={x(run[0].day)}
                            y1={y(run[0].value + (run[0].spread ?? 0))}
                            y2={y(run[0].value - (run[0].spread ?? 0))}
                            stroke={color}
                            strokeWidth={1.5}
                            opacity={0.6}
                          />
                        ) : null}
                        <polyline
                          points={run.map((p) => `${x(p.day)},${y(p.value)}`).join(" ")}
                          fill="none"
                          stroke={color}
                          strokeWidth={1.5}
                          strokeLinejoin="round"
                          strokeLinecap="round"
                          strokeDasharray={dash}
                        />
                      </g>
                    );
                  })}
                  {item.runs.flat().map((point) => (
                    <g key={point.date} transform={`translate(${x(point.day)} ${y(point.value)})`}>
                      <PointMark tier={point.tier} color={color} r={point.day === activeDay ? 4.5 : 3.25} />
                    </g>
                  ))}
                </g>
              );
            })}

            {activeDay !== null ? (
              <line x1={x(activeDay)} x2={x(activeDay)} y1={MARGIN.top} y2={HEIGHT - MARGIN.bottom} stroke={LABEL} strokeWidth={1} strokeDasharray="3 3" />
            ) : null}
          </svg>
        ) : (
          <div style={{ height: HEIGHT }} />
        )}

        {activeDay !== null && activeRows.length > 0 ? (
          <div
            className="pointer-events-none absolute top-2 z-10 w-max max-w-[min(18rem,85%)] rounded-xl border border-line bg-panel p-3 text-[13px] shadow-card"
            style={tooltipOnLeft ? { right: width - x(activeDay) + 12 } : { left: x(activeDay) + 12 }}
            role="status"
            aria-live="polite"
          >
            <p className="text-ink">{formatDate(activeRows[0].point.date)}</p>
            <ul className="mt-1.5 space-y-1.5">
              {activeRows.map(({ point, label, color }) => (
                <li key={label}>
                  <p className="flex items-center gap-1.5 text-ink-2">
                    <span className="inline-block h-0.5 w-3 shrink-0 rounded-full" style={{ background: color }} aria-hidden="true" />
                    {label}
                  </p>
                  <p className="pl-[18px] text-ink">
                    {point.value === null ? (
                      "no value"
                    ) : (
                      <>
                        {formatNumber(point.value, decimals)}
                        {point.spread !== null ? ` ± ${formatNumber(point.spread, decimals)}` : ""}
                        {unit ? ` ${unit}` : ""}
                      </>
                    )}
                    {point.tier ? <span className="ml-1.5 text-ink-3">{TIERS[point.tier].label.toLowerCase()}</span> : null}
                  </p>
                  {point.granule_id ? (
                    <p className="pl-[18px] font-mono text-[11px] [overflow-wrap:anywhere] text-ink-3">{shortenMiddle(point.granule_id, 24, 20)}</p>
                  ) : null}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>
    </div>
  );
}

function PointShapeLegend({ series }: { series: Series[] }) {
  const present = TIER_ORDER.filter((tier) => series.some((item) => item.points.some((point) => point.tier === tier)));
  if (present.length === 0) return null;
  return (
    <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[13px] text-ink-2" aria-label="Point shapes by calibration tier">
      {present.map((tier) => (
        <li key={tier} className="flex items-center gap-1.5" title={TIERS[tier].meaning}>
          <svg width="14" height="14" viewBox="-7 -7 14 14" aria-hidden="true">
            <PointMark tier={tier} color="var(--ink)" r={3.25} />
          </svg>
          {TIERS[tier].label}
        </li>
      ))}
      <li>Shaded band: value ± spread</li>
    </ul>
  );
}

function SeriesTable({ series }: { series: Series[] }) {
  const dates = [...new Set(series.flatMap((item) => item.points.map((point) => point.date)))].sort();
  return (
    <div className="scroll-quiet mt-3 max-h-72 overflow-auto rounded-xl border border-line" tabIndex={0} role="group" aria-label="Values, scrolls">
      <table className="w-full border-collapse text-left text-[13px]">
        <thead className="sticky top-0 bg-raised text-ink-2">
          <tr>
            <th scope="col" className="px-2.5 py-2 font-normal whitespace-nowrap">
              Date (UTC)
            </th>
            {series.map((item) => (
              <th key={item.id} scope="col" className="px-2.5 py-2 font-normal">
                {item.label} ({formatUnit(item.unit)})
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {dates.map((date) => (
            <tr key={date} className="border-t border-line text-ink">
              <th scope="row" className="px-2.5 py-1.5 font-normal whitespace-nowrap">
                {date}
              </th>
              {series.map((item) => {
                const point = item.points.find((p) => p.date === date);
                return (
                  <td key={item.id} className="px-2.5 py-1.5 whitespace-nowrap">
                    {!point ? (
                      <span className="text-ink-3">not acquired</span>
                    ) : point.value === null ? (
                      <span className="text-ink-3">no value</span>
                    ) : (
                      <>
                        {formatNumber(point.value, 2)}
                        {point.spread !== null ? ` ± ${formatNumber(point.spread, 2)}` : ""}
                        {point.tier ? <span className="ml-1.5 text-ink-3">{TIERS[point.tier].label.toLowerCase()}</span> : null}
                      </>
                    )}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * Time series of a result. Series with different units are never put on one axis: each unit gets
 * its own chart. Lines break at missing values and at long gaps in the record.
 */
export function SeriesChart({ series }: { series: Series[] }) {
  const units = [...new Set(series.map((item) => item.unit))];
  // Colour follows the series, in fixed order, whichever chart it lands in.
  const styles = new Map<string, SeriesStyle>(
    series.map((item, index) => [
      item.id,
      { color: COLORS[index % COLORS.length], dash: index >= COLORS.length ? "5 4" : undefined },
    ]),
  );
  return (
    <div className="space-y-5">
      {units.map((unit) => (
        <Chart key={unit} series={series.filter((item) => item.unit === unit)} styles={styles} />
      ))}
      <PointShapeLegend series={series} />
      <details>
        <summary className="w-max text-sm text-ink-2 underline underline-offset-2 hover:text-ink">
          Show the values as a table
        </summary>
        <SeriesTable series={series} />
      </details>
    </div>
  );
}

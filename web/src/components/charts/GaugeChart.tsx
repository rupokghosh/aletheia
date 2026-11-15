"use client";

import { useRef, useState } from "react";
import { dayNumber, formatDate, formatNumber } from "@/lib/format";
import { monthTicks, niceTicks, thin } from "@/lib/scale";
import { useElementWidth } from "@/lib/useElementWidth";
import { AXIS, GRID, LABEL } from "./palette";

const HEIGHT = 196;
const MARGIN = { top: 26, right: 14, bottom: 26, left: 38 };

export interface GaugeSeries {
  /** [ISO day, level in metres], oldest first */
  daily: Array<[string, number]>;
  /** the days of the radar passes, to be marked on the line */
  marks: string[];
}

/** Water level at a river gauge day by day, with the days of the radar passes marked on it. */
export function GaugeChart({ daily, marks }: GaugeSeries) {
  const frameRef = useRef<HTMLDivElement>(null);
  const width = useElementWidth(frameRef);
  const [active, setActive] = useState<number | null>(null);

  const points = daily.map(([day, level]) => ({ iso: day, day: dayNumber(day), level }));
  if (points.length < 2) return null;
  const first = points[0].day;
  const last = points[points.length - 1].day;
  const lowest = Math.min(...points.map((p) => p.level));
  const highest = Math.max(...points.map((p) => p.level));
  const pad = (highest - lowest || 1) * 0.12;
  const yMin = lowest - pad;
  const yMax = highest + pad;

  const innerWidth = Math.max(10, width - MARGIN.left - MARGIN.right);
  const innerHeight = HEIGHT - MARGIN.top - MARGIN.bottom;
  const x = (day: number) => MARGIN.left + ((day - first) / (last - first || 1)) * innerWidth;
  const y = (level: number) => MARGIN.top + (1 - (level - yMin) / (yMax - yMin)) * innerHeight;
  const base = HEIGHT - MARGIN.bottom;
  const yTicks = niceTicks(yMin, yMax, 4);
  const yDecimals = yTicks.some((tick) => !Number.isInteger(tick)) ? 1 : 0;
  const xTicks = thin(monthTicks(first, last), Math.max(2, Math.floor(innerWidth / 64)));
  const marked = marks.flatMap((iso) => {
    const point = points.find((p) => p.iso === iso);
    return point ? [point] : [];
  });

  const nearest = (clientX: number) => {
    const rect = frameRef.current?.getBoundingClientRect();
    if (!rect) return null;
    const px = clientX - rect.left;
    let best = 0;
    points.forEach((point, index) => {
      if (Math.abs(x(point.day) - px) < Math.abs(x(points[best].day) - px)) best = index;
    });
    return best;
  };
  const shown = active === null ? null : points[active];

  return (
    <div>
      <div
        ref={frameRef}
        className="relative"
        role="img"
        aria-label={`Water level from ${formatDate(points[0].iso)} to ${formatDate(points[points.length - 1].iso)}, between ${formatNumber(lowest, 2)} and ${formatNumber(highest, 2)} m.${marked
          .map((p) => ` On ${formatDate(p.iso)}, a radar pass day, it was ${formatNumber(p.level, 2)} m.`)
          .join("")}`}
        onPointerMove={(event) => setActive(nearest(event.clientX))}
        onPointerDown={(event) => setActive(nearest(event.clientX))}
        onPointerLeave={() => setActive(null)}
      >
        {width > 0 ? (
          <svg width={width} height={HEIGHT} className="block select-none" role="presentation">
            {yTicks.map((tick) => (
              <g key={tick}>
                <line x1={MARGIN.left} x2={width - MARGIN.right} y1={y(tick)} y2={y(tick)} stroke={GRID} />
                <text x={MARGIN.left - 7} y={y(tick)} textAnchor="end" dominantBaseline="middle" fontSize={11} fill={LABEL}>
                  {formatNumber(tick, yDecimals)}
                </text>
              </g>
            ))}
            <text x={MARGIN.left - 7} y={10} textAnchor="end" fontSize={11} fill={LABEL}>
              m
            </text>
            <line x1={MARGIN.left} x2={width - MARGIN.right} y1={base} y2={base} stroke={AXIS} />
            {xTicks.map((tick) => (
              <g key={tick.day}>
                <line x1={x(tick.day)} x2={x(tick.day)} y1={base} y2={base + 4} stroke={AXIS} />
                <text x={x(tick.day)} y={HEIGHT - 6} textAnchor="middle" fontSize={11} fill={LABEL}>
                  {tick.label}
                </text>
              </g>
            ))}
            <polygon
              points={[`${x(first)},${base}`, ...points.map((p) => `${x(p.day)},${y(p.level)}`), `${x(last)},${base}`].join(" ")}
              fill="var(--blue)"
              opacity={0.08}
            />
            <polyline
              points={points.map((p) => `${x(p.day)},${y(p.level)}`).join(" ")}
              fill="none"
              stroke="var(--blue)"
              strokeWidth={1.75}
              strokeLinejoin="round"
              strokeLinecap="round"
            />
            {marked.map((point, index) => {
              // The label of a pass near the right edge is written to its left, so it stays inside the chart.
              const flip = x(point.day) > width - 96;
              return (
                <g key={point.iso}>
                  <line x1={x(point.day)} x2={x(point.day)} y1={MARGIN.top - 6} y2={base} stroke="var(--ink)" strokeDasharray="3 3" />
                  <circle cx={x(point.day)} cy={y(point.level)} r={4.5} fill="var(--ink)" stroke="var(--panel)" strokeWidth={1.75} />
                  <text x={x(point.day) + (flip ? -6 : 6)} y={MARGIN.top - 12} textAnchor={flip ? "end" : "start"} fontSize={11} fill="var(--ink)">
                    {index === 0 && marked.length > 1 ? "First pass" : marked.length > 1 ? "Second pass" : "Radar pass"}: {formatNumber(point.level, 2)} m
                  </text>
                </g>
              );
            })}
            {shown ? <circle cx={x(shown.day)} cy={y(shown.level)} r={3.5} fill="var(--blue)" stroke="var(--panel)" strokeWidth={1.5} /> : null}
          </svg>
        ) : (
          <div style={{ height: HEIGHT }} />
        )}
      </div>
      <p className="mt-1 min-h-[1.25rem] text-[13px] leading-snug text-ink-2" aria-live="polite">
        {shown ? `${formatDate(shown.iso)}: ${formatNumber(shown.level, 2)} m` : <span className="text-ink-3">Dashed lines: the days the radar passed over.</span>}
      </p>
    </div>
  );
}

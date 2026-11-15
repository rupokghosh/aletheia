"use client";

import { useRef, useState } from "react";
import { formatNumber, formatUnit } from "@/lib/format";
import { niceTicks } from "@/lib/scale";
import type { ProfileData } from "@/lib/types";
import { useElementWidth } from "@/lib/useElementWidth";
import { AXIS, BAND, GRID, LABEL } from "./palette";

const HEIGHT = 200;
const MARGIN = { top: 12, right: 12, bottom: 34, left: 40 };

interface Point {
  x: number;
  y: number;
  low: number;
  high: number;
}

/** Splits the profile into unbroken runs: a gap in the data breaks the line instead of being bridged. */
function runsOf(data: ProfileData): Point[][] {
  const runs: Point[][] = [];
  let run: Point[] = [];
  data.x.forEach((x, index) => {
    const y = data.y[index];
    if (x === null || y === null) {
      if (run.length > 0) runs.push(run);
      run = [];
      return;
    }
    run.push({ x, y, low: data.low[index] ?? y, high: data.high[index] ?? y });
  });
  if (run.length > 0) runs.push(run);
  return runs;
}

/**
 * The typical value across the area along one compass direction: a line, the spread across the area as a
 * grey ribbon around it, and the noise band as a stripe around zero.
 */
export function Profile({ data }: { data: ProfileData }) {
  const frameRef = useRef<HTMLDivElement>(null);
  const width = useElementWidth(frameRef);
  const [active, setActive] = useState<Point | null>(null);

  const runs = runsOf(data);
  const points = runs.flat();
  if (points.length < 2) return null;
  const unit = formatUnit(data.unit);
  const xMin = points[0].x;
  const xMax = points[points.length - 1].x;
  const lowest = Math.min(...points.map((p) => p.low), data.band[0]);
  const highest = Math.max(...points.map((p) => p.high), data.band[1]);
  const pad = (highest - lowest || 1) * 0.08;
  const yMin = lowest - pad;
  const yMax = highest + pad;

  const innerWidth = Math.max(10, width - MARGIN.left - MARGIN.right);
  const innerHeight = HEIGHT - MARGIN.top - MARGIN.bottom;
  const x = (value: number) => MARGIN.left + ((value - xMin) / (xMax - xMin || 1)) * innerWidth;
  const y = (value: number) => MARGIN.top + (1 - (value - yMin) / (yMax - yMin)) * innerHeight;
  const base = HEIGHT - MARGIN.bottom;
  const yTicks = niceTicks(yMin, yMax, 5);
  const xTicks = niceTicks(xMin, xMax, Math.max(2, Math.floor(innerWidth / 70))).filter((tick) => tick > xMin && tick < xMax);

  const nearest = (clientX: number) => {
    const rect = frameRef.current?.getBoundingClientRect();
    if (!rect) return null;
    const px = clientX - rect.left;
    return points.reduce((best, point) => (Math.abs(x(point.x) - px) < Math.abs(x(best.x) - px) ? point : best), points[0]);
  };

  return (
    <div>
      <div
        ref={frameRef}
        className="relative"
        role="img"
        aria-label={`Typical value from ${data.start} to ${data.end}, between ${formatNumber(Math.min(...points.map((p) => p.y)), 1)} and ${formatNumber(Math.max(...points.map((p) => p.y)), 1)} ${unit}.`}
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
                  {formatNumber(tick, 0)}
                </text>
              </g>
            ))}
            <text x={MARGIN.left - 7} y={8} textAnchor="end" fontSize={11} fill={LABEL}>
              {unit}
            </text>
            <rect x={MARGIN.left} y={y(data.band[1])} width={innerWidth} height={Math.max(1, y(data.band[0]) - y(data.band[1]))} fill={BAND} />
            <line x1={MARGIN.left} x2={width - MARGIN.right} y1={y(0)} y2={y(0)} stroke={AXIS} strokeDasharray="3 3" />
            {runs.map((run) => (
              <g key={run[0].x}>
                <polygon
                  points={[...run.map((p) => `${x(p.x)},${y(p.high)}`), ...[...run].reverse().map((p) => `${x(p.x)},${y(p.low)}`)].join(" ")}
                  fill="var(--ink)"
                  opacity={0.09}
                />
                <polyline
                  points={run.map((p) => `${x(p.x)},${y(p.y)}`).join(" ")}
                  fill="none"
                  stroke="var(--ink)"
                  strokeWidth={1.75}
                  strokeLinejoin="round"
                  strokeLinecap="round"
                />
              </g>
            ))}
            <line x1={MARGIN.left} x2={width - MARGIN.right} y1={base} y2={base} stroke={AXIS} />
            {xTicks.map((tick) => (
              <g key={tick}>
                <line x1={x(tick)} x2={x(tick)} y1={base} y2={base + 4} stroke={AXIS} />
                <text x={x(tick)} y={base + 16} textAnchor="middle" fontSize={11} fill={LABEL}>
                  {formatNumber(tick, 0)} {data.x_unit}
                </text>
              </g>
            ))}
            <text x={MARGIN.left} y={HEIGHT - 3} fontSize={11} fill={LABEL}>
              {data.start}
            </text>
            <text x={width - MARGIN.right} y={HEIGHT - 3} textAnchor="end" fontSize={11} fill={LABEL}>
              {data.end}
            </text>
            {active ? (
              <g>
                <line x1={x(active.x)} x2={x(active.x)} y1={MARGIN.top} y2={base} stroke={LABEL} strokeDasharray="3 3" />
                <circle cx={x(active.x)} cy={y(active.y)} r={4} fill="var(--ink)" stroke="var(--panel)" strokeWidth={1.5} />
              </g>
            ) : null}
          </svg>
        ) : (
          <div style={{ height: HEIGHT }} />
        )}
      </div>
      <p className="mt-1.5 min-h-[1.25rem] text-[13px] leading-snug text-ink-2" aria-live="polite">
        {active ? (
          `${formatNumber(active.x, 1)} ${data.x_unit} from the ${data.start} edge: ${active.y > 0 ? "+" : ""}${formatNumber(active.y, 1)} ${unit} (most of the area between ${formatNumber(active.low, 1)} and ${formatNumber(active.high, 1)})`
        ) : (
          <span className="text-ink-3">
            Line: typical value. Ribbon: where most of the area lies. Stripe around zero: {data.band_label}.
          </span>
        )}
      </p>
    </div>
  );
}

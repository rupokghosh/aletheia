"use client";

import { useRef } from "react";
import { dayNumber, formatDate, formatNumber } from "@/lib/format";
import { useElementWidth } from "@/lib/useElementWidth";
import { AXIS, GRID, LABEL, UP } from "./palette";

const HEIGHT = 176;
const MARGIN = { top: 26, right: 14, bottom: 26, left: 34 };

export interface Quake {
  time_utc: string;
  magnitude: number;
  distance_km: number | null;
  place: string | null;
}

/** Days since the Unix epoch, with the time of day as a fraction. */
function dayOf(stamp: string): number {
  return Date.parse(stamp) / 86_400_000;
}

/**
 * Earthquakes near the area as stems on a time line (taller = stronger), with the two radar passes that the
 * motion map compares marked, so it is plain at a glance whether the shaking fell between them.
 */
export function QuakeTimeline({ events, marks }: { events: Quake[]; marks: string[] }) {
  const frameRef = useRef<HTMLDivElement>(null);
  const width = useElementWidth(frameRef);
  if (events.length === 0) return null;

  const times = events.map((event) => dayOf(event.time_utc));
  const passDays = marks.map((iso) => dayNumber(iso) + 0.5);
  const first = Math.min(...times, ...passDays);
  const last = Math.max(...times, ...passDays);
  const pad = Math.max(1, (last - first) * 0.08);
  const xMin = first - pad;
  const xMax = last + pad;
  const strongest = events.reduce((best, event) => (event.magnitude > best.magnitude ? event : best), events[0]);
  const floor = Math.floor(Math.min(...events.map((event) => event.magnitude)) - 0.5);
  const ceiling = Math.ceil(strongest.magnitude + 0.3);

  const innerWidth = Math.max(10, width - MARGIN.left - MARGIN.right);
  const innerHeight = HEIGHT - MARGIN.top - MARGIN.bottom;
  const x = (day: number) => MARGIN.left + ((day - xMin) / (xMax - xMin)) * innerWidth;
  const y = (magnitude: number) => MARGIN.top + (1 - (magnitude - floor) / (ceiling - floor)) * innerHeight;
  const base = HEIGHT - MARGIN.bottom;
  const levels = Array.from({ length: ceiling - floor + 1 }, (_, i) => floor + i).filter((level) => level > floor);
  const labelLeft = x(dayOf(strongest.time_utc)) > width - 90;

  return (
    <div
      ref={frameRef}
      role="img"
      aria-label={`${events.length} earthquakes between ${formatDate(new Date(first * 86_400_000).toISOString().slice(0, 10))} and ${formatDate(
        new Date(last * 86_400_000).toISOString().slice(0, 10),
      )}. The strongest was magnitude ${formatNumber(strongest.magnitude, 1)} on ${formatDate(strongest.time_utc.slice(0, 10))}.`}
    >
      {width > 0 ? (
        <svg width={width} height={HEIGHT} className="block select-none" role="presentation">
          {levels.map((level) => (
            <g key={level}>
              <line x1={MARGIN.left} x2={width - MARGIN.right} y1={y(level)} y2={y(level)} stroke={GRID} />
              <text x={MARGIN.left - 7} y={y(level)} textAnchor="end" dominantBaseline="middle" fontSize={11} fill={LABEL}>
                M{level}
              </text>
            </g>
          ))}
          <line x1={MARGIN.left} x2={width - MARGIN.right} y1={base} y2={base} stroke={AXIS} />
          {marks.map((iso, index) => {
            const px = x(dayNumber(iso) + 0.5);
            const flip = px > width - 96;
            return (
              <g key={iso}>
                <line x1={px} x2={px} y1={MARGIN.top - 6} y2={base} stroke="var(--ink)" strokeDasharray="3 3" />
                <text x={px + (flip ? -6 : 6)} y={MARGIN.top - 12} textAnchor={flip ? "end" : "start"} fontSize={11} fill="var(--ink)">
                  {marks.length > 1 ? (index === 0 ? "First pass" : "Second pass") : "Radar pass"}
                </text>
                <text x={px} y={HEIGHT - 6} textAnchor="middle" fontSize={11} fill={LABEL}>
                  {formatDate(iso).replace(/\s\d{4}$/, "")}
                </text>
              </g>
            );
          })}
          {events.map((event) => {
            const px = x(dayOf(event.time_utc));
            const strong = event === strongest;
            return (
              <g key={`${event.time_utc}-${event.magnitude}`}>
                <line x1={px} x2={px} y1={base} y2={y(event.magnitude)} stroke={UP} strokeWidth={strong ? 2 : 1.25} opacity={strong ? 1 : 0.55} />
                <circle cx={px} cy={y(event.magnitude)} r={strong ? 5 : 3} fill={UP} stroke="var(--panel)" strokeWidth={1.5} opacity={strong ? 1 : 0.7} />
              </g>
            );
          })}
          <text
            x={x(dayOf(strongest.time_utc)) + (labelLeft ? -9 : 9)}
            y={y(strongest.magnitude) + 4}
            textAnchor={labelLeft ? "end" : "start"}
            fontSize={12}
            fill="var(--ink)"
          >
            M{formatNumber(strongest.magnitude, 1)}, {formatDate(strongest.time_utc.slice(0, 10)).replace(/\s\d{4}$/, "")}
          </text>
        </svg>
      ) : (
        <div style={{ height: HEIGHT }} />
      )}
    </div>
  );
}

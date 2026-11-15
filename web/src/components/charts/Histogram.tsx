"use client";

import { useRef, useState } from "react";
import { formatNumber, formatUnit } from "@/lib/format";
import { niceTicks } from "@/lib/scale";
import type { HistogramData } from "@/lib/types";
import { useElementWidth } from "@/lib/useElementWidth";
import { AXIS, BAND, DOWN, LABEL, STEADY, UP } from "./palette";

const HEIGHT = 168;
const MARGIN = { top: 22, right: 10, bottom: 40, left: 10 };

/**
 * Area per step of a measured quantity. Bars inside the band (no clear change, or within the noise) are grey;
 * the tails beyond it take the colours of the map. Heights use a square-root scale: on a straight scale the
 * middle is so tall that the tails, which are the finding, would not show.
 */
export function Histogram({ data }: { data: HistogramData }) {
  const frameRef = useRef<HTMLDivElement>(null);
  const width = useElementWidth(frameRef);
  const [active, setActive] = useState<number | null>(null);

  const { edges, area_km2: area, band } = data;
  const unit = formatUnit(data.unit);
  const bins = area.length;
  if (bins === 0 || edges.length !== bins + 1) return null;
  const low = edges[0];
  const high = edges[bins];
  const peak = Math.max(...area, 1e-9);

  const innerWidth = Math.max(10, width - MARGIN.left - MARGIN.right);
  const innerHeight = HEIGHT - MARGIN.top - MARGIN.bottom;
  const x = (value: number) => MARGIN.left + ((value - low) / (high - low)) * innerWidth;
  const barHeight = (value: number) => (value <= 0 ? 0 : Math.max(1.5, Math.sqrt(value / peak) * innerHeight));
  const base = HEIGHT - MARGIN.bottom;
  const colourOf = (index: number) => {
    const centre = (edges[index] + edges[index + 1]) / 2;
    return centre < band[0] ? DOWN : centre > band[1] ? UP : STEADY;
  };
  const ticks = niceTicks(low, high, 6).filter((tick) => tick > low && tick < high);
  const decimals = ticks.some((tick) => !Number.isInteger(tick)) ? 1 : 0;

  const binAt = (clientX: number) => {
    const rect = frameRef.current?.getBoundingClientRect();
    if (!rect) return null;
    const share = (clientX - rect.left - MARGIN.left) / innerWidth;
    return Math.max(0, Math.min(bins - 1, Math.floor(share * bins)));
  };
  const reading =
    active === null
      ? null
      : `${active === 0 ? "Below" : "From"} ${active === 0 ? "" : `${formatNumber(edges[active], 1)} to `}${formatNumber(edges[active + 1], 1)} ${unit}${
          active === bins - 1 ? " and beyond" : ""
        }: ${formatNumber(area[active], area[active] < 10 ? 2 : 1)} km²`;

  return (
    <div>
      <div
        ref={frameRef}
        className="relative"
        role="img"
        aria-label={`Area per step of change from ${formatNumber(low, 0)} to ${formatNumber(high, 0)} ${unit}. Values between ${formatNumber(band[0], 1)} and ${formatNumber(band[1], 1)} ${unit} are ${data.band_label}.`}
        onPointerMove={(event) => setActive(binAt(event.clientX))}
        onPointerDown={(event) => setActive(binAt(event.clientX))}
        onPointerLeave={() => setActive(null)}
      >
        {width > 0 ? (
          <svg width={width} height={HEIGHT} className="block select-none" role="presentation">
            <rect x={x(band[0])} y={MARGIN.top - 4} width={Math.max(0, x(band[1]) - x(band[0]))} height={innerHeight + 4} fill={BAND} rx={4} />
            <text x={(x(band[0]) + x(band[1])) / 2} y={11} textAnchor="middle" fontSize={11} fill={LABEL}>
              {data.band_label}
            </text>
            {area.map((value, index) => {
              const h = barHeight(value);
              const left = x(edges[index]);
              const barWidth = Math.max(1, x(edges[index + 1]) - left - 1);
              return (
                <rect
                  key={edges[index]}
                  x={left + 0.5}
                  y={base - h}
                  width={barWidth}
                  height={h}
                  rx={Math.min(1.5, barWidth / 2)}
                  fill={colourOf(index)}
                  opacity={active === null || active === index ? 1 : 0.45}
                />
              );
            })}
            <line x1={MARGIN.left} x2={width - MARGIN.right} y1={base} y2={base} stroke={AXIS} />
            {ticks.map((tick) => (
              <g key={tick}>
                <line x1={x(tick)} x2={x(tick)} y1={base} y2={base + 4} stroke={AXIS} />
                <text x={x(tick)} y={base + 16} textAnchor="middle" fontSize={11} fill={LABEL}>
                  {tick > 0 ? "+" : ""}
                  {formatNumber(tick, decimals)}
                </text>
              </g>
            ))}
            <text x={MARGIN.left} y={HEIGHT - 4} fontSize={11} fill={DOWN}>
              ← {data.low_label}
            </text>
            <text x={width / 2} y={HEIGHT - 4} textAnchor="middle" fontSize={11} fill={LABEL}>
              {unit}
            </text>
            <text x={width - MARGIN.right} y={HEIGHT - 4} textAnchor="end" fontSize={11} fill={UP}>
              {data.high_label} →
            </text>
          </svg>
        ) : (
          <div style={{ height: HEIGHT }} />
        )}
      </div>
      <p className="mt-1.5 min-h-[1.25rem] text-[13px] leading-snug text-ink-2" aria-live="polite">
        {reading ?? <span className="text-ink-3">Taller bars mean more area (square-root scale, so the small tails stay visible).</span>}
      </p>
    </div>
  );
}

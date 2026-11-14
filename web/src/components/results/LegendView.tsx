import { colormapGradient, isDiverging } from "@/lib/colormaps";
import { decimalsFor, formatNumber, formatUnit } from "@/lib/format";
import type { Legend } from "@/lib/types";

/** Draws the legend a layer came with: a labelled colour ramp or a list of classes. */
export function LegendView({ legend }: { legend: Legend }) {
  if (legend.type === "categorical") {
    if (legend.classes.length === 0) return null;
    return (
      <ul className="space-y-1 text-[13px] leading-snug text-ink-2">
        {legend.classes.map((item) => (
          <li key={item.label} className="flex items-start gap-2">
            <span
              className="mt-0.5 inline-block size-3 shrink-0 rounded-[3px] border border-black/15"
              style={{ background: item.color }}
              aria-hidden="true"
            />
            {item.label}
          </li>
        ))}
      </ul>
    );
  }

  const { min, max } = legend;
  const unit = formatUnit(legend.unit);
  const decimals = Math.min(decimalsFor([min, max]), 1);
  const gradient = colormapGradient(legend.colormap);
  const middle = min !== null && max !== null && isDiverging(legend.colormap) ? (min + max) / 2 : null;

  return (
    <div className="text-[13px] text-ink-2">
      {gradient ? (
        <div
          className="h-2.5 w-full rounded-full border border-black/10"
          style={{ background: gradient }}
          role="img"
          aria-label={`Colour scale from ${formatNumber(min, decimals)} to ${formatNumber(max, decimals)} ${unit}`}
        />
      ) : null}
      <div className="mt-1 flex justify-between gap-2">
        <span>{formatNumber(min, decimals)}</span>
        {middle !== null ? <span>{formatNumber(middle, decimals)}</span> : null}
        <span>
          {formatNumber(max, decimals)}
          {unit ? ` ${unit}` : ""}
        </span>
      </div>
    </div>
  );
}

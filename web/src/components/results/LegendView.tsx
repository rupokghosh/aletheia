import { colormapGradient, isDiverging } from "@/lib/colormaps";
import { decimalsFor, formatNumber, formatUnit } from "@/lib/format";
import type { Legend } from "@/lib/types";

/**
 * Draws the legend a layer came with: a colour ramp captioned in words at both ends (with the
 * numbers underneath), or a list of classes.
 */
export function LegendView({ legend }: { legend: Legend }) {
  if (legend.type === "categorical") {
    if (legend.classes.length === 0) return null;
    return (
      <ul className="space-y-1.5 text-[13px] leading-snug text-ink">
        {legend.classes.map((item) => (
          <li key={item.label} className="flex items-start gap-2">
            <span
              className="mt-0.5 inline-block size-3 shrink-0 rounded-[3px] border border-black/15"
              style={{ background: item.color }}
              aria-hidden="true"
            />
            <span>
              {item.label}
              {item.detail ? <span className="block text-ink-3">{item.detail}</span> : null}
            </span>
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
  const worded = Boolean(legend.min_label || legend.max_label);

  return (
    <div className="text-[13px]">
      {gradient ? (
        <div
          className="h-2.5 w-full rounded-full border border-black/10"
          style={{ background: gradient }}
          role="img"
          aria-label={
            worded
              ? `Colour scale from ${legend.min_label ?? formatNumber(min, decimals)} to ${legend.max_label ?? formatNumber(max, decimals)}`
              : `Colour scale from ${formatNumber(min, decimals)} to ${formatNumber(max, decimals)} ${unit}`
          }
        />
      ) : null}
      {worded ? (
        <div className="mt-1 flex justify-between gap-3 leading-snug text-ink">
          <span className="max-w-[48%]">{legend.min_label}</span>
          <span className="max-w-[48%] text-right">{legend.max_label}</span>
        </div>
      ) : null}
      <div className={`flex justify-between gap-2 ${worded ? "mt-0.5 text-ink-3" : "mt-1 text-ink-2"}`}>
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

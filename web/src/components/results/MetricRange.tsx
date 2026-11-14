import { decimalsFor, formatNumber, formatUnit, unitFor } from "@/lib/format";
import type { Metric } from "@/lib/types";

type RangedMetric = Metric & { low: number; high: number };

const isRanged = (metric: Metric): metric is RangedMetric => metric.low !== null && metric.high !== null;

/** How many ranges are shown with a result before the rest go under "More numbers". */
const LEAD = 2;

/** The metrics of a result, split into the ranges shown first and everything else. */
export function splitMetrics(metrics: Metric[]): { lead: RangedMetric[]; moreRanges: RangedMetric[]; single: Metric[] } {
  const ranged = metrics.filter(isRanged);
  return {
    lead: ranged.slice(0, LEAD),
    moreRanges: ranged.slice(LEAD),
    single: metrics.filter((metric) => !isRanged(metric) && metric.central !== null),
  };
}

/** One metric as a bar from low to high with the central value marked on it. */
export function MetricRange({ metric }: { metric: RangedMetric }) {
  const { low, central, high } = metric;
  const unit = formatUnit(metric.unit);
  const decimals = decimalsFor([low, central, high]);
  const least = Math.min(low, high, central ?? low);
  const most = Math.max(low, high, central ?? high);
  const pad = most > least ? (most - least) * 0.3 : Math.max(Math.abs(most) * 0.5, 1);
  // A range of positive quantities starts at zero when zero is near, so the bar shows true proportions.
  const start = least >= 0 && least - pad < (most - least) * 0.25 ? 0 : least - pad;
  const end = most + pad;
  const at = (value: number) => `${((value - start) / (end - start)) * 100}%`;
  const zeroShare = start < 0 && end > 0 ? -start / (end - start) : null;
  const shown = central ?? (low + high) / 2;

  return (
    <div>
      <p className="max-w-[65ch] text-sm leading-snug [overflow-wrap:anywhere] text-ink-2">{metric.label}</p>
      <div className="mt-1 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-0.5">
        <p className="text-2xl leading-tight tracking-tight text-ink">
          {formatNumber(shown, decimals)}
          {unit ? <span className={`text-[15px] tracking-normal text-ink-2 ${unit === "%" ? "" : "ml-1"}`}>{unit}</span> : null}
          {central === null ? <span className="ml-2 text-[13px] tracking-normal text-ink-3">midpoint</span> : null}
        </p>
        <p className="text-sm whitespace-nowrap text-ink-2">
          {formatNumber(low, decimals)} to {formatNumber(high, decimals)}
          {unit === "%" ? "%" : unit ? ` ${unit}` : ""}
        </p>
      </div>

      <div
        className="relative mt-2 h-4"
        role="img"
        aria-label={`${metric.label}: low ${formatNumber(low, decimals)}, central ${formatNumber(central, decimals)}, high ${formatNumber(high, decimals)} ${unit}`}
      >
        <div className="absolute inset-x-0 top-1/2 h-1 -translate-y-1/2 rounded-full bg-raised-2" />
        {zeroShare !== null ? <div className="absolute inset-y-0 w-px bg-ink-3" style={{ left: at(0) }} /> : null}
        <div
          className="absolute top-1/2 h-1 -translate-y-1/2 rounded-full bg-ink"
          style={{ left: at(low), width: `max(2px, calc(${at(high)} - ${at(low)}))` }}
        />
        {central !== null ? (
          <div
            className="absolute top-1/2 size-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-ink bg-panel"
            style={{ left: at(central) }}
          />
        ) : null}
      </div>
      <div className="relative mt-0.5 h-4 text-xs text-ink-3" aria-hidden="true">
        <span className="absolute left-0">{formatNumber(start, decimals)}</span>
        {zeroShare !== null && zeroShare > 0.18 && zeroShare < 0.82 ? (
          <span className="absolute -translate-x-1/2" style={{ left: at(0) }}>
            0
          </span>
        ) : null}
        <span className="absolute right-0">{formatNumber(end, decimals)}</span>
      </div>
    </div>
  );
}

/**
 * Values the analysis reports without a range (counts, a single shift). They are listed apart and
 * labelled as such, so a lone number is never mistaken for a range.
 */
export function SingleValues({ metrics }: { metrics: Metric[] }) {
  return (
    <div>
      <h4 className="text-sm text-ink-2">Single values, reported without a range</h4>
      <dl className="mt-1 text-sm">
        {metrics.map((metric) => {
          const unit = unitFor(metric.central, metric.unit);
          return (
            <div key={metric.key} className="flex items-baseline justify-between gap-4 border-b border-line py-2 last:border-b-0">
              <dt className="min-w-0 [overflow-wrap:anywhere] text-ink-2">{metric.label}</dt>
              <dd className="shrink-0 whitespace-nowrap text-ink">
                {formatNumber(metric.central, decimalsFor([metric.central]))}
                {unit === "%" ? "%" : unit ? ` ${unit}` : ""}
              </dd>
            </div>
          );
        })}
      </dl>
    </div>
  );
}

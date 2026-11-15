import { formatNumber, plural } from "@/lib/format";

/** What it took to get a result's data out of NASA's archive: stats.effort from the API. */
interface Effort {
  files: number;
  archive_gb: number;
  read_mb: number;
  share_read: number | null;
}

function isEffort(value: unknown): value is Effort {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  return typeof v.files === "number" && typeof v.archive_gb === "number" && typeof v.read_mb === "number";
}

/** How many radar measurements went into the result: the pixels of the window, on every date and channel read. */
function measurements(stats: Record<string, unknown>, files: number): number | null {
  const window = stats.window as { shape?: unknown } | undefined;
  const shape = window?.shape;
  if (!Array.isArray(shape) || shape.length !== 2 || typeof shape[0] !== "number" || typeof shape[1] !== "number") return null;
  const channels = typeof stats.polarizations === "object" && stats.polarizations !== null ? Math.max(1, Object.keys(stats.polarizations).length) : 1;
  return shape[0] * shape[1] * Math.max(1, files) * channels;
}

function count(value: number): string {
  if (value >= 1e6) return `${formatNumber(value / 1e6, value >= 1e7 ? 0 : 1)} million`;
  if (value >= 1e4) return `${formatNumber(Math.round(value / 1000), 0)},000`;
  return formatNumber(value, 0);
}

function Figure({ value, label }: { value: string; label: string }) {
  return (
    <div className="min-w-0 flex-1 px-3 first:pl-0 last:pr-0">
      <p className="text-[19px] leading-tight tracking-tight tabular-nums text-ink">{value}</p>
      <p className="mt-0.5 text-[13px] leading-snug text-ink-3">{label}</p>
    </div>
  );
}

/**
 * Three figures under the headline: how much NASA holds for the passes used, how little of it had to be
 * read, and how many radar measurements the result rests on. They are measured, not estimated.
 */
export function EffortStrip({ stats }: { stats: Record<string, unknown> }) {
  const effort = stats.effort;
  if (!isEffort(effort)) return null;
  const share = effort.share_read !== null ? effort.share_read * 100 : null;
  const used = measurements(stats, effort.files);
  return (
    <div className="mt-5 rounded-2xl bg-raised p-3.5">
      <div className="flex divide-x divide-line">
        <Figure value={`${formatNumber(effort.archive_gb, 1)} GB`} label={`in NASA’s archive for ${effort.files === 1 ? "this pass" : `these ${plural(effort.files, "pass", "passes")}`}`} />
        <Figure
          value={`${formatNumber(effort.read_mb, 0)} MB`}
          label={share !== null ? `read to answer this (${formatNumber(share, share < 1 ? 1 : 0)}%)` : "read to answer this"}
        />
        {used !== null ? <Figure value={count(used)} label="radar measurements behind this result" /> : null}
      </div>
    </div>
  );
}

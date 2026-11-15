import { formatNumber, plural } from "@/lib/format";

/** What it took to get a result's data out of NASA's archive: stats.effort from the API. */
interface Effort {
  files: number;
  archive_gb: number;
  read_mb: number;
  share_read: number | null;
  seconds_per_file: number;
}

function isEffort(value: unknown): value is Effort {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  return typeof v.files === "number" && typeof v.archive_gb === "number" && typeof v.read_mb === "number";
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
 * Three figures under the headline: how much NASA holds for the passes used, how little of it was
 * read, and how long a file took. They are measured, the first time each file was read.
 */
export function EffortStrip({ stats }: { stats: Record<string, unknown> }) {
  const effort = stats.effort;
  if (!isEffort(effort)) return null;
  const share = effort.share_read !== null ? effort.share_read * 100 : null;
  return (
    <div className="mt-5 rounded-2xl bg-raised p-3.5">
      <div className="flex divide-x divide-line">
        <Figure value={`${formatNumber(effort.archive_gb, 1)} GB`} label={`in NASA’s archive for ${effort.files === 1 ? "this pass" : `these ${plural(effort.files, "pass", "passes")}`}`} />
        <Figure
          value={`${formatNumber(effort.read_mb, 0)} MB`}
          label={share !== null ? `read to answer this (${formatNumber(share, share < 1 ? 1 : 0)}%)` : "read to answer this"}
        />
        <Figure value={`${formatNumber(effort.seconds_per_file, 0)} s`} label="per file, straight from NASA" />
      </div>
    </div>
  );
}

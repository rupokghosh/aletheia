import type { DataSource } from "@/lib/api";

const LABELS: Record<Exclude<DataSource, "live">, { short: string; detail: string }> = {
  demo: {
    short: "Sample data",
    detail: "Not a live result. These values are fixtures for reviewing the interface and were not computed from NISAR.",
  },
  showcase: {
    short: "Precomputed",
    detail: "Computed from NISAR data before you opened it, not run for this session.",
  },
};

/** Marks anything that is not a live measurement. Live results carry no badge. */
export function SourceBadge({ source, detailed = false }: { source: DataSource; detailed?: boolean }) {
  if (source === "live") return null;
  const label = LABELS[source];
  const dot = source === "demo" ? "bg-purple" : "bg-ink-3";
  if (detailed) {
    return (
      <p className="max-w-[65ch] rounded-xl bg-raised px-3.5 py-2.5 text-sm leading-snug text-ink-2" role="note">
        <span className={`mr-2 inline-block size-2 rounded-full align-middle ${dot}`} aria-hidden="true" />
        <span className="text-ink">{label.short}.</span> {label.detail}
      </p>
    );
  }
  return (
    <span
      className="inline-flex shrink-0 items-center gap-1.5 rounded-full border border-line bg-panel px-2.5 py-0.5 text-[13px] whitespace-nowrap text-ink"
      title={`${label.short}. ${label.detail}`}
    >
      <span className={`size-2 rounded-full ${dot}`} aria-hidden="true" />
      {label.short}
    </span>
  );
}

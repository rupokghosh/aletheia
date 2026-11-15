import type { DataSource } from "@/lib/api";

const SAMPLE = {
  short: "Sample data",
  detail: "Not a live result. These values are fixtures for reviewing the interface and were not computed from NISAR.",
};

/**
 * Marks sample data: fixtures that were not computed from NISAR. Live results carry no badge, and neither
 * do the worked examples, which are real results of the same pipeline, computed earlier; when each was
 * computed is in its receipt.
 */
export function SourceBadge({ source, detailed = false }: { source: DataSource; detailed?: boolean }) {
  if (source !== "demo") return null;
  if (detailed) {
    return (
      <p className="max-w-[65ch] rounded-xl bg-raised px-3.5 py-2.5 text-sm leading-snug text-ink-2" role="note">
        <span className="mr-2 inline-block size-2 rounded-full bg-purple align-middle" aria-hidden="true" />
        <span className="text-ink">{SAMPLE.short}.</span> {SAMPLE.detail}
      </p>
    );
  }
  return (
    <span
      className="inline-flex shrink-0 items-center gap-1.5 rounded-full border border-line bg-panel px-2.5 py-0.5 text-[13px] whitespace-nowrap text-ink"
      title={`${SAMPLE.short}. ${SAMPLE.detail}`}
    >
      <span className="size-2 rounded-full bg-purple" aria-hidden="true" />
      {SAMPLE.short}
    </span>
  );
}

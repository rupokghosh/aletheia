import { CopyButton } from "@/components/ui/CopyButton";
import { TierBadge } from "@/components/ui/Tier";
import { ExternalIcon } from "@/components/ui/icons";
import type { DataSource } from "@/lib/api";
import { formatDate, formatSeconds, formatTimestamp, humanizeKey } from "@/lib/format";
import type { JsonValue, ReceiptGranule, WorkflowResult } from "@/lib/types";

function granuleDate(granule: ReceiptGranule): string {
  return granule.reference_date
    ? `${formatDate(granule.reference_date)} to ${formatDate(granule.secondary_date)}`
    : formatDate(granule.date);
}

function show(value: JsonValue): string {
  return typeof value === "string" ? value : JSON.stringify(value).replace(/,/g, ", ");
}

const HEADING = "text-sm text-ink-2";

/**
 * The receipt of a result: which files were read, what was done to them, with which software, and
 * code that repeats it. File links are not offered for sample data, because sample files do not exist.
 */
export function ReceiptSection({ result, source }: { result: WorkflowResult; source: DataSource }) {
  const { granules, steps, software, generated_at: generatedAt, reproduce } = result.receipt;
  const request = Object.entries(result.request).filter(([, value]) => value !== null && typeof value !== "object");

  return (
    <div className="space-y-5">
      <div>
        <h4 className={HEADING}>{granules.length === 1 ? "Source file" : `Source files (${granules.length})`}</h4>
        {granules.length === 0 ? (
          <p className="mt-1 text-sm text-ink-3">No file was read.</p>
        ) : (
          <ul className="mt-1.5 divide-y divide-line rounded-xl border border-line">
            {granules.map((granule) => (
              <li key={granule.granule_id} className="px-3.5 py-3">
                <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1 text-sm text-ink-2">
                  <span className="text-ink">{granuleDate(granule)}</span>
                  <TierBadge tier={granule.tier} />
                </div>
                <p className="mt-1 text-[13px] text-ink-2">
                  {granule.product}, track {granule.track}, {granule.direction}, frame {granule.frame}
                  {granule.polarizations.length > 0 ? `, ${granule.polarizations.join(" ")}` : ""}
                </p>
                <p className="mt-1 font-mono text-xs leading-snug [overflow-wrap:anywhere] text-ink-3">{granule.granule_id}</p>
                {source === "demo" ? null : (
                  <a
                    className="mt-1.5 inline-flex items-center gap-1 text-sm text-ink underline underline-offset-2"
                    href={granule.url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    File at the Alaska Satellite Facility
                    <ExternalIcon width={12} height={12} />
                    <span className="sr-only">(opens in a new tab, needs a free Earthdata login)</span>
                  </a>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>

      {steps.length > 0 ? (
        <div>
          <h4 className={HEADING}>Steps</h4>
          <ol className="mt-1.5 divide-y divide-line rounded-xl border border-line">
            {steps.map((step, index) => (
              <li key={`${step.name}-${index}`} className="grid grid-cols-[1.25rem_minmax(0,1fr)_auto] gap-x-2.5 px-3.5 py-2.5 text-sm">
                <span className="text-ink-3">{index + 1}</span>
                <div className="min-w-0">
                  <p className="font-mono text-[13px] [overflow-wrap:anywhere] text-ink">{step.name}</p>
                  {Object.keys(step.params).length > 0 ? (
                    <dl className="mt-0.5 space-y-0.5 text-[13px] text-ink-3">
                      {Object.entries(step.params).map(([key, value]) => (
                        <div key={key} className="flex gap-1.5">
                          <dt className="shrink-0">{humanizeKey(key)}:</dt>
                          <dd className="min-w-0 font-mono text-xs leading-5 [overflow-wrap:anywhere] text-ink-2">{show(value)}</dd>
                        </div>
                      ))}
                    </dl>
                  ) : null}
                </div>
                <span className="text-right whitespace-nowrap text-ink-2">{step.seconds === null ? "" : formatSeconds(step.seconds)}</span>
              </li>
            ))}
          </ol>
        </div>
      ) : null}

      <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1.5 text-sm">
        <dt className="text-ink-2">Result</dt>
        <dd className="font-mono text-[13px] leading-5 [overflow-wrap:anywhere] text-ink">{result.id}</dd>
        {request.map(([key, value]) => (
          <div key={key} className="col-span-2 grid grid-cols-subgrid">
            <dt className="text-ink-2">{humanizeKey(key)}</dt>
            <dd className="[overflow-wrap:anywhere] text-ink">{show(value)}</dd>
          </div>
        ))}
        <dt className="text-ink-2">Software</dt>
        <dd className="[overflow-wrap:anywhere] text-ink">
          {software.name ?? "not stated"} {software.version ?? ""}
          {software.commit ? ` (commit ${software.commit})` : ""}
        </dd>
        <dt className="text-ink-2">Computed</dt>
        <dd className="text-ink">{generatedAt ? formatTimestamp(generatedAt) : "not stated"}</dd>
      </dl>

      {reproduce ? (
        <div>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h4 className={HEADING}>Code that reproduces this result</h4>
            <CopyButton text={reproduce} label="Copy code" />
          </div>
          <pre
            className="scroll-quiet mt-2 max-h-80 overflow-auto rounded-xl bg-raised p-3.5 font-mono text-[13px] leading-relaxed text-ink"
            tabIndex={0}
            aria-label="Python code that reproduces this result"
          >
            <code>{reproduce}</code>
          </pre>
        </div>
      ) : null}
    </div>
  );
}

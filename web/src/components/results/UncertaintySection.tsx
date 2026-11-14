import { formatNumber, formatPercent, formatUnit } from "@/lib/format";
import type { Uncertainty, WorkflowKind } from "@/lib/types";

/** What the contract's noise_floor_fraction means for each analysis, in plain words. */
const UNUSABLE: Record<WorkflowKind, { title: string; about: string }> = {
  change: {
    title: "of the area is at the noise floor",
    about: "There the radar return is too weak to tell from instrument noise, so those pixels say little about change.",
  },
  timeseries: {
    title: "of the area is at the noise floor",
    about: "There the radar return is too weak to tell from instrument noise. The mean still includes those pixels.",
  },
  motion: {
    title: "of the area has no usable measurement",
    about: "It is masked out because the surface is water, the signal was lost or the motion could not be resolved.",
  },
};

/** How sure the result is: how it was measured, how much of the area is unusable, and how the answer moves with each choice. */
export function UncertaintySection({ uncertainty, workflow }: { uncertainty: Uncertainty; workflow: WorkflowKind }) {
  const { method, sensitivity, noise_floor_fraction: noise, notes } = uncertainty;
  const unusable = UNUSABLE[workflow];

  return (
    <div className="space-y-5">
      <p className="max-w-[65ch] text-sm leading-snug [overflow-wrap:anywhere] text-ink">{method}</p>

      {noise !== null ? (
        <div>
          <p className="text-sm text-ink">
            <span className="mr-1.5 text-2xl tracking-tight">{formatPercent(noise)}</span>
            {unusable.title}
          </p>
          <div className="mt-2 h-1 overflow-hidden rounded-full bg-raised-2" role="img" aria-label={`${formatPercent(noise)} ${unusable.title}`}>
            <div className="h-full rounded-full bg-ink-3" style={{ width: `${Math.min(1, Math.max(0, noise)) * 100}%` }} />
          </div>
          <p className="mt-2 max-w-[65ch] text-sm leading-snug text-ink-2">{unusable.about}</p>
        </div>
      ) : null}

      {sensitivity.length > 0 ? (
        <div>
          <h4 className="text-sm text-ink-2">How the result moves with each processing choice</h4>
          <div className="scroll-quiet mt-1.5 overflow-x-auto rounded-xl border border-line" tabIndex={0} role="group" aria-label="Sensitivity table, scrolls">
            <table className="w-full border-collapse text-sm">
              <thead className="bg-raised text-[13px] text-ink-2">
                <tr>
                  <th scope="col" className="px-3 py-2 text-left font-normal">
                    Choice
                  </th>
                  <th scope="col" className="px-3 py-2 text-right font-normal">
                    Value
                  </th>
                  <th scope="col" className="px-3 py-2 text-right font-normal">
                    Result
                  </th>
                </tr>
              </thead>
              <tbody>
                {sensitivity.map((row, index) => (
                  <tr key={`${row.parameter}-${row.value}-${index}`} className="border-t border-line">
                    <td className="px-3 py-1.5 [overflow-wrap:anywhere] text-ink-2">{row.parameter}</td>
                    <td className="px-3 py-1.5 text-right whitespace-nowrap text-ink-2">{row.value}</td>
                    <td className="px-3 py-1.5 text-right whitespace-nowrap text-ink">
                      {formatNumber(row.result, 2)}
                      {row.result !== null && row.unit ? ` ${formatUnit(row.unit)}` : ""}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}

      {notes.length > 0 ? (
        <ul className="max-w-[65ch] space-y-2 text-sm leading-snug [overflow-wrap:anywhere] text-ink-2">
          {notes.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

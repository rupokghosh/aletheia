"use client";

import { SeriesChart } from "@/components/results/SeriesChart";
import { CloseIcon } from "@/components/ui/icons";
import { formatNumber, formatUnit } from "@/lib/format";
import type { PointReading } from "@/lib/types";

/** The spot the user clicked, tied to the result it was read from. */
export type SpotState =
  | { status: "loading"; resultId: string; lon: number; lat: number }
  | { status: "ready"; resultId: string; lon: number; lat: number; reading: PointReading }
  | { status: "error"; resultId: string; lon: number; lat: number; message: string };

function coordinates(lon: number, lat: number): string {
  const ns = lat >= 0 ? "N" : "S";
  const ew = lon >= 0 ? "E" : "W";
  return `${Math.abs(lat).toFixed(4)}° ${ns}, ${Math.abs(lon).toFixed(4)}° ${ew}`;
}

/**
 * What the open result says at the clicked spot: one plain sentence first, then the values, the
 * common causes of a change like it, and for a time series the history of that spot.
 */
export function SpotCard({ spot, onClose }: { spot: SpotState; onClose: () => void }) {
  const reading = spot.status === "ready" ? spot.reading : null;
  return (
    <section
      aria-label="Reading at the clicked spot"
      aria-live="polite"
      className="pointer-events-auto max-h-[60vh] w-full max-w-[440px] overflow-y-auto rounded-2xl border border-line bg-panel p-4 shadow-card"
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-[15px] tracking-normal text-ink">At this spot</h2>
          <p className="text-[13px] text-ink-3">{coordinates(spot.lon, spot.lat)}</p>
        </div>
        <button
          type="button"
          className="press -mt-1 -mr-1 grid size-9 shrink-0 place-items-center rounded-full text-ink-2 hover:bg-raised hover:text-ink"
          aria-label="Close the reading"
          onClick={onClose}
        >
          <CloseIcon />
        </button>
      </div>

      {spot.status === "loading" ? (
        <p className="mt-3 text-sm text-ink-2" role="status">
          Reading the radar values here
        </p>
      ) : null}

      {spot.status === "error" ? <p className="mt-3 text-sm leading-snug text-ink-2">{spot.message}</p> : null}

      {reading ? (
        <>
          <p className="mt-3 max-w-[65ch] text-[15px] leading-snug text-ink">{reading.sentence}</p>

          {reading.readings.length > 0 ? (
            <dl className="mt-3 divide-y divide-line border-y border-line">
              {reading.readings.map((item) => (
                <div key={item.label} className="flex items-baseline justify-between gap-4 py-2">
                  <dt className="min-w-0 text-sm leading-snug text-ink-2">{item.label}</dt>
                  <dd className="shrink-0 text-right text-sm tabular-nums text-ink">
                    {formatNumber(item.value, item.unit ? 1 : 2)}
                    {item.unit ? ` ${formatUnit(item.unit)}` : ""}
                  </dd>
                </div>
              ))}
            </dl>
          ) : null}

          {reading.common_causes && reading.common_causes.length > 0 ? (
            <div className="mt-3">
              <p className="text-sm text-ink">What often causes a change like this</p>
              <ul className="mt-1 list-disc space-y-0.5 pl-5 text-sm leading-snug text-ink-2">
                {reading.common_causes.map((cause) => (
                  <li key={cause}>{cause}</li>
                ))}
              </ul>
              <p className="mt-1.5 text-[13px] leading-snug text-ink-3">
                These are possibilities to check, not a diagnosis.
              </p>
            </div>
          ) : null}

          {reading.series && reading.series.length > 0 ? (
            <div className="mt-4">
              <p className="mb-2 text-sm text-ink">Radar brightness at this spot on every date</p>
              <SeriesChart series={reading.series} />
            </div>
          ) : null}
        </>
      ) : null}
    </section>
  );
}

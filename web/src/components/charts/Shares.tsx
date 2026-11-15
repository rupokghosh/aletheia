import { formatNumber } from "@/lib/format";
import type { SharesData } from "@/lib/types";
import { DOWN, STEADY, UNKNOWN, UP } from "./palette";

const COLOURS: Record<string, string> = { brighter: UP, darker: DOWN, steady: STEADY, cannot_tell: UNKNOWN };

function percent(share: number): string {
  if (share <= 0) return "0%";
  if (share < 0.001) return "< 0.1%";
  return `${formatNumber(share * 100, share < 0.1 ? 1 : 0)}%`;
}

/** The analysed area as one bar divided into classes, with each class's area and share written out. */
export function Shares({ data }: { data: SharesData }) {
  const total = data.total > 0 ? data.total : data.parts.reduce((sum, part) => sum + part.value, 0);
  if (total <= 0) return null;
  const shown = data.parts.filter((part) => part.value > 0);
  return (
    <div>
      <div className="flex h-3 w-full gap-px overflow-hidden rounded-full" role="img" aria-label={data.parts.map((part) => `${part.label}: ${percent(part.value / total)}`).join(", ")}>
        {shown.map((part) => (
          // A class too small to see at its true width still gets a few pixels, so it is not lost.
          <div key={part.key} style={{ flexGrow: part.value / total, flexBasis: 0, minWidth: 4, background: COLOURS[part.key] ?? STEADY }} />
        ))}
      </div>
      <dl className="mt-3 grid grid-cols-2 gap-x-5 gap-y-2.5">
        {data.parts.map((part) => (
          <div key={part.key} className="flex items-start gap-2">
            <span className="mt-1 inline-block size-2.5 shrink-0 rounded-[3px]" style={{ background: COLOURS[part.key] ?? STEADY }} aria-hidden="true" />
            <div className="min-w-0">
              <dt className="text-[13px] leading-snug text-ink-2">{part.label}</dt>
              <dd className="text-[15px] leading-snug tabular-nums text-ink">
                {formatNumber(part.value, part.value < 10 ? 2 : 1)} km²
                <span className="ml-1.5 text-[13px] text-ink-3">{percent(part.value / total)}</span>
              </dd>
            </div>
          </div>
        ))}
      </dl>
    </div>
  );
}

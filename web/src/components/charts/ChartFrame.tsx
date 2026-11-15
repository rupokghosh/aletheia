import type { ReactNode } from "react";

/** A chart with its title and the one or two sentences that say how to read it. */
export function ChartFrame({ title, description, children }: { title: string; description?: string | null; children: ReactNode }) {
  return (
    <figure className="rounded-2xl border border-line bg-panel p-4">
      <figcaption>
        <p className="text-[15px] tracking-tight text-ink">{title}</p>
        {description ? <p className="mt-0.5 max-w-[65ch] text-[13px] leading-snug text-ink-3">{description}</p> : null}
      </figcaption>
      <div className="mt-3">{children}</div>
    </figure>
  );
}

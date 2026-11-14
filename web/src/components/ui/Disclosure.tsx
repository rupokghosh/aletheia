import type { ReactNode } from "react";
import { ChevronDownIcon } from "./icons";

interface DisclosureProps {
  title: string;
  /** what is inside, in a few words, shown beside the title */
  summary?: string;
  defaultOpen?: boolean;
  children: ReactNode;
}

/** A row that opens: detail that supports a result without crowding it. Closed until asked for. */
export function Disclosure({ title, summary, defaultOpen = false, children }: DisclosureProps) {
  return (
    <details className="group border-t border-line" open={defaultOpen}>
      <summary className="flex min-h-12 items-center justify-between gap-4 py-3 hover:text-black">
        <span className="shrink-0 text-[15px] text-ink">{title}</span>
        <span className="flex min-w-0 items-center gap-2 text-sm text-ink-3">
          {summary ? <span className="truncate">{summary}</span> : null}
          <ChevronDownIcon className="shrink-0 text-ink-2 group-open:rotate-180" />
        </span>
      </summary>
      <div className="pt-1 pb-5">{children}</div>
    </details>
  );
}

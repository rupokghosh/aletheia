import type { ReactNode } from "react";
import { InfoIcon, WarningIcon } from "./icons";

type Tone = "info" | "warn" | "error";

/** A calm inline message. Errors use role="alert"; everything else is a polite status. */
export function Notice({ tone = "info", title, children }: { tone?: Tone; title?: string; children: ReactNode }) {
  const Icon = tone === "info" ? InfoIcon : WarningIcon;
  return (
    <div
      className="flex max-w-[65ch] gap-2.5 rounded-xl bg-raised px-3.5 py-3 text-sm leading-snug text-ink-2"
      role={tone === "error" ? "alert" : "status"}
    >
      <Icon className={`mt-0.5 shrink-0 ${tone === "error" ? "text-danger" : "text-ink"}`} />
      <div className="min-w-0 [overflow-wrap:anywhere]">
        {title ? <p className="text-ink">{title}</p> : null}
        <div>{children}</div>
      </div>
    </div>
  );
}

"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/Button";

/** Whole seconds since `startedAt`, updated once a second. */
function useElapsedSeconds(startedAt: number | null): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  return startedAt === null ? 0 : Math.max(0, Math.floor((now - startedAt) / 1000));
}

interface RunProgressProps {
  description: string;
  /** what to expect while waiting; defaults to the note for a single analysis */
  note?: string;
  startedAt: number | null;
  demo: boolean;
  onCancel: () => void;
}

/**
 * Progress for a request. The server sends no percentage, so this states what was asked and how
 * long it has taken, and does not pretend to know the current stage.
 */
export function RunProgress({
  description,
  note = "This usually takes 5 to 60 seconds. The server does not report progress until it has finished.",
  startedAt,
  demo,
  onCancel,
}: RunProgressProps) {
  const elapsed = useElapsedSeconds(startedAt);
  return (
    <div className="rounded-2xl bg-raised p-4" role="status" aria-live="polite">
      <div className="flex items-baseline justify-between gap-3">
        <p className="text-[15px] text-ink">{demo ? "Preparing a sample result" : "Working"}</p>
        <p className="text-sm text-ink-2">{elapsed} s</p>
      </div>
      <div className="mt-2.5 h-1 overflow-hidden rounded-full bg-raised-2">
        <div className="sweep h-full w-2/5 rounded-full bg-ink" />
      </div>
      <p className="mt-3 max-w-[65ch] text-sm leading-snug text-ink-2">{description}</p>
      <p className="mt-1.5 max-w-[65ch] text-sm leading-snug text-ink-3">{demo ? "Sample data mode: no NISAR file is being read." : note}</p>
      <Button size="sm" className="mt-3" onClick={onCancel}>
        Cancel
      </Button>
    </div>
  );
}

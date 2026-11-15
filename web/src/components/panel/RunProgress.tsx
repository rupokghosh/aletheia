"use client";

import { Button } from "@/components/ui/Button";

interface RunProgressProps {
  description: string;
  /** what is happening while the bar moves; defaults to the note for a single analysis */
  note?: string;
  demo: boolean;
  onCancel: () => void;
}

/**
 * Progress for a request. The server sends no percentage, so this states what was asked and what is
 * being done, and does not pretend to know how far along it is.
 */
export function RunProgress({
  description,
  note = "Reading only the part of each NASA file that covers your area, then measuring it.",
  demo,
  onCancel,
}: RunProgressProps) {
  return (
    <div className="rounded-2xl bg-raised p-4" role="status" aria-live="polite">
      <p className="text-[15px] text-ink">{demo ? "Preparing a sample result" : "Working on it"}</p>
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

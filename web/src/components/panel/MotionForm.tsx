"use client";

import { useId } from "react";
import { Button } from "@/components/ui/Button";
import { Notice } from "@/components/ui/Notice";
import { motionPairs, type StackView } from "@/lib/coverage";
import { daysBetween, formatDate, plural } from "@/lib/format";
import { useApp } from "@/lib/store";
import { useActions } from "@/lib/useActions";
import type { BBox } from "@/lib/types";

/** One pair of dates, from the pairs NASA has already processed. It starts as the newest on the best track. */
export function MotionForm({ bbox, views }: { bbox: BBox; views: StackView[] }) {
  const { state, dispatch } = useApp();
  const actions = useActions();
  const id = useId();
  const pairs = motionPairs(views);

  if (pairs.length === 0) {
    return (
      <Notice>
        Ground motion is read from pairs of dates that NASA has already processed. None cover this area yet, and
        this tool does not build them itself.
      </Notice>
    );
  }

  const { mark, stack } = pairs.find((pair) => pair.mark.granule.granule_id === state.selection.pairId) ?? pairs[0];

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    void actions.runMotion(
      { bbox, reference_date: mark.date, track: stack.track },
      `Searching the catalogue for the pair, reading this area from one pair of images (${formatDate(mark.date)} to ${formatDate(mark.secondaryDate)}), then converting it to ground motion.`,
    );
  };

  return (
    <form onSubmit={submit} className="space-y-3">
      <div>
        <label htmlFor={`${id}-pair`} className="mb-1 block text-sm text-ink-2">
          Pair of dates
        </label>
        <select
          id={`${id}-pair`}
          className="field"
          value={mark.granule.granule_id}
          onChange={(event) => dispatch({ type: "select", selection: { pairId: event.target.value } })}
        >
          {pairs.map((pair) => (
            <option key={pair.mark.granule.granule_id} value={pair.mark.granule.granule_id}>
              {formatDate(pair.mark.date)} to {formatDate(pair.mark.secondaryDate)}, track {pair.stack.track}
              {pair.mark.tier === "beta" ? " (beta)" : ""}
            </option>
          ))}
        </select>
      </div>
      <p className="text-sm text-ink-2">
        {mark.secondaryDate ? `${plural(daysBetween(mark.date, mark.secondaryDate), "day")} apart. ` : ""}
        Only pairs that exist can be chosen.
      </p>
      <Button type="submit" variant="primary">
        Measure ground motion
      </Button>
    </form>
  );
}

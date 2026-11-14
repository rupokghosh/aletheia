"use client";

import { useId, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Notice } from "@/components/ui/Notice";
import { describeStack, resolveChange, type StackView } from "@/lib/coverage";
import { daysBetween, formatDate, formatPercent, plural } from "@/lib/format";
import { TIERS } from "@/lib/tiers";
import { useApp } from "@/lib/store";
import { useActions } from "@/lib/useActions";
import type { BBox, PolarizationChoice } from "@/lib/types";

const POLARIZATIONS: PolarizationChoice[] = ["HH", "HV", "VV", "VH"];

/**
 * Two dates to compare. They start as the first and last calibrated dates of the track that covers
 * the area best; the track and the radar channel are under "Options".
 */
export function ChangeForm({ bbox, views }: { bbox: BBox; views: StackView[] }) {
  const { state, dispatch } = useApp();
  const actions = useActions();
  const id = useId();
  const [polarization, setPolarization] = useState<PolarizationChoice>("auto");
  const choice = resolveChange(views, state.selection);

  if (!choice) {
    return <Notice>Comparing two dates needs two radar images from the same track. This area does not have that yet.</Notice>;
  }

  const { view, before, after } = choice;
  const stacks = views.filter((item) => item.stack.product === "GCOV" && !item.isPair && item.marks.length >= 2);
  const offered = POLARIZATIONS.filter((item) => view.stack.polarizations.includes(item));
  const channel = polarization === "auto" || offered.includes(polarization) ? polarization : "auto";
  const usesBeta = view.marks.some((mark) => (mark.date === before || mark.date === after) && mark.tier === "beta");
  const choose = (patch: { before?: string | null; after?: string | null }) =>
    dispatch({ type: "select", selection: { stackKey: view.key, before, after, ...patch } });

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    if (!before || !after) return;
    void actions.runChange(
      { bbox, date_before: before, date_after: after, track: view.stack.track, polarization: channel },
      `Searching the catalogue for the two images, reading this area from 2 dates (${formatDate(before)} and ${formatDate(after)}), then computing the change map and its statistics.`,
    );
  };

  return (
    <form onSubmit={submit} className="space-y-3">
      <div className="grid grid-cols-2 gap-2.5">
        <div>
          <label htmlFor={`${id}-before`} className="mb-1 block text-sm text-ink-2">
            Before
          </label>
          <select
            id={`${id}-before`}
            className="field"
            value={before ?? ""}
            onChange={(event) => {
              const next = event.target.value || null;
              choose({ before: next, after: next && after && after <= next ? null : after });
            }}
          >
            <option value="">Choose a date</option>
            {view.marks.slice(0, -1).map((mark) => (
              <option key={mark.date} value={mark.date}>
                {formatDate(mark.date)}
                {mark.tier === "beta" ? " (beta)" : ""}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor={`${id}-after`} className="mb-1 block text-sm text-ink-2">
            After
          </label>
          <select id={`${id}-after`} className="field" value={after ?? ""} disabled={!before} onChange={(event) => choose({ after: event.target.value || null })}>
            <option value="">{before ? "Choose a date" : "Choose before first"}</option>
            {view.marks
              .filter((mark) => before !== null && mark.date > before)
              .map((mark) => (
                <option key={mark.date} value={mark.date}>
                  {formatDate(mark.date)}
                  {mark.tier === "beta" ? " (beta)" : ""}
                </option>
              ))}
          </select>
        </div>
      </div>

      <p className="text-sm text-ink-2">
        {before && after ? `${plural(daysBetween(before, after), "day")} apart. ` : ""}
        Only dates NISAR imaged this area can be chosen.
      </p>

      {usesBeta ? (
        <Notice tone="warn">
          One of these dates is beta: {TIERS.beta.meaning.charAt(0).toLowerCase() + TIERS.beta.meaning.slice(1)} A
          difference between a beta date and a calibrated one can come from calibration alone.
        </Notice>
      ) : null}

      <details>
        <summary className="w-max text-sm text-ink-2 underline underline-offset-2 hover:text-ink">Options</summary>
        <div className="mt-2.5 space-y-2.5">
          <div>
            <label htmlFor={`${id}-stack`} className="mb-1 block text-sm text-ink-2">
              Track
            </label>
            <select
              id={`${id}-stack`}
              className="field"
              value={view.key}
              onChange={(event) => dispatch({ type: "select", selection: { stackKey: event.target.value, before: null, after: null } })}
            >
              {stacks.map((item) => (
                <option key={item.key} value={item.key}>
                  {describeStack(item.stack)}, {plural(item.marks.length, "date")}
                  {item.areaShare !== null && item.areaShare < 0.995 ? `, covers ${formatPercent(item.areaShare)} of the area` : ""}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor={`${id}-pol`} className="mb-1 block text-sm text-ink-2">
              Radar channel (polarization)
            </label>
            <select id={`${id}-pol`} className="field" value={channel} onChange={(event) => setPolarization(event.target.value as PolarizationChoice)}>
              <option value="auto">Automatic: the channel with the most signal</option>
              {offered.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </div>
        </div>
      </details>

      <Button type="submit" variant="primary" disabled={!before || !after}>
        Measure the change
      </Button>
    </form>
  );
}

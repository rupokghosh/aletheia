"use client";

import { useId, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Notice } from "@/components/ui/Notice";
import type { StackView } from "@/lib/coverage";
import { formatDate, plural } from "@/lib/format";
import { useActions } from "@/lib/useActions";
import type { BBox } from "@/lib/types";

/** Every date in a range, on every track. The radar channels are under "Options". */
export function TimeSeriesForm({ bbox, views }: { bbox: BBox; views: StackView[] }) {
  const actions = useActions();
  const id = useId();
  const stacks = views.filter((view) => view.stack.product === "GCOV" && !view.isPair);
  const dates = [...new Set(stacks.flatMap((view) => view.marks.map((mark) => mark.date)))].sort();
  const available = [...new Set(stacks.flatMap((view) => view.stack.polarizations))].sort();
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [excluded, setExcluded] = useState<string[]>([]);

  if (dates.length === 0) return <Notice>A time series needs at least one radar image of this area.</Notice>;

  const polarizations = available.filter((item) => !excluded.includes(item));
  const inRange = (date: string) => (!start || date >= start) && (!end || date <= end);
  const count = stacks.reduce((sum, view) => sum + view.marks.filter((mark) => inRange(mark.date)).length, 0);
  const ready = count > 0 && polarizations.length > 0;

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    if (!ready) return;
    void actions.runTimeSeries(
      { bbox, geometry: null, start: start || null, end: end || null, polarizations },
      `Searching the catalogue, reading this area from ${plural(count, "image")}, then computing the mean and spread for each date.`,
    );
  };

  return (
    <form onSubmit={submit} className="space-y-3">
      <div className="grid grid-cols-2 gap-2.5">
        <div>
          <label htmlFor={`${id}-start`} className="mb-1 block text-sm text-ink-2">
            From
          </label>
          <select id={`${id}-start`} className="field" value={start} onChange={(event) => setStart(event.target.value)}>
            <option value="">{formatDate(dates[0])} (first)</option>
            {dates
              .filter((date) => !end || date <= end)
              .map((date) => (
                <option key={date} value={date}>
                  {formatDate(date)}
                </option>
              ))}
          </select>
        </div>
        <div>
          <label htmlFor={`${id}-end`} className="mb-1 block text-sm text-ink-2">
            To
          </label>
          <select id={`${id}-end`} className="field" value={end} onChange={(event) => setEnd(event.target.value)}>
            <option value="">{formatDate(dates[dates.length - 1])} (last)</option>
            {dates
              .filter((date) => !start || date >= start)
              .map((date) => (
                <option key={date} value={date}>
                  {formatDate(date)}
                </option>
              ))}
          </select>
        </div>
      </div>

      <p className="text-sm text-ink-2">Reads {plural(count, "image")}, straight from NASA’s archive.</p>

      <details>
        <summary className="w-max text-sm text-ink-2 underline underline-offset-2 hover:text-ink">Options</summary>
        <fieldset className="mt-2.5">
          <legend className="mb-1.5 text-sm text-ink-2">Radar channels (polarizations)</legend>
          <div className="flex flex-wrap gap-x-5 gap-y-2">
            {available.map((item) => (
              <label key={item} className="flex items-center gap-2 text-sm text-ink">
                <input
                  type="checkbox"
                  checked={!excluded.includes(item)}
                  onChange={(event) => setExcluded(event.target.checked ? excluded.filter((value) => value !== item) : [...excluded, item])}
                />
                {item}
              </label>
            ))}
          </div>
        </fieldset>
      </details>

      <Button type="submit" variant="primary" disabled={!ready}>
        Build the time series
      </Button>
    </form>
  );
}

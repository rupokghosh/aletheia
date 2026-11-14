"use client";

import { useId } from "react";
import { Button } from "@/components/ui/Button";
import { ChevronLeftIcon } from "@/components/ui/icons";
import { plural } from "@/lib/format";
import { activeResult, useApp } from "@/lib/store";
import { ResultView, WORKFLOW_NAMES } from "./ResultView";

/** The results of this session, one open at a time. The open result is the one drawn on the map. */
export function ResultsView() {
  const { state, dispatch } = useApp();
  const selectId = useId();
  const stored = activeResult(state);
  const { investigation } = state;

  if (!stored) {
    return (
      <div className="px-5 pb-6">
        <p className="text-[17px] text-ink">No results yet</p>
        <p className="mt-1.5 max-w-[65ch] text-sm leading-snug text-ink-2">Results appear here after you ask a question or run an analysis.</p>
        <Button className="mt-4" onClick={() => dispatch({ type: "view", view: "home" })}>
          Choose a place
        </Button>
      </div>
    );
  }

  return (
    <>
      <div className="space-y-3 px-5 pb-4">
        <button
          type="button"
          className="flex max-w-full items-center gap-1 text-left text-sm text-ink-2 hover:text-ink"
          onClick={() => dispatch({ type: "view", view: investigation ? "investigation" : "home" })}
        >
          <ChevronLeftIcon className="shrink-0" />
          <span className="truncate">{investigation ? `Back to: ${investigation.question}` : "Back to the area"}</span>
        </button>
        {state.results.length > 1 ? (
          <div>
            <label htmlFor={selectId} className="mb-1 block text-sm text-ink-2">
              {plural(state.results.length, "result")} in this session
            </label>
            <select id={selectId} className="field" value={stored.result.id} onChange={(event) => dispatch({ type: "openResult", id: event.target.value })}>
              {state.results.map(({ result }, index) => (
                <option key={result.id} value={result.id}>
                  {index + 1}. {WORKFLOW_NAMES[result.workflow]}
                  {result.status === "unsupported" ? " (not supported)" : ""}
                  {result.status === "error" ? " (failed)" : ""}
                </option>
              ))}
            </select>
          </div>
        ) : null}
      </div>
      <ResultView key={stored.result.id} stored={stored} />
    </>
  );
}

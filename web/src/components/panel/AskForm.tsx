"use client";

import { useId, useState } from "react";
import { Button } from "@/components/ui/Button";
import { useApp } from "@/lib/store";
import { useActions } from "@/lib/useActions";
import type { BBox } from "@/lib/types";

const EXAMPLE = "How did this lake change between June and October?";

/** The question box: the main thing to do with an area. */
export function AskForm({ bbox }: { bbox: BBox }) {
  const { state } = useApp();
  const actions = useActions();
  const questionId = useId();
  const [question, setQuestion] = useState("");
  const running = state.investigation?.status === "running";
  const ready = question.trim().length >= 8 && !running;

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    if (!ready) return;
    void actions.ask({ question: question.trim(), bbox, place_name: state.placeName });
  };

  return (
    <form onSubmit={submit}>
      <label htmlFor={questionId} className="sr-only">
        Your question about this area
      </label>
      <textarea
        id={questionId}
        className="field min-h-24 resize-y leading-snug"
        placeholder={EXAMPLE}
        value={question}
        maxLength={500}
        onChange={(event) => setQuestion(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) submit(event);
        }}
      />
      <div className="mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-2">
        <Button type="submit" variant="primary" disabled={!ready}>
          {running ? "An investigation is running" : "Ask about this area"}
        </Button>
        {question ? null : (
          <button type="button" className="text-sm text-ink-2 underline underline-offset-2 hover:text-ink" onClick={() => setQuestion(EXAMPLE)}>
            Try the example
          </button>
        )}
      </div>
    </form>
  );
}

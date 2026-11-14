"use client";

import type { ReactNode } from "react";
import { prettyUnits } from "@/lib/format";
import { useApp } from "@/lib/store";
import type { Report } from "@/lib/types";

const escapeForRegex = (text: string) => text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/** A result id as a button that opens that result (or the coverage section, for "coverage"). */
function ResultLink({ id }: { id: string }) {
  const { state, dispatch } = useApp();
  const isResult = state.results.some((stored) => stored.result.id === id);
  return (
    <button
      type="button"
      className="rounded-sm font-mono text-[0.86em] [overflow-wrap:anywhere] text-ink underline underline-offset-2"
      title={isResult ? "Open this result" : "Show what NISAR has here"}
      onClick={() => (isResult ? dispatch({ type: "openResult", id }) : dispatch({ type: "view", view: "home" }))}
    >
      {id}
    </button>
  );
}

/** Text with every known result id turned into a link, wherever it appears in the sentence. */
function Linked({ text, refs }: { text: string; refs: string[] }) {
  const known = refs.filter(Boolean).sort((a, b) => b.length - a.length);
  if (known.length === 0) return text;
  const pattern = new RegExp(`(${known.map(escapeForRegex).join("|")})`, "g");
  return text.split(pattern).map((part, index) => (known.includes(part) ? <ResultLink key={index} id={part} /> : part));
}

/**
 * An observed statement. The API ends each with its result id in square brackets; that id is shown
 * as a labelled source link. Ids mentioned elsewhere in the sentence are linked in place.
 */
function Observed({ text, refs }: { text: string; refs: string[] }) {
  const match = /^([\s\S]*?)\s*\[([^[\]]+)\]\s*$/.exec(text);
  if (!match || !refs.includes(match[2])) return <Linked text={prettyUnits(text)} refs={refs} />;
  return (
    <>
      <Linked text={prettyUnits(match[1])} refs={refs} />{" "}
      <span className="text-ink-3">
        Source: <ResultLink id={match[2]} />
      </span>
    </>
  );
}

/** A hypothesis and, set apart, what would confirm it or rule it out. */
function Explanation({ text }: { text: string }) {
  const [hypothesis, check] = text.split(/\s+To check:\s+/);
  return (
    <>
      {prettyUnits(hypothesis)}
      {check ? (
        <span className="mt-1 block text-sm text-ink-2">To check: {prettyUnits(check)}</span>
      ) : null}
    </>
  );
}

function Part({ title, about, children }: { title: string; about?: string; children: ReactNode }) {
  return (
    <section className="mt-6">
      <h3 className="text-[17px] tracking-tight text-ink">{title}</h3>
      {about ? <p className="mt-0.5 text-sm text-ink-3">{about}</p> : null}
      <div className="mt-2.5">{children}</div>
    </section>
  );
}

function Statements({ items, empty, render }: { items: string[]; empty: string; render: (text: string) => ReactNode }) {
  if (items.length === 0) return <p className="text-sm text-ink-3">{empty}</p>;
  return (
    <ul className="max-w-[65ch] space-y-3">
      {items.map((item, index) => (
        <li key={`${index}-${item}`} className="text-[15px] leading-snug [overflow-wrap:anywhere] text-ink">
          {render(item)}
        </li>
      ))}
    </ul>
  );
}

interface ReportViewProps {
  report: Report;
  /** ids of the results this investigation produced */
  refs: string[];
  /** which language model planned the steps and wrote the report */
  model: string | null;
}

/**
 * The report under four plain headings, kept apart: the answer, what was observed (measured, with
 * links to the results), what might explain it (hypotheses) and what is unknown. Then a small line
 * with the confidence and the model that wrote it.
 */
export function ReportView({ report, refs, model }: ReportViewProps) {
  const confidence = /^\s*(low|medium|high)\b[\s:,.-]*([\s\S]*)$/i.exec(report.confidence);
  const level = confidence?.[1].toLowerCase();
  const reason = confidence ? confidence[2] : report.confidence;

  return (
    <div>
      <Part title="Answer">
        <p className="max-w-[65ch] text-[17px] leading-snug [overflow-wrap:anywhere] text-ink">
          <Linked text={prettyUnits(report.answer)} refs={refs} />
        </p>
      </Part>

      <Part title="Observed" about="Measured from NISAR data.">
        <Statements items={report.observed} empty="Nothing was measured." render={(text) => <Observed text={text} refs={refs} />} />
      </Part>

      <Part title="Possible explanations" about="Hypotheses, not measurements.">
        <Statements
          items={report.possible_explanations}
          empty="None offered: there is no measurement to explain."
          render={(text) => <Explanation text={text} />}
        />
      </Part>

      <Part title="Unknown" about="What this data cannot tell.">
        <Statements items={report.unknown} empty="Nothing listed." render={prettyUnits} />
      </Part>

      <p className="mt-6 max-w-[65ch] border-t border-line pt-3 text-sm leading-snug [overflow-wrap:anywhere] text-ink-2">
        {report.confidence ? (
          <>
            {level ? <span className="text-ink">Confidence: {level}. </span> : <span className="text-ink">Confidence. </span>}
            {reason ? `${reason.charAt(0).toUpperCase()}${reason.slice(1)} ` : ""}
          </>
        ) : null}
        {model ? `Steps chosen and report written by ${model}. ` : ""}
        Every number was computed by the analyses, not by the language model.
      </p>
    </div>
  );
}

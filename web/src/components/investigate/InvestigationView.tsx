"use client";

import { RunProgress } from "@/components/panel/RunProgress";
import { StatsTable } from "@/components/results/StatsTable";
import { Button } from "@/components/ui/Button";
import { Notice } from "@/components/ui/Notice";
import { SourceBadge } from "@/components/ui/SourceBadge";
import { CheckIcon, ChevronLeftIcon, CloseIcon } from "@/components/ui/icons";
import { plural, prettyUnits } from "@/lib/format";
import { useApp, type InvestigationState, type StepResult, type TimelineStep } from "@/lib/store";
import { useActions } from "@/lib/useActions";
import type { JsonObject } from "@/lib/types";
import { Evidence } from "./Evidence";
import { ReportView } from "./ReportView";

/** What a step found, with the way to open it. */
function Finding({ result, other }: { result: StepResult; other: JsonObject | undefined }) {
  const { dispatch } = useApp();
  return (
    <div className="text-sm leading-snug">
      <p className="max-w-[65ch] [overflow-wrap:anywhere] text-ink-2">{prettyUnits(result.headline)}</p>
      {result.kind === "other" ? (
        other ? (
          <details className="mt-1">
            <summary className="w-max text-ink-2 underline underline-offset-2 hover:text-ink">Show the data</summary>
            <div className="mt-2">
              <StatsTable stats={other} />
            </div>
          </details>
        ) : null
      ) : (
        <button
          type="button"
          className="mt-0.5 text-ink underline underline-offset-2"
          onClick={() => (result.kind === "coverage" ? dispatch({ type: "view", view: "home" }) : dispatch({ type: "openResult", id: result.ref }))}
        >
          {result.kind === "coverage" ? "See what NISAR has" : "Open this result"}
        </button>
      )}
    </div>
  );
}

function StepMark({ step, active }: { step: TimelineStep; active: boolean }) {
  if (active) {
    return (
      <span className="mt-1 grid size-4 shrink-0 place-items-center" aria-hidden="true">
        <span className="size-2 rounded-full bg-blue" />
      </span>
    );
  }
  const failed = step.status === "failed";
  return (
    <span
      className={`mt-1 grid size-4 shrink-0 place-items-center rounded-full ${failed ? "bg-danger text-white" : "bg-ink text-white"}`}
      aria-hidden="true"
    >
      {failed ? <CloseIcon width={9} height={9} strokeWidth={2.25} /> : <CheckIcon width={10} height={10} strokeWidth={2.25} />}
    </span>
  );
}

/** The steps as a quiet checklist that fills in as the server reports them. */
function Steps({ investigation }: { investigation: InvestigationState }) {
  const { steps, others } = investigation;
  if (steps.length === 0) return null;

  return (
    <ol className="space-y-3.5" aria-label="Steps taken">
      {steps.map((step, index) => {
        const active = investigation.status === "running" && step.status === "running";
        const state = active
          ? "in progress"
          : step.status === "failed"
            ? "failed"
            : step.status === "retry"
              ? "sent back for revision"
              : step.attempts > 1
                ? `${step.attempts} attempts`
                : null;
        return (
          <li key={`${step.title}-${index}`} className="flex gap-2.5">
            <StepMark step={step} active={active} />
            <div className="min-w-0 space-y-1">
              <p className="text-[15px] leading-snug [overflow-wrap:anywhere] text-ink">
                {step.title}
                {state ? <span className="ml-2 text-sm text-ink-3">{state}</span> : null}
              </p>
              {/* The closing detail of a step repeats the headline of its result, so it is shown only without one. */}
              {step.detail && step.results.length === 0 ? (
                <p className="max-w-[65ch] text-sm leading-snug [overflow-wrap:anywhere] text-ink-2">{prettyUnits(step.detail)}</p>
              ) : null}
              {step.results.map((result) => (
                <Finding key={result.ref} result={result} other={others[result.ref]} />
              ))}
            </div>
          </li>
        );
      })}
    </ol>
  );
}

/** A question, the steps taken to answer it as they arrive, and the report in its separate parts. */
export function InvestigationView() {
  const { state, dispatch } = useApp();
  const actions = useActions();
  const investigation = state.investigation;

  if (!investigation) {
    return (
      <div className="px-5 pb-6">
        <p className="text-[17px] text-ink">No question asked yet</p>
        <p className="mt-1.5 max-w-[65ch] text-sm leading-snug text-ink-2">
          Choose an area and ask a question about it. The steps taken to answer it appear here, followed by the
          report.
        </p>
        <Button className="mt-4" onClick={() => dispatch({ type: "view", view: "home" })}>
          Choose a place
        </Button>
      </div>
    );
  }

  const { status, source, final } = investigation;
  const refs = [...new Set([...Object.keys(final?.results ?? {}), ...investigation.steps.flatMap((step) => step.results.map((r) => r.ref))])];
  const steps = <Steps investigation={investigation} />;

  return (
    <article aria-label="Investigation" className="px-5 pb-6">
      <button type="button" className="flex items-center gap-1 text-sm text-ink-2 hover:text-ink" onClick={() => dispatch({ type: "view", view: "home" })}>
        <ChevronLeftIcon className="shrink-0" />
        Back to the area
      </button>

      <div className="mt-3 flex flex-wrap items-center gap-x-2.5 gap-y-1.5">
        <p className="text-sm text-ink-2">{investigation.placeName ?? "Your question"}</p>
        <SourceBadge source={source} />
      </div>
      <h2 className="mt-1.5 max-w-[65ch] text-2xl [overflow-wrap:anywhere] text-ink">{investigation.question}</h2>
      {source === "demo" ? (
        <div className="mt-3">
          <SourceBadge source={source} detailed />
        </div>
      ) : null}

      {investigation.error ? (
        <div className="mt-4">
          <Notice tone="error" title={final ? "The investigation ended early" : "The investigation stopped"}>
            {investigation.error}
          </Notice>
        </div>
      ) : null}

      {final?.report ? (
        <>
          <ReportView
            report={final.report}
            refs={refs}
            model={final.model}
            evidence={
              <Evidence
                results={state.results.filter((stored) => refs.includes(stored.result.id)).map((stored) => stored.result)}
                others={investigation.others}
              />
            }
          />
          <details className="mt-6 border-t border-line pt-3">
            <summary className="w-max text-[15px] text-ink underline underline-offset-2">
              How this was worked out, in {plural(investigation.steps.length, "step")}
            </summary>
            <div className="mt-4">{steps}</div>
          </details>
        </>
      ) : (
        <section className="mt-6" aria-live="polite">
          {steps}

          {status === "running" ? (
            <div className="mt-5">
              <RunProgress
                description={
                  investigation.steps.length === 0
                    ? "The question has been sent. Steps appear here as they are taken."
                    : "Each step appears above as it starts and again when it ends."
                }
                note="The measuring is done by analysis code; a language model chooses the steps and writes the report from the results."
                demo={source === "demo"}
                onCancel={actions.stopInvestigation}
              />
            </div>
          ) : null}

          {status === "running" && investigation.draft ? (
            <p className="mt-4 max-w-[65ch] text-sm leading-snug whitespace-pre-wrap text-ink-2">{prettyUnits(investigation.draft)}</p>
          ) : null}

          {status === "done" ? (
            <div className="mt-5">
              <Notice>The investigation finished without a report. The results above can still be opened.</Notice>
            </div>
          ) : null}
        </section>
      )}
    </article>
  );
}

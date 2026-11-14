/**
 * Demo-data fixture for POST /api/investigate: a scripted event sequence in the shape of the real
 * stream (see backend/nisar_investigator/agent.py). SAMPLE content only; nothing here is computed
 * from NISAR data and no language model is involved.
 */

import type {
  InvestigateEvent,
  InvestigateRequest,
  Investigation,
  InvestigationResult,
  InvestigationStep,
  JsonObject,
  Report,
} from "@/lib/types";
import { buildDemoCoverage } from "./catalogue";
import { delay } from "./delay";
import { buildDemoChange, buildDemoTimeSeries, buildDemoUnsupported } from "./results";

const UNSUPPORTED_TOPICS = /subsid|sink|uplift|landslide|forecast|predict/i;
const MODEL = "sample script (no language model)";

interface ScriptedTool {
  title: string;
  tool: string;
  input: JsonObject;
  ref: string;
  result: InvestigationResult;
  /** what the step reports when it ends */
  detail: string;
  seconds: number;
}

let counter = 0;

function changeScript(request: InvestigateRequest): { tools: ScriptedTool[]; report: Report } {
  const change = buildDemoChange({
    bbox: request.bbox,
    date_before: "2026-06-19",
    date_after: "2026-10-17",
    track: 77,
    polarization: "auto",
  });
  const series = buildDemoTimeSeries({ bbox: request.bbox, start: "2026-06-01", end: null, polarizations: ["HH", "HV"] });

  return {
    tools: [
      {
        title: "Measuring change between 2026-06-19 and 2026-10-17",
        tool: "run_change",
        input: { date_before: "2026-06-19", date_after: "2026-10-17", track: 77 },
        ref: change.id,
        result: change,
        detail: change.summary.headline,
        seconds: 1.2,
      },
      {
        title: "Building a time series from every available date",
        tool: "run_timeseries",
        input: { start: "2026-06-01", end: null },
        ref: series.id,
        result: series,
        detail: series.summary.headline,
        seconds: 1.2,
      },
    ],
    report: {
      answer:
        "Sample answer: the water-covered area shrank between 19 June and 17 October 2026, by 0.2 to 1.1 km2 of a 7.2 km2 water body.",
      observed: [
        `Between 2026-06-19 and 2026-10-17, 0.2 to 1.1 km2 changed from water to land, central estimate 0.44 km2. [${change.id}]`,
        `Mean HH backscatter over the area rose by 1.2 to 1.8 dB from June to November 2026 on track 77. [${series.id}]`,
        `HV is at the noise floor for 62% of the area and was not used for the change map. [${change.id}]`,
        "NISAR has 30 backscatter acquisitions on two tracks for this area, with none between 2026-01-09 and 2026-06-19. [coverage]",
      ],
      possible_explanations: [
        "Seasonal drawdown: the water level falls after the spring high. To check: a river gauge record with a falling stage over the same months would confirm it; a steady stage would rule it out.",
        "Wind on one of the two dates: rough water returns more signal and can look like land. To check: the steady rise across many dates in the time series makes this less likely; a calm-day acquisition would settle it.",
      ],
      unknown: [
        "The depth or volume of water lost: backscatter shows the extent of the water surface only.",
        "Whether the newly exposed shore is dry ground or wet mud.",
        "What happened between acquisitions, which are 12 days apart.",
      ],
      confidence:
        "medium: the change exceeds the shift of stable reference pixels at every tested threshold, but the later acquisitions carry provisional calibration.",
    },
  };
}

function unsupportedScript(request: InvestigateRequest): { tools: ScriptedTool[]; report: Report } {
  const unsupported = buildDemoUnsupported(request.bbox);
  return {
    tools: [
      {
        title: "Reading ground motion from NASA's interferogram",
        tool: "run_motion",
        input: { reference_date: null, track: null },
        ref: unsupported.id,
        result: unsupported,
        detail: unsupported.summary.headline,
        seconds: 0.9,
      },
    ],
    report: {
      answer: "Sample answer: this question is not supported yet, so no measurement was made.",
      observed: [
        "NISAR has six 12-day ground-motion pairs for this area between August and October 2026. [coverage]",
        `The ground-motion analysis declined the request: slow motion is below what a single pair can resolve. [${unsupported.id}]`,
      ],
      possible_explanations: [],
      unknown: [
        "Whether the ground is moving slowly here. Answering needs a displacement time series built from many interferograms, which this tool does not compute yet.",
      ],
      confidence: "low: no analysis was run, so there is no evidence either way.",
    },
  };
}

export async function* demoInvestigationEvents(
  request: InvestigateRequest,
  signal?: AbortSignal,
): AsyncGenerator<InvestigateEvent, void, undefined> {
  const coverage = buildDemoCoverage({ bbox: request.bbox });
  const script = UNSUPPORTED_TOPICS.test(request.question) ? unsupportedScript(request) : changeScript(request);
  const tools: ScriptedTool[] = [
    {
      title: "Checking what NISAR has for this area",
      tool: "check_coverage",
      input: {},
      ref: "coverage",
      result: coverage,
      detail: `${coverage.products.GCOV?.length ?? 0} backscatter acquisitions in ${coverage.stacks.length} stacks`,
      seconds: 0.7,
    },
    ...script.tools,
  ];

  const steps: InvestigationStep[] = [];
  const results: Record<string, InvestigationResult> = {};
  const blank = (title: string): InvestigationStep => ({ title, detail: "", result_ref: null });

  yield { type: "step", status: "done", step: blank(`Planning with ${MODEL}`) };

  for (const item of tools) {
    await delay(400, signal);
    yield { type: "step", status: "running", step: blank(item.title) };
    yield { type: "tool_call", name: item.tool, input: item.input };
    await delay(item.seconds * 1000, signal);
    const finished: InvestigationStep = { title: item.title, detail: item.detail, result_ref: item.ref };
    steps.push(finished);
    results[item.ref] = item.result;
    yield { type: "tool_result", ref: item.ref, result: item.result };
    yield { type: "step", status: "done", step: finished };
  }

  const writing = "Writing the report";
  await delay(400, signal);
  yield { type: "step", status: "running", step: blank(writing) };
  yield { type: "tool_call", name: "submit_report", input: {} };
  for (const sentence of [script.report.answer, ...script.report.observed]) {
    await delay(200, signal);
    yield { type: "text", delta: `${sentence} ` };
  }
  const accepted: InvestigationStep = { title: writing, detail: "Report accepted", result_ref: null };
  steps.push(accepted);
  yield { type: "step", status: "done", step: accepted };

  counter += 1;
  const investigation: Investigation = {
    id: `inv_demo_${String(counter).padStart(4, "0")}`,
    question: request.question,
    place_name: request.place_name ?? null,
    bbox: request.bbox,
    steps,
    results,
    report: script.report,
    model: MODEL,
  };
  await delay(250, signal);
  yield { type: "done", investigation };
}

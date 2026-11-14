/**
 * Demo-data mode. The API client (src/lib/api.ts) calls these instead of the network when
 * NEXT_PUBLIC_API_URL is unset or the API cannot be reached. Everything returned here is sample
 * data in the exact shape of the contract, and the interface labels it as such.
 *
 * In development only, `?data=worst`, `?data=empty` or `?data=one` in the address swaps the
 * ordinary fixtures for worst-case data (src/mocks/worstCase.ts), to find layout breaks.
 */

import type {
  ChangeRequest,
  Coverage,
  CoverageQuery,
  InvestigateEvent,
  InvestigateRequest,
  MotionRequest,
  TimeSeriesRequest,
  WorkflowResult,
} from "@/lib/types";
import { buildDemoCoverage } from "./catalogue";
import { delay } from "./delay";
import { demoInvestigationEvents } from "./investigation";
import { buildDemoChange, buildDemoMotion, buildDemoTimeSeries } from "./results";
import type { DevDataset } from "./worstCase";

const DEV_DATASETS: DevDataset[] = ["worst", "empty", "one"];

/** The worst-case dataset asked for in the address, or null. Always null in a production build. */
export function devDataset(): DevDataset | null {
  if (process.env.NODE_ENV !== "development") return null;
  const wanted = new URLSearchParams(window.location.search).get("data");
  return DEV_DATASETS.find((name) => name === wanted) ?? null;
}

export async function demoCoverage(query: CoverageQuery, signal?: AbortSignal): Promise<Coverage> {
  await delay(700, signal);
  const dataset = devDataset();
  if (dataset) return (await import("./worstCase")).worstCoverage(query, dataset);
  return buildDemoCoverage(query);
}

export async function demoChange(request: ChangeRequest, signal?: AbortSignal): Promise<WorkflowResult> {
  const dataset = devDataset();
  if (dataset) return (await import("./worstCase")).worstChange(request.bbox, dataset);
  await delay(1800, signal);
  return buildDemoChange(request);
}

export async function demoTimeSeries(request: TimeSeriesRequest, signal?: AbortSignal): Promise<WorkflowResult> {
  const dataset = devDataset();
  if (dataset) return (await import("./worstCase")).worstTimeSeries(request.bbox, dataset);
  await delay(1800, signal);
  return buildDemoTimeSeries(request);
}

export async function demoMotion(request: MotionRequest, signal?: AbortSignal): Promise<WorkflowResult> {
  const dataset = devDataset();
  if (dataset) return (await import("./worstCase")).worstUnsupported(request.bbox);
  await delay(1500, signal);
  return buildDemoMotion(request);
}

export async function* demoInvestigate(
  request: InvestigateRequest,
  signal?: AbortSignal,
): AsyncGenerator<InvestigateEvent, void, undefined> {
  const dataset = devDataset();
  if (dataset) yield* (await import("./worstCase")).worstInvestigation(request, dataset, signal);
  else yield* demoInvestigationEvents(request, signal);
}

/**
 * The one API client. Every request to the backend goes through this file.
 *
 * DEMO-DATA SWITCH
 * ----------------
 * `NEXT_PUBLIC_API_URL` is the base URL of the backend (for example http://localhost:8000).
 *  - Unset or empty: the client starts in demo-data mode and answers from fixtures in src/mocks.
 *  - Set, but the server cannot be reached: the client switches to demo-data mode and says so.
 *  - Set and reachable: every response is live. An HTTP error from a reachable server is shown
 *    as an error and is never replaced by a fixture.
 * Every response carries its `source`, and the interface labels anything that is not "live".
 */

import { readEventStream } from "./sse";
import {
  isInvestigation,
  type ChangeRequest,
  type Coverage,
  type CoverageQuery,
  type InvestigateEvent,
  type InvestigateRequest,
  type InvestigationResult,
  type JsonObject,
  type MotionRequest,
  type StepStatus,
  type TimeSeriesRequest,
  type WorkflowResult,
} from "./types";

export const API_BASE = (process.env.NEXT_PUBLIC_API_URL ?? "").trim().replace(/\/+$/, "");

/** Where a piece of data came from. Only "live" is a measurement made for this request. */
export type DataSource = "live" | "demo" | "showcase";

export interface Sourced<T> {
  data: T;
  source: DataSource;
}

export type DemoReason = "unconfigured" | "unreachable";

export interface ApiMode {
  demo: boolean;
  reason: DemoReason | null;
}

export class ApiError extends Error {
  readonly status: number | null;

  constructor(message: string, status: number | null = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

// ----------------------------------------------------------------- mode

/**
 * Development only: `?data=worst` (or `empty`, `one`) in the address runs the interface on the
 * worst-case fixtures even when an API is configured. Always false in a production build.
 */
const DEV_FIXTURES =
  process.env.NODE_ENV === "development" &&
  typeof window !== "undefined" &&
  new URLSearchParams(window.location.search).has("data");

let mode: ApiMode =
  API_BASE && !DEV_FIXTURES ? { demo: false, reason: null } : { demo: true, reason: "unconfigured" };
const listeners = new Set<() => void>();

function setMode(next: ApiMode): void {
  if (next.demo === mode.demo && next.reason === mode.reason) return;
  mode = next;
  listeners.forEach((listener) => listener());
}

export function getApiMode(): ApiMode {
  return mode;
}

export function subscribeApiMode(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** True when the server answers at all. Uses a no-cors request so CORS policy cannot hide it. */
async function serverAnswers(): Promise<boolean> {
  const timeout = AbortSignal.timeout(5000);
  try {
    await fetch(`${API_BASE}/api/health`, { mode: "no-cors", cache: "no-store", signal: timeout });
    return true;
  } catch {
    return false;
  }
}

/** Checks the configured API and sets the mode. Called once at start and by "Retry". */
export async function checkApi(): Promise<ApiMode> {
  if (!API_BASE || DEV_FIXTURES) return mode;
  const reachable = await serverAnswers();
  setMode(reachable ? { demo: false, reason: null } : { demo: true, reason: "unreachable" });
  return mode;
}

// ------------------------------------------------------------- requests

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

async function errorMessage(response: Response): Promise<string> {
  const fallback = `The API answered ${response.status} ${response.statusText}`.trim();
  try {
    // The API reports problems as {"error": code, "message": sentence}; FastAPI's own errors use "detail".
    const body = asRecord(await response.json());
    if (typeof body?.message === "string") return body.message;
    if (typeof body?.detail === "string") return body.detail;
    if (body?.detail !== undefined) return `${fallback}: ${JSON.stringify(body.detail)}`;
  } catch {
    // The body was not JSON: the status line is the best description available.
  }
  return fallback;
}

/**
 * Sends a request to the live API. Returns null when the client is (or has just switched to)
 * demo-data mode, in which case the caller answers from a fixture.
 */
async function liveFetch(path: string, init: RequestInit): Promise<Response | null> {
  if (mode.demo) return null;
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, init);
  } catch (error) {
    if (isAbort(error)) throw error;
    if (await serverAnswers()) {
      throw new ApiError(
        "The request did not complete. The API is reachable, so this is likely a timeout or a blocked cross-origin request.",
      );
    }
    setMode({ demo: true, reason: "unreachable" });
    return null;
  }
  if (!response.ok) throw new ApiError(await errorMessage(response), response.status);
  return response;
}

async function getJson<T>(path: string, signal: AbortSignal | undefined, demo: () => Promise<T>): Promise<Sourced<T>> {
  const response = await liveFetch(path, { signal, headers: { Accept: "application/json" } });
  if (!response) return { data: await demo(), source: "demo" };
  return { data: (await response.json()) as T, source: "live" };
}

async function postJson<T>(
  path: string,
  body: object,
  signal: AbortSignal | undefined,
  demo: () => Promise<T>,
): Promise<Sourced<T>> {
  const response = await liveFetch(path, {
    method: "POST",
    signal,
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(body),
  });
  if (!response) return { data: await demo(), source: "demo" };
  return { data: (await response.json()) as T, source: "live" };
}

// ------------------------------------------------------------ endpoints

export async function getCoverage(query: CoverageQuery, signal?: AbortSignal): Promise<Sourced<Coverage>> {
  const params =
    "bbox" in query
      ? `bbox=${query.bbox.map((v) => v.toFixed(6)).join(",")}`
      : `lon=${query.lon.toFixed(6)}&lat=${query.lat.toFixed(6)}`;
  return getJson(`/api/coverage?${params}`, signal, async () => {
    const { demoCoverage } = await import("@/mocks");
    return demoCoverage(query, signal);
  });
}

export async function runChange(request: ChangeRequest, signal?: AbortSignal): Promise<Sourced<WorkflowResult>> {
  return postJson("/api/change", request, signal, async () => {
    const { demoChange } = await import("@/mocks");
    return demoChange(request, signal);
  });
}

export async function runTimeSeries(
  request: TimeSeriesRequest,
  signal?: AbortSignal,
): Promise<Sourced<WorkflowResult>> {
  return postJson("/api/timeseries", request, signal, async () => {
    const { demoTimeSeries } = await import("@/mocks");
    return demoTimeSeries(request, signal);
  });
}

export async function runMotion(request: MotionRequest, signal?: AbortSignal): Promise<Sourced<WorkflowResult>> {
  return postJson("/api/motion", request, signal, async () => {
    const { demoMotion } = await import("@/mocks");
    return demoMotion(request, signal);
  });
}

// ---------------------------------------------------------- investigate

function firstString(record: Record<string, unknown> | null, keys: string[]): string | null {
  if (!record) return null;
  for (const key of keys) {
    const value = record[key];
    if (typeof value === "string" && value) return value;
  }
  return null;
}

const STEP_STATUSES: StepStatus[] = ["running", "done", "retry", "failed"];

function asStepStatus(value: unknown): StepStatus {
  return STEP_STATUSES.find((status) => status === value) ?? "done";
}

/**
 * Turns one server-sent event into a typed event. The contract names the events but not every
 * payload field, so this accepts the reasonable spellings and ignores what it cannot read.
 */
function toInvestigateEvent(name: string, raw: string): InvestigateEvent | null {
  let payload: unknown = raw;
  try {
    payload = JSON.parse(raw);
  } catch {
    // Plain-text payloads are valid for `text` and `error`.
  }
  const record = asRecord(payload);

  switch (name) {
    case "step": {
      const title = firstString(record, ["title", "name"]);
      if (!title) return null;
      return {
        type: "step",
        status: asStepStatus(record?.status),
        step: {
          title,
          detail: firstString(record, ["detail", "description"]) ?? "",
          result_ref: firstString(record, ["result_ref"]),
        },
      };
    }
    case "tool_call": {
      const toolName = firstString(record, ["name", "tool"]);
      if (!toolName) return null;
      const input = asRecord(record?.input) ?? asRecord(record?.arguments) ?? {};
      return { type: "tool_call", name: toolName, input: input as JsonObject };
    }
    case "tool_result": {
      // Sent as {name, result_ref, result}. The result is a WorkflowResult, a coverage object or context evidence.
      const result = asRecord(record?.result);
      const ref = firstString(record, ["result_ref", "ref"]) ?? firstString(result, ["id"]);
      if (!result || !ref) return null;
      return { type: "tool_result", ref, result: result as InvestigationResult };
    }
    case "text": {
      const delta = typeof payload === "string" ? payload : firstString(record, ["delta", "text"]);
      return delta ? { type: "text", delta } : null;
    }
    case "done": {
      const investigation = isInvestigation(record?.investigation) ? record.investigation : payload;
      return isInvestigation(investigation) ? { type: "done", investigation } : null;
    }
    case "error": {
      const message =
        typeof payload === "string" ? payload : firstString(record, ["message", "detail", "error"]);
      return { type: "error", message: message ?? "The investigation failed without a message." };
    }
    default:
      return null;
  }
}

/** Streams the events of one investigation. Each event says whether it is live or demo data. */
export async function* investigate(
  request: InvestigateRequest,
  signal?: AbortSignal,
): AsyncGenerator<Sourced<InvestigateEvent>, void, undefined> {
  const response = await liveFetch("/api/investigate", {
    method: "POST",
    signal,
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify(request),
  });

  if (!response) {
    const { demoInvestigate } = await import("@/mocks");
    for await (const event of demoInvestigate(request, signal)) yield { data: event, source: "demo" };
    return;
  }
  if (!response.body) throw new ApiError("The API returned an empty stream.");

  for await (const message of readEventStream(response.body)) {
    const event = toInvestigateEvent(message.event, message.data);
    if (event) yield { data: event, source: "live" };
  }
}

// ------------------------------------------------------------ artifacts

/**
 * Resolves a layer or download URL from a result.
 *  - absolute URLs are returned unchanged;
 *  - demo fixtures map /api/artifacts/<id>/<file> to the static files in public/demo-artifacts;
 *  - /api/... paths are resolved against the API base;
 *  - anything else (for example /showcases/...) is a static file of this site.
 */
export function resolveArtifactUrl(url: string, source: DataSource): string {
  if (/^(https?:|data:|blob:)/.test(url)) return url;
  if (source === "demo") return url.replace(/^\/api\/artifacts\/[^/]+\//, "/demo-artifacts/");
  if (url.startsWith("/api/")) return `${API_BASE}${url}`;
  return url;
}

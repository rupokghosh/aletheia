"use client";

/** Network actions: everything that calls the API client and feeds the result into the store. */

import { useEffect, useEffectEvent, useMemo, useSyncExternalStore } from "react";
import {
  EXAMPLES_ONLY,
  ApiError,
  checkApi,
  getApiMode,
  getCoverage,
  investigate,
  runChange,
  runMotion,
  runTimeSeries,
  subscribeApiMode,
  type ApiMode,
  type Sourced,
  getCanAsk,
  subscribeCanAsk,
} from "./api";
import { bboxKey } from "./geo";
import { useApp } from "./store";
import type {
  ChangeRequest,
  InvestigateRequest,
  MotionRequest,
  TimeSeriesRequest,
  WorkflowKind,
  WorkflowResult,
} from "./types";

/** Requests in flight. Module scope so "Cancel" still works after the panel view changes. */
const inFlight: { run: AbortController | null; investigation: AbortController | null } = {
  run: null,
  investigation: null,
};

function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

function describe(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "The request failed for an unknown reason.";
}

const SERVER_MODE: ApiMode = { demo: false, reason: null };

export function useApiMode(): ApiMode {
  return useSyncExternalStore(subscribeApiMode, getApiMode, () => SERVER_MODE);
}

/** Whether the server behind the API can answer questions asked in plain language. */
export function useCanAsk(): boolean {
  return useSyncExternalStore(subscribeCanAsk, getCanAsk, () => true);
}

/** Checks once, at start, whether the configured API answers. */
export function useApiCheck(): void {
  useEffect(() => {
    void checkApi();
  }, []);
}

/** Loads coverage whenever the area changes. A short wait absorbs typing in the coordinate fields. */
export function useCoverageLoader(): void {
  const { state, dispatch } = useApp();
  const { bbox, coverage } = state;
  const isLoaded = useEffectEvent((key: string) => coverage.key === key && coverage.status !== "error");

  useEffect(() => {
    if (!bbox || EXAMPLES_ONLY) return;
    const key = bboxKey(bbox);
    if (isLoaded(key)) return;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      dispatch({ type: "coverageLoading", key });
      getCoverage({ bbox }, controller.signal)
        .then(({ data, source }) => dispatch({ type: "coverageLoaded", key, data, source }))
        .catch((error: unknown) => {
          if (!isAbort(error)) dispatch({ type: "coverageFailed", key, error: describe(error) });
        });
    }, 350);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [bbox, dispatch]);
}

export function useActions() {
  const { dispatch } = useApp();

  return useMemo(() => {
    const run = async (
      kind: WorkflowKind,
      description: string,
      call: (signal: AbortSignal) => Promise<Sourced<WorkflowResult>>,
    ) => {
      inFlight.run?.abort();
      const controller = new AbortController();
      inFlight.run = controller;
      dispatch({ type: "runStarted", kind, description });
      try {
        const { data, source } = await call(controller.signal);
        if (inFlight.run === controller) {
          dispatch({ type: "resultAdded", stored: { result: data, source }, open: true });
        }
      } catch (error) {
        if (inFlight.run !== controller) return;
        dispatch(isAbort(error) ? { type: "runCleared" } : { type: "runFailed", error: describe(error) });
      } finally {
        if (inFlight.run === controller) inFlight.run = null;
      }
    };

    return {
      runChange: (request: ChangeRequest, description: string) =>
        run("change", description, (signal) => runChange(request, signal)),
      runTimeSeries: (request: TimeSeriesRequest, description: string) =>
        run("timeseries", description, (signal) => runTimeSeries(request, signal)),
      runMotion: (request: MotionRequest, description: string) =>
        run("motion", description, (signal) => runMotion(request, signal)),
      cancelRun: () => {
        inFlight.run?.abort();
        inFlight.run = null;
        dispatch({ type: "runCleared" });
      },

      ask: async (request: InvestigateRequest) => {
        inFlight.investigation?.abort();
        const controller = new AbortController();
        inFlight.investigation = controller;
        dispatch({
          type: "investigationStarted",
          question: request.question,
          placeName: request.place_name ?? null,
          bbox: request.bbox,
          source: getApiMode().demo ? "demo" : "live",
        });
        try {
          let finished = false;
          for await (const { data, source } of investigate(request, controller.signal)) {
            if (inFlight.investigation !== controller) return;
            dispatch({ type: "investigationEvent", event: data, source });
            if (data.type === "done" || data.type === "error") finished = true;
          }
          if (!finished && inFlight.investigation === controller) {
            dispatch({
              type: "investigationFailed",
              error: "The stream ended before the report was complete.",
            });
          }
        } catch (error) {
          if (inFlight.investigation !== controller) return;
          dispatch({
            type: "investigationFailed",
            error: isAbort(error) ? "Stopped before the report was complete." : describe(error),
          });
        } finally {
          if (inFlight.investigation === controller) inFlight.investigation = null;
        }
      },
      stopInvestigation: () => inFlight.investigation?.abort(),
    };
  }, [dispatch]);
}

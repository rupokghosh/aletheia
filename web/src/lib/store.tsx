"use client";

/** Application state: one reducer, read through `useApp()`. Network calls live in useActions.ts. */

import { createContext, useContext, useMemo, useReducer, type Dispatch, type ReactNode } from "react";
import type { DataSource } from "./api";
import { plural } from "./format";
import { bboxKey } from "./geo";
import { initialDisplay, type LayerSetting, type ResultDisplay } from "./layers";
import type {
  BBox,
  Coverage,
  InvestigateEvent,
  Investigation,
  InvestigationResult,
  InvestigationStep,
  JsonObject,
  StepStatus,
  WorkflowKind,
  WorkflowResult,
} from "./types";
import { isCoverage, isWorkflowResult } from "./types";

/** "home" is the one working view: choose a place, see what NISAR has, ask or analyse. */
export type PanelView = "home" | "investigation" | "results";
/** The two things the Results tab can show: an investigation with its report, or a single result. */
export type Reading = "investigation" | "results";
export type AnalysisTab = "ask" | WorkflowKind;

export interface StoredResult {
  result: WorkflowResult;
  source: DataSource;
}

export interface CoverageState {
  status: "idle" | "loading" | "ready" | "error";
  /** bbox key the coverage belongs to */
  key: string | null;
  data: Coverage | null;
  source: DataSource | null;
  error: string | null;
}

export interface Selection {
  /** GCOV stack chosen for the change workflow */
  stackKey: string | null;
  before: string | null;
  after: string | null;
  /** GUNW granule chosen for the ground-motion workflow */
  pairId: string | null;
}

export interface RunState {
  status: "idle" | "running" | "error";
  kind: WorkflowKind | null;
  /** plain description of what the server was asked to do */
  description: string;
  startedAt: number | null;
  error: string | null;
}

/** A result attached to a step of an investigation. */
export interface StepResult {
  ref: string;
  /** "other" is context evidence or anything else that is not a coverage object or a workflow result */
  kind: "coverage" | "workflow" | "other";
  headline: string;
}

/** One step of an investigation with the tool calls and results that belong to it. */
export interface TimelineStep {
  title: string;
  detail: string;
  status: StepStatus;
  /** how many times the step was started: more than one when it was sent back and tried again */
  attempts: number;
  calls: Array<{ name: string; input: JsonObject }>;
  results: StepResult[];
}

export interface InvestigationState {
  status: "running" | "done" | "error";
  source: DataSource;
  question: string;
  placeName: string | null;
  bbox: BBox;
  steps: TimelineStep[];
  /** results that are neither coverage nor a workflow result, by reference */
  others: Record<string, JsonObject>;
  /** report text as it streams, before the structured report arrives */
  draft: string;
  final: Investigation | null;
  error: string | null;
  startedAt: number;
}

export interface GibsState {
  enabled: boolean;
  /** the last day shown */
  date: string;
  /** how many days up to `date` are stacked: 12 covers the planet once, 1 shows a single day's passes */
  days: number;
  opacity: number;
}

export interface FlyTarget {
  bbox: BBox;
  nonce: number;
}

export interface AppState {
  view: PanelView;
  /** what the Results tab opens on: whichever of the two was read last */
  reading: Reading;
  panelOpen: boolean;
  bbox: BBox | null;
  placeName: string | null;
  drawing: boolean;
  coverage: CoverageState;
  analysisTab: AnalysisTab;
  selection: Selection;
  run: RunState;
  results: StoredResult[];
  displays: Record<string, ResultDisplay>;
  activeResultId: string | null;
  investigation: InvestigationState | null;
  gibs: GibsState;
  flyTo: FlyTarget | null;
}

export type Action =
  | { type: "view"; view: PanelView }
  | { type: "panel"; open: boolean }
  | { type: "area"; bbox: BBox; placeName?: string | null }
  | { type: "placeName"; placeName: string | null }
  | { type: "clearArea" }
  | { type: "drawing"; drawing: boolean }
  | { type: "coverageLoading"; key: string }
  | { type: "coverageLoaded"; key: string; data: Coverage; source: DataSource }
  | { type: "coverageFailed"; key: string; error: string }
  | { type: "analysisTab"; tab: AnalysisTab }
  | { type: "select"; selection: Partial<Selection> }
  | { type: "pickDate"; stackKey: string; date: string }
  | { type: "runStarted"; kind: WorkflowKind; description: string }
  | { type: "runFailed"; error: string }
  | { type: "runCleared" }
  | { type: "resultAdded"; stored: StoredResult; open: boolean }
  | { type: "openResult"; id: string }
  | { type: "layer"; resultId: string; layerId: string; setting: Partial<LayerSetting> }
  | { type: "display"; resultId: string; display: Partial<Omit<ResultDisplay, "layers">> }
  | { type: "investigationStarted"; question: string; placeName: string | null; bbox: BBox; source: DataSource }
  | { type: "investigationEvent"; event: InvestigateEvent; source: DataSource }
  | { type: "investigationFailed"; error: string }
  | { type: "investigationOpened"; investigation: Investigation; source: DataSource }
  | { type: "gibs"; gibs: Partial<GibsState> }
  | { type: "flyTo"; bbox: BBox };

const IDLE_RUN: RunState = { status: "idle", kind: null, description: "", startedAt: null, error: null };
const EMPTY_SELECTION: Selection = { stackKey: null, before: null, after: null, pairId: null };
const NO_COVERAGE: CoverageState = { status: "idle", key: null, data: null, source: null, error: null };

/**
 * The last day of the radar picture shown at the start. NASA's daily pictures keep filling in for about
 * two weeks after a pass, so the most recent complete 12-day sweep of the planet ends two weeks back.
 */
function latestCompleteDay(): string {
  // Snapped to a 7-day grid (days since 1970, UTC) so the server's cached tiles stay valid for a week.
  // The server computes the same day (default_end in backend/nisar_investigator/radar_tiles.py).
  const day = Math.floor(Date.now() / 86_400_000) - 14;
  return new Date((day - (day % 7)) * 86_400_000).toISOString().slice(0, 10);
}

function initialState(): AppState {
  return {
    view: "home",
    reading: "results",
    panelOpen: true,
    bbox: null,
    placeName: null,
    drawing: false,
    coverage: NO_COVERAGE,
    analysisTab: "ask",
    selection: EMPTY_SELECTION,
    run: IDLE_RUN,
    results: [],
    displays: {},
    activeResultId: null,
    investigation: null,
    gibs: { enabled: true, date: latestCompleteDay(), days: 12, opacity: 0.85 },
    flyTo: null,
  };
}

function withResult(state: AppState, stored: StoredResult): Pick<AppState, "results" | "displays"> {
  const exists = state.results.some((r) => r.result.id === stored.result.id);
  return {
    results: exists
      ? state.results.map((r) => (r.result.id === stored.result.id ? stored : r))
      : [...state.results, stored],
    displays: exists
      ? state.displays
      : { ...state.displays, [stored.result.id]: initialDisplay(stored.result) },
  };
}

function nextFly(state: AppState, bbox: BBox): FlyTarget {
  return { bbox, nonce: (state.flyTo?.nonce ?? 0) + 1 };
}

function pickDate(selection: Selection, stackKey: string, date: string): Selection {
  if (selection.stackKey !== stackKey || (selection.before && selection.after)) {
    return { ...selection, stackKey, before: date, after: null };
  }
  if (!selection.before) return { ...selection, before: date };
  if (date === selection.before) return { ...selection, before: null };
  return date < selection.before
    ? { ...selection, before: date, after: selection.before }
    : { ...selection, after: date };
}

function describeResult(ref: string, value: InvestigationResult): StepResult {
  if (isWorkflowResult(value)) return { ref: value.id, kind: "workflow", headline: value.summary.headline };
  if (isCoverage(value)) {
    return { ref, kind: "coverage", headline: `${plural(value.stacks.length, "stack")} of acquisitions found` };
  }
  // A workflow that is not available on the server answers with a bare {id, status, summary}.
  const summary = (value as JsonObject).summary;
  const headline =
    typeof summary === "object" && summary !== null && !Array.isArray(summary) && typeof summary.headline === "string"
      ? summary.headline
      : typeof value.source === "string"
        ? value.source
        : "Additional evidence";
  return { ref, kind: "other", headline };
}

const blankStep = (title: string): TimelineStep => ({
  title,
  detail: "",
  status: "running",
  attempts: 1,
  calls: [],
  results: [],
});

/** Applies `change` to the step in progress, starting one if the stream has not announced any. */
function withOpenStep(steps: TimelineStep[], change: (step: TimelineStep) => TimelineStep): TimelineStep[] {
  const list = steps.length > 0 ? steps : [blankStep("Started")];
  return [...list.slice(0, -1), change(list[list.length - 1])];
}

function applyStep(steps: TimelineStep[], step: InvestigationStep, status: StepStatus): TimelineStep[] {
  const last = steps[steps.length - 1];
  if (status === "running") {
    // A step that was sent back for revision and starts again stays one row, with its attempts counted.
    if (last && last.title === step.title && last.status === "retry") {
      return [...steps.slice(0, -1), { ...last, status, attempts: last.attempts + 1 }];
    }
    return [...steps, blankStep(step.title)];
  }
  // A step is announced as "running" and reported again when it ends: the second event updates the first.
  const open = steps.findLastIndex((s) => s.title === step.title && s.status === "running");
  if (open === -1) return [...steps, { ...blankStep(step.title), detail: step.detail, status }];
  return steps.map((s, index) => (index === open ? { ...s, detail: step.detail || s.detail, status } : s));
}

function applyInvestigationEvent(state: AppState, event: InvestigateEvent, source: DataSource): AppState {
  const current = state.investigation;
  if (!current) return state;
  const investigation: InvestigationState = { ...current, source };

  switch (event.type) {
    case "step":
      investigation.steps = applyStep(current.steps, event.step, event.status);
      return { ...state, investigation };
    case "tool_call":
      investigation.steps = withOpenStep(current.steps, (step) => ({
        ...step,
        calls: [...step.calls, { name: event.name, input: event.input }],
      }));
      return { ...state, investigation };
    case "tool_result": {
      const described = describeResult(event.ref, event.result);
      investigation.steps = withOpenStep(current.steps, (step) => ({ ...step, results: [...step.results, described] }));
      if (isWorkflowResult(event.result)) {
        return {
          ...state,
          investigation,
          ...withResult(state, { result: event.result, source }),
          // The newest result with layers goes on the map as soon as it arrives.
          activeResultId: event.result.layers.length > 0 ? event.result.id : state.activeResultId,
        };
      }
      if (described.kind === "other") investigation.others = { ...current.others, [event.ref]: event.result as JsonObject };
      return { ...state, investigation };
    }
    case "text":
      investigation.draft = current.draft + event.delta;
      return { ...state, investigation };
    case "done": {
      investigation.status = "done";
      investigation.final = event.investigation;
      let next: AppState = { ...state, investigation };
      for (const value of Object.values(event.investigation.results)) {
        if (isWorkflowResult(value)) next = { ...next, ...withResult(next, { result: value, source }) };
      }
      return next;
    }
    case "error":
      investigation.status = "error";
      investigation.error = event.message;
      return { ...state, investigation };
  }
}

function openInvestigation(state: AppState, final: Investigation, source: DataSource): AppState {
  let next: AppState = state;
  const others: Record<string, JsonObject> = {};
  const steps: TimelineStep[] = final.steps.map((step) => {
    const value = step.result_ref ? final.results[step.result_ref] : undefined;
    const results = step.result_ref && value ? [describeResult(step.result_ref, value)] : [];
    if (step.result_ref && value && results[0].kind === "other") others[step.result_ref] = value as JsonObject;
    return {
      title: step.title,
      detail: step.detail,
      status: step.detail.startsWith("Failed:") ? "failed" : "done",
      attempts: 1,
      calls: [],
      results,
    };
  });
  const workflowResults = Object.values(final.results).filter(isWorkflowResult);
  for (const result of workflowResults) next = { ...next, ...withResult(next, { result, source }) };
  const included = Object.values(final.results).find(isCoverage);
  return {
    ...next,
    activeResultId: workflowResults.find((result) => result.layers.length > 0)?.id ?? next.activeResultId,
    coverage: included
      ? { status: "ready", key: bboxKey(final.bbox), data: included, source, error: null }
      : next.coverage,
    view: "investigation",
    reading: "investigation",
    bbox: final.bbox,
    placeName: final.place_name,
    drawing: false,
    selection: EMPTY_SELECTION,
    flyTo: nextFly(state, final.bbox),
    investigation: {
      status: "done",
      source,
      question: final.question,
      placeName: final.place_name,
      bbox: final.bbox,
      steps,
      others,
      draft: "",
      final,
      error: null,
      startedAt: Date.now(),
    },
  };
}

function reducer(state: AppState, action: Action): AppState {
  switch (action.type) {
    case "view":
      return {
        ...state,
        view: action.view,
        reading: action.view === "investigation" || action.view === "results" ? action.view : state.reading,
        panelOpen: true,
      };
    case "panel":
      return { ...state, panelOpen: action.open };
    case "area":
      return {
        ...state,
        bbox: action.bbox,
        placeName: action.placeName === undefined ? state.placeName : action.placeName,
        drawing: false,
        selection: EMPTY_SELECTION,
      };
    case "placeName":
      return { ...state, placeName: action.placeName };
    case "clearArea":
      return { ...state, bbox: null, drawing: false, coverage: NO_COVERAGE, selection: EMPTY_SELECTION };
    case "drawing":
      return { ...state, drawing: action.drawing };
    case "coverageLoading":
      return { ...state, coverage: { status: "loading", key: action.key, data: null, source: null, error: null } };
    case "coverageLoaded":
      if (state.coverage.key !== action.key) return state;
      return {
        ...state,
        coverage: { status: "ready", key: action.key, data: action.data, source: action.source, error: null },
      };
    case "coverageFailed":
      if (state.coverage.key !== action.key) return state;
      return { ...state, coverage: { status: "error", key: action.key, data: null, source: null, error: action.error } };
    case "analysisTab":
      return { ...state, analysisTab: action.tab, run: state.run.status === "error" ? IDLE_RUN : state.run };
    case "select":
      return { ...state, selection: { ...state.selection, ...action.selection } };
    case "pickDate":
      return { ...state, selection: pickDate(state.selection, action.stackKey, action.date) };
    case "runStarted":
      return {
        ...state,
        run: { status: "running", kind: action.kind, description: action.description, startedAt: Date.now(), error: null },
      };
    case "runFailed":
      return { ...state, run: { ...state.run, status: "error", error: action.error } };
    case "runCleared":
      return { ...state, run: IDLE_RUN };
    case "resultAdded":
      return {
        ...state,
        ...withResult(state, action.stored),
        run: IDLE_RUN,
        activeResultId: action.open ? action.stored.result.id : state.activeResultId,
        view: action.open ? "results" : state.view,
        reading: action.open ? "results" : state.reading,
      };
    case "openResult":
      return { ...state, activeResultId: action.id, view: "results", reading: "results", panelOpen: true };
    case "layer": {
      const display = state.displays[action.resultId];
      if (!display) return state;
      const current = display.layers[action.layerId] ?? { visible: false, opacity: 0.9 };
      return {
        ...state,
        displays: {
          ...state.displays,
          [action.resultId]: {
            ...display,
            layers: { ...display.layers, [action.layerId]: { ...current, ...action.setting } },
          },
        },
      };
    }
    case "display": {
      const display = state.displays[action.resultId];
      const stored = state.results.find((r) => r.result.id === action.resultId);
      if (!display || !stored) return state;
      let layers = display.layers;
      // Entering compare hides the other layers so the two dates are not covered; leaving restores defaults.
      if (action.display.compare !== undefined && action.display.compare !== display.compare) {
        layers = action.display.compare
          ? Object.fromEntries(
              stored.result.layers.map((layer) => [
                layer.id,
                { ...(display.layers[layer.id] ?? { opacity: 0.9 }), visible: false },
              ]),
            )
          : initialDisplay(stored.result).layers;
      }
      return {
        ...state,
        displays: { ...state.displays, [action.resultId]: { ...display, ...action.display, layers } },
      };
    }
    case "investigationStarted":
      return {
        ...state,
        view: "investigation",
        reading: "investigation",
        investigation: {
          status: "running",
          source: action.source,
          question: action.question,
          placeName: action.placeName,
          bbox: action.bbox,
          steps: [],
          others: {},
          draft: "",
          final: null,
          error: null,
          startedAt: Date.now(),
        },
      };
    case "investigationEvent":
      return applyInvestigationEvent(state, action.event, action.source);
    case "investigationFailed":
      return state.investigation
        ? { ...state, investigation: { ...state.investigation, status: "error", error: action.error } }
        : state;
    case "investigationOpened":
      return openInvestigation(state, action.investigation, action.source);
    case "gibs":
      return { ...state, gibs: { ...state.gibs, ...action.gibs } };
    case "flyTo":
      return { ...state, flyTo: nextFly(state, action.bbox) };
  }
}

interface AppContextValue {
  state: AppState;
  dispatch: Dispatch<Action>;
}

const AppContext = createContext<AppContextValue | null>(null);

export function AppProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(reducer, undefined, initialState);
  const value = useMemo(() => ({ state, dispatch }), [state]);
  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}

export function useApp(): AppContextValue {
  const value = useContext(AppContext);
  if (!value) throw new Error("useApp must be used inside AppProvider");
  return value;
}

/** The open result: the one chosen, or the most recent when none has been chosen. */
export function activeResult(state: AppState): StoredResult | null {
  return (
    state.results.find((r) => r.result.id === state.activeResultId) ?? state.results[state.results.length - 1] ?? null
  );
}

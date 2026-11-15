/**
 * API contract types. These mirror backend/nisar_investigator/schemas.py field for field.
 * When the pydantic models change, change this file to match.
 */

export type Tier = "validated" | "provisional" | "beta";
export type Direction = "ascending" | "descending";
/** west, south, east, north (WGS84 degrees) */
export type BBox = [number, number, number, number];
/** lon, lat */
export type LonLat = [number, number];

/** Values the backend types as `Any`: valid JSON, shape not fixed by the contract. */
export type JsonValue = string | number | boolean | null | JsonValue[] | { [key: string]: JsonValue };
export type JsonObject = { [key: string]: JsonValue };

// ---------------------------------------------------------------- catalogue

export interface Granule {
  granule_id: string;
  /** GCOV, GUNW, GOFF, SME2 */
  product: string;
  tier: Tier;
  url: string;
  size_gb: number | null;
  track: number;
  frame: number;
  direction: Direction;
  mode: string;
  /** frequency A */
  polarizations: string[];
  /** single-date products */
  date: string | null;
  start_time: string | null;
  /** pair products (GUNW, GOFF) */
  reference_date: string | null;
  secondary_date: string | null;
  footprint: LonLat[];
}

/** Acquisitions that share track, direction and frame, so their pixel grids line up. */
export interface Stack {
  product: string;
  track: number;
  direction: Direction;
  frame: number;
  dates: string[];
  tiers: Record<string, number>;
  polarizations: string[];
}

export interface Coverage {
  query: JsonObject;
  products: Record<string, Granule[]>;
  stacks: Stack[];
  notes: string[];
}

// ------------------------------------------------------------------ results

export interface Metric {
  key: string;
  label: string;
  unit: string;
  central: number | null;
  low: number | null;
  high: number | null;
}

export interface Summary {
  headline: string;
  metrics: Metric[];
}

export interface LegendClass {
  label: string;
  /** "#rrggbb" */
  color: string;
  /** the precise definition behind the plain label, for example "Brighter by at least 2.4 dB" */
  detail?: string;
}

export interface Legend {
  type: "continuous" | "categorical";
  unit: string;
  min: number | null;
  max: number | null;
  colormap: string | null;
  classes: LegendClass[];
  /** plain-language captions for the two ends of a continuous scale */
  min_label?: string | null;
  max_label?: string | null;
}

export interface Layer {
  id: string;
  title: string;
  kind: "image";
  url: string;
  /** top-left, top-right, bottom-right, bottom-left (lon, lat) */
  corners: LonLat[];
  legend: Legend | null;
  default_visible: boolean;
  date: string | null;
  /** one or two sentences: what this layer shows and what its colours mean */
  description?: string | null;
  /** the precise name, for specialists */
  technical_title?: string | null;
  /** "advanced" layers are kept behind "More layers" */
  group?: "main" | "advanced";
}

/** What a result says at one spot: GET /api/results/{id}/point */
export interface PointReading {
  result_id: string;
  workflow: WorkflowKind;
  lon: number;
  lat: number;
  /** the reading in one plain sentence */
  sentence: string;
  readings: Array<{ label: string; value: number; unit: string; note: string }>;
  common_causes?: string[];
  causes_note?: string;
  /** time-series results: the history of this spot */
  series?: Series[];
}

export interface SeriesPoint {
  date: string;
  value: number | null;
  spread: number | null;
  tier: Tier | null;
  granule_id: string | null;
}

export interface Series {
  id: string;
  label: string;
  unit: string;
  track: number | null;
  direction: Direction | null;
  polarization: string | null;
  points: SeriesPoint[];
}

export interface Sensitivity {
  parameter: string;
  value: number | string;
  result: number | null;
  unit: string;
}

export interface Uncertainty {
  method: string;
  sensitivity: Sensitivity[];
  noise_floor_fraction: number | null;
  notes: string[];
}

export interface Caveat {
  code: string;
  text: string;
}

export interface ReceiptStep {
  name: string;
  params: JsonObject;
  seconds: number | null;
}

export interface ReceiptGranule {
  granule_id: string;
  url: string;
  tier: Tier;
  product: string;
  date: string | null;
  reference_date: string | null;
  secondary_date: string | null;
  track: number;
  frame: number;
  direction: Direction;
  polarizations: string[];
}

export interface Receipt {
  granules: ReceiptGranule[];
  steps: ReceiptStep[];
  software: Record<string, string>;
  generated_at: string;
  reproduce: string;
}

export interface Download {
  label: string;
  url: string;
  format: string;
}

export type WorkflowKind = "change" | "timeseries" | "motion";
export type WorkflowStatus = "ok" | "unsupported" | "error";

/** Area per step of a measured quantity. `band` is the span that cannot be told from no change. */
export interface HistogramData {
  unit: string;
  edges: number[];
  area_km2: number[];
  band: [number, number];
  band_label: string;
  low_label: string;
  high_label: string;
}

/** How the analysed area divides into classes. */
export interface SharesData {
  unit: string;
  total: number;
  parts: Array<{ key: string; label: string; value: number }>;
}

/** The typical value across the area along one compass direction, with the spread across it. */
export interface ProfileData {
  unit: string;
  x_unit: string;
  x: Array<number | null>;
  y: Array<number | null>;
  low: Array<number | null>;
  high: Array<number | null>;
  band: [number, number];
  band_label: string;
  start: string;
  end: string;
}

interface ChartBase {
  id: string;
  title: string;
  /** one or two sentences on how to read it */
  description: string | null;
}

/** Numbers for one small chart shown with a result, computed by the API from the result's own arrays. */
export type Chart =
  | (ChartBase & { kind: "histogram"; data: HistogramData })
  | (ChartBase & { kind: "shares"; data: SharesData })
  | (ChartBase & { kind: "profile"; data: ProfileData });

export interface WorkflowResult {
  id: string;
  workflow: WorkflowKind;
  status: WorkflowStatus;
  request: JsonObject;
  summary: Summary;
  layers: Layer[];
  series: Series[];
  /** absent in results stored by older builds */
  charts?: Chart[];
  stats: JsonObject;
  uncertainty: Uncertainty | null;
  caveats: Caveat[];
  receipt: Receipt;
  downloads: Download[];
}

// ----------------------------------------------------------------- requests

export type PolarizationChoice = "auto" | "HH" | "HV" | "VV" | "VH";

export interface ChangeRequest {
  bbox: BBox;
  date_before: string;
  date_after: string;
  track?: number | null;
  polarization?: PolarizationChoice;
}

export interface TimeSeriesRequest {
  bbox: BBox;
  /** GeoJSON Polygon, optional refinement inside bbox */
  geometry?: JsonObject | null;
  start?: string | null;
  end?: string | null;
  polarizations?: string[];
}

export interface MotionRequest {
  bbox: BBox;
  reference_date?: string | null;
  track?: number | null;
  /** optional processing choices; the server uses its defaults when they are left out */
  coherence_threshold?: number | null;
  remove_ramp?: boolean | null;
  apply_ionosphere?: boolean | null;
}

export interface InvestigateRequest {
  question: string;
  bbox: BBox;
  place_name?: string | null;
}

export type CoverageQuery = { bbox: BBox } | { lon: number; lat: number };

// ------------------------------------------------------------ investigation

export interface InvestigationStep {
  title: string;
  detail: string;
  result_ref: string | null;
}

export interface Report {
  answer: string;
  observed: string[];
  possible_explanations: string[];
  unknown: string[];
  confidence: string;
}

/**
 * A value in Investigation.results (typed `Any` by the backend): the coverage object, one workflow
 * result, or context evidence such as an earthquake list, which has no fixed shape.
 */
export type InvestigationResult = Coverage | WorkflowResult | JsonObject;

export interface Investigation {
  id: string;
  question: string;
  place_name: string | null;
  bbox: BBox;
  steps: InvestigationStep[];
  results: Record<string, InvestigationResult>;
  report: Report | null;
  /** which language model planned the steps and wrote the report */
  model: string | null;
}

/**
 * Where a step stands. The stream announces a step as "running" and reports it again when it ends.
 * "retry" means the report was sent back for revision because a figure could not be traced.
 */
export type StepStatus = "running" | "done" | "retry" | "failed";

/** Events of the POST /api/investigate text/event-stream response. */
export type InvestigateEvent =
  | { type: "step"; step: InvestigationStep; status: StepStatus }
  | { type: "tool_call"; name: string; input: JsonObject }
  | { type: "tool_result"; ref: string; result: InvestigationResult }
  | { type: "text"; delta: string }
  | { type: "done"; investigation: Investigation }
  | { type: "error"; message: string };

// ------------------------------------------------------------------- guards

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** True for a complete WorkflowResult as the three workflow endpoints return it. */
export function isWorkflowResult(value: unknown): value is WorkflowResult {
  return (
    isRecord(value) &&
    typeof value.id === "string" &&
    (value.workflow === "change" || value.workflow === "timeseries" || value.workflow === "motion") &&
    isRecord(value.summary) &&
    typeof value.summary.headline === "string" &&
    Array.isArray(value.layers) &&
    Array.isArray(value.series) &&
    isRecord(value.receipt)
  );
}

export function isCoverage(value: unknown): value is Coverage {
  return isRecord(value) && Array.isArray(value.stacks) && isRecord(value.products);
}

export function isInvestigation(value: unknown): value is Investigation {
  return (
    isRecord(value) &&
    typeof value.id === "string" &&
    typeof value.question === "string" &&
    Array.isArray(value.bbox) &&
    isRecord(value.results)
  );
}

// ---------------------------------------------------------------- showcases

/** One entry of /showcases/index.json. `file` is relative to /showcases/. */
export interface ShowcaseEntry {
  id: string;
  title: string;
  place_name: string;
  question: string;
  summary?: string;
  /** Path of the Investigation JSON, relative to /showcases/ */
  file: string;
  /** a small picture of the example's main map, as a site path */
  thumbnail?: string | null;
}

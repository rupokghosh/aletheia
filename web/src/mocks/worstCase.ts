/**
 * Worst-case fixtures for development. Each value is something the API could plausibly return: a
 * long record, an empty one, missing optional fields, a granule name at its realistic limit, long
 * sentences from the analyses. They exist to find layout breaks, never ship to production (see
 * mocks/index.ts) and are as much sample data as the ordinary fixtures.
 */

import { bboxCorners } from "@/lib/geo";
import type {
  BBox,
  Coverage,
  CoverageQuery,
  Granule,
  InvestigateEvent,
  InvestigateRequest,
  Investigation,
  InvestigationResult,
  JsonObject,
  Layer,
  Series,
  Stack,
  Tier,
  WorkflowResult,
} from "@/lib/types";
import { delay } from "./delay";

export type DevDataset = "worst" | "empty" | "one";

const DAY = 86_400_000;
const iso = (start: string, days: number) => new Date(Date.parse(`${start}T00:00:00Z`) + days * DAY).toISOString().slice(0, 10);
const artifact = (file: string) => `/api/artifacts/worst_case/${file}`;

/** A NISAR-style granule name padded to 180 characters, with no place for a browser to break it. */
function longGranuleId(product: string, track: number, date: string): string {
  const stamp = date.replace(/-/g, "");
  const base = `NISAR_L2_PR_${product}_023_${String(track).padStart(3, "0")}_A_027_4005_DHDH_A_${stamp}T124759_${stamp}T124834_P05023_N_F_J_001`;
  return `${base}_${"REPROCESSED_CALIBRATION_UPDATE_".repeat(4)}`.slice(0, 180);
}

function granule(product: string, track: number, frame: number, date: string, tier: Tier, secondary: string | null = null): Granule {
  const id = longGranuleId(product, track, secondary ? `${date}${secondary.replace(/-/g, "")}` : date);
  return {
    granule_id: id,
    product,
    tier,
    url: `https://sample.invalid/NISAR/${id}.h5`,
    size_gb: 11.94,
    track,
    frame,
    direction: track % 2 === 0 ? "descending" : "ascending",
    mode: "4005",
    polarizations: product === "GUNW" ? ["HH"] : ["HH", "HV", "VH", "VV"],
    date: secondary ? null : date,
    start_time: `${date}T12:47:59Z`,
    reference_date: secondary ? date : null,
    secondary_date: secondary,
    footprint: [],
  };
}

function stackOf(granules: Granule[]): Stack {
  const tiers: Record<string, number> = {};
  for (const g of granules) tiers[g.tier] = (tiers[g.tier] ?? 0) + 1;
  const first = granules[0];
  return {
    product: first.product,
    track: first.track,
    direction: first.direction,
    frame: first.frame,
    dates: [...new Set(granules.map((g) => g.date ?? g.reference_date ?? ""))].sort(),
    tiers,
    polarizations: first.polarizations,
  };
}

function echo(query: CoverageQuery): JsonObject {
  return "bbox" in query ? { bbox: [...query.bbox] } : { lon: query.lon, lat: query.lat };
}

export function worstCoverage(query: CoverageQuery, dataset: DevDataset): Coverage {
  if (dataset === "empty") {
    return {
      query: echo(query),
      products: { GCOV: [], GUNW: [], SME2: [] },
      stacks: [],
      notes: ["No NISAR backscatter (GCOV) granules intersect this location."],
    };
  }
  if (dataset === "one") {
    const only = granule("GCOV", 77, 27, "2026-10-17", "beta");
    return { query: echo(query), products: { GCOV: [only], GUNW: [], SME2: [] }, stacks: [stackOf([only])], notes: [] };
  }

  // 66 dates over two years on one stack, with a long gap and every tier.
  const long: Granule[] = [];
  for (let i = 0; i < 80; i += 1) {
    if (i >= 14 && i < 28) continue;
    const tier: Tier = i < 10 ? "beta" : i < 50 ? "provisional" : "validated";
    long.push(granule("GCOV", 77, 27, iso("2025-10-17", i * 12), tier));
  }
  const single = [granule("GCOV", 100, 163, "2026-03-04", "beta")];
  const pairs: Granule[] = [];
  for (let i = 0; i < 24; i += 1) {
    pairs.push(granule("GUNW", 77, 27, iso("2026-01-09", i * 12), "provisional", iso("2026-01-09", i * 12 + 12)));
    if (i % 2 === 0) pairs.push(granule("GUNW", 77, 27, iso("2026-01-09", i * 12), "beta", iso("2026-01-09", i * 12 + 24)));
  }
  return {
    query: echo(query),
    products: { GCOV: [...long, ...single], GUNW: pairs, SME2: [] },
    stacks: [stackOf(long), stackOf(single), stackOf(pairs)],
    notes: [
      "No acquisitions between 2026-03-22 and 2026-09-18 (180 days).",
      "Beta-tier acquisitions are uncalibrated; compare them with later dates only with care.",
      "Track 100 clips only the north-eastern corner of the area; fewer than 2% of its pixels fall inside the rectangle and most of those are at the instrument noise floor, so analyses on that stack will be declined. See https://sample.invalid/documentation/known-issues/frame-edge-coverage-and-partial-acquisitions-in-the-commissioning-phase for details.",
    ],
  };
}

const LONG_CAVEAT =
  "The two acquisitions were processed with different calibration versions (P05023 and P05101). A difference in absolute brightness of up to 1.2 dB between them can come from calibration alone, which is larger than the lenient change threshold used here; areas that changed by less than about 3 dB should be treated as unconfirmed until both dates are available in the same processing version. Steep north-facing slopes in the upper third of the rectangle are in radar layover on this ascending track and are not masked. Reference: https://sample.invalid/nisar/known-issues/calibration-version-differences-between-provisional-and-validated-products.html";

function worstLayers(bbox: BBox): Layer[] {
  const corners = bboxCorners(bbox);
  return [
    {
      id: "change_db",
      title: "HH change, after minus before, scene-wide shift removed, 9 by 9 multilook, noise-floor pixels masked (dB)",
      kind: "image",
      url: artifact("change_db.png"),
      corners,
      legend: { type: "continuous", unit: "dB", min: -12.5, max: 12.5, colormap: "turbo-not-a-known-map", classes: [] },
      default_visible: true,
      date: null,
    },
    {
      id: "classes",
      title: "Change classes",
      kind: "image",
      url: artifact("change_class.png"),
      corners,
      legend: {
        type: "categorical",
        unit: "",
        min: null,
        max: null,
        colormap: null,
        classes: [
          { label: "Brighter by at least 2.9 dB on both polarizations", color: "#b2182b" },
          { label: "Darker by at least 2.9 dB on both polarizations", color: "#2166ac" },
          { label: "At the noise floor on both dates (cannot tell)", color: "#808080" },
          { label: "Layover or shadow", color: "#5e3c99" },
          { label: "Water on both dates", color: "#1b7837" },
          { label: "No data", color: "#000000" },
        ],
      },
      default_visible: false,
      date: null,
    },
    { id: "no_legend", title: "Mask", kind: "image", url: artifact("coherence.png"), corners, legend: null, default_visible: false, date: null },
  ];
}

export function worstChange(bbox: BBox, dataset: DevDataset): WorkflowResult {
  const granules = ["2026-06-19", "2026-10-17"].map((date) => granule("GCOV", 77, 27, date, "provisional"));
  const one = dataset === "one";
  return {
    id: "chg_20261114_worst_case_identifier_0123456789abcdef",
    workflow: "change",
    status: "ok",
    request: { bbox: [...bbox], date_before: "2026-06-19", date_after: "2026-10-17", track: 77, polarization: "auto" },
    summary: {
      headline: one
        ? "Nothing changed."
        : "Radar brightness rose over 1,204.5 to 12,345.7 km2 and fell over 0.004 to 0.011 km2 of the 14,902 km2 area between 19 June and 17 October 2026; the rise is concentrated along the northern shore and the valley floor east of the outlet, and the fall along three narrow strips beside the highway.",
      metrics: one
        ? [{ key: "changed_area_km2", label: "Changed area", unit: "km2", central: 0, low: 0, high: 0 }]
        : [
            { key: "increased_area_km2", label: "Area where radar brightness rose (HH), counted after removing patches smaller than a disk of 11 pixels", unit: "km2", central: 4820.25, low: 1204.5, high: 12345.678 },
            { key: "tiny_area_km2", label: "Area where it fell", unit: "km2", central: 0.007, low: 0.004, high: 0.011 },
            { key: "shift_db", label: "Scene shift", unit: "dB", central: -0.4, low: -2.75, high: 1.9 },
            { key: "no_range", label: "Typical (median) change where it rose", unit: "dB", central: 4.7, low: null, high: null },
            { key: "no_central", label: "Range without a central value", unit: "cm", central: null, low: 1.5, high: 9 },
            { key: "zero_width", label: "Thresholds agree", unit: "%", central: 12, low: 12, high: 12 },
            { key: "count_one", label: "Dates used", unit: "dates", central: 1, low: null, high: null },
            { key: "nothing", label: "Not computed for this stack", unit: "km2", central: null, low: null, high: null },
            { key: "odd_unit", label: "Fringe count", unit: "fringes", central: 3, low: 2, high: 31 },
          ],
    },
    layers: one ? worstLayers(bbox).slice(0, 1) : worstLayers(bbox),
    series: [],
    stats: one
      ? {}
      : {
          primary_polarization: "HH",
          sign_convention:
            "Positive values mean the surface returned more signal on the later date; negative values mean it returned less. Values are differences of decibels after the scene-wide shift was removed.",
          window: { shape: [7200, 11600], pixel_size_m: [10, 10], epsg: 32611, multilook: 9, analysed_area_km2: 14902.123456, valid_fraction: 0.9999 },
          polarizations: {
            HH: { mean_db_before: -9.93, mean_db_after: -9.32, thresholds_db: { lenient: 2, central: 2.94, strict: 3.92 }, increased: { area_km2: { low: 1204.5, central: 4820.25, high: 12345.678 }, median_change_db: 4.7 }, informative: true },
            HV: { mean_db_before: -16.7, mean_db_after: -16.51, thresholds_db: { lenient: 1.4, central: 2.1, strict: 2.8 }, increased: { area_km2: { low: 0.09, central: 0.16, high: 0.18 }, median_change_db: 2.4 }, informative: false },
            VV: { mean_db_before: null, mean_db_after: null, thresholds_db: {}, informative: false },
          },
          skipped: [
            { date: "2026-07-01", track: 5, reason: "The frame covers less than 2% of the area and has no valid samples inside it.", granule_id: longGranuleId("GCOV", 5, "2026-07-01") },
            { date: "2026-07-13", track: 100, reason: "Read timed out.", granule_id: null },
          ],
          empty_group: {},
        },
    uncertainty: {
      method:
        "Per-pixel change in dB (after minus before) after 9x9 multilook in linear power, minus the median change of all measurable pixels (+0.71 dB for HH). The no-change spread sigma (0.98 dB) is 1.4826 x the median absolute deviation of the change. A pixel counts as changed when its change is at least k x sigma and at least 2 dB, for k = 2, 3 and 4; patches that cannot hold a disk 11 pixels across are removed. Pixels within 1.5 dB of the estimated noise floor on both dates are excluded as 'cannot tell'.",
      sensitivity: one
        ? []
        : Array.from({ length: 22 }, (_, i) => ({
            parameter: i % 3 === 0 ? `increase: minimum patch size of ${5 + i} pixels across, with the strict threshold` : `threshold ${i}`,
            value: i % 4 === 0 ? `${5 + i}x${5 + i}` : 1.5 + i * 0.25,
            result: i === 7 ? null : 4820.25 - i * 137.5,
            unit: "km2",
          })),
      noise_floor_fraction: one ? 0 : 1,
      notes: one ? [] : [LONG_CAVEAT, "HV is at the noise floor for 100% of the area and was not used."],
    },
    caveats: one
      ? []
      : [
          { code: "calibration_versions", text: LONG_CAVEAT },
          { code: "water_wind", text: "Wind roughens open water and changes its brightness from one pass to the next." },
          { code: "terrain", text: "On steep slopes the radar image is distorted (layover) or blind (shadow); changes there are unreliable." },
          { code: "short", text: "Beta." },
        ],
    receipt: {
      granules: granules.map(({ granule_id, url, tier, product, date, track, frame, direction, polarizations }) => ({
        granule_id,
        url,
        tier,
        product,
        date,
        reference_date: null,
        secondary_date: null,
        track,
        frame,
        direction,
        polarizations,
      })),
      steps: [
        { name: "search_catalog", params: { product: "GCOV", bbox: [...bbox], granules_found: 1284 }, seconds: 0.93 },
        { name: "select_stack_with_a_long_internal_step_name_that_has_no_spaces_in_it_at_all", params: { other_tracks_with_both_dates: [5, 100, 172], reason: "most valid samples inside the area" }, seconds: null },
        { name: "read_windows", params: { rows: [13072, 20272], cols: [15993, 27593], megabytes_transferred: 6312.75, urls: ["https://sample.invalid/a/very/long/signed/path/that/should/never/be/shown/but/might/be/one/day.h5"] }, seconds: 482.31 },
      ],
      software: { name: "nisar-investigator" },
      generated_at: "",
      reproduce: [
        "# Needs: pip install -e backend/  and an Earthdata Login in ~/.netrc (or EARTHDATA_TOKEN).",
        "from nisar_investigator.schemas import ChangeRequest",
        "from nisar_investigator.workflows.change import run_change",
        "",
        `result = run_change(ChangeRequest(bbox=(${bbox.join(", ")}), date_before="2026-06-19", date_after="2026-10-17", track=77, polarization="auto"))  # one long line that a narrow panel cannot hold without scrolling sideways`,
        ...Array.from({ length: 40 }, (_, i) => `print(result.summary.metrics[${i}])`),
      ].join("\n"),
    },
    downloads: one
      ? []
      : Array.from({ length: 14 }, (_, i) => ({
          label: i === 0 ? "HH change, scene shift removed, 9 by 9 multilook, float32 with NaN as no data (dB, GeoTIFF)" : `File ${i + 1} (GeoTIFF)`,
          url: artifact(`file_${i}.tif`),
          format: i === 3 ? "application/x-hdf5" : "geotiff",
        })),
  };
}

export function worstTimeSeries(bbox: BBox, dataset: DevDataset): WorkflowResult {
  const corners = bboxCorners(bbox);
  const points = (count: number, base: number, start: string) =>
    Array.from({ length: count }, (_, i) => ({
      date: iso(start, i * 12),
      value: i === 5 ? null : base + Math.sin(i / 3) * 1.4,
      spread: i % 7 === 0 ? null : 3.2,
      tier: (i < 6 ? "beta" : i < 40 ? "provisional" : "validated") as Tier,
      granule_id: longGranuleId("GCOV", 77, iso(start, i * 12)),
    }));
  const one: Series = {
    id: "single",
    label: "HH mean, track 100 descending (one acquisition only)",
    unit: "dB",
    track: 100,
    direction: "descending",
    polarization: "HH",
    points: [{ date: "2026-03-04", value: -11.2, spread: 2.9, tier: null, granule_id: null }],
  };
  const series: Series[] =
    dataset === "one"
      ? [one]
      : [
          { id: "long", label: "HH mean, track 77 ascending", unit: "dB", track: 77, direction: "ascending", polarization: "HH", points: points(66, -10, "2025-10-17") },
          one,
          { id: "empty", label: "VV mean, track 5 ascending (no valid pixels on any date)", unit: "dB", track: 5, direction: "ascending", polarization: "VV", points: points(4, 0, "2026-06-01").map((p) => ({ ...p, value: null, spread: null })) },
          ...["HV", "VH", "VV", "HH b", "HV b", "VH b"].map((name, i) => ({ id: `extra_${i}`, label: `${name} mean, track 77 ascending`, unit: "dB", track: 77, direction: "ascending" as const, polarization: name, points: points(30, -17 - i, "2026-06-19") })),
          { id: "other_unit", label: "Water level at the gauge", unit: "m", track: null, direction: null, polarization: null, points: points(12, 341.2, "2026-06-19").map((p) => ({ ...p, tier: null, granule_id: null })) },
        ];
  return {
    id: "ts_20261114_worst_case",
    workflow: "timeseries",
    status: "ok",
    request: { bbox: [...bbox], start: null, end: null, polarizations: ["HH", "HV", "VH", "VV"] },
    summary: { headline: dataset === "one" ? "1 date on 1 track: 4 March 2026." : "66 dates on 3 tracks from 17 October 2025 to 4 December 2027.", metrics: [{ key: "n_dates", label: "Dates used", unit: "dates", central: dataset === "one" ? 1 : 66, low: null, high: null }] },
    layers:
      dataset === "one"
        ? []
        : Array.from({ length: 66 }, (_, i) => ({
            id: `hh_${i}`,
            title: `HH, ${iso("2025-10-17", i * 12)} (dB)`,
            kind: "image" as const,
            url: artifact(`hh_t${i % 6}.png`),
            corners,
            legend: { type: "continuous" as const, unit: "dB", min: -19, max: -3, colormap: "grey", classes: [] },
            default_visible: i === 65,
            date: iso("2025-10-17", i * 12),
          })),
    series,
    stats: {},
    uncertainty: null,
    caveats: [],
    receipt: { granules: [], steps: [], software: {}, generated_at: "2026-11-14T21:00:00Z", reproduce: "" },
    downloads: [],
  };
}

export function worstUnsupported(bbox: BBox): WorkflowResult {
  return {
    id: "mot_20261114_worst_case",
    workflow: "motion",
    status: "unsupported",
    request: { bbox: [...bbox] },
    summary: {
      headline:
        "Not supported yet: no ready-made interferogram covers this area on track 100 between 1 June 2026 and 31 October 2026, and this tool does not build interferograms from single-look complex data; the two nearest pairs (2026-05-20 to 2026-06-01 on track 77 and 2026-11-05 to 2026-11-17 on track 172) fall outside the dates asked for, and the pair on track 5 covers less than 2% of the rectangle. Try track 77 with a reference date in June, or widen the dates.",
      metrics: [],
    },
    layers: [],
    series: [],
    stats: {},
    uncertainty: null,
    caveats: [{ code: "edge", text: LONG_CAVEAT }],
    receipt: { granules: [], steps: [], software: {}, generated_at: "", reproduce: "" },
    downloads: [],
  };
}

export async function* worstInvestigation(
  request: InvestigateRequest,
  dataset: DevDataset,
  signal?: AbortSignal,
): AsyncGenerator<InvestigateEvent, void, undefined> {
  const coverage = worstCoverage({ bbox: request.bbox }, dataset);
  const change = worstChange(request.bbox, dataset);
  const unsupported = worstUnsupported(request.bbox);
  const context: JsonObject = {
    id: "ctx_earthquakes",
    available: true,
    source: "USGS Earthquake Catalog (FDSN event service)",
    count: 2,
    events: [
      { time: "2026-06-11T03:14:07Z", magnitude: 6.4, place: "23 km SSW of a place with a very long transliterated name, Venezuela", depth_km: 12.4 },
      { time: "2026-06-12T19:50:41Z", magnitude: 5.1, place: "Offshore", depth_km: null },
    ],
  };
  const results: Record<string, InvestigationResult> = { coverage, [change.id]: change, [unsupported.id]: unsupported, ctx_earthquakes: context };
  const blank = (title: string) => ({ title, detail: "", result_ref: null });

  yield { type: "step", status: "done", step: blank("Planning with a-model-with-a-very-long-name-and-tag:70b-instruct-q4_K_M (local, Ollama)") };
  yield { type: "step", status: "running", step: blank("Checking what NISAR has for this area") };
  yield { type: "tool_call", name: "check_coverage", input: {} };
  await delay(300, signal);
  yield { type: "tool_result", ref: "coverage", result: coverage };
  yield { type: "step", status: "done", step: { title: "Checking what NISAR has for this area", detail: "", result_ref: "coverage" } };

  yield { type: "step", status: "running", step: blank("Measuring change between 2026-06-19 and 2026-10-17") };
  yield { type: "tool_call", name: "run_change", input: { date_before: "2026-06-19", date_after: "2026-10-17", track: 77 } };
  yield { type: "tool_result", ref: change.id, result: change };
  yield { type: "step", status: "done", step: { title: "Measuring change between 2026-06-19 and 2026-10-17", detail: change.summary.headline, result_ref: change.id } };

  yield { type: "step", status: "running", step: blank("Reading ground motion from NASA's interferogram") };
  yield { type: "tool_call", name: "run_motion", input: { reference_date: null } };
  yield { type: "tool_result", ref: unsupported.id, result: unsupported };
  yield { type: "step", status: "done", step: { title: "Reading ground motion from NASA's interferogram", detail: unsupported.summary.headline, result_ref: unsupported.id } };

  yield { type: "step", status: "running", step: blank("Looking up independent evidence") };
  yield { type: "tool_call", name: "get_context", input: { kind: "earthquakes", start: "2026-06-01", end: "2026-06-30" } };
  yield { type: "tool_result", ref: "ctx_earthquakes", result: context };
  yield { type: "step", status: "done", step: { title: "Looking up independent evidence", detail: "2 earthquakes of magnitude 4.5 or more within 150 km", result_ref: "ctx_earthquakes" } };

  yield { type: "step", status: "running", step: blank("Building a time series from every available date") };
  yield { type: "step", status: "failed", step: { title: "Building a time series from every available date", detail: "TimeoutError: HTTPSConnectionPool(host='sample.invalid', port=443): Read timed out. (read timeout=60) while reading NISAR_L2_PR_GCOV_023_077_A_027_4005_DHDH_A_20260619T124759", result_ref: null } };

  yield { type: "step", status: "running", step: blank("Writing the report") };
  yield { type: "step", status: "retry", step: { title: "Writing the report", detail: "Figures did not match the results; revising", result_ref: null } };
  yield { type: "step", status: "running", step: blank("Writing the report") };
  yield { type: "step", status: "done", step: { title: "Writing the report", detail: "Report accepted", result_ref: null } };

  const investigation: Investigation = {
    id: "inv_20261114_worst_case",
    question: request.question,
    place_name: request.place_name ?? null,
    bbox: request.bbox,
    steps: [],
    results,
    report: {
      answer:
        "Radar brightness rose over 1,204.5 to 12,345.7 km2 of the area between 19 June and 17 October 2026, mostly along the northern shore and the valley floor east of the outlet, while ground motion could not be measured because no ready-made interferogram covers the dates asked for.",
      observed: [
        `Brightness rose over 1204.5 to 12345.678 km2, central estimate 4820.25 km2. [${change.id}]`,
        "A statement the model wrote without citing any result, which the interface should still show as plain text.",
        `The ground-motion request was declined. [${unsupported.id}]`,
        "Two earthquakes of magnitude 4.5 or more were recorded within 150 km in June 2026. [ctx_earthquakes]",
        "A statement that cites an id the interface has never seen. [chg_20261114_unknown]",
      ],
      possible_explanations: [
        `A drop in water level exposing bright shoreline (see ${change.id}). To check: compare with the gauge record at https://sample.invalid/hydrometric/stations/08LF023/daily-water-level-and-discharge-2026.csv over the same months.`,
        "An explanation without a check.",
      ],
      unknown: [],
      confidence: "The model did not give a level, only this sentence about why the result should be read with care.",
    },
    model: "a-model-with-a-very-long-name-and-tag:70b-instruct-q4_K_M (local, Ollama)",
  };
  yield { type: "error", message: "The investigation ended without every step succeeding. The steps and results above are still valid." };
  yield { type: "done", investigation };
}

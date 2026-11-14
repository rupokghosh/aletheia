/**
 * Demo-data fixtures for workflow results. SAMPLE values that conform to the API contract; they are
 * not NISAR measurements. The images they point at (public/demo-artifacts) carry a "SAMPLE" stamp.
 */

import { bboxCorners } from "@/lib/geo";
import type {
  BBox,
  ChangeRequest,
  Granule,
  JsonObject,
  Layer,
  MotionRequest,
  ReceiptGranule,
  Series,
  SeriesPoint,
  TimeSeriesRequest,
  WorkflowResult,
} from "@/lib/types";
import { DEMO_PAIRS, DEMO_STACK_A, DEMO_STACK_B, demoGcovGranules, demoGunwGranule } from "./catalogue";

const SOFTWARE = { name: "nisar-investigator", version: "0.1.0", commit: "sample" };

let counter = 0;
function demoId(prefix: string): string {
  counter += 1;
  return `${prefix}_demo_${String(counter).padStart(4, "0")}`;
}

const artifact = (id: string, file: string) => `/api/artifacts/${id}/${file}`;
const now = () => new Date().toISOString().replace(/\.\d{3}Z$/, "Z");
const tuple = (bbox: BBox) => `(${bbox.map((v) => v.toFixed(5)).join(", ")})`;

function receiptGranule(granule: Granule): ReceiptGranule {
  return {
    granule_id: granule.granule_id,
    url: granule.url,
    tier: granule.tier,
    product: granule.product,
    date: granule.date,
    reference_date: granule.reference_date,
    secondary_date: granule.secondary_date,
    track: granule.track,
    frame: granule.frame,
    direction: granule.direction,
    polarizations: granule.polarizations,
  };
}

function tierCaveats(granules: Granule[]): WorkflowResult["caveats"] {
  const caveats: WorkflowResult["caveats"] = [];
  if (granules.some((g) => g.tier === "beta")) {
    caveats.push({ code: "tier_beta", text: "Beta calibration: these acquisitions are uncalibrated." });
  }
  if (granules.some((g) => g.tier === "provisional")) {
    caveats.push({
      code: "tier_provisional",
      text: "Provisional calibration: values may change after reprocessing.",
    });
  }
  return caveats;
}

// ------------------------------------------------------------------ change

export function buildDemoChange(request: ChangeRequest): WorkflowResult {
  const id = demoId("chg");
  const stack = request.track === DEMO_STACK_B.track ? DEMO_STACK_B : DEMO_STACK_A;
  const granules = demoGcovGranules(stack).filter(
    (g) => g.date === request.date_before || g.date === request.date_after,
  );
  const corners = bboxCorners(request.bbox);
  const backscatterLegend = {
    type: "continuous" as const,
    unit: "dB",
    min: -25,
    max: -5,
    colormap: "grey",
    classes: [],
  };

  return {
    id,
    workflow: "change",
    status: "ok",
    request: { ...request, bbox: [...request.bbox] } as JsonObject,
    summary: {
      headline: "0.2 to 1.1 km2 of the 7.2 km2 water body became land",
      metrics: [
        { key: "changed_area_km2", label: "Changed area (water to land)", unit: "km2", low: 0.2, central: 0.44, high: 1.1 },
        { key: "water_area_before_km2", label: "Water area before", unit: "km2", low: 6.9, central: 7.2, high: 7.6 },
        { key: "water_area_after_km2", label: "Water area after", unit: "km2", low: 6.1, central: 6.76, high: 7.2 },
        { key: "median_change_db", label: "Median HH change of changed pixels", unit: "dB", low: 3.1, central: 4.2, high: 5.6 },
        { key: "reference_shift_db", label: "Shift of stable reference pixels", unit: "dB", low: 1.2, central: 1.5, high: 1.8 },
      ],
    },
    layers: [
      {
        id: "change_db",
        title: "HH change (dB)",
        kind: "image",
        url: artifact(id, "change_db.png"),
        corners,
        legend: { type: "continuous", unit: "dB", min: -6, max: 6, colormap: "RdBu", classes: [] },
        default_visible: true,
        date: null,
      },
      {
        id: "change_class",
        title: "Change class",
        kind: "image",
        url: artifact(id, "change_class.png"),
        corners,
        legend: {
          type: "categorical",
          unit: "",
          min: null,
          max: null,
          colormap: null,
          classes: [
            { label: "Water to land", color: "#e66101" },
            { label: "Land to water", color: "#5e3c99" },
          ],
        },
        default_visible: false,
        date: null,
      },
      {
        id: "hh_before",
        title: "HH backscatter, before",
        kind: "image",
        url: artifact(id, "hh_t0.png"),
        corners,
        legend: backscatterLegend,
        default_visible: false,
        date: request.date_before,
      },
      {
        id: "hh_after",
        title: "HH backscatter, after",
        kind: "image",
        url: artifact(id, "hh_t5.png"),
        corners,
        legend: backscatterLegend,
        default_visible: false,
        date: request.date_after,
      },
    ],
    series: [],
    stats: {
      per_polarization: {
        HH: {
          mean_before_db: -14.8,
          mean_after_db: -13.9,
          median_change_db: 0.4,
          p05_change_db: -1.9,
          p95_change_db: 4.6,
          noise_floor_fraction: 0.02,
        },
        HV: {
          mean_before_db: -22.6,
          mean_after_db: -22.3,
          median_change_db: 0.1,
          p05_change_db: -1.2,
          p95_change_db: 1.4,
          noise_floor_fraction: 0.62,
        },
      },
      window: { rows: 720, cols: 1160, pixel_spacing_m: 10, multilook: "9x9" },
      polarization_used: "HH",
    },
    uncertainty: {
      method:
        "Per-pixel log-ratio after 9x9 multilook, normalised by the median shift of stable reference pixels.",
      sensitivity: [
        { parameter: "change threshold (dB)", value: 1.5, result: 1.1, unit: "km2" },
        { parameter: "change threshold (dB)", value: 2, result: 0.44, unit: "km2" },
        { parameter: "change threshold (dB)", value: 3, result: 0.2, unit: "km2" },
        { parameter: "multilook window", value: "5x5", result: 0.52, unit: "km2" },
        { parameter: "multilook window", value: "13x13", result: 0.39, unit: "km2" },
      ],
      noise_floor_fraction: 0.31,
      notes: [
        "HV is at the noise floor for 62% of the area and was not used.",
        "Stable water shifted by about +1.5 dB between the two dates (wind); the change is measured relative to that shift.",
      ],
    },
    caveats: [
      ...tierCaveats(granules),
      {
        code: "water_land_ambiguity",
        text: "In dry terrain, open water and smooth dry ground have similar HH backscatter. The changed area is a range across thresholds, not a single value.",
      },
    ],
    receipt: {
      granules: granules.map(receiptGranule),
      steps: [
        { name: "search_catalogue", params: { product: "GCOV", track: stack.track, frame: stack.frame }, seconds: 1.3 },
        { name: "read_window", params: { date: request.date_before, rows: [13072, 13792], cols: [15993, 17153], requests: 15, megabytes: 63 }, seconds: 8.9 },
        { name: "read_window", params: { date: request.date_after, rows: [13072, 13792], cols: [15993, 17153], requests: 14, megabytes: 61 }, seconds: 8.1 },
        { name: "multilook", params: { window: [9, 9], weighting: "validity" }, seconds: 0.21 },
        { name: "normalise_by_reference", params: { reference_class: "stable water", shift_db: 1.5 }, seconds: 0.05 },
        { name: "classify_change", params: { thresholds_db: [1.5, 2, 3] }, seconds: 0.12 },
        { name: "render", params: { colormap: "RdBu", range_db: [-6, 6] }, seconds: 0.34 },
      ],
      software: SOFTWARE,
      generated_at: now(),
      reproduce: [
        "from nisar_investigator.workflows import change",
        "",
        "result = change.run(",
        `    bbox=${tuple(request.bbox)},`,
        `    date_before="${request.date_before}",`,
        `    date_after="${request.date_after}",`,
        `    track=${stack.track},`,
        `    polarization="${request.polarization ?? "auto"}",`,
        ")",
        "print(result.summary.headline)",
        "for metric in result.summary.metrics:",
        "    print(metric.label, metric.low, metric.central, metric.high, metric.unit)",
      ].join("\n"),
    },
    downloads: [
      { label: "Change map (PNG)", url: artifact(id, "change_db.png"), format: "png" },
      { label: "Change map (GeoTIFF)", url: artifact(id, "change_db.tif"), format: "geotiff" },
      { label: "Statistics (CSV)", url: artifact(id, "stats.csv"), format: "csv" },
      { label: "Full result (JSON)", url: artifact(id, "result.json"), format: "json" },
    ],
  };
}

// -------------------------------------------------------------- time series

const HH_A = [-13.9, -14.1, -13.6, -13.8, -14.0, -13.7, -15.6, -15.5, -15.3, -15.2, -14.9, -14.8, -14.6, -14.5, -14.3, -14.2, -14.2, -14.1];
const HV_A = [-22.1, -22.3, -21.9, -22.0, -22.2, -22.0, -23.4, -23.3, -23.3, -23.1, -23.0, -22.9, -22.8, -22.8, -22.7, -22.6, -22.6, -22.5];
const HH_B = [-15.1, -15.0, -14.9, -14.7, -14.6, -14.4, -14.3, -14.1, -14.0, -13.9, -13.8, -13.8];
const HV_B: Array<number | null> = [-23.0, -22.9, -22.9, -22.8, null, -22.6, -22.5, -22.5, -22.4, -22.3, -22.3, -22.2];

function demoSeries(
  stack: typeof DEMO_STACK_A,
  polarization: string,
  values: Array<number | null>,
  request: TimeSeriesRequest,
): Series {
  const granules = demoGcovGranules(stack);
  const points: SeriesPoint[] = granules
    .map((granule, index) => ({
      date: granule.date ?? "",
      value: values[index] ?? null,
      spread: values[index] === null ? null : granule.tier === "beta" ? 0.8 : polarization === "HH" ? 0.45 : 0.3,
      tier: granule.tier,
      granule_id: granule.granule_id,
    }))
    .filter((point) => (!request.start || point.date >= request.start) && (!request.end || point.date <= request.end));
  return {
    id: `${polarization.toLowerCase()}_mean_t${String(stack.track).padStart(3, "0")}`,
    label: `${polarization} mean, track ${stack.track}`,
    unit: "dB",
    track: stack.track,
    direction: stack.direction,
    polarization,
    points,
  };
}

export function buildDemoTimeSeries(request: TimeSeriesRequest): WorkflowResult {
  const id = demoId("ts");
  const wanted = request.polarizations ?? ["HH", "HV"];
  const all: Array<[typeof DEMO_STACK_A, string, Array<number | null>]> = [
    [DEMO_STACK_A, "HH", HH_A],
    [DEMO_STACK_A, "HV", HV_A],
    [DEMO_STACK_B, "HH", HH_B],
    [DEMO_STACK_B, "HV", HV_B],
  ];
  const series = all
    .filter(([, polarization]) => wanted.includes(polarization))
    .map(([stack, polarization, values]) => demoSeries(stack, polarization, values, request))
    .filter((s) => s.points.length > 0);

  const granules = [...demoGcovGranules(DEMO_STACK_A), ...demoGcovGranules(DEMO_STACK_B)].filter(
    (g) => (!request.start || (g.date ?? "") >= request.start) && (!request.end || (g.date ?? "") <= request.end),
  );
  const corners = bboxCorners(request.bbox);
  const frames = ["2026-06-19", "2026-07-13", "2026-08-18", "2026-09-11", "2026-10-05", "2026-10-29"];
  const layers: Layer[] = frames
    .filter((date) => granules.some((g) => g.date === date))
    .map((date) => ({
      id: `hh_${date.replace(/-/g, "")}`,
      title: `HH backscatter, ${date}`,
      kind: "image" as const,
      url: artifact(id, `hh_t${frames.indexOf(date)}.png`),
      corners,
      legend: { type: "continuous" as const, unit: "dB", min: -25, max: -5, colormap: "grey", classes: [] },
      default_visible: true,
      date,
    }));

  return {
    id,
    workflow: "timeseries",
    status: "ok",
    request: { ...request, bbox: [...request.bbox] } as JsonObject,
    summary: {
      headline: `Mean HH backscatter rose by 1.2 to 1.8 dB between June and November 2026 across ${granules.length} acquisitions on 2 tracks`,
      metrics: [
        { key: "hh_trend_db", label: "HH change, first to last 2026 date (track 77)", unit: "dB", low: 1.2, central: 1.5, high: 1.8 },
        { key: "hv_trend_db", label: "HV change, first to last 2026 date (track 77)", unit: "dB", low: 0.5, central: 0.9, high: 1.3 },
        { key: "track_offset_db", label: "HH offset between tracks 149 and 77", unit: "dB", low: 0.3, central: 0.5, high: 0.8 },
      ],
    },
    layers,
    series,
    stats: {
      acquisitions: granules.length,
      tracks: { "77": "ascending, frame 27", "149": "descending, frame 71" },
      window: { pixel_spacing_m: 10, multilook: "9x9" },
    },
    uncertainty: {
      method:
        "Mean of valid pixels per date after 9x9 multilook. Spread is the standard deviation of the multilooked pixels in dB. Tracks are kept separate because their viewing geometry differs.",
      sensitivity: [
        { parameter: "statistic", value: "mean", result: 1.5, unit: "dB" },
        { parameter: "statistic", value: "median", result: 1.3, unit: "dB" },
        { parameter: "multilook window", value: "5x5", result: 1.6, unit: "dB" },
      ],
      noise_floor_fraction: 0.48,
      notes: [
        "HV is within 2 dB of the instrument noise floor on every date; its trend is weakly constrained.",
        "One HV value on track 149 (2026-08-11) had too few valid pixels and is reported as missing.",
      ],
    },
    caveats: [
      ...tierCaveats(granules),
      {
        code: "geometry",
        text: "Ascending and descending tracks see the ground from different directions. Compare values within a track, not between tracks.",
      },
    ],
    receipt: {
      granules: granules.map(receiptGranule),
      steps: [
        { name: "search_catalogue", params: { product: "GCOV", start: request.start ?? null, end: request.end ?? null }, seconds: 1.6 },
        { name: "read_windows", params: { dates: granules.length, polarizations: wanted, megabytes: granules.length * 31 }, seconds: granules.length * 1.9 },
        { name: "multilook", params: { window: [9, 9], weighting: "validity" }, seconds: 0.9 },
        { name: "aggregate", params: { statistic: "mean", spread: "standard deviation" }, seconds: 0.2 },
      ],
      software: SOFTWARE,
      generated_at: now(),
      reproduce: [
        "from nisar_investigator.workflows import timeseries",
        "",
        "result = timeseries.run(",
        `    bbox=${tuple(request.bbox)},`,
        `    start=${request.start ? `"${request.start}"` : "None"},`,
        `    end=${request.end ? `"${request.end}"` : "None"},`,
        `    polarizations=${JSON.stringify(wanted)},`,
        ")",
        "for series in result.series:",
        "    for point in series.points:",
        "        print(series.label, point.date, point.value, point.spread)",
      ].join("\n"),
    },
    downloads: [
      { label: "Time series (CSV)", url: artifact(id, "timeseries.csv"), format: "csv" },
      { label: "Full result (JSON)", url: artifact(id, "result.json"), format: "json" },
    ],
  };
}

// ------------------------------------------------------------------ motion

export function buildDemoMotion(request: MotionRequest): WorkflowResult {
  const id = demoId("mot");
  const pair = DEMO_PAIRS.find(([reference]) => reference === request.reference_date) ?? DEMO_PAIRS[DEMO_PAIRS.length - 1];
  const granule = demoGunwGranule(pair[0], pair[1]);
  const corners = bboxCorners(request.bbox);

  return {
    id,
    workflow: "motion",
    status: "ok",
    request: { ...request, bbox: [...request.bbox] } as JsonObject,
    summary: {
      headline: `No ground motion above the noise level between ${pair[0]} and ${pair[1]}: median line-of-sight change is -0.8 to 0.4 cm`,
      metrics: [
        { key: "los_median_cm", label: "Median line-of-sight displacement", unit: "cm", low: -0.8, central: -0.3, high: 0.4 },
        { key: "los_p95_abs_cm", label: "95th percentile of absolute displacement", unit: "cm", low: 1.1, central: 1.6, high: 2.3 },
        { key: "coherent_fraction", label: "Fraction of pixels above the coherence mask", unit: "", low: 0.58, central: 0.66, high: 0.74 },
      ],
    },
    layers: [
      {
        id: "los_displacement",
        title: "Line-of-sight displacement (cm)",
        kind: "image",
        url: artifact(id, "los_displacement.png"),
        corners,
        legend: { type: "continuous", unit: "cm", min: -3, max: 3, colormap: "RdBu", classes: [] },
        default_visible: true,
        date: null,
      },
      {
        id: "coherence",
        title: "Coherence",
        kind: "image",
        url: artifact(id, "coherence.png"),
        corners,
        legend: { type: "continuous", unit: "", min: 0, max: 1, colormap: "viridis", classes: [] },
        default_visible: false,
        date: null,
      },
    ],
    series: [],
    stats: {
      pair: { reference_date: pair[0], secondary_date: pair[1], temporal_baseline_days: 12 },
      coherence: { mean: 0.52, mask_threshold: 0.3 },
      reference_point: { method: "median of coherent pixels set to zero" },
    },
    uncertainty: {
      method:
        "Unwrapped phase from NASA's GUNW product converted to line-of-sight displacement, masked where coherence is below 0.3, referenced to the median of coherent pixels.",
      sensitivity: [
        { parameter: "coherence mask", value: 0.2, result: -0.8, unit: "cm" },
        { parameter: "coherence mask", value: 0.3, result: -0.3, unit: "cm" },
        { parameter: "coherence mask", value: 0.5, result: 0.4, unit: "cm" },
      ],
      noise_floor_fraction: null,
      notes: [
        "Displacement is along the radar line of sight, positive towards the satellite. It is not vertical motion.",
        "Water surfaces lose coherence and are masked.",
      ],
    },
    caveats: [
      { code: "tier_provisional", text: "Provisional calibration: values may change after reprocessing." },
      { code: "atmosphere", text: "A single 12-day pair is not corrected for atmospheric delay, which can add 1 to 3 cm of apparent motion." },
      { code: "reference_point", text: "Displacement is relative to the median of coherent pixels in this area, not to a fixed ground station." },
    ],
    receipt: {
      granules: [receiptGranule(granule)],
      steps: [
        { name: "search_catalogue", params: { product: "GUNW", reference_date: pair[0] }, seconds: 1.1 },
        { name: "read_window", params: { layers: ["unwrappedPhase", "coherenceMagnitude"], megabytes: 22 }, seconds: 5.4 },
        { name: "phase_to_displacement", params: { wavelength_cm: 23.8 }, seconds: 0.04 },
        { name: "mask_and_reference", params: { coherence_threshold: 0.3, reference: "median" }, seconds: 0.08 },
        { name: "render", params: { colormap: "RdBu", range_cm: [-3, 3] }, seconds: 0.29 },
      ],
      software: SOFTWARE,
      generated_at: now(),
      reproduce: [
        "from nisar_investigator.workflows import motion",
        "",
        "result = motion.run(",
        `    bbox=${tuple(request.bbox)},`,
        `    reference_date="${pair[0]}",`,
        `    track=${granule.track},`,
        ")",
        "print(result.summary.headline)",
      ].join("\n"),
    },
    downloads: [
      { label: "Displacement (GeoTIFF)", url: artifact(id, "los_displacement.tif"), format: "geotiff" },
      { label: "Full result (JSON)", url: artifact(id, "result.json"), format: "json" },
    ],
  };
}

// ------------------------------------------------------------- unsupported

export function buildDemoUnsupported(bbox: BBox): WorkflowResult {
  return {
    id: demoId("mot"),
    workflow: "motion",
    status: "unsupported",
    request: { bbox: [...bbox], question_type: "slow subsidence" },
    summary: {
      headline:
        "Not supported yet: slow ground motion needs a time series of many interferograms. This tool reads single 12-day pairs, where motion of a few millimetres is smaller than the atmospheric noise.",
      metrics: [],
    },
    layers: [],
    series: [],
    stats: {},
    uncertainty: null,
    caveats: [
      {
        code: "unsupported_slow_motion",
        text: "Single-pair ground motion can show sudden changes of several centimetres, for example after an earthquake.",
      },
    ],
    receipt: { granules: [], steps: [], software: SOFTWARE, generated_at: now(), reproduce: "" },
    downloads: [],
  };
}

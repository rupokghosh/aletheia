/**
 * Demo-data fixtures for the catalogue. These are SAMPLE values that conform to the API contract.
 * They are not NISAR measurements and are only served in demo-data mode (see src/lib/api.ts).
 */

import type { Coverage, CoverageQuery, Direction, Granule, JsonObject, Stack, Tier } from "@/lib/types";

interface DemoAcquisition {
  date: string;
  tier: Tier;
}

interface DemoStack {
  track: number;
  direction: Direction;
  frame: number;
  time: string;
  acquisitions: DemoAcquisition[];
}

const tiered = (tier: Tier, dates: string[]): DemoAcquisition[] => dates.map((date) => ({ date, tier }));

export const DEMO_STACK_A: DemoStack = {
  track: 77,
  direction: "ascending",
  frame: 27,
  time: "124759",
  acquisitions: [
    ...tiered("beta", ["2025-11-10", "2025-11-22", "2025-12-04", "2025-12-16", "2025-12-28", "2026-01-09"]),
    ...tiered("validated", [
      "2026-06-19",
      "2026-07-01",
      "2026-07-13",
      "2026-07-25",
      "2026-08-18",
      "2026-08-30",
      "2026-09-11",
    ]),
    ...tiered("provisional", ["2026-09-23", "2026-10-05", "2026-10-17", "2026-10-29", "2026-11-10"]),
  ],
};

export const DEMO_STACK_B: DemoStack = {
  track: 149,
  direction: "descending",
  frame: 71,
  time: "013312",
  acquisitions: tiered("provisional", [
    "2026-06-24",
    "2026-07-06",
    "2026-07-18",
    "2026-07-30",
    "2026-08-11",
    "2026-08-23",
    "2026-09-04",
    "2026-09-16",
    "2026-09-28",
    "2026-10-10",
    "2026-10-22",
    "2026-11-03",
  ]),
};

/** Ground-motion pairs (reference, secondary) on the grid of stack A. */
export const DEMO_PAIRS: Array<[string, string]> = [
  ["2026-08-18", "2026-08-30"],
  ["2026-08-30", "2026-09-11"],
  ["2026-09-11", "2026-09-23"],
  ["2026-09-23", "2026-10-05"],
  ["2026-10-05", "2026-10-17"],
  ["2026-10-17", "2026-10-29"],
];

const pad3 = (value: number) => String(value).padStart(3, "0");
const compact = (date: string) => date.replace(/-/g, "");
const directionCode = (direction: Direction) => (direction === "ascending" ? "A" : "D");

/** The reserved .invalid domain makes it plain that a sample granule cannot be downloaded. */
const sampleUrl = (granuleId: string) => `https://sample.invalid/NISAR/${granuleId}.h5`;

function cycleOf(date: string): number {
  const days = Math.round((Date.parse(`${date}T00:00:00Z`) - Date.parse("2025-09-17T00:00:00Z")) / 86_400_000);
  return Math.max(1, Math.floor(days / 12) + 1);
}

export function demoGcovGranule(stack: DemoStack, acquisition: DemoAcquisition): Granule {
  const { date, tier } = acquisition;
  const stamp = `${compact(date)}T${stack.time}`;
  const granuleId = [
    "NISAR_L2_PR_GCOV",
    pad3(cycleOf(date)),
    pad3(stack.track),
    directionCode(stack.direction),
    pad3(stack.frame),
    "4005_DHDH_A",
    stamp,
    `${compact(date)}T${String(Number(stack.time) + 35).padStart(6, "0")}`,
    "P05023_N_F_J_001",
  ].join("_");
  return {
    granule_id: granuleId,
    product: "GCOV",
    tier,
    url: sampleUrl(granuleId),
    size_gb: 7.3,
    track: stack.track,
    frame: stack.frame,
    direction: stack.direction,
    mode: "4005",
    polarizations: ["HH", "HV"],
    date,
    start_time: `${date}T${stack.time.slice(0, 2)}:${stack.time.slice(2, 4)}:${stack.time.slice(4, 6)}Z`,
    reference_date: null,
    secondary_date: null,
    footprint: [],
  };
}

export function demoGunwGranule(reference: string, secondary: string): Granule {
  const stack = DEMO_STACK_A;
  const granuleId = [
    "NISAR_L2_PR_GUNW",
    pad3(cycleOf(reference)),
    pad3(stack.track),
    directionCode(stack.direction),
    pad3(stack.frame),
    pad3(cycleOf(secondary)),
    "4000_SH",
    `${compact(reference)}T${stack.time}`,
    `${compact(reference)}T124834`,
    `${compact(secondary)}T${stack.time}`,
    `${compact(secondary)}T124834`,
    "P05023_N_F_J_001",
  ].join("_");
  return {
    granule_id: granuleId,
    product: "GUNW",
    tier: "provisional",
    url: sampleUrl(granuleId),
    size_gb: 2.1,
    track: stack.track,
    frame: stack.frame,
    direction: stack.direction,
    mode: "4000",
    polarizations: ["HH"],
    date: null,
    start_time: `${reference}T12:47:59Z`,
    reference_date: reference,
    secondary_date: secondary,
    footprint: [],
  };
}

export function demoGcovGranules(stack: DemoStack): Granule[] {
  return stack.acquisitions.map((acquisition) => demoGcovGranule(stack, acquisition));
}

function stackOf(granules: Granule[], product: string): Stack {
  const tiers: Record<string, number> = {};
  for (const granule of granules) tiers[granule.tier] = (tiers[granule.tier] ?? 0) + 1;
  const first = granules[0];
  return {
    product,
    track: first.track,
    direction: first.direction,
    frame: first.frame,
    dates: [...new Set(granules.map((g) => g.date ?? g.reference_date ?? ""))].sort(),
    tiers,
    polarizations: [...new Set(granules.flatMap((g) => g.polarizations))].sort(),
  };
}

export function buildDemoCoverage(query: CoverageQuery): Coverage {
  const gcovA = demoGcovGranules(DEMO_STACK_A);
  const gcovB = demoGcovGranules(DEMO_STACK_B);
  const gunw = DEMO_PAIRS.map(([reference, secondary]) => demoGunwGranule(reference, secondary));
  const echoed: JsonObject = "bbox" in query ? { bbox: [...query.bbox] } : { lon: query.lon, lat: query.lat };
  return {
    query: echoed,
    products: {
      GCOV: [...gcovA, ...gcovB].sort((a, b) => (a.start_time ?? "").localeCompare(b.start_time ?? "")),
      GUNW: gunw,
      SME2: [],
    },
    stacks: [stackOf(gcovA, "GCOV"), stackOf(gcovB, "GCOV"), stackOf(gunw, "GUNW")],
    notes: [
      "No acquisitions between 2026-01-09 and 2026-06-19 (161 days).",
      "Beta-tier acquisitions are uncalibrated; compare them with later dates only with care.",
    ],
  };
}

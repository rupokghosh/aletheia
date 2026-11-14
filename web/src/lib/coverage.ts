/** Derivations over a Coverage object: which acquisitions belong to which stack, and where the gaps are. */

import { dayNumber } from "./format";
import { footprintShare } from "./geo";
import { TIER_ORDER } from "./tiers";
import type { BBox, Coverage, Granule, Stack, Tier } from "./types";

export interface StackMark {
  /** single-date products: the acquisition date. Pair products: the reference date. */
  date: string;
  /** pair products only */
  secondaryDate: string | null;
  tier: Tier;
  granule: Granule;
  /** vertical sub-row, so overlapping pairs do not cover each other */
  lane: number;
}

export interface StackGap {
  from: string;
  to: string;
  days: number;
}

export interface StackView {
  key: string;
  stack: Stack;
  isPair: boolean;
  marks: StackMark[];
  lanes: number;
  gaps: StackGap[];
  /**
   * Share of the area inside this stack's footprint, 0 to 1, or null when the catalogue gives no
   * footprint. The usable share can be smaller: a footprint includes the empty margins of a frame.
   */
  areaShare: number | null;
}

export function stackKeyOf(stack: Pick<Stack, "product" | "track" | "frame" | "direction">): string {
  return `${stack.product}|${stack.track}|${stack.frame}|${stack.direction}`;
}

const tierRank = (tier: Tier) => TIER_ORDER.indexOf(tier);

function belongsTo(stack: Stack, granule: Granule): boolean {
  return granule.track === stack.track && granule.frame === stack.frame && granule.direction === stack.direction;
}

/** Gaps at least twice the usual revisit, and never shorter than 30 days. */
function gapsOf(dates: string[]): StackGap[] {
  const intervals = dates.slice(1).map((date, i) => dayNumber(date) - dayNumber(dates[i]));
  if (intervals.length === 0) return [];
  const usual = [...intervals].sort((a, b) => a - b)[Math.floor(intervals.length / 2)];
  const threshold = Math.max(30, usual * 2);
  return intervals
    .map((days, i) => ({ from: dates[i], to: dates[i + 1], days }))
    .filter((gap) => gap.days >= threshold);
}

/** Products in the order they are listed: the ones this tool can analyse first. */
const PRODUCT_ORDER = ["GCOV", "GUNW"];

function productRank(product: string): number {
  const rank = PRODUCT_ORDER.indexOf(product);
  return rank === -1 ? PRODUCT_ORDER.length : rank;
}

/**
 * One view per stack, best first: by product, then by how much of the area the stack covers, then
 * by how many acquisitions it has. The first backscatter stack is therefore the sensible default.
 */
export function stackViews(coverage: Coverage, bbox: BBox): StackView[] {
  const views = coverage.stacks.map((stack): StackView => {
    const granules = (coverage.products[stack.product] ?? []).filter((granule) => belongsTo(stack, granule));
    const isPair = granules.some((granule) => granule.reference_date);
    let marks: StackMark[];

    if (isPair) {
      const laneEnds: number[] = [];
      marks = granules
        .filter((g): g is Granule & { reference_date: string } => Boolean(g.reference_date))
        .sort((a, b) => a.reference_date.localeCompare(b.reference_date))
        .map((granule) => {
          const start = dayNumber(granule.reference_date);
          const end = granule.secondary_date ? dayNumber(granule.secondary_date) : start;
          let lane = laneEnds.findIndex((laneEnd) => laneEnd <= start);
          if (lane === -1) lane = laneEnds.length;
          laneEnds[lane] = end;
          return {
            date: granule.reference_date,
            secondaryDate: granule.secondary_date,
            tier: granule.tier,
            granule,
            lane,
          };
        });
    } else {
      // One mark per date. If a date exists in more than one tier, keep the best calibrated copy.
      const best = new Map<string, Granule>();
      for (const granule of granules) {
        if (!granule.date) continue;
        const current = best.get(granule.date);
        if (!current || tierRank(granule.tier) < tierRank(current.tier)) best.set(granule.date, granule);
      }
      marks = [...best.entries()]
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([date, granule]) => ({ date, secondaryDate: null, tier: granule.tier, granule, lane: 0 }));
    }

    const shares = granules
      .slice(0, 5)
      .map((granule) => footprintShare(bbox, granule.footprint))
      .filter((share): share is number => share !== null);
    return {
      key: stackKeyOf(stack),
      stack,
      isPair,
      marks,
      lanes: Math.max(1, ...marks.map((mark) => mark.lane + 1)),
      gaps: isPair ? [] : gapsOf(marks.map((mark) => mark.date)),
      areaShare: shares.length > 0 ? Math.min(...shares) : null,
    };
  });
  const share = (view: StackView) => Math.round((view.areaShare ?? 1) * 100);
  return views.sort(
    (a, b) =>
      productRank(a.stack.product) - productRank(b.stack.product) ||
      share(b) - share(a) ||
      b.marks.length - a.marks.length,
  );
}

/** First and last date across every stack, as day numbers. */
export function coverageSpan(views: StackView[]): { start: number; end: number } | null {
  const days = views.flatMap((view) =>
    view.marks.flatMap((mark) => [mark.date, mark.secondaryDate].filter((d): d is string => Boolean(d)).map(dayNumber)),
  );
  return days.length > 0 ? { start: Math.min(...days), end: Math.max(...days) } : null;
}

export function describeStack(stack: Stack): string {
  return `Track ${stack.track}, ${stack.direction}, frame ${stack.frame}`;
}

export const PRODUCT_NAMES: Record<string, string> = {
  GCOV: "radar brightness (GCOV)",
  GUNW: "ground-motion pairs (GUNW)",
  GOFF: "pixel offsets (GOFF)",
  SME2: "soil moisture (SME2)",
};

/** True when the stack's footprint covers the whole area (or the catalogue gives no footprint to judge by). */
export function coversArea(view: StackView): boolean {
  return (view.areaShare ?? 1) >= 0.995;
}

export interface CoverageSummary {
  /** distinct backscatter dates on tracks that cover the whole area */
  dates: number;
  tracks: number;
  first: string;
  last: string;
}

/** The one-sentence answer to "what does NISAR have here": usable backscatter dates and tracks. */
export function summarizeCoverage(views: StackView[]): CoverageSummary | null {
  const backscatter = views.filter((view) => view.stack.product === "GCOV" && !view.isPair);
  const usable = backscatter.some(coversArea) ? backscatter.filter(coversArea) : backscatter;
  const dates = [...new Set(usable.flatMap((view) => view.marks.map((mark) => mark.date)))].sort();
  if (dates.length === 0) return null;
  return { dates: dates.length, tracks: usable.length, first: dates[0], last: dates[dates.length - 1] };
}

export interface ChangeChoice {
  view: StackView;
  before: string | null;
  after: string | null;
}

/**
 * The stack and dates of the change analysis. Until the user chooses, it is the best-covered
 * stack with its first and last calibrated dates (beta dates are used only if there are no others).
 */
export function resolveChange(
  views: StackView[],
  selection: { stackKey: string | null; before: string | null; after: string | null },
): ChangeChoice | null {
  const stacks = views.filter((view) => view.stack.product === "GCOV" && !view.isPair && view.marks.length >= 2);
  if (stacks.length === 0) return null;
  const chosen = stacks.find((view) => view.key === selection.stackKey);
  if (chosen) return { view: chosen, before: selection.before, after: selection.after };
  const view = stacks[0];
  const calibrated = view.marks.filter((mark) => mark.tier !== "beta");
  const pool = calibrated.length >= 2 ? calibrated : view.marks;
  return { view, before: pool[0].date, after: pool[pool.length - 1].date };
}

/** Pairs for the ground-motion analysis, best-covered stack first and newest first within it. */
export function motionPairs(views: StackView[]): Array<{ mark: StackMark; stack: Stack }> {
  return views
    .filter((view) => view.stack.product === "GUNW")
    .flatMap((view) =>
      [...view.marks].sort((a, b) => b.date.localeCompare(a.date)).map((mark) => ({ mark, stack: view.stack })),
    );
}

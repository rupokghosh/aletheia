import type { Tier } from "./types";

export interface TierInfo {
  tier: Tier;
  label: string;
  /** one-line meaning, used in tooltips and the legend */
  meaning: string;
  color: string;
}

/** Calibration tiers, best first. Colour is always paired with a shape (see TierMark). */
export const TIERS: Record<Tier, TierInfo> = {
  validated: {
    tier: "validated",
    label: "Validated",
    meaning: "Uncertainties characterised by the mission. Suitable for quantitative work.",
    color: "var(--tier-validated)",
  },
  provisional: {
    tier: "provisional",
    label: "Provisional",
    meaning: "Calibrated, with validation still in progress. Values may change after reprocessing.",
    color: "var(--tier-provisional)",
  },
  beta: {
    tier: "beta",
    label: "Beta",
    meaning: "Early release, treated here as uncalibrated. Compare with other dates only with care.",
    color: "var(--tier-beta)",
  },
};

export const TIER_ORDER: Tier[] = ["validated", "provisional", "beta"];

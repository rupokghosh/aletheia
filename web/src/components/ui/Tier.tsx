import { TIERS } from "@/lib/tiers";
import type { Tier } from "@/lib/types";

/**
 * Tier marker as SVG content centred on (0, 0). Shape carries the tier as well as colour:
 * validated is a filled circle, provisional a filled diamond, beta a hollow triangle.
 */
export function TierShape({ tier, r = 5, surface = "var(--panel)" }: { tier: Tier | null; r?: number; surface?: string }) {
  if (tier === "validated") return <circle r={r} fill={TIERS.validated.color} stroke={surface} strokeWidth={1.5} />;
  if (tier === "provisional") {
    const d = r * 1.25;
    return (
      <path
        d={`M0 ${-d}L${d} 0L0 ${d}L${-d} 0Z`}
        fill={TIERS.provisional.color}
        stroke={surface}
        strokeWidth={1.5}
      />
    );
  }
  if (tier === "beta") {
    const d = r * 1.15;
    return (
      <path
        d={`M0 ${-d}L${d} ${d * 0.85}L${-d} ${d * 0.85}Z`}
        fill={surface}
        stroke={TIERS.beta.color}
        strokeWidth={1.75}
        strokeLinejoin="round"
      />
    );
  }
  return <rect x={-r * 0.8} y={-r * 0.8} width={r * 1.6} height={r * 1.6} fill="var(--ink-3)" stroke={surface} strokeWidth={1.5} />;
}

export function TierMark({ tier, size = 14 }: { tier: Tier | null; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="-8 -8 16 16" aria-hidden="true" focusable="false" className="shrink-0">
      <TierShape tier={tier} />
    </svg>
  );
}

export function TierBadge({ tier }: { tier: Tier }) {
  const info = TIERS[tier];
  return (
    <span
      className="inline-flex shrink-0 items-center gap-1.5 rounded-full border border-line bg-panel px-2 py-0.5 text-[13px] whitespace-nowrap text-ink"
      title={info.meaning}
    >
      <TierMark tier={tier} size={12} />
      {info.label}
    </span>
  );
}

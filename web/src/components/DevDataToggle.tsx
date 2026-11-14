"use client";

import { useApiMode } from "@/lib/useActions";

const OPTIONS = [
  ["demo", "Demo data"],
  ["worst", "Worst case"],
  ["empty", "Empty"],
  ["one", "One"],
] as const;

/**
 * Development only: swaps the demo fixtures for worst-case data, to find layout breaks. The choice
 * lives in the address (?data=worst) so a reload keeps it. Plain on purpose: it is a tool, not
 * part of the interface, and it is never rendered in a production build or against a live API.
 */
export function DevDataToggle() {
  const mode = useApiMode();
  if (process.env.NODE_ENV !== "development" || !mode.demo) return null;

  const params = new URLSearchParams(window.location.search);
  // "demo" keeps the ordinary fixtures on screen when an API is configured.
  const current = params.get("data") ?? "demo";
  const choose = (value: string) => {
    const url = new URL(window.location.href);
    url.searchParams.set("data", value);
    window.location.assign(url);
  };

  return (
    <div
      role="group"
      aria-label="Development data set"
      className="fixed bottom-2 left-1/2 z-50 flex -translate-x-1/2 gap-0.5 rounded-md bg-neutral-300 p-0.5 font-sans text-xs text-neutral-800"
    >
      {OPTIONS.map(([value, label]) => (
        <button
          key={value}
          type="button"
          aria-pressed={current === value}
          className={`rounded px-2 py-1 ${current === value ? "bg-white" : ""}`}
          onClick={() => choose(value)}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

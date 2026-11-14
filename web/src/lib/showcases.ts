/** Precomputed investigations served as static files from web/public/showcases. */

import { SHOWCASE_INDEX_URL } from "./config";
import { isInvestigation, type Investigation, type ShowcaseEntry } from "./types";

function isEntry(value: unknown): value is ShowcaseEntry {
  if (typeof value !== "object" || value === null) return false;
  const entry = value as Record<string, unknown>;
  return ["id", "title", "place_name", "question", "file"].every((key) => typeof entry[key] === "string");
}

/** Reads the index. Accepts a bare array or {"showcases": [...]}. */
export async function loadShowcaseIndex(signal?: AbortSignal): Promise<ShowcaseEntry[]> {
  const response = await fetch(SHOWCASE_INDEX_URL, { signal, cache: "no-cache" });
  if (!response.ok) throw new Error(`The showcase index could not be loaded (${response.status}).`);
  const body: unknown = await response.json();
  const list = Array.isArray(body) ? body : (body as { showcases?: unknown } | null)?.showcases;
  return Array.isArray(list) ? list.filter(isEntry) : [];
}

export async function loadShowcase(entry: ShowcaseEntry, signal?: AbortSignal): Promise<Investigation> {
  const base = SHOWCASE_INDEX_URL.replace(/[^/]+$/, "");
  const response = await fetch(new URL(entry.file, new URL(base, window.location.origin)), { signal });
  if (!response.ok) throw new Error(`"${entry.title}" could not be loaded (${response.status}).`);
  const body: unknown = await response.json();
  if (!isInvestigation(body)) throw new Error(`"${entry.title}" is not a valid investigation file.`);
  return body;
}

/** How the layers of a result are shown on the map: plain toggles, a two-date compare or a time scrubber. */

import { resolveArtifactUrl, type DataSource } from "./api";
import type { Layer, Legend, LonLat, WorkflowResult } from "./types";

export type LayerMode = "plain" | "compare" | "scrub";

export interface LayerSetting {
  visible: boolean;
  opacity: number;
}

/** Display state of one result. Kept per result so switching results restores the view. */
export interface ResultDisplay {
  layers: Record<string, LayerSetting>;
  /** which date group is compared or scrubbed, as an index into dateGroups() */
  group: number;
  /** compare mode: swipe between the two dated layers of the group */
  compare: boolean;
  /** swipe position across the map, 0 (left edge) to 1 (right edge) */
  swipe: number;
  /** scrub mode: the dated layers of the group act as one layer */
  groupVisible: boolean;
  groupOpacity: number;
  scrubIndex: number;
}

export interface MapLayer {
  key: string;
  title: string;
  url: string;
  corners: LonLat[];
  opacity: number;
  resampling: "linear" | "nearest";
  role: "plain" | "before" | "after";
  legend: Legend | null;
  date: string | null;
  /** false for scrubber frames that are loaded but not the one on show */
  shown: boolean;
}

const DEFAULT_OPACITY = 0.9;
const HIDDEN: LayerSetting = { visible: false, opacity: DEFAULT_OPACITY };

/**
 * Sets of layers that show the same quantity on different dates, in date order: the before and
 * after images of one polarization, or the frames of a time series. Layers belong together when
 * they share a legend; a repeated or earlier date starts a new set (HH pair, then HV pair).
 */
export function dateGroups(result: WorkflowResult): Layer[][] {
  const bySignature = new Map<string, Layer[][]>();
  for (const layer of result.layers) {
    if (!layer.date) continue;
    const signature = JSON.stringify(layer.legend);
    const runs = bySignature.get(signature) ?? [];
    const run = runs[runs.length - 1];
    const last = run?.[run.length - 1];
    if (run && last?.date && layer.date > last.date) run.push(layer);
    else runs.push([layer]);
    bySignature.set(signature, runs);
  }
  return [...bySignature.values()].flat().filter((run) => run.length >= 2);
}

export function layerMode(result: WorkflowResult): LayerMode {
  const groups = dateGroups(result);
  if (groups.some((group) => group.length > 2)) return "scrub";
  return groups.length > 0 ? "compare" : "plain";
}

/** The group in use: the chosen one, falling back to the first. For scrubbing, only sets of three or more count. */
export function activeGroup(result: WorkflowResult, display: Pick<ResultDisplay, "group">): Layer[] {
  const groups = dateGroups(result);
  const usable = layerMode(result) === "scrub" ? groups.filter((group) => group.length > 2) : groups;
  return usable[display.group] ?? usable[0] ?? [];
}

/** A short name for a date group, from what its layer titles have in common ("HH" for "HH before…", "HH after…"). */
export function groupName(group: Layer[], index: number): string {
  const [first = "", ...rest] = group.map((layer) => layer.title);
  let length = first.length;
  for (const title of rest) {
    let i = 0;
    while (i < length && title[i] === first[i]) i += 1;
    length = i;
  }
  // Titles that differ only in a date share part of it ("HH, 202"): step back to the last whole word.
  const wordChar = /[\p{L}\p{N}]/u;
  if (length < first.length && wordChar.test(first[length]) && length > 0 && wordChar.test(first[length - 1])) {
    while (length > 0 && wordChar.test(first[length - 1])) length -= 1;
  }
  const common = first.slice(0, length).replace(/[\s,;:(\u2013-]+$/, "").trim();
  return common.length >= 2 ? common : `Set ${index + 1}`;
}

export function initialDisplay(result: WorkflowResult): ResultDisplay {
  const mode = layerMode(result);
  const group = activeGroup(result, { group: 0 });
  const grouped = (layer: Layer) => mode === "scrub" && group.includes(layer);
  const free = result.layers.filter((layer) => !grouped(layer));
  const anyDefault = free.some((layer) => layer.default_visible);

  const layers: Record<string, LayerSetting> = {};
  result.layers.forEach((layer) => {
    const fallback = !anyDefault && mode !== "scrub" && layer === free[0];
    layers[layer.id] = { visible: layer.default_visible || fallback, opacity: DEFAULT_OPACITY };
  });

  const defaultFrame = group.findLastIndex((layer) => layer.default_visible);
  return {
    layers,
    group: 0,
    compare: false,
    swipe: 0.5,
    groupVisible: mode === "scrub" && (defaultFrame !== -1 || !anyDefault),
    groupOpacity: DEFAULT_OPACITY,
    scrubIndex: defaultFrame !== -1 ? defaultFrame : Math.max(0, group.length - 1),
  };
}

/** The layers that are on the map right now, bottom to top. */
export function mapLayersFor(result: WorkflowResult, display: ResultDisplay, source: DataSource): MapLayer[] {
  const mode = layerMode(result);
  const group = activeGroup(result, display);
  const scrubbed = group[Math.min(display.scrubIndex, group.length - 1)];
  const out: MapLayer[] = [];

  // The first layer of a result is its main one, so it is drawn last (on top).
  for (const layer of [...result.layers].reverse()) {
    const setting = display.layers[layer.id] ?? HIDDEN;
    let visible = setting.visible;
    let opacity = setting.opacity;
    let role: MapLayer["role"] = "plain";
    let shown = true;

    if (mode === "scrub" && group.includes(layer)) {
      // Every frame stays loaded so that scrubbing only changes opacity and never reloads an image.
      visible = display.groupVisible;
      shown = layer === scrubbed;
      opacity = shown ? display.groupOpacity : 0;
    } else if (mode === "compare" && display.compare && group.includes(layer)) {
      visible = true;
      role = layer === group[0] ? "before" : "after";
    }
    if (!visible) continue;

    out.push({
      key: `${result.id}:${layer.id}`,
      title: layer.title,
      url: resolveArtifactUrl(layer.url, source),
      corners: layer.corners,
      opacity,
      resampling: layer.legend?.type === "categorical" ? "nearest" : "linear",
      role,
      legend: layer.legend,
      date: layer.date,
      shown,
    });
  }

  // Compare needs "before" directly under "after". Other layers the user switches on go above.
  const before = out.filter((l) => l.role === "before");
  const after = out.filter((l) => l.role === "after");
  return [...before, ...after, ...out.filter((l) => l.role === "plain")];
}

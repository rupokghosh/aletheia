"use client";

import { useId, useState, type ReactNode } from "react";
import { LegendView } from "@/components/results/LegendView";
import { SourceBadge } from "@/components/ui/SourceBadge";
import { ChevronDownIcon, ChevronLeftIcon, ChevronRightIcon, LayersIcon } from "@/components/ui/icons";
import { GIBS } from "@/lib/config";
import { dayNumber, formatDate, isoFromDayNumber, mentionsDate, plural } from "@/lib/format";
import { activeGroup, dateGroups, groupName, layerMode, type MapLayer, type ResultDisplay } from "@/lib/layers";
import { useApp, type StoredResult } from "@/lib/store";
import type { Layer, Legend } from "@/lib/types";
import { TimeScrubber } from "./TimeScrubber";

interface LayerRowProps {
  title: string;
  detail?: string;
  /** what the layer shows and what its colours mean, in a sentence or two */
  description?: string | null;
  visible: boolean;
  locked?: boolean;
  opacity: number;
  legend: Legend | null;
  onVisible: (visible: boolean) => void;
  onOpacity: (opacity: number) => void;
  children?: ReactNode;
}

function LayerRow({ title, detail, description, visible, locked = false, opacity, legend, onVisible, onOpacity, children }: LayerRowProps) {
  const id = useId();
  return (
    <li className="py-2">
      <div className="flex items-start gap-2.5">
        <input
          id={`${id}-visible`}
          type="checkbox"
          className="mt-0.5 shrink-0"
          checked={visible}
          disabled={locked}
          onChange={(event) => onVisible(event.target.checked)}
        />
        <label htmlFor={`${id}-visible`} className="min-w-0 flex-1 text-sm leading-snug [overflow-wrap:anywhere] text-ink">
          {title}
          {detail ? <span className="ml-1.5 text-ink-3">{detail}</span> : null}
        </label>
      </div>
      {visible ? (
        <div className="mt-2 space-y-2.5 pl-[26px]">
          {description ? <p className="text-[13px] leading-snug text-ink-2">{description}</p> : null}
          {legend ? <LegendView legend={legend} /> : null}
          <div className="flex items-center gap-2.5">
            <label htmlFor={`${id}-opacity`} className="text-[13px] text-ink-3">
              Opacity
            </label>
            <input
              id={`${id}-opacity`}
              type="range"
              className="min-w-0 flex-1"
              min={0.1}
              max={1}
              step={0.05}
              value={opacity}
              onChange={(event) => onOpacity(Number(event.target.value))}
            />
            <span className="w-10 text-right text-[13px] text-ink-2">{Math.round(opacity * 100)}%</span>
          </div>
          {children}
        </div>
      ) : null}
    </li>
  );
}

/** The layers of the open result: visibility, opacity, legend, the before/after swipe and the date slider. */
function ResultLayers({ stored, display }: { stored: StoredResult; display: ResultDisplay }) {
  const { dispatch } = useApp();
  const compareId = useId();
  const groupId = useId();
  const { result } = stored;
  const mode = layerMode(result);
  const groups = dateGroups(result).filter((group) => (mode === "scrub" ? group.length > 2 : true));
  const group = activeGroup(result, display);
  const resultId = result.id;
  const scrubIndex = Math.min(display.scrubIndex, group.length - 1);
  const dateOf = (layer: Layer) => (layer.date && !mentionsDate(layer.title, layer.date) ? formatDate(layer.date) : undefined);
  const free = result.layers.filter((layer) => !(mode === "scrub" && group.includes(layer)));
  const advanced = free.filter((layer) => layer.group === "advanced");
  const row = (layer: Layer) => {
    const setting = display.layers[layer.id] ?? { visible: false, opacity: 0.9 };
    const inComparison = mode === "compare" && display.compare && group.includes(layer);
    return (
      <LayerRow
        key={layer.id}
        title={layer.title}
        detail={dateOf(layer)}
        description={layer.description}
        visible={inComparison || setting.visible}
        locked={inComparison}
        opacity={setting.opacity}
        legend={layer.legend}
        onVisible={(visible) => dispatch({ type: "layer", resultId, layerId: layer.id, setting: { visible } })}
        onOpacity={(opacity) => dispatch({ type: "layer", resultId, layerId: layer.id, setting: { opacity } })}
      />
    );
  };

  return (
    <>
      {mode === "compare" ? (
        <div className="border-b border-line pb-2.5">
          <div className="flex items-start gap-2.5">
            <input
              id={compareId}
              type="checkbox"
              className="mt-0.5 shrink-0"
              checked={display.compare}
              onChange={(event) => dispatch({ type: "display", resultId, display: { compare: event.target.checked } })}
            />
            <label htmlFor={compareId} className="min-w-0 text-sm leading-snug text-ink">
              Compare before and after
              <span className="block text-[13px] text-ink-3">
                Swipe between {formatDate(group[0].date)} and {formatDate(group[1].date)}.
              </span>
            </label>
          </div>
          {groups.length > 1 ? (
            <div className="mt-2 flex items-center gap-2.5 pl-[26px]">
              <label htmlFor={groupId} className="shrink-0 text-[13px] text-ink-3">
                Images
              </label>
              <select
                id={groupId}
                className="field min-h-9 py-1 text-sm"
                value={Math.max(0, groups.indexOf(group))}
                onChange={(event) => dispatch({ type: "display", resultId, display: { group: Number(event.target.value) } })}
              >
                {groups.map((item, index) => (
                  <option key={item[0].id} value={index}>
                    {groupName(item, index)}
                  </option>
                ))}
              </select>
            </div>
          ) : null}
        </div>
      ) : null}

      <ul className="divide-y divide-line">
        {mode === "scrub" ? (
          <LayerRow
            title={`${groupName(group, 0)}, ${plural(group.length, "date")}`}
            visible={display.groupVisible}
            opacity={display.groupOpacity}
            description={group[scrubIndex].description}
            legend={group[scrubIndex].legend}
            onVisible={(groupVisible) => dispatch({ type: "display", resultId, display: { groupVisible } })}
            onOpacity={(groupOpacity) => dispatch({ type: "display", resultId, display: { groupOpacity } })}
          >
            <TimeScrubber
              dates={group.map((layer) => layer.date ?? "")}
              index={scrubIndex}
              onChange={(index) => dispatch({ type: "display", resultId, display: { scrubIndex: index } })}
            />
          </LayerRow>
        ) : null}

        {free.filter((layer) => layer.group !== "advanced").map(row)}
      </ul>
      {advanced.length > 0 ? (
        <details className="border-t border-line pt-1">
          <summary className="w-max py-2 text-sm text-ink-2 underline underline-offset-2 hover:text-ink">
            More layers ({advanced.length})
          </summary>
          <ul className="divide-y divide-line">{advanced.map(row)}</ul>
        </details>
      ) : null}
    </>
  );
}

function today(): string {
  return new Date().toISOString().slice(0, 10);
}

/** NASA GIBS quick-look imagery: a picture for orientation, with its date. Never measured from. */
function ReferenceImagery() {
  const { state, dispatch } = useApp();
  const { gibs } = state;
  const toggleId = useId();
  const dateId = useId();
  const latest = today();
  const setDate = (date: string) => {
    if (date >= GIBS.firstDate && date <= latest) dispatch({ type: "gibs", gibs: { date } });
  };
  const step = "press grid size-9 shrink-0 place-items-center rounded-full border border-line-strong text-ink-2 hover:bg-raised";

  return (
    <div>
      <div className="flex items-start gap-2.5">
        <input
          id={toggleId}
          type="checkbox"
          className="mt-0.5 shrink-0"
          checked={gibs.enabled}
          onChange={(event) => dispatch({ type: "gibs", gibs: { enabled: event.target.checked } })}
        />
        <label htmlFor={toggleId} className="text-sm leading-snug text-ink">
          {GIBS.label}
        </label>
      </div>
      {gibs.enabled ? (
        <div className="mt-2 pl-[26px]">
          <label htmlFor={dateId} className="mb-1 block text-[13px] text-ink-3">
            Day shown (UTC). Most days are empty at any one place.
          </label>
          <div className="flex items-center gap-1.5">
            <button type="button" aria-label="Previous day" className={step} onClick={() => setDate(isoFromDayNumber(dayNumber(gibs.date) - 1))}>
              <ChevronLeftIcon />
            </button>
            <input
              id={dateId}
              type="date"
              className="field min-h-9 py-1 text-sm"
              min={GIBS.firstDate}
              max={latest}
              value={gibs.date}
              onChange={(event) => setDate(event.target.value)}
            />
            <button type="button" aria-label="Next day" className={step} onClick={() => setDate(isoFromDayNumber(dayNumber(gibs.date) + 1))}>
              <ChevronRightIcon />
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

interface LayersCardProps {
  /** the result whose layers are on the map, or null when none is being read */
  stored: StoredResult | null;
  display: ResultDisplay | undefined;
  layers: MapLayer[];
}

/**
 * The floating card on the map that controls what is drawn on it. On a wide screen it opens by
 * itself when a result puts layers on the map; it can always be folded away to a small pill.
 */
export function LayersCard({ stored, display, layers }: LayersCardProps) {
  const hasLayers = stored !== null && display !== undefined && stored.result.layers.length > 0;
  const [folded, setFolded] = useState<boolean | null>(null);
  // Until the user decides: open when a result has layers, except on a phone, where it would cover the map.
  const open = folded === null ? hasLayers && window.matchMedia("(min-width: 768px)").matches : !folded;
  const shown = layers.filter((layer) => layer.shown && layer.opacity > 0).length;

  if (!open) {
    return (
      <button
        type="button"
        className="press pointer-events-auto flex items-center gap-2 rounded-full border border-line bg-panel px-4 py-2.5 text-sm text-ink shadow-card hover:bg-raised"
        aria-expanded={false}
        onClick={() => setFolded(false)}
      >
        <LayersIcon />
        Map layers
        {shown > 0 ? <span className="text-ink-3">{shown} on</span> : null}
      </button>
    );
  }

  return (
    <section
      aria-label="Map layers"
      className="popover pointer-events-auto flex max-h-full w-80 max-w-[calc(100vw-1.5rem)] origin-top-right flex-col overflow-hidden rounded-2xl border border-line bg-panel shadow-card"
    >
      <header className="flex shrink-0 items-center justify-between gap-2 py-2 pr-2 pl-4">
        <h2 className="text-[15px] tracking-normal text-ink">On the map</h2>
        <div className="flex items-center gap-1.5">
          {stored && hasLayers ? <SourceBadge source={stored.source} /> : null}
          <button
            type="button"
            className="press grid size-9 place-items-center rounded-full text-ink-2 hover:bg-raised hover:text-ink"
            aria-label="Fold the layers card"
            aria-expanded={true}
            onClick={() => setFolded(true)}
          >
            <ChevronDownIcon />
          </button>
        </div>
      </header>
      <div className="scroll-quiet min-h-0 overflow-y-auto px-4 pb-4">
        {hasLayers ? (
          <p className="mb-2 rounded-xl bg-raised px-3 py-2 text-[13px] leading-snug text-ink-2">
            Click anywhere on the map to read what the radar measured at that spot.
          </p>
        ) : null}
        {hasLayers ? <ResultLayers stored={stored} display={display} /> : null}
        <div className={hasLayers ? "mt-1 border-t border-line pt-3" : ""}>
          <ReferenceImagery />
        </div>
      </div>
    </section>
  );
}

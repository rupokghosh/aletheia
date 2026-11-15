"use client";

import { ChartFrame } from "@/components/charts/ChartFrame";
import { GaugeChart } from "@/components/charts/GaugeChart";
import { QuakeTimeline, type Quake } from "@/components/charts/QuakeTimeline";
import { ChartView } from "@/components/charts/ResultCharts";
import { SeriesChart } from "@/components/results/SeriesChart";
import { decimalsFor, formatDate, formatNumber, formatUnit } from "@/lib/format";
import { useApp } from "@/lib/store";
import type { JsonObject, JsonValue, Metric, WorkflowResult } from "@/lib/types";

const isObject = (value: JsonValue | undefined): value is JsonObject => typeof value === "object" && value !== null && !Array.isArray(value);
const text = (value: JsonValue | undefined): string | null => (typeof value === "string" ? value : null);
const number = (value: JsonValue | undefined): number | null => (typeof value === "number" && Number.isFinite(value) ? value : null);

/** "THOMPSON RIVER AT KAMLOOPS" as "Thompson River at Kamloops". */
function placeCase(name: string): string {
  const small = new Set(["at", "nr", "near", "of", "the", "on", "above", "below"]);
  return name
    .toLowerCase()
    .split(/\s+/)
    .map((word, index) => (index > 0 && small.has(word) ? word : word.charAt(0).toUpperCase() + word.slice(1)))
    .join(" ")
    .replace(/\bNr\b/i, "near");
}

/** The days of the radar passes an analysis compared, where it compared two. */
function passDays(result: WorkflowResult): string[] {
  if (result.workflow === "change") {
    return [text(result.request.date_before), text(result.request.date_after)].filter((d): d is string => d !== null);
  }
  if (result.workflow === "motion" && isObject(result.stats.pair)) {
    return [text(result.stats.pair.reference_date), text(result.stats.pair.secondary_date)].filter((d): d is string => d !== null);
  }
  return [];
}

interface Figure {
  key: string;
  value: string;
  label: string;
}

function rangeOf(metric: Metric): string {
  const unit = formatUnit(metric.unit);
  const tail = unit === "%" ? "%" : unit ? ` ${unit}` : "";
  if (metric.low !== null && metric.high !== null) {
    const decimals = Math.min(decimalsFor([metric.low, metric.high]), Math.max(Math.abs(metric.high), Math.abs(metric.low)) >= 100 ? 0 : 2);
    return `${formatNumber(metric.low, decimals)} to ${formatNumber(metric.high, decimals)}${tail}`;
  }
  return `${formatNumber(metric.central, decimalsFor([metric.central]))}${tail}`;
}

interface Gauge {
  id: string;
  name: string;
  distanceKm: number | null;
  daily: Array<[string, number]>;
  marks: string[];
  levels: Array<{ day: string; level: number }>;
}

function gaugesOf(context: JsonObject | undefined): Gauge[] {
  if (!context || !Array.isArray(context.gauges)) return [];
  return context.gauges.flatMap((item) => {
    if (!isObject(item)) return [];
    const onDates = isObject(item.level_on_dates) ? item.level_on_dates : {};
    const levels = Object.entries(onDates)
      .flatMap(([day, level]) => (typeof level === "number" ? [{ day, level }] : []))
      .sort((a, b) => a.day.localeCompare(b.day));
    const daily = Array.isArray(item.daily)
      ? item.daily.flatMap((row): Array<[string, number]> => (Array.isArray(row) && typeof row[0] === "string" && typeof row[1] === "number" ? [[row[0], row[1]]] : []))
      : [];
    return [
      {
        id: text(item.station_id) ?? "gauge",
        name: placeCase(text(item.station_name) ?? "River gauge"),
        distanceKm: number(item.distance_km),
        daily,
        marks: levels.map((entry) => entry.day),
        levels,
      },
    ];
  });
}

function quakesOf(context: JsonObject | undefined): Quake[] {
  if (!context || !Array.isArray(context.events)) return [];
  return context.events.flatMap((item) => {
    if (!isObject(item)) return [];
    const time = text(item.time_utc);
    const magnitude = number(item.magnitude);
    return time !== null && magnitude !== null ? [{ time_utc: time, magnitude, distance_km: number(item.distance_km), place: text(item.place) }] : [];
  });
}

/** The few figures a reader should take away, taken from the results themselves (never from the written report). */
function figuresOf(results: WorkflowResult[], gauges: Gauge[], quakes: Quake[]): Figure[] {
  const figures: Figure[] = [];
  for (const result of results) {
    if (result.status !== "ok") continue;
    const ranged = result.summary.metrics.filter((metric) => metric.low !== null && metric.high !== null).slice(0, 2);
    for (const metric of ranged) figures.push({ key: `${result.id}-${metric.key}`, value: rangeOf(metric), label: metric.label });
  }
  const gauge = gauges.find((item) => item.levels.length >= 2);
  if (gauge) {
    const first = gauge.levels[0];
    const last = gauge.levels[gauge.levels.length - 1];
    const change = last.level - first.level;
    figures.push({
      key: `gauge-${gauge.id}`,
      value: `${change > 0 ? "+" : "−"}${formatNumber(Math.abs(change), 2)} m`,
      label: `River level at the gauge, ${formatNumber(first.level, 2)} m on ${formatDate(first.day).replace(/\s\d{4}$/, "")} to ${formatNumber(last.level, 2)} m on ${formatDate(last.day).replace(/\s\d{4}$/, "")}`,
    });
  }
  if (quakes.length > 0) {
    const strongest = quakes.reduce((best, quake) => (quake.magnitude > best.magnitude ? quake : best), quakes[0]);
    figures.push({
      key: "quake",
      value: `Magnitude ${formatNumber(strongest.magnitude, 1)}`,
      label: `Strongest earthquake nearby, ${formatDate(strongest.time_utc.slice(0, 10))}${strongest.distance_km !== null ? `, ${formatNumber(strongest.distance_km, 0)} km away` : ""}`,
    });
  }
  return figures.slice(0, 4);
}

interface EvidenceProps {
  /** the analyses this investigation ran */
  results: WorkflowResult[];
  /** its other findings by id: coverage and the independent context */
  others: Record<string, JsonObject>;
}

/**
 * The evidence behind a report, shown rather than described: the key figures, the independent record
 * (river level, earthquakes) with the radar passes marked on it, and the leading chart of each analysis.
 */
export function Evidence({ results, others }: EvidenceProps) {
  const { dispatch } = useApp();
  const gauges = gaugesOf(others.ctx_river_gauges);
  const quakes = quakesOf(others.ctx_earthquakes);
  const figures = figuresOf(results, gauges, quakes);
  const passes = [...new Set(results.flatMap(passDays))].sort();
  const charted = results.filter((result) => result.status === "ok" && ((result.charts?.length ?? 0) > 0 || result.series.length > 0));
  const gauge = gauges.find((item) => item.daily.length > 1);
  const search = isObject(others.ctx_earthquakes?.search) ? others.ctx_earthquakes.search : null;
  if (figures.length === 0 && charted.length === 0 && !gauge && quakes.length === 0) return null;

  return (
    <section className="mt-5 space-y-3" aria-label="Evidence">
      {figures.length > 0 ? (
        <dl className="grid grid-cols-2 gap-2">
          {figures.map((figure, index) => (
            <div key={figure.key} className={`rounded-2xl bg-raised p-3.5 ${figures.length % 2 === 1 && index === figures.length - 1 ? "col-span-2" : ""}`}>
              <dd className="text-[21px] leading-tight tracking-tight tabular-nums text-ink">{figure.value}</dd>
              <dt className="mt-1 text-[13px] leading-snug text-ink-2">{figure.label}</dt>
            </div>
          ))}
        </dl>
      ) : null}

      {gauge ? (
        <ChartFrame
          title={`River level at ${gauge.name}`}
          description={`An independent record${gauge.distanceKm !== null ? ` from a gauge ${formatNumber(gauge.distanceKm, 1)} km away` : ""}: not radar. It shows what the water was doing on the days the radar passed.`}
        >
          <GaugeChart daily={gauge.daily} marks={gauge.marks.length > 0 ? gauge.marks : passes} />
        </ChartFrame>
      ) : null}

      {quakes.length > 0 ? (
        <ChartFrame
          title={`Earthquakes within ${search && number(search.radius_km) !== null ? formatNumber(number(search.radius_km), 0) : "150"} km`}
          description="From the USGS catalogue: not radar. Taller stems are stronger earthquakes. Shaking that falls between the two radar passes is what the motion map can show."
        >
          <QuakeTimeline events={quakes} marks={passes} />
        </ChartFrame>
      ) : null}

      {charted.map((result) => (
        <div key={result.id} className="space-y-1.5">
          {result.charts && result.charts.length > 0 ? (
            <ChartView chart={result.charts[0]} />
          ) : (
            <ChartFrame title="Radar brightness on every date" description="One point per radar pass. A step that stands out from the rest is the change to look at.">
              <SeriesChart series={result.series} />
            </ChartFrame>
          )}
          <button type="button" className="text-sm text-ink underline underline-offset-2" onClick={() => dispatch({ type: "openResult", id: result.id })}>
            Open this result on the map, with all its charts
          </button>
        </div>
      ))}
    </section>
  );
}

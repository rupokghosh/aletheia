import type { Chart } from "@/lib/types";
import { ChartFrame } from "./ChartFrame";
import { Histogram } from "./Histogram";
import { Profile } from "./Profile";
import { Shares } from "./Shares";

export function ChartView({ chart }: { chart: Chart }) {
  return (
    <ChartFrame title={chart.title} description={chart.description}>
      {chart.kind === "histogram" ? <Histogram data={chart.data} /> : null}
      {chart.kind === "shares" ? <Shares data={chart.data} /> : null}
      {chart.kind === "profile" ? <Profile data={chart.data} /> : null}
    </ChartFrame>
  );
}

/** The charts a result came with, in the order the API listed them. */
export function ResultCharts({ charts }: { charts: Chart[] | undefined }) {
  if (!charts || charts.length === 0) return null;
  return (
    <div className="space-y-3">
      {charts.map((chart) => (
        <ChartView key={chart.id} chart={chart} />
      ))}
    </div>
  );
}

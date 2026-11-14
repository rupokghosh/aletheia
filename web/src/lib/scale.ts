/** Axis helpers shared by the chart and the coverage timeline. */

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export interface DayTick {
  /** days since the Unix epoch */
  day: number;
  label: string;
}

/** One tick at the start of each month inside [start, end]. The year is shown on the first tick and each January. */
export function monthTicks(start: number, end: number): DayTick[] {
  const ticks: DayTick[] = [];
  const cursor = new Date(start * 86_400_000);
  cursor.setUTCDate(1);
  for (let i = 0; i < 600; i += 1) {
    cursor.setUTCMonth(cursor.getUTCMonth() + 1);
    const day = Math.round(cursor.getTime() / 86_400_000);
    if (day > end) break;
    const month = cursor.getUTCMonth();
    const withYear = month === 0 || ticks.length === 0;
    ticks.push({ day, label: withYear ? `${MONTHS[month]} ${cursor.getUTCFullYear()}` : MONTHS[month] });
  }
  return ticks;
}

/** Keeps at most `max` ticks by taking every k-th one. */
export function thin<T>(ticks: T[], max: number): T[] {
  if (ticks.length <= max) return ticks;
  const step = Math.ceil(ticks.length / max);
  return ticks.filter((_, index) => index % step === 0);
}

/** Round tick values that cover [min, max], about `count` of them. */
export function niceTicks(min: number, max: number, count = 5): number[] {
  if (!Number.isFinite(min) || !Number.isFinite(max)) return [];
  if (min === max) return [min];
  const rough = (max - min) / Math.max(1, count);
  const power = 10 ** Math.floor(Math.log10(rough));
  // The round step closest to the ideal spacing, compared as a ratio.
  const step = [1, 2, 5, 10]
    .map((m) => m * power)
    .reduce((best, s) => (Math.abs(Math.log(s / rough)) < Math.abs(Math.log(best / rough)) ? s : best));
  const first = Math.ceil(min / step) * step;
  const ticks: number[] = [];
  for (let value = first; value <= max + step * 1e-9; value += step) ticks.push(Number(value.toPrecision(12)));
  return ticks;
}

/** Number, unit and date formatting. Every number in the interface goes through here. */

const UNIT_LABELS: Record<string, string> = {
  km2: "km²",
  m2: "m²",
  db: "dB",
  dB: "dB",
  cm: "cm",
  mm: "mm",
  m: "m",
  fraction: "",
  "%": "%",
};

/** Display form of a contract unit string ("km2" becomes "km²"). */
export function formatUnit(unit: string): string {
  return UNIT_LABELS[unit] ?? unit;
}

/** Sets contract unit spellings inside a sentence in display form: "7.2 km2" becomes "7.2 km²". */
export function prettyUnits(text: string): string {
  return text.replace(/\bkm2\b/g, "km²");
}

/** Fixed number of decimals chosen from the magnitude, so related values align. Whole numbers get none. */
export function decimalsFor(values: Array<number | null | undefined>): number {
  const finite = values.filter((v): v is number => typeof v === "number" && Number.isFinite(v));
  if (finite.length === 0 || finite.every((v) => Number.isInteger(v))) return 0;
  const largest = Math.max(...finite.map((v) => Math.abs(v)));
  if (largest >= 1000) return 0;
  if (largest >= 100) return 1;
  if (largest >= 0.1) return 2;
  return 3;
}

const pluralRules = new Intl.PluralRules("en");

/** "1 date", "2 dates". The plural is the singular plus "s" unless one is given. */
export function plural(count: number, singular: string, pluralForm = `${singular}s`): string {
  return `${count.toLocaleString("en-US")}\u00a0${pluralRules.select(count) === "one" ? singular : pluralForm}`;
}

/** A count unit from the API ("dates", "tracks") in the form that agrees with the value: "1 date". */
export function unitFor(value: number | null, unit: string): string {
  const label = formatUnit(unit);
  return value === 1 && /^[a-z]{3,}s$/.test(label) ? label.slice(0, -1) : label;
}

/** A number with a fixed count of decimals, thousands separators ("12,346") and a true minus sign. */
export function formatNumber(value: number | null | undefined, decimals = 2): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "n/a";
  // Avoid "-0.00"
  const rounded = Number(value.toFixed(decimals)) === 0 ? 0 : value;
  return rounded
    .toLocaleString("en-US", { minimumFractionDigits: decimals, maximumFractionDigits: decimals })
    .replace("-", "\u2212");
}

export function formatPercent(fraction: number | null | undefined, decimals = 0): string {
  if (fraction === null || fraction === undefined || !Number.isFinite(fraction)) return "n/a";
  return `${(fraction * 100).toFixed(decimals)}%`;
}

export function formatArea(km2: number): string {
  if (km2 >= 1000) return `${Math.round(km2).toLocaleString("en-US")} km²`;
  if (km2 >= 100) return `${km2.toFixed(0)} km²`;
  if (km2 >= 10) return `${km2.toFixed(1)} km²`;
  return `${km2.toFixed(2)} km²`;
}

export function formatSeconds(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return "n/a";
  return `${seconds.toFixed(seconds >= 10 ? 1 : 2)} s`;
}

export function formatCoordinate(value: number): string {
  return value.toFixed(4);
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "2026-06-19" becomes "19 Jun 2026". Input is a UTC acquisition date. */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "n/a";
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  if (!match) return iso;
  return `${Number(match[3])} ${MONTHS[Number(match[2]) - 1]} ${match[1]}`;
}

const MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

/** "June to October 2026", or "November 2025 to October 2026" when the years differ. */
export function formatMonthSpan(first: string, last: string): string {
  const [y1, m1] = [first.slice(0, 4), MONTH_NAMES[Number(first.slice(5, 7)) - 1]];
  const [y2, m2] = [last.slice(0, 4), MONTH_NAMES[Number(last.slice(5, 7)) - 1]];
  if (y1 === y2) return m1 === m2 ? `${m1} ${y1}` : `${m1} to ${m2} ${y1}`;
  return `${m1} ${y1} to ${m2} ${y2}`;
}

/** "2026-11-14T21:00:00Z" becomes "14 Nov 2026, 21:00 UTC". */
export function formatTimestamp(iso: string): string {
  const match = /^(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2})/.exec(iso);
  if (!match) return iso || "n/a";
  return `${formatDate(match[1])}, ${match[2]}:${match[3]} UTC`;
}

/** True when a title already states this date, as "2026-06-19" or as "19 June 2026". */
export function mentionsDate(text: string, iso: string): boolean {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  if (!match) return false;
  if (text.includes(match[0])) return true;
  const month = MONTHS[Number(match[2]) - 1];
  return text.includes(match[1]) && text.includes(month) && new RegExp(`\\b${Number(match[3])}\\b`).test(text);
}

/** Days since the Unix epoch for a "YYYY-MM-DD" date, in UTC. */
export function dayNumber(iso: string): number {
  return Math.round(Date.parse(`${iso.slice(0, 10)}T00:00:00Z`) / 86_400_000);
}

export function isoFromDayNumber(day: number): string {
  return new Date(day * 86_400_000).toISOString().slice(0, 10);
}

export function daysBetween(a: string, b: string): number {
  return dayNumber(b) - dayNumber(a);
}

/** Shortens a long granule name in the middle, keeping the informative ends. */
export function shortenMiddle(text: string, keepStart = 22, keepEnd = 18): string {
  if (text.length <= keepStart + keepEnd + 1) return text;
  return `${text.slice(0, keepStart)}…${text.slice(-keepEnd)}`;
}

const KEY_UNITS: Record<string, string> = { db: "dB", km2: "km²", cm: "cm", mm: "mm", m: "m", days: "days" };

/**
 * Readable label for a free-form key: "mean_before_db" becomes "Mean before (dB)".
 * A trailing unit is recognised and set in parentheses.
 */
export function humanizeKey(key: string): string {
  const words = key.split("_").filter(Boolean);
  const unit = words.length > 1 ? KEY_UNITS[words[words.length - 1].toLowerCase()] : undefined;
  // A unit in the middle of a key ("mean_db_before") keeps its place but gets its proper spelling.
  const text = (unit ? words.slice(0, -1) : words)
    .map((word) => (word === "db" ? "dB" : word === "km2" ? "km\u00b2" : word))
    .join(" ");
  const label = text.charAt(0).toUpperCase() + text.slice(1);
  return unit ? `${label} (${unit})` : label;
}

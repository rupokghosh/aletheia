import type { ReactNode } from "react";
import { humanizeKey, plural } from "@/lib/format";
import type { JsonObject, JsonValue } from "@/lib/types";

/**
 * Lays out free-form JSON: the `stats` object of a result, or context evidence from an
 * investigation. The contract does not fix its shape, so this reads the structure it is given:
 * single values become rows, like objects (one per polarization, say) become a side-by-side table,
 * and lists of records become a table with one row each.
 */

interface Leaf {
  path: string[];
  value: JsonValue;
}

const RANGE_KEYS = ["low", "central", "high"];

function isObject(value: JsonValue | undefined): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** {low, central, high}: shown as one value with its range, not as three rows. */
function isRange(value: JsonValue | undefined): value is JsonObject {
  if (!isObject(value)) return false;
  const keys = Object.keys(value);
  return keys.length >= 2 && keys.every((key) => RANGE_KEYS.includes(key) && typeof value[key] !== "object");
}

function isRecordList(value: JsonValue | undefined): value is JsonObject[] {
  return Array.isArray(value) && value.length > 0 && value.every((item) => isObject(item));
}

/** Up to six significant digits: enough to keep 14,902.1 honest without printing float noise. */
function number(value: number): string {
  return value.toLocaleString("en-US", { maximumSignificantDigits: 6 }).replace("-", "\u2212");
}

function show(value: JsonValue | undefined): string {
  if (value === null || value === undefined || value === "") return "n/a";
  if (typeof value === "number") return number(value);
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (typeof value === "string") return value;
  if (isRange(value)) return `${show(value.central)} (${show(value.low)} to ${show(value.high)})`;
  if (isRecordList(value)) return plural(value.length, "item");
  if (Array.isArray(value)) return value.length > 0 ? value.map(show).join(", ") : "none";
  // What remains is an object nested inside a table cell: its fields on one line.
  if (Object.keys(value).length === 0) return "none";
  return Object.entries(value as JsonObject)
    .map(([key, inner]) => `${humanizeKey(key).toLowerCase()} ${show(inner)}`)
    .join("; ");
}

/** Walks nested objects down to the values that can be shown in one cell. */
function flatten(value: JsonObject, path: string[] = []): Leaf[] {
  return Object.entries(value).flatMap(([key, inner]) =>
    isObject(inner) && !isRange(inner) && Object.keys(inner).length > 0
      ? flatten(inner, [...path, key])
      : [{ path: [...path, key], value: inner }],
  );
}

const label = (path: string[]) => path.map((part, index) => (index === 0 ? humanizeKey(part) : humanizeKey(part).toLowerCase())).join(", ");

function Rows({ leaves }: { leaves: Leaf[] }) {
  return (
    <dl className="text-sm">
      {leaves.map((leaf) => {
        const text = show(leaf.value);
        const long = text.length > 34;
        return (
          <div
            key={leaf.path.join(".")}
            className={`border-b border-line py-2 last:border-b-0 ${long ? "" : "flex items-baseline justify-between gap-4"}`}
          >
            <dt className="text-ink-2">{label(leaf.path)}</dt>
            <dd className={`[overflow-wrap:anywhere] text-ink ${long ? "mt-0.5" : "text-right"}`}>{text}</dd>
          </div>
        );
      })}
    </dl>
  );
}

function Table({ head, children }: { head: string[]; children: ReactNode }) {
  return (
    <div className="scroll-quiet overflow-x-auto rounded-xl border border-line" tabIndex={0} role="group" aria-label="Table, scrolls sideways">
      <table className="w-full border-collapse text-sm">
        <thead className="bg-raised text-[13px] text-ink-2">
          <tr>
            {head.map((heading, index) => (
              <th key={`${heading}-${index}`} scope="col" className={`px-3 py-2 font-normal whitespace-nowrap ${index === 0 ? "text-left" : "text-right"}`}>
                {heading}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}

/** Like objects side by side: one column per member (HH, HV), one row per value. */
function Compared({ members }: { members: Array<[string, JsonObject]> }) {
  const flat = members.map(([, member]) => flatten(member));
  const paths = [...new Map(flat.flat().map((leaf) => [leaf.path.join("."), leaf.path])).values()];
  return (
    <Table head={["", ...members.map(([name]) => name)]}>
      {paths.map((path) => (
        <tr key={path.join(".")} className="border-t border-line">
          <th scope="row" className="min-w-36 px-3 py-1.5 text-left font-normal text-ink-2">
            {label(path)}
          </th>
          {flat.map((leaves, index) => (
            <td key={members[index][0]} className="px-3 py-1.5 text-right whitespace-nowrap text-ink">
              {show(leaves.find((leaf) => leaf.path.join(".") === path.join("."))?.value)}
            </td>
          ))}
        </tr>
      ))}
    </Table>
  );
}

/** A list of records: one row each, one column per field. */
function Records({ records }: { records: JsonObject[] }) {
  const columns = [...new Set(records.flatMap((record) => Object.keys(record)))];
  return (
    <Table head={columns.map(humanizeKey)}>
      {records.map((record, row) => (
        <tr key={row} className="border-t border-line">
          {columns.map((column, index) => (
            <td
              key={column}
              className={`max-w-64 px-3 py-1.5 align-top ${index === 0 ? "text-left text-ink" : "text-right text-ink-2"} ${
                show(record[column]).length > 28 ? "min-w-48 text-left [overflow-wrap:anywhere]" : "whitespace-nowrap"
              }`}
            >
              {show(record[column])}
            </td>
          ))}
        </tr>
      ))}
    </Table>
  );
}

function Group({ name, value }: { name: string; value: JsonObject | JsonObject[] }) {
  let body: ReactNode;
  let size: number;
  if (Array.isArray(value)) {
    body = <Records records={value} />;
    size = value.length;
  } else {
    const members = Object.entries(value);
    const alike = members.length >= 2 && members.every(([, member]) => isObject(member) && !isRange(member));
    body = alike ? <Compared members={members as Array<[string, JsonObject]>} /> : <Rows leaves={flatten(value)} />;
    size = alike ? flatten(members[0][1] as JsonObject).length : flatten(value).length;
  }
  return (
    <details open={size <= 6} className="group/stats">
      <summary className="w-max py-1 text-sm text-ink-2 underline underline-offset-2 hover:text-ink">{humanizeKey(name)}</summary>
      <div className="mt-1.5 mb-2">{body}</div>
    </details>
  );
}

export function StatsTable({ stats }: { stats: JsonObject }) {
  const entries = Object.entries(stats);
  const isGroup = (value: JsonValue): value is JsonObject | JsonObject[] =>
    isRecordList(value) || (isObject(value) && !isRange(value) && Object.keys(value).length > 0);
  const single = entries.filter(([, value]) => !isGroup(value)).map(([key, value]) => ({ path: [key], value }));
  const groups = entries.filter((entry): entry is [string, JsonObject | JsonObject[]] => isGroup(entry[1]));

  return (
    <div className="space-y-2">
      {single.length > 0 ? <Rows leaves={single} /> : null}
      {groups.map(([key, value]) => (
        <Group key={key} name={key} value={value} />
      ))}
    </div>
  );
}

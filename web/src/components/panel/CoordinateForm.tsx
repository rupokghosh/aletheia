"use client";

import { useId, useState } from "react";
import { Button } from "@/components/ui/Button";
import { formatCoordinate } from "@/lib/format";
import { isValidBBox } from "@/lib/geo";
import { useApp } from "@/lib/store";
import type { BBox } from "@/lib/types";

const EDGES = ["West", "South", "East", "North"] as const;

/** Four number fields: the keyboard route to an area, and the precise one. */
export function CoordinateForm({ bbox }: { bbox: BBox | null }) {
  const { dispatch } = useApp();
  const id = useId();
  const [values, setValues] = useState<string[]>(() => (bbox ? bbox.map(formatCoordinate) : ["", "", "", ""]));
  const [error, setError] = useState<string | null>(null);

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    const next = values.map((value) => Number(value)) as BBox;
    if (values.some((value) => value.trim() === "") || !isValidBBox(next)) {
      setError("Enter four numbers in degrees. East must be greater than west, and north greater than south.");
      return;
    }
    setError(null);
    dispatch({ type: "area", bbox: next });
    dispatch({ type: "flyTo", bbox: next });
  };

  return (
    <form onSubmit={submit} className="mt-3" noValidate>
      <div className="grid grid-cols-2 gap-2.5">
        {EDGES.map((edge, index) => (
          <div key={edge}>
            <label htmlFor={`${id}-${edge}`} className="mb-1 block text-[13px] text-ink-2">
              {edge} ({index % 2 === 0 ? "longitude" : "latitude"})
            </label>
            <input
              id={`${id}-${edge}`}
              className="field"
              inputMode="decimal"
              autoComplete="off"
              value={values[index]}
              aria-invalid={error ? true : undefined}
              onChange={(event) => setValues(values.map((value, i) => (i === index ? event.target.value : value)))}
            />
          </div>
        ))}
      </div>
      {error ? (
        <p className="mt-2 text-sm text-danger" role="alert">
          {error}
        </p>
      ) : null}
      <Button type="submit" size="sm" className="mt-3">
        Use these coordinates
      </Button>
    </form>
  );
}

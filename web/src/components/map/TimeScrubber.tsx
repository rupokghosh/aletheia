"use client";

import { useEffect, useId, useState } from "react";
import { ChevronLeftIcon, ChevronRightIcon, PauseIcon, PlayIcon } from "@/components/ui/icons";
import { formatDate } from "@/lib/format";

interface TimeScrubberProps {
  dates: string[];
  index: number;
  onChange: (index: number) => void;
}

function prefersReducedMotion(): boolean {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/** Steps through the dated images of a result, one date at a time. */
export function TimeScrubber({ dates, index, onChange }: TimeScrubberProps) {
  const [playing, setPlaying] = useState(false);
  const sliderId = useId();
  const last = dates.length - 1;

  useEffect(() => {
    if (!playing) return;
    const timer = setInterval(() => onChange(index >= last ? 0 : index + 1), 1100);
    return () => clearInterval(timer);
  }, [playing, index, last, onChange]);

  const button = "press grid size-8 shrink-0 place-items-center rounded-full text-ink-2 hover:bg-raised hover:text-ink disabled:text-ink-3 disabled:hover:bg-transparent";

  return (
    <div>
      <p className="text-sm text-ink" aria-live="polite">
        {formatDate(dates[index])}
        <span className="ml-1.5 text-ink-3">
          {index + 1} of {dates.length}
        </span>
      </p>
      <div className="-ml-1.5 flex items-center gap-0.5">
        {/* Automatic playback is not offered when the system asks for reduced motion. */}
        {prefersReducedMotion() ? null : (
          <button type="button" className={button} aria-label={playing ? "Pause" : "Play through the dates"} onClick={() => setPlaying((value) => !value)}>
            {playing ? <PauseIcon /> : <PlayIcon />}
          </button>
        )}
        <button type="button" className={button} aria-label="Previous date" disabled={index <= 0} onClick={() => onChange(index - 1)}>
          <ChevronLeftIcon />
        </button>
        <label htmlFor={sliderId} className="sr-only">
          Date of the image on the map
        </label>
        <input
          id={sliderId}
          type="range"
          className="min-w-0 flex-1"
          min={0}
          max={last}
          step={1}
          value={index}
          aria-valuetext={`${formatDate(dates[index])}, ${index + 1} of ${dates.length}`}
          onChange={(event) => onChange(Number(event.target.value))}
        />
        <button type="button" className={button} aria-label="Next date" disabled={index >= last} onClick={() => onChange(index + 1)}>
          <ChevronRightIcon />
        </button>
      </div>
    </div>
  );
}

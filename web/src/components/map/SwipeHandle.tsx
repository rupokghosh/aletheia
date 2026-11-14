"use client";

import { useRef } from "react";
import { formatDate } from "@/lib/format";

interface SwipeHandleProps {
  position: number;
  beforeDate: string | null;
  afterDate: string | null;
  onChange: (position: number) => void;
}

const clamp = (value: number) => Math.max(0.02, Math.min(0.98, value));
const LABEL = "absolute top-4 rounded-full border border-line bg-panel px-3 py-1 text-[13px] whitespace-nowrap text-ink shadow-card";

/**
 * The before/after swipe line. Drag the handle, or focus it and use the arrow keys.
 * Left of the line is the earlier date, right of it the later one; the labels travel with the line.
 */
export function SwipeHandle({ position, beforeDate, afterDate, onChange }: SwipeHandleProps) {
  const trackRef = useRef<HTMLDivElement>(null);

  const fromPointer = (event: React.PointerEvent) => {
    const rect = trackRef.current?.getBoundingClientRect();
    if (rect && rect.width > 0) onChange(clamp((event.clientX - rect.left) / rect.width));
  };

  return (
    <div ref={trackRef} className="pointer-events-none absolute inset-0 z-10 overflow-hidden">
      <div className="absolute inset-y-0 w-0" style={{ left: `${position * 100}%` }}>
        <p className={`${LABEL} right-3`}>
          <span className="text-ink-3">Before</span> {formatDate(beforeDate)}
        </p>
        <p className={`${LABEL} left-3`}>
          <span className="text-ink-3">After</span> {formatDate(afterDate)}
        </p>
        <div className="absolute inset-y-0 -left-px w-0.5 bg-ink shadow-[0_0_0_1px_rgb(255_255_255/0.9)]" />
        <div
          className="pointer-events-auto absolute top-1/2 left-0 grid size-11 -translate-x-1/2 -translate-y-1/2 cursor-ew-resize touch-none place-items-center rounded-full border border-line-strong bg-panel text-ink shadow-card has-focus-visible:outline-2 has-focus-visible:outline-offset-2 has-focus-visible:outline-blue"
          onPointerDown={(event) => {
            event.currentTarget.setPointerCapture(event.pointerId);
            fromPointer(event);
          }}
          onPointerMove={(event) => {
            if (event.currentTarget.hasPointerCapture(event.pointerId)) fromPointer(event);
          }}
        >
          <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M6.5 5 3 9l3.5 4M11.5 5 15 9l-3.5 4" />
          </svg>
          {/* Keyboard route only: the pointer drags the handle itself, so the slider ignores it. */}
          <input
            type="range"
            className="pointer-events-none absolute inset-0 opacity-0"
            aria-label="Position of the before and after dividing line"
            aria-valuetext={`${Math.round(position * 100)}% from the left`}
            min={2}
            max={98}
            step={1}
            value={Math.round(position * 100)}
            onChange={(event) => onChange(clamp(Number(event.target.value) / 100))}
          />
        </div>
      </div>
    </div>
  );
}

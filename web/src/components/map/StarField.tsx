"use client";

import { useEffect, useRef } from "react";

/** A small repeatable random source, so the stars stay where they are when the window is resized. */
function seeded(seed: number): () => number {
  let state = seed;
  return () => {
    state = (state + 0x6d2b79f5) | 0;
    let t = Math.imul(state ^ (state >>> 15), 1 | state);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const TINTS = ["255 255 255", "214 228 255", "255 240 214"];
/** The few stars that slowly brighten and dim, as shares of the sky. */
const TWINKLERS = Array.from({ length: 9 }, (_, index) => {
  const random = seeded(977 + index * 31);
  return { x: random(), y: random() * 0.9, size: 2 + random() * 1.5, seconds: 3.5 + random() * 4, delay: random() * 4 };
});

/**
 * Still stars behind the globe, drawn once on a canvas (about one for every 5,500 square pixels of sky),
 * with a handful that twinkle. It is behind the map, so the planet and the cards cover it.
 */
export function StarField() {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const parent = canvas?.parentElement;
    if (!canvas || !parent) return;
    const draw = () => {
      const width = parent.clientWidth;
      const height = parent.clientHeight;
      const ratio = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = Math.round(width * ratio);
      canvas.height = Math.round(height * ratio);
      const context = canvas.getContext("2d");
      if (!context) return;
      context.setTransform(ratio, 0, 0, ratio, 0, 0);
      context.clearRect(0, 0, width, height);
      const random = seeded(20261115);
      const count = Math.round((width * height) / 5500);
      for (let i = 0; i < count; i += 1) {
        const x = random() * width;
        const y = random() * height;
        const big = random() < 0.08;
        const radius = big ? 1.1 + random() * 0.7 : 0.35 + random() * 0.6;
        const alpha = big ? 0.75 + random() * 0.25 : 0.25 + random() * 0.55;
        context.fillStyle = `rgb(${TINTS[Math.floor(random() * TINTS.length)]} / ${alpha.toFixed(2)})`;
        context.beginPath();
        context.arc(x, y, radius, 0, Math.PI * 2);
        context.fill();
      }
    };
    draw();
    const observer = new ResizeObserver(draw);
    observer.observe(parent);
    return () => observer.disconnect();
  }, []);

  return (
    <div className="star-field">
      <canvas ref={canvasRef} className="absolute inset-0 h-full w-full" />
      {TWINKLERS.map((star) => (
        <span
          key={`${star.x}-${star.y}`}
          className="twinkle"
          style={{ left: `${star.x * 100}%`, top: `${star.y * 100}%`, width: star.size, height: star.size, animationDuration: `${star.seconds}s`, animationDelay: `${star.delay}s` }}
        />
      ))}
    </div>
  );
}

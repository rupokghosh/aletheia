"use client";

import { useEffect, useState, type CSSProperties } from "react";

interface Star {
  id: number;
  /** where the streak starts, as a share of the backdrop */
  x: number;
  y: number;
  /** direction of travel in degrees, clockwise from pointing right */
  angle: number;
  length: number;
  travel: number;
  seconds: number;
}

const between = (low: number, high: number) => low + Math.random() * (high - low);

/** One star, somewhere in the upper part of the sky, falling to the right or to the left. */
function newStar(id: number): Star {
  const rightward = Math.random() < 0.5;
  return {
    id,
    x: rightward ? between(0.34, 0.66) : between(0.62, 0.95),
    y: between(0.03, 0.26),
    angle: rightward ? between(16, 34) : between(146, 164),
    length: between(200, 320),
    travel: between(560, 860),
    seconds: between(1.8, 2.5),
  };
}

const FIRST_WAIT_SECONDS = [3, 6] as const;
const WAIT_SECONDS = [14, 26] as const;

/**
 * Now and then a shooting star crosses the sky behind the globe: one at a time, with quiet gaps
 * of a quarter to half a minute. It is drawn behind the map, so it passes behind the planet and the cards.
 * None are shown to people who ask their system for reduced motion, or while the page is hidden.
 */
export function ShootingStars() {
  const [star, setStar] = useState<Star | null>(null);

  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    let timer = 0;
    let count = 0;
    const schedule = (range: readonly [number, number]) => {
      timer = window.setTimeout(() => {
        if (!document.hidden) {
          count += 1;
          setStar(newStar(count));
        }
        schedule(WAIT_SECONDS);
      }, between(range[0], range[1]) * 1000);
    };
    schedule(FIRST_WAIT_SECONDS);
    return () => window.clearTimeout(timer);
  }, []);

  if (!star) return null;
  const style = {
    left: `${star.x * 100}%`,
    top: `${star.y * 100}%`,
    width: star.length,
    "--star-angle": `${star.angle}deg`,
    "--star-travel": `${star.travel}px`,
    "--star-time": `${star.seconds}s`,
  } as CSSProperties;
  return <span key={star.id} className="shooting-star" style={style} onAnimationEnd={() => setStar(null)} />;
}

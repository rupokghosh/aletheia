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
    x: rightward ? between(0.3, 0.72) : between(0.55, 0.96),
    y: between(0.04, 0.42),
    angle: rightward ? between(16, 38) : between(142, 164),
    length: between(110, 190),
    travel: between(320, 520),
    seconds: between(1.1, 1.6),
  };
}

const FIRST_WAIT_SECONDS = [6, 10] as const;
const WAIT_SECONDS = [22, 48] as const;

/**
 * Now and then a shooting star crosses the sky behind the globe: one at a time, with long quiet gaps
 * (about two a minute at most). It is drawn behind the map, so it passes behind the planet and the cards.
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

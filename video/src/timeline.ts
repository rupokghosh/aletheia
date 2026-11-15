// The film's clock. Everything is counted in frames at 30 a second; the whole film is 29.5 seconds, under
// the 30-second limit for a Space Apps demo.

export const FPS = 30;
export const WIDTH = 1920;
export const HEIGHT = 1080;

/** Where each shot starts and how long it runs. */
export const SHOTS = {
  opening: { from: 0, frames: 226 }, // the globe turns, Venezuela is clicked, the camera flies down
  ask: { from: 226, frames: 90 }, // the question is typed
  venezuela: { from: 316, frames: 156 }, // the ground-movement answer
  flight: { from: 472, frames: 96 }, // across the Caribbean to Florida
  florida: { from: 568, frames: 160 }, // the floodplain after Hurricane Isaias, and its river gauge
  receipts: { from: 728, frames: 87 }, // what the answer rests on
  end: { from: 815, frames: 70 }, // the closing card
} as const;

export const TOTAL = SHOTS.end.from + SHOTS.end.frames;

/** How many frames of each shot were filmed (see capture/capture.mjs). */
export const FILMED = {
  opening: 240,
  turn: 135, // of which the turning globe; the flight down follows
  openingSkipped: 14, // frames of the turn left out at the start
  ask: 105,
  venezuelaReveal: 40,
  flight: 96,
  florida: 176,
  receiptsScroll: 50,
} as const;

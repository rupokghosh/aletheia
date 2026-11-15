// The film's clock. Everything is counted in frames at 30 a second; the whole film is 29.5 seconds, under
// the 30-second limit for a Space Apps demo.

export const FPS = 30;
export const WIDTH = 1920;
export const HEIGHT = 1080;

/** Where each shot starts and how long it runs. */
export const SHOTS = {
  opening: { from: 0, frames: 240 }, // the globe turns, a place is clicked, the camera flies down
  ask: { from: 240, frames: 105 }, // the question is typed
  answer: { from: 345, frames: 204 }, // the ground-movement answer
  kamloops: { from: 549, frames: 150 }, // Kamloops Lake and its river gauge
  receipts: { from: 699, frames: 108 }, // what the answer rests on
  end: { from: 807, frames: 78 }, // the closing card
} as const;

export const TOTAL = SHOTS.end.from + SHOTS.end.frames;

/** How many frames of each shot were filmed (see capture/capture.mjs). */
export const FILMED = {
  opening: 240,
  turn: 135,
  ask: 105,
  answerReveal: 40,
  answerScroll: 64,
  kamloops: 165,
  receiptsScroll: 50,
} as const;

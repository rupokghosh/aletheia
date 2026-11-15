import type { ReactNode } from "react";
import { AbsoluteFill, Easing, interpolate, useCurrentFrame } from "remotion";
import { Camera, Caption, EndCard, Footage, type Framing, framingAt, land, Pointer, Strong, WHOLE } from "./parts";
import { FILMED, SHOTS } from "./timeline";

// Places on the app's screen (1920 x 1080), read from the filmed frames.
const GLOBE = { x: 1034, y: 545 }; // middle of the globe while the side panel and layers card are open
const CLICK = { x: 1048, y: 555 }; // the Carabobo coast on the globe when the turn stops
const TEXTAREA = { x: 246, y: 899 }; // middle of the question box, panel scrolled to its end
const ASK_BUTTON = { x: 123, y: 985 }; // "Ask about this area"
const MAP_MIDDLE = 1034; // middle of the map between the panel and the layers card
const BESIDE_PANEL = 1372; // middle of the map when the camera is close on the panel

const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;
const smoother = (t: number) => {
  const u = Math.min(1, Math.max(0, t));
  return u * u * u * (u * (u * 6 - 15) + 10);
};

/** One shot: on screen from a little before its start (it fades in over the one before) until the next has faded in. */
function Shot({ from, frames, fadeIn, linger, children }: { from: number; frames: number; fadeIn: number; linger: number; children: ReactNode }) {
  const frame = useCurrentFrame();
  if (frame < from - fadeIn || frame >= from + frames + linger) return null;
  const opacity = fadeIn === 0 ? 1 : interpolate(frame, [from - fadeIn, from], [0, 1], clamp);
  return <AbsoluteFill style={{ opacity }}>{children}</AbsoluteFill>;
}

function Opening() {
  const frame = useCurrentFrame();
  // Close on the globe, drifting back slowly, then one move out to the whole app.
  const framing = framingAt(
    frame,
    [
      [0, { ...GLOBE, scale: 2.2 }],
      [122, WHOLE],
    ],
    (t) => 0.1 * t + 0.9 * smoother((t - 0.52) / 0.48),
  );
  const index = Math.min(frame, FILMED.opening - 1);
  // As the flight begins the side panel folds away: the last frame of the turn fades off the first of the flight.
  const panel = interpolate(frame, [FILMED.turn - 1, FILMED.turn + 9], [1, 0], clamp);
  return (
    <Camera framing={framing}>
      <Footage shot="opening" index={index} />
      {frame >= FILMED.turn && panel > 0 ? (
        <AbsoluteFill style={{ opacity: panel }}>
          <Footage shot="opening" index={FILMED.turn - 1} />
        </AbsoluteFill>
      ) : null}
      <Pointer
        path={[
          [102, 1480, 820],
          [126, CLICK.x, CLICK.y],
          [135, CLICK.x, CLICK.y],
        ]}
        clicks={[130]}
      />
    </Camera>
  );
}

function Ask() {
  const frame = useCurrentFrame();
  const { from } = SHOTS.ask;
  const local = Math.min(Math.max(frame - from, 0), FILMED.ask - 1);
  const framing = framingAt(
    frame,
    [
      [from - 4, { x: 600, y: 760, scale: 1.42 }],
      [from + 104, { x: 600, y: 790, scale: 1.52 }],
    ],
    Easing.linear,
  );
  return (
    <Camera framing={framing}>
      <Footage shot="ask" index={local} />
      <Pointer
        path={[
          [from - 2, 520, 640],
          [from + 9, TEXTAREA.x - 40, TEXTAREA.y],
          [from + 80, TEXTAREA.x + 150, TEXTAREA.y + 60],
          [from + 96, ASK_BUTTON.x, ASK_BUTTON.y],
          [from + 104, ASK_BUTTON.x, ASK_BUTTON.y],
        ]}
        clicks={[from + 10, from + 99]}
        scale={0.82}
      />
    </Camera>
  );
}

const ANSWER_PANEL: Framing = { x: 560, y: 430, scale: 1.72 };
const ANSWER_CHARTS: Framing = { x: 560, y: 540, scale: 1.72 };

function Answer() {
  const frame = useCurrentFrame();
  const { from } = SHOTS.answer;
  const local = frame - from;
  const scrollFrom = 128;
  const index =
    local < FILMED.answerReveal
      ? Math.max(0, local)
      : local < scrollFrom
        ? FILMED.answerReveal - 1
        : Math.min(FILMED.answerReveal + (local - scrollFrom), FILMED.answerReveal + FILMED.answerScroll - 1);
  const settle = framingAt(
    frame,
    [
      [from - 8, { x: 960, y: 540, scale: 1.05 }],
      [from + 16, WHOLE],
    ],
    land,
  );
  const framing =
    local < 66
      ? settle
      : framingAt(frame, [
          [from + 66, WHOLE],
          [from + 106, ANSWER_PANEL],
          [from + scrollFrom, ANSWER_PANEL],
          [from + scrollFrom + FILMED.answerScroll, ANSWER_CHARTS],
        ]);
  return (
    <Camera framing={framing}>
      <Footage shot="answer" index={index} />
    </Camera>
  );
}

const LAKE_PANEL: Framing = { x: 565, y: 650, scale: 1.66 };
const LAKE_PANEL_END: Framing = { x: 565, y: 690, scale: 1.74 };

function Kamloops() {
  const frame = useCurrentFrame();
  const { from, frames } = SHOTS.kamloops;
  const local = frame - from;
  const index = Math.min(Math.max(local, 0), FILMED.kamloops - 1);
  const settle = framingAt(
    frame,
    [
      [from - 10, { x: 960, y: 540, scale: 1.06 }],
      [from + 14, WHOLE],
    ],
    land,
  );
  const framing =
    local < 56
      ? settle
      : framingAt(frame, [
          [from + 56, WHOLE],
          [from + 96, LAKE_PANEL],
          [from + frames + 10, LAKE_PANEL_END],
        ]);
  return (
    <Camera framing={framing}>
      <Footage shot="kamloops" index={index} />
    </Camera>
  );
}

function Receipts() {
  const frame = useCurrentFrame();
  const { from, frames } = SHOTS.receipts;
  const local = frame - from;
  const scrollFrom = 52;
  const index = local < scrollFrom ? 0 : Math.min(1 + (local - scrollFrom), FILMED.receiptsScroll);
  const framing = framingAt(frame, [
    [from - 8, { x: 500, y: 320, scale: 1.92 }],
    [from + scrollFrom, { x: 500, y: 335, scale: 2.02 }],
    [from + scrollFrom + FILMED.receiptsScroll, { x: 530, y: 470, scale: 1.78 }],
    [from + frames + 12, { x: 530, y: 480, scale: 1.82 }],
  ]);
  return (
    <Camera framing={framing}>
      <Footage shot="receipts" index={index} />
    </Camera>
  );
}

export function Film({ site }: { site: string }) {
  const frame = useCurrentFrame();
  const { opening, ask, answer, kamloops, receipts, end } = SHOTS;
  return (
    <AbsoluteFill style={{ background: "#fdfcf9" }}>
      <Shot from={opening.from} frames={opening.frames} fadeIn={0} linger={4}>
        <Opening />
      </Shot>
      <Shot from={ask.from} frames={ask.frames} fadeIn={4} linger={8}>
        <Ask />
      </Shot>
      <Shot from={answer.from} frames={answer.frames} fadeIn={8} linger={10}>
        <Answer />
      </Shot>
      <Shot from={kamloops.from} frames={kamloops.frames} fadeIn={10} linger={8}>
        <Kamloops />
      </Shot>
      <Shot from={receipts.from} frames={receipts.frames} fadeIn={8} linger={12}>
        <Receipts />
      </Shot>
      <Shot from={end.from} frames={end.frames} fadeIn={12} linger={0}>
        <EndCard frame={frame - end.from} site={site} />
      </Shot>

      <Caption from={8} to={98}>
        The NISAR radar satellite passes over
        <br />
        <Strong>every place on Earth</Strong>, every 12 days.
      </Caption>
      <Caption from={106} to={170} x={MAP_MIDDLE}>
        Aletheia turns that radar into
        <br />
        answers anyone can check.
      </Caption>
      <Caption from={178} to={236} x={MAP_MIDDLE}>
        Pick any place.
      </Caption>
      <Caption from={ask.from + 6} to={ask.from + ask.frames - 6} x={1330}>
        Ask in plain words.
      </Caption>
      <Caption from={answer.from + 6} to={answer.from + 68} x={MAP_MIDDLE}>
        The answer is measured:
        <br />
        two radar passes, 12 days apart.
      </Caption>
      <Caption from={answer.from + 108} to={answer.from + answer.frames - 8} x={BESIDE_PANEL}>
        <Strong>48 to 66 cm</Strong> of ground movement
        <br />
        around the 24 June earthquakes.
      </Caption>
      <Caption from={kamloops.from + 6} to={kamloops.from + 56} x={MAP_MIDDLE}>
        Kamloops Lake, June to October 2026.
      </Caption>
      <Caption from={kamloops.from + 66} to={kamloops.from + kamloops.frames - 8} x={BESIDE_PANEL}>
        The shore changed as the river fell <Strong>2.97 m</Strong>.
        <br />
        An independent gauge agrees.
      </Caption>
      <Caption from={receipts.from + 6} to={receipts.from + receipts.frames - 10} x={1420}>
        Every answer comes with receipts:
        <br />
        the files, the steps, the uncertainty.
      </Caption>
    </AbsoluteFill>
  );
}

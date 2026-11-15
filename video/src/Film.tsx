import type { ReactNode } from "react";
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
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
  const skipped = FILMED.openingSkipped;
  const lift = FILMED.turn - skipped; // the film frame on which the flight down begins
  // Close on the globe, drifting back slowly, then one move out to the whole app.
  const framing = framingAt(
    frame,
    [
      [0, { ...GLOBE, scale: 2.2 }],
      [108, WHOLE],
    ],
    (t) => 0.1 * t + 0.9 * smoother((t - 0.48) / 0.52),
  );
  const index = Math.min(frame + skipped, FILMED.opening - 1);
  // As the flight begins the side panel folds away: the last frame of the turn fades off the first of the flight.
  const panel = interpolate(frame, [lift - 1, lift + 9], [1, 0], clamp);
  return (
    <Camera framing={framing}>
      <Footage shot="opening" index={index} />
      {frame >= lift && panel > 0 ? (
        <AbsoluteFill style={{ opacity: panel }}>
          <Footage shot="opening" index={FILMED.turn - 1} />
        </AbsoluteFill>
      ) : null}
      <Pointer
        path={[
          [88, 1480, 820],
          [112, CLICK.x, CLICK.y],
          [lift, CLICK.x, CLICK.y],
        ]}
        clicks={[116]}
      />
    </Camera>
  );
}

function Ask() {
  const frame = useCurrentFrame();
  const { from, frames } = SHOTS.ask;
  const pace = (FILMED.ask - 1) / (frames - 1); // the typing is played a little faster than it was filmed
  const local = Math.min(Math.max((frame - from) * pace, 0), FILMED.ask - 1);
  const framing = framingAt(
    frame,
    [
      [from - 4, { x: 600, y: 760, scale: 1.42 }],
      [from + frames, { x: 600, y: 790, scale: 1.52 }],
    ],
    (t) => t,
  );
  return (
    <Camera framing={framing}>
      <Footage shot="ask" index={local} />
      <Pointer
        path={[
          [from - 2, 520, 640],
          [from + 8, TEXTAREA.x - 40, TEXTAREA.y],
          [from + 68, TEXTAREA.x + 150, TEXTAREA.y + 60],
          [from + 82, ASK_BUTTON.x, ASK_BUTTON.y],
          [from + frames, ASK_BUTTON.x, ASK_BUTTON.y],
        ]}
        clicks={[from + 9, from + 85]}
        scale={0.82}
      />
    </Camera>
  );
}

const VENEZUELA_PANEL: Framing = { x: 560, y: 440, scale: 1.72 };
const VENEZUELA_PANEL_END: Framing = { x: 560, y: 500, scale: 1.78 };

function Venezuela() {
  const frame = useCurrentFrame();
  const { from, frames } = SHOTS.venezuela;
  const local = frame - from;
  const index = Math.min(Math.max(local, 0), FILMED.venezuelaReveal - 1);
  const settle = framingAt(
    frame,
    [
      [from - 8, { x: 960, y: 540, scale: 1.05 }],
      [from + 16, WHOLE],
    ],
    land,
  );
  const framing =
    local < 58
      ? settle
      : framingAt(frame, [
          [from + 58, WHOLE],
          [from + 98, VENEZUELA_PANEL],
          [from + frames + 10, VENEZUELA_PANEL_END],
        ]);
  return (
    <Camera framing={framing}>
      <Footage shot="answer" index={index} />
    </Camera>
  );
}

function Flight() {
  const frame = useCurrentFrame();
  const local = frame - SHOTS.flight.from;
  // Half-way, out of sight of both places, the app moves on to the Florida example and its map-layers card
  // changes. The card of the frame before is faded off over it, so the change does not jump.
  const swap = FILMED.flight / 2;
  const old = interpolate(local, [swap - 1, swap + 11], [1, 0], clamp);
  return (
    <>
      <Footage shot="flight" index={Math.min(Math.max(local, 0), FILMED.flight - 1)} />
      {local >= swap && old > 0 ? (
        <AbsoluteFill style={{ opacity: old, clipPath: "inset(92px 4px 44px 1584px round 20px)" }}>
          <Footage shot="flight" index={swap - 1} />
        </AbsoluteFill>
      ) : null}
    </>
  );
}

const FLORIDA_PANEL: Framing = { x: 565, y: 650, scale: 1.64 };
const FLORIDA_PANEL_END: Framing = { x: 565, y: 690, scale: 1.72 };

function Florida() {
  const frame = useCurrentFrame();
  const { from, frames } = SHOTS.florida;
  const local = frame - from;
  const index = Math.min(Math.max(local, 0), FILMED.florida - 1);
  const framing = framingAt(frame, [
    [from, WHOLE],
    [from + 62, WHOLE],
    [from + 102, FLORIDA_PANEL],
    [from + frames + 8, FLORIDA_PANEL_END],
  ]);
  return (
    <Camera framing={framing}>
      <Footage shot="florida" index={index} />
    </Camera>
  );
}

function Receipts() {
  const frame = useCurrentFrame();
  const { from, frames } = SHOTS.receipts;
  const local = frame - from;
  const scrollFrom = 44;
  const index = local < scrollFrom ? 0 : Math.min(1 + (local - scrollFrom), FILMED.receiptsScroll);
  const framing = framingAt(frame, [
    [from - 8, { x: 500, y: 330, scale: 1.9 }],
    [from + scrollFrom, { x: 500, y: 350, scale: 2.0 }],
    [from + frames + 12, { x: 530, y: 470, scale: 1.8 }],
  ]);
  return (
    <Camera framing={framing}>
      <Footage shot="receipts" index={index} />
    </Camera>
  );
}

export function Film({ site }: { site: string }) {
  const frame = useCurrentFrame();
  const { opening, ask, venezuela, flight, florida, receipts, end } = SHOTS;
  return (
    <AbsoluteFill style={{ background: "#fdfcf9" }}>
      <Shot from={opening.from} frames={opening.frames} fadeIn={0} linger={4}>
        <Opening />
      </Shot>
      <Shot from={ask.from} frames={ask.frames} fadeIn={4} linger={8}>
        <Ask />
      </Shot>
      <Shot from={venezuela.from} frames={venezuela.frames} fadeIn={8} linger={10}>
        <Venezuela />
      </Shot>
      <Shot from={flight.from} frames={flight.frames} fadeIn={10} linger={10}>
        <Flight />
      </Shot>
      <Shot from={florida.from} frames={florida.frames} fadeIn={10} linger={8}>
        <Florida />
      </Shot>
      <Shot from={receipts.from} frames={receipts.frames} fadeIn={8} linger={12}>
        <Receipts />
      </Shot>
      <Shot from={end.from} frames={end.frames} fadeIn={12} linger={0}>
        <EndCard frame={frame - end.from} site={site} />
      </Shot>

      <Caption from={8} to={86}>
        The NISAR radar satellite passes over
        <br />
        <Strong>every place on Earth</Strong>, every 12 days.
      </Caption>
      <Caption from={92} to={150} x={MAP_MIDDLE}>
        Aletheia turns that radar into
        <br />
        answers anyone can check.
      </Caption>
      <Caption from={158} to={222} x={MAP_MIDDLE}>
        <Strong>24 June 2026.</Strong> Two major earthquakes
        <br />
        strike Venezuela.
      </Caption>
      <Caption from={ask.from + 6} to={ask.from + ask.frames - 6} x={1330}>
        Ask in plain words.
      </Caption>
      <Caption from={venezuela.from + 6} to={venezuela.from + 60} x={MAP_MIDDLE}>
        The answer is measured:
        <br />
        two radar passes, 12 days apart.
      </Caption>
      <Caption from={venezuela.from + 100} to={venezuela.from + venezuela.frames - 6} x={BESIDE_PANEL}>
        <Strong>48 to 66 cm</Strong> of ground movement.
      </Caption>
      <Caption from={flight.from + 12} to={flight.from + flight.frames - 4} x={MAP_MIDDLE}>
        <Strong>9 October 2026.</Strong> Hurricane Isaias
        <br />
        makes landfall in Florida.
      </Caption>
      <Caption from={florida.from + 8} to={florida.from + 62} x={MAP_MIDDLE}>
        Twelve days later, the Choctawhatchee
        <br />
        floodplain lights up on radar.
      </Caption>
      <Caption from={florida.from + 104} to={florida.from + florida.frames - 6} x={BESIDE_PANEL}>
        An independent river gauge agrees:
        <br />
        the water is up <Strong>1.82 m</Strong>.
      </Caption>
      <Caption from={receipts.from + 6} to={receipts.from + receipts.frames - 8} x={1420}>
        Every answer comes with receipts:
        <br />
        the files, the steps, the uncertainty.
      </Caption>
    </AbsoluteFill>
  );
}

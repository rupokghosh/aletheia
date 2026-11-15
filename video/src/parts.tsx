import type { CSSProperties, ReactNode } from "react";
import { AbsoluteFill, Easing, Img, interpolate, staticFile, useCurrentFrame } from "remotion";
import { loadFont } from "@remotion/google-fonts/Geist";
import { HEIGHT, WIDTH } from "./timeline";

export const { fontFamily } = loadFont("normal", { weights: ["400", "500", "600"], subsets: ["latin"] });

export const INK = "#191919";
export const glide = Easing.bezier(0.65, 0, 0.35, 1); // slow in, slow out: camera moves
export const land = Easing.bezier(0.23, 1, 0.32, 1); // fast start, soft landing: the app's own easing

const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;

/** One filmed frame of the app. The pictures are twice the film's size, so a closer framing stays sharp. */
export function Footage({ shot, index }: { shot: string; index: number }) {
  const name = String(Math.max(0, Math.round(index))).padStart(4, "0");
  return <Img src={staticFile(`footage/${shot}/${name}.jpg`)} style={{ position: "absolute", inset: 0, width: WIDTH, height: HEIGHT }} />;
}

/** A framing of the picture: the point (x, y) of the app's screen sits mid-frame, enlarged `scale` times. */
export interface Framing {
  x: number;
  y: number;
  scale: number;
}

export const WHOLE: Framing = { x: WIDTH / 2, y: HEIGHT / 2, scale: 1 };

/** Blend between framings at given frames, easing each move. */
export function framingAt(frame: number, keys: [number, Framing][], easing = glide): Framing {
  const at = keys.map(([f]) => f);
  const pick = (get: (k: Framing) => number) =>
    keys.length === 1
      ? get(keys[0][1])
      : interpolate(
          frame,
          at,
          keys.map(([, k]) => get(k)),
          { ...clamp, easing },
        );
  return { x: pick((k) => k.x), y: pick((k) => k.y), scale: pick((k) => k.scale) };
}

/** Holds its children at a framing. The frame is always kept covered: a framing never shows past an edge. */
export function Camera({ framing, children }: { framing: Framing; children: ReactNode }) {
  const { scale } = framing;
  const tx = Math.min(0, Math.max(WIDTH - WIDTH * scale, WIDTH / 2 - framing.x * scale));
  const ty = Math.min(0, Math.max(HEIGHT - HEIGHT * scale, HEIGHT / 2 - framing.y * scale));
  return (
    <AbsoluteFill style={{ transformOrigin: "0 0", transform: `translate(${tx}px, ${ty}px) scale(${scale})`, willChange: "transform" }}>
      {children}
    </AbsoluteFill>
  );
}

/** A line of words along the bottom, for a few seconds. Times are frames of the whole film. */
export function Caption({ from, to, children, x = WIDTH / 2, bottom = 64 }: { from: number; to: number; children: ReactNode; x?: number; bottom?: number }) {
  const frame = useCurrentFrame();
  if (frame < from - 1 || frame > to + 1) return null;
  const arrive = interpolate(frame, [from, from + 12], [0, 1], { ...clamp, easing: land });
  const leave = interpolate(frame, [to - 8, to], [1, 0], { ...clamp, easing: Easing.in(Easing.quad) });
  const style: CSSProperties = {
    position: "absolute",
    left: x,
    bottom,
    transform: `translateX(-50%) translateY(${(1 - arrive) * 18}px)`,
    opacity: arrive * leave,
    whiteSpace: "nowrap", // lines are broken by hand, so the plate hugs the words
    padding: "17px 32px 19px",
    borderRadius: 20,
    background: "rgba(20, 20, 20, 0.88)",
    boxShadow: "0 2px 4px rgba(0,0,0,0.12), 0 18px 48px rgba(0,0,0,0.22)",
    color: "#ffffff",
    fontFamily,
    fontSize: 38,
    fontWeight: 500,
    lineHeight: 1.22,
    letterSpacing: "-0.012em",
    textAlign: "center",
  };
  return <div style={style}>{children}</div>;
}

/** The figure in a caption that the eye should land on. */
export function Strong({ children }: { children: ReactNode }) {
  return <span style={{ fontWeight: 600, color: "#ffd9a6", whiteSpace: "nowrap" }}>{children}</span>;
}

/** A pointer that travels between places on the app's screen and clicks. Lives inside a Camera. */
export function Pointer({ path, clicks = [], scale = 1 }: { path: [number, number, number][]; clicks?: number[]; scale?: number }) {
  const frame = useCurrentFrame();
  const first = path[0][0];
  const last = path[path.length - 1][0];
  if (frame < first - 6 || frame > last + 12) return null;
  const at = path.map(([f]) => f);
  const x = interpolate(frame, at, path.map(([, px]) => px), { ...clamp, easing: glide });
  const y = interpolate(frame, at, path.map(([, , py]) => py), { ...clamp, easing: glide });
  const opacity = interpolate(frame, [first - 6, first, last + 4, last + 12], [0, 1, 1, 0], clamp);
  const press = clicks.reduce((down, c) => Math.max(down, interpolate(frame, [c - 2, c, c + 5], [0, 1, 0], clamp)), 0);
  return (
    <>
      {clicks.map((c) => {
        if (frame < c || frame > c + 16) return null;
        const t = interpolate(frame, [c, c + 16], [0, 1], { ...clamp, easing: Easing.out(Easing.cubic) });
        const size = (20 + 70 * t) * scale;
        return (
          <div
            key={c}
            style={{ position: "absolute", left: x - size / 2, top: y - size / 2, width: size, height: size, borderRadius: "50%", border: `${3 * scale}px solid rgba(255,255,255,${0.95 * (1 - t)})`, boxShadow: `0 0 0 ${1.5 * scale}px rgba(25,25,25,${0.35 * (1 - t)})` }}
          />
        );
      })}
      <svg
        width={30 * scale}
        height={30 * scale}
        viewBox="0 0 24 24"
        style={{ position: "absolute", left: x - 5 * scale, top: y - 3 * scale, opacity, transform: `scale(${1 - 0.12 * press})`, transformOrigin: "20% 12%", filter: "drop-shadow(0 2px 3px rgba(0,0,0,0.35))" }}
      >
        <path d="M4.5 2.5 L4.5 19.2 L8.9 15.3 L11.8 21.8 L14.6 20.6 L11.7 14.2 L17.6 14.2 Z" fill={INK} stroke="#ffffff" strokeWidth="1.5" strokeLinejoin="round" />
      </svg>
    </>
  );
}

/** The app's mark: a disc coming out from behind another. */
export function Mark({ size }: { size: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 20 20">
      <circle cx="10" cy="10" r="9" fill={INK} />
      <circle cx="13.2" cy="7.4" r="6.2" fill="#ffffff" />
      <circle cx="13.2" cy="7.4" r="2.6" fill="#317cff" />
    </svg>
  );
}

/** The closing card, on the same daylight wash the app draws behind its globe. `frame` counts from its start. */
export function EndCard({ frame, site }: { frame: number; site: string }) {
  const rise = (delay: number) => {
    const t = interpolate(frame, [delay, delay + 16], [0, 1], { ...clamp, easing: land });
    return { opacity: t, transform: `translateY(${(1 - t) * 22}px)` };
  };
  const links = [site, "github.com/rupokghosh/aletheia"].filter(Boolean);
  return (
    <AbsoluteFill
      style={{
        background:
          "radial-gradient(circle at 50% 46%, rgba(255,255,255,0.95) 0, rgba(255,255,255,0) 720px), linear-gradient(158deg, #fcdcc0 0%, #fdefdf 26%, #f8f6f2 52%, #e4edf9 80%, #d3e2f6 100%)",
        fontFamily,
        color: INK,
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 30, ...rise(4) }}>
        <Mark size={104} />
        <div style={{ fontSize: 132, fontWeight: 500, letterSpacing: "-0.04em", lineHeight: 1 }}>Aletheia</div>
      </div>
      <div style={{ marginTop: 44, fontSize: 44, lineHeight: 1.25, letterSpacing: "-0.015em", textAlign: "center", maxWidth: 1180, color: "rgba(25,25,25,0.78)", ...rise(12) }}>
        Ask a question about any place on Earth.
        <br />
        Get a radar-backed answer, with receipts.
      </div>
      <div style={{ marginTop: 56, display: "flex", gap: 18, ...rise(20) }}>
        {links.map((link) => (
          <div key={link} style={{ padding: "14px 28px", borderRadius: 999, background: INK, color: "#ffffff", fontSize: 30, fontWeight: 500, letterSpacing: "-0.005em" }}>
            {link}
          </div>
        ))}
      </div>
      <div style={{ position: "absolute", bottom: 58, left: 0, right: 0, textAlign: "center", fontSize: 24, lineHeight: 1.5, color: "rgba(25,25,25,0.6)", ...rise(26) }}>
        NASA Space Apps Challenge 2026 · Dancing with the SARs
        <br />
        Radar data: NASA-ISRO NISAR, from the Alaska Satellite Facility and NASA GIBS
      </div>
    </AbsoluteFill>
  );
}

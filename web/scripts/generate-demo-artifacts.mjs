// Generates the sample images used in demo-data mode (public/demo-artifacts).
// They are procedural pictures, not radar data, and every image is stamped "SAMPLE" in its pixels
// so it cannot be mistaken for a measurement. Run with: pnpm demo:artifacts

import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { deflateSync } from "node:zlib";

const OUT = join(dirname(fileURLToPath(import.meta.url)), "..", "public", "demo-artifacts");
const W = 464;
const H = 268;

// ------------------------------------------------------------------ PNG

const CRC_TABLE = Array.from({ length: 256 }, (_, n) => {
  let c = n;
  for (let k = 0; k < 8; k += 1) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
  return c >>> 0;
});

function crc32(buffer) {
  let c = 0xffffffff;
  for (const byte of buffer) c = CRC_TABLE[(c ^ byte) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

function chunk(type, data) {
  const head = Buffer.alloc(8);
  head.writeUInt32BE(data.length, 0);
  head.write(type, 4, "ascii");
  const tail = Buffer.alloc(4);
  tail.writeUInt32BE(crc32(Buffer.concat([head.subarray(4), data])), 0);
  return Buffer.concat([head, data, tail]);
}

function encodePng(rgba) {
  const header = Buffer.alloc(13);
  header.writeUInt32BE(W, 0);
  header.writeUInt32BE(H, 4);
  header.set([8, 6, 0, 0, 0], 8);
  const raw = Buffer.alloc((W * 4 + 1) * H);
  for (let y = 0; y < H; y += 1) {
    raw[y * (W * 4 + 1)] = 0;
    rgba.copy(raw, y * (W * 4 + 1) + 1, y * W * 4, (y + 1) * W * 4);
  }
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk("IHDR", header),
    chunk("IDAT", deflateSync(raw, { level: 9 })),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}

// ------------------------------------------------------------ colormaps
// Same control points as backend/nisar_investigator/render.py.

const COLORMAPS = {
  grey: [[0, 0, 0, 0], [1, 255, 255, 255]],
  RdBu: [[0, 33, 102, 172], [0.25, 103, 169, 207], [0.5, 247, 247, 247], [0.75, 239, 138, 98], [1, 178, 24, 43]],
  viridis: [[0, 68, 1, 84], [0.25, 59, 82, 139], [0.5, 33, 145, 140], [0.75, 94, 201, 98], [1, 253, 231, 37]],
};

function colour(name, t) {
  const stops = COLORMAPS[name];
  const x = Math.max(0, Math.min(1, t));
  for (let i = 1; i < stops.length; i += 1) {
    if (x <= stops[i][0]) {
      const [p0, ...c0] = stops[i - 1];
      const [p1, ...c1] = stops[i];
      const f = (x - p0) / (p1 - p0);
      return c0.map((v, k) => Math.round(v + (c1[k] - v) * f));
    }
  }
  return stops[stops.length - 1].slice(1);
}

// ---------------------------------------------------------------- noise

function hash(x, y, seed) {
  let h = (x * 374761393 + y * 668265263 + seed * 2147483647) | 0;
  h = Math.imul(h ^ (h >>> 13), 1274126177);
  return ((h ^ (h >>> 16)) >>> 0) / 4294967295;
}

function smooth(u, v, seed) {
  const x0 = Math.floor(u);
  const y0 = Math.floor(v);
  const fx = u - x0;
  const fy = v - y0;
  const sx = fx * fx * (3 - 2 * fx);
  const sy = fy * fy * (3 - 2 * fy);
  const top = hash(x0, y0, seed) * (1 - sx) + hash(x0 + 1, y0, seed) * sx;
  const bottom = hash(x0, y0 + 1, seed) * (1 - sx) + hash(x0 + 1, y0 + 1, seed) * sx;
  return top * (1 - sy) + bottom * sy;
}

function fractal(u, v, seed) {
  return smooth(u, v, seed) * 0.55 + smooth(u * 2.1, v * 2.1, seed + 7) * 0.3 + smooth(u * 4.3, v * 4.3, seed + 13) * 0.15;
}

// ---------------------------------------------------------------- scene

/** Signed distance-like field of an elongated water body. Below `level` is water. */
function shore(x, y) {
  const u = x / W - 0.5;
  const v = y / H - 0.5;
  const along = u * 0.96 + v * 0.26;
  const across = -u * 0.26 + v * 0.96;
  return (along / 0.4) ** 2 + (across / 0.19) ** 2 + (fractal(x / 60, y / 60, 3) - 0.5) * 0.7;
}

/** Sample HH backscatter in dB for a water level between 1 (full) and 0.8 (drawn down). */
function backscatter(x, y, level, seed) {
  const speckle = (hash(x, y, seed) - 0.5) * 2.4;
  if (shore(x, y) < level) return -19.5 + speckle * 0.5 + (fractal(x / 25, y / 25, seed) - 0.5) * 1.5;
  return -11.5 + (fractal(x / 35, y / 35, 5) - 0.5) * 7 + speckle;
}

// ---------------------------------------------------------------- stamp

const GLYPHS = {
  S: ["01111", "10000", "10000", "01110", "00001", "00001", "11110"],
  A: ["01110", "10001", "10001", "11111", "10001", "10001", "10001"],
  M: ["10001", "11011", "10101", "10101", "10001", "10001", "10001"],
  P: ["11110", "10001", "10001", "11110", "10000", "10000", "10000"],
  L: ["10000", "10000", "10000", "10000", "10000", "10000", "11111"],
  E: ["11111", "10000", "10000", "11110", "10000", "10000", "11111"],
};
const WORD = "SAMPLE";
const SCALE = 3;
const WORD_W = WORD.length * 6 * SCALE;
const WORD_H = 7 * SCALE;

/** True where a tiled, staggered "SAMPLE" covers the pixel. */
function stamped(x, y) {
  const periodX = WORD_W + 48;
  const periodY = WORD_H + 46;
  const row = Math.floor(y / periodY);
  const localY = y - row * periodY - 20;
  const localX = (((x + (row % 2) * (periodX / 2)) % periodX) + periodX) % periodX - 20;
  if (localX < 0 || localY < 0 || localX >= WORD_W || localY >= WORD_H) return false;
  const letter = GLYPHS[WORD[Math.floor(localX / (6 * SCALE))]];
  const col = Math.floor((localX % (6 * SCALE)) / SCALE);
  return col < 5 && letter[Math.floor(localY / SCALE)][col] === "1";
}

function render(name, pixel, ink) {
  const rgba = Buffer.alloc(W * H * 4);
  for (let y = 0; y < H; y += 1) {
    for (let x = 0; x < W; x += 1) {
      let [r, g, b, a] = pixel(x, y);
      if (stamped(x, y)) {
        r = Math.round(r * 0.25 + ink[0] * 0.75);
        g = Math.round(g * 0.25 + ink[1] * 0.75);
        b = Math.round(b * 0.25 + ink[2] * 0.75);
        a = 255;
      }
      rgba.set([r, g, b, a], (y * W + x) * 4);
    }
  }
  writeFileSync(join(OUT, name), encodePng(rgba));
}

// --------------------------------------------------------------- output

mkdirSync(OUT, { recursive: true });
const AMBER = [255, 190, 60];
const INK = [20, 22, 26];
const LEVELS = [1.0, 0.97, 0.93, 0.89, 0.85, 0.81];

LEVELS.forEach((level, index) => {
  render(`hh_t${index}.png`, (x, y) => [...colour("grey", (backscatter(x, y, level, 20 + index) + 25) / 20), 255], AMBER);
});

const before = (x, y) => backscatter(x, y, LEVELS[0], 20);
const after = (x, y) => backscatter(x, y, LEVELS[5], 25);

render("change_db.png", (x, y) => [...colour("RdBu", (after(x, y) - before(x, y) + 6) / 12), 235], INK);

render(
  "change_class.png",
  (x, y) => {
    const s = shore(x, y);
    if (s < LEVELS[0] && s >= LEVELS[5]) return [230, 97, 1, 235];
    if (fractal(x / 9, y / 9, 41) > 0.83 && s > 1.25 && s < 1.6) return [94, 60, 153, 235];
    return [0, 0, 0, 0];
  },
  AMBER,
);

render(
  "los_displacement.png",
  (x, y) => {
    if (shore(x, y) < LEVELS[2]) return [0, 0, 0, 0];
    const cm = (fractal(x / 110, y / 110, 61) - 0.5) * 4.5 + (hash(x, y, 62) - 0.5) * 0.5;
    return [...colour("RdBu", (cm + 3) / 6), 235];
  },
  INK,
);

render(
  "coherence.png",
  (x, y) => {
    const water = shore(x, y) < LEVELS[2];
    const value = water ? 0.08 + hash(x, y, 71) * 0.1 : 0.35 + fractal(x / 45, y / 45, 72) * 0.55;
    return [...colour("viridis", value), 255];
  },
  [255, 255, 255],
);

console.log(`Wrote sample images to ${OUT}`);

/** Colour maps as control points. Same values as backend/nisar_investigator/render.py. */

type Stop = [position: number, r: number, g: number, b: number];

const COLORMAPS: Record<string, Stop[]> = {
  grey: [
    [0, 0, 0, 0],
    [1, 255, 255, 255],
  ],
  rdbu: [
    [0, 33, 102, 172],
    [0.25, 103, 169, 207],
    [0.5, 247, 247, 247],
    [0.75, 239, 138, 98],
    [1, 178, 24, 43],
  ],
  viridis: [
    [0, 68, 1, 84],
    [0.25, 59, 82, 139],
    [0.5, 33, 145, 140],
    [0.75, 94, 201, 98],
    [1, 253, 231, 37],
  ],
  // cyclic (first colour = last colour), for wrapped quantities such as interferometric fringes
  cyclic: [
    [0, 226, 74, 74],
    [1 / 6, 236, 196, 64],
    [2 / 6, 84, 186, 96],
    [3 / 6, 62, 186, 198],
    [4 / 6, 72, 104, 208],
    [5 / 6, 186, 84, 198],
    [1, 226, 74, 74],
  ],
  magma: [
    [0, 0, 0, 4],
    [0.25, 81, 18, 124],
    [0.5, 183, 55, 121],
    [0.75, 252, 137, 97],
    [1, 252, 253, 191],
  ],
};

const ALIASES: Record<string, string> = { gray: "grey", greys: "grey", grays: "grey" };

/** CSS gradient for a named colour map, or null when the name is not known. */
export function colormapGradient(name: string | null): string | null {
  if (!name) return null;
  const key = name.toLowerCase();
  const stops = COLORMAPS[ALIASES[key] ?? key];
  if (!stops) return null;
  const css = stops.map(([position, r, g, b]) => `rgb(${r} ${g} ${b}) ${position * 100}%`).join(", ");
  return `linear-gradient(to right, ${css})`;
}

/** True for colour maps with a neutral midpoint, where the centre value deserves a tick. */
export function isDiverging(name: string | null): boolean {
  return name?.toLowerCase() === "rdbu";
}

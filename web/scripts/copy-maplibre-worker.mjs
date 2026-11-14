// MapLibre GL JS 6 runs its tile worker from a separate module file that a bundler does not emit.
// This copies that file into public/vendor so the app can point MapLibre at it (see MapView.tsx).
// It runs before `next dev` and `next build`, so the worker always matches the installed version.

import { copyFileSync, mkdirSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const source = join(dirname(require.resolve("maplibre-gl/package.json")), "dist", "maplibre-gl-worker.mjs");
const target = join(root, "public", "vendor", "maplibre-gl-worker.mjs");

mkdirSync(dirname(target), { recursive: true });
copyFileSync(source, target);
console.log("Copied the MapLibre worker to public/vendor/");

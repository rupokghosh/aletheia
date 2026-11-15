// Shared helpers for filming the running app: open it in Chrome, take hold of its map, and step the
// camera one film frame at a time, so every frame is drawn in full before it is photographed.

import { chromium } from "playwright-core";
import { mkdir, rm } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

export const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
export const FOOTAGE = path.join(ROOT, "public", "footage");
export const APP_URL = process.env.ALETHEIA_URL ?? "http://localhost:3000";
export const WIDTH = 1920;
export const HEIGHT = 1080;
export const FPS = 30;

export async function openBrowser({ scale = 2 } = {}) {
  const browser = await chromium.launch({
    channel: "chrome",
    headless: true,
    args: ["--use-angle=metal", "--enable-gpu", "--ignore-gpu-blocklist", "--hide-scrollbars"],
  });
  const context = await browser.newContext({
    viewport: { width: WIDTH, height: HEIGHT },
    deviceScaleFactor: scale,
    reducedMotion: "reduce", // the app then leaves the camera to us: no idle turning, no timed flights
  });
  const page = await context.newPage();
  page.on("pageerror", (error) => console.error("page error:", error.message));
  return { browser, page };
}

export async function openApp(options = {}) {
  const { browser, page } = await openBrowser(options);
  await loadApp(page);
  return { browser, page };
}

export async function loadApp(page) {
  await page.goto(APP_URL, { waitUntil: "domcontentloaded" });
  await holdMap(page);
}

/** Find the app's MapLibre map (it lives in React state, not on `window`) and add frame-stepping helpers. */
export async function holdMap(page) {
  await page.waitForSelector(".globe-stage canvas", { timeout: 60_000 });
  await page.waitForFunction(
    () => {
      const stage = document.querySelector(".globe-stage");
      if (!stage) return false;
      const key = Object.keys(stage).find((name) => name.startsWith("__reactFiber$"));
      let fiber = key ? stage[key] : null;
      while (fiber) {
        let hook = fiber.memoizedState;
        while (hook && typeof hook === "object" && "memoizedState" in hook) {
          const value = hook.memoizedState;
          if (value && typeof value === "object" && typeof value.jumpTo === "function" && typeof value.getCanvas === "function") {
            window.__map = value;
            return true;
          }
          hook = hook.next;
        }
        fiber = fiber.return;
      }
      return false;
    },
    undefined,
    { timeout: 60_000 },
  );
  await page.evaluate(() => {
    const map = window.__map;
    const originals = {};
    const settled = (limit = 15000) =>
      new Promise((resolve) => {
        let finished = false;
        const finish = () => {
          if (finished) return;
          finished = true;
          requestAnimationFrame(() => requestAnimationFrame(() => resolve(true)));
        };
        map.once("idle", finish);
        map.triggerRepaint();
        setTimeout(finish, limit);
      });
    window.__film = {
      settled,
      /** Put the camera somewhere and resolve once that view is completely drawn. */
      async look(camera) {
        map.jumpTo(camera);
        await settled();
      },
      camera() {
        const centre = map.getCenter();
        return { center: [centre.lng, centre.lat], zoom: map.getZoom() };
      },
      /** Timed fades would be caught half-way by a frame-by-frame camera: switch them off. */
      quiet() {
        try {
          map.setTransition({ duration: 0, delay: 0 });
        } catch {
          /* older MapLibre: fades simply finish before each frame is taken */
        }
        for (const layer of map.getStyle().layers) {
          if (layer.type === "raster") map.setPaintProperty(layer.id, "raster-fade-duration", 0);
        }
      },
      /** Place names at a strength from 0 (hidden) to 1 (as the app draws them). */
      labels(strength) {
        for (const layer of map.getStyle().layers) {
          if (layer.type !== "symbol") continue;
          if (!(layer.id in originals)) {
            originals[layer.id] = {
              "text-opacity": map.getPaintProperty(layer.id, "text-opacity"),
              "icon-opacity": map.getPaintProperty(layer.id, "icon-opacity"),
            };
          }
          let simple = true;
          for (const [property, value] of Object.entries(originals[layer.id])) {
            if (value === undefined || typeof value === "number") {
              map.setPaintProperty(layer.id, property, strength >= 1 ? value : (value ?? 1) * strength);
            } else {
              simple = false;
            }
          }
          const visible = simple ? strength > 0 : strength > 0.5;
          map.setLayoutProperty(layer.id, "visibility", visible ? "visible" : "none");
        }
      },
      /** Strength of the result picture drawn over the map (the app draws it at 0.9). */
      overlay(opacity) {
        const ids = map.getStyle().layers.filter((layer) => layer.type === "raster" && layer.id.startsWith("result-")).map((layer) => layer.id);
        for (const id of ids) map.setPaintProperty(id, "raster-opacity", opacity);
        return ids;
      },
      /** The side panel's scrolling area. */
      scroller() {
        return [...document.querySelectorAll(".scroll-quiet")].find((el) => el.scrollHeight > el.clientHeight + 4 && el.getBoundingClientRect().left < 400) ?? null;
      },
      scrollTo(top) {
        const el = window.__film.scroller();
        if (el) el.scrollTop = top;
        return el ? el.scrollTop : -1;
      },
      /** Where on screen the smallest element holding this text sits (CSS pixels). */
      rect(text) {
        let best = null;
        for (const el of document.querySelectorAll("body *")) {
          if (el.offsetParent === null || !el.textContent?.includes(text)) continue;
          if ([...el.children].some((child) => child.textContent?.includes(text))) continue;
          best = el;
          break;
        }
        if (!best) return null;
        const box = best.getBoundingClientRect();
        return { x: box.x, y: box.y, width: box.width, height: box.height };
      },
      /** Screen position of a place on the map (CSS pixels). */
      point(lngLat) {
        const p = map.project(lngLat);
        const box = map.getCanvas().getBoundingClientRect();
        return { x: box.left + p.x, y: box.top + p.y };
      },
    };
  });
  await page.evaluate(() => window.__film.settled(30000));
}

export async function shotDir(name, { fresh = false } = {}) {
  const dir = path.join(FOOTAGE, name);
  if (fresh) await rm(dir, { recursive: true, force: true });
  await mkdir(dir, { recursive: true });
  return dir;
}

export const frameName = (index) => `${String(index).padStart(4, "0")}.jpg`;

export async function photograph(page, file) {
  await page.screenshot({ path: file, type: "jpeg", quality: 92 });
}

// Easing ---------------------------------------------------------------------------------------------
export const clamp01 = (t) => Math.min(1, Math.max(0, t));
export const smooth = (t) => t * t * t * (t * (t * 6 - 15) + 10); // smootherstep: eases in and out
export const easeOut = (t) => 1 - (1 - t) ** 3;
export const lerp = (a, b, t) => a + (b - a) * t;

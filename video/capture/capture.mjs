// Films the running app (http://localhost:3000) frame by frame into public/footage/<shot>/0000.jpg ...
//
//   node capture/capture.mjs                 every shot
//   node capture/capture.mjs opening answer  only those shots
//
// Nothing here is drawn by the film: every frame is the real app, photographed after the map has finished
// drawing. The camera is moved by the script, and typing, clicks and scrolling are done in the page.

import { writeFile } from "node:fs/promises";
import path from "node:path";
import { clamp01, frameName, lerp, loadApp, openBrowser, photograph, shotDir, smooth } from "./lib.mjs";

const QUESTION = "Did the ground move here during the earthquakes of 24 June 2026, and by how much?";
const VENEZUELA = { bbox: [-68.45, 10.3, -67.95, 10.75], centre: [-68.2, 10.525], title: "The June 2026 earthquakes in Venezuela" };
const KAMLOOPS = { title: "Kamloops Lake through the summer" };
// The map's margins while the side panel and the layers card are open (the app's own numbers), and the
// camera the app settles on for the Venezuela area. The flight ends there and the answer is shown from there.
const PANEL_MARGIN = { left: 492, right: 344, top: 0, bottom: 0 };
const ARRIVE = { center: [-68.2, 10.525082080223626], zoom: 10.416665599935463 };

const wanted = process.argv.slice(2);
const want = (name) => wanted.length === 0 || wanted.includes(name);
const meta = {};

const { browser, page } = await openBrowser();
const film = (fn, arg) => page.evaluate(fn, arg);
const look = (camera) => film((c) => window.__film.look(c), camera);
const settle = () => film(() => window.__film.settled(20000));
const rect = (text) => film((t) => window.__film.rect(t), text);

async function take(dir, index) {
  await photograph(page, path.join(dir, frameName(index)));
  if (index % 20 === 0) console.log(`  ${path.basename(dir)} ${index}`);
}

// -- 1. Opening: the globe turns, a place is clicked, the camera flies down to it; then the question ----
if (want("opening")) {
  console.log("opening");
  await loadApp(page);
  await film(() => {
    window.__film.quiet();
    window.__film.labels(0);
  });
  const dir = await shotDir("opening", { fresh: true });

  const TURN = 135; // frames of turning globe
  const FLIGHT = 105; // frames of flight
  const start = { center: [-99, 21], zoom: 1.7 };
  const hover = { center: [-71, 13.5], zoom: 1.8 };
  // The turn runs at a steady pace, then slows to a stop a little before the click.
  const pace = (f) => (f < 96 ? 1 : f < 126 ? 1 - smooth((f - 96) / 30) : 0);
  const total = Array.from({ length: TURN }, (_, f) => pace(f)).reduce((a, b) => a + b, 0);
  let travelled = 0;
  for (let f = 0; f < TURN; f += 1) {
    const t = travelled / total;
    await look({ center: [lerp(start.center[0], hover.center[0], t), lerp(start.center[1], hover.center[1], t)], zoom: lerp(start.zoom, hover.zoom, t) });
    if (f === TURN - 1) meta.click = await film((c) => window.__film.point(c), VENEZUELA.centre);
    await take(dir, f);
    travelled += pace(f);
  }

  // Off camera: click the place, then give the area the exact corners of the worked example, so the
  // answer shown later belongs to this very area.
  await page.mouse.click(meta.click.x, meta.click.y);
  await page.getByText("Coordinates", { exact: true }).click();
  const edges = ["West (longitude)", "South (latitude)", "East (longitude)", "North (latitude)"];
  for (const [i, label] of edges.entries()) await page.getByLabel(label).fill(String(VENEZUELA.bbox[i]));
  await page.getByRole("button", { name: "Use these coordinates" }).click();
  await page.getByText(/usable dates here/).waitFor({ timeout: 60_000 });
  await page.waitForTimeout(1500); // the place name arrives a moment after the area
  await settle();
  meta.appFit = await film(() => window.__film.camera());
  // The flight is filmed with the side panel folded away (the app's own "Hide this panel" button), so the
  // map fills the frame; the map keeps the panel's margin, so nothing shifts when the panel comes back.
  await page.getByRole("button", { name: "Hide this panel" }).click();
  await page.waitForTimeout(300);

  // The flight zooms toward the place: the remaining distance shrinks with the scale, so the target
  // glides to the middle instead of sliding past.
  const span = 2 ** -hover.zoom - 2 ** -ARRIVE.zoom;
  for (let f = 0; f < FLIGHT; f += 1) {
    const t = smooth(f / (FLIGHT - 1));
    const zoom = lerp(hover.zoom, ARRIVE.zoom, t);
    const left = (2 ** -zoom - 2 ** -ARRIVE.zoom) / span;
    const names = clamp01((f - (FLIGHT - 22)) / 18); // place names come in as the camera settles
    await film((k) => window.__film.labels(k), names);
    await look({ center: [lerp(ARRIVE.center[0], hover.center[0], left), lerp(ARRIVE.center[1], hover.center[1], left)], zoom, padding: PANEL_MARGIN });
    await take(dir, TURN + f);
  }
  await film(() => window.__film.labels(1));
  meta.opening = { frames: TURN + FLIGHT, turn: TURN };

  // The question, typed into the real box one letter a frame.
  console.log("ask");
  await page.getByRole("button", { name: /Open$/ }).click();
  await page.getByText(/usable dates here/).waitFor({ timeout: 60_000 });
  await look({ ...ARRIVE, padding: PANEL_MARGIN });
  const bottom = await film(() => {
    const el = window.__film.scroller();
    if (el) el.scrollTop = el.scrollHeight;
    return el ? el.scrollTop : 0;
  });
  await settle();
  const ask = await shotDir("ask", { fresh: true });
  const box = page.locator("textarea");
  meta.askScrolled = bottom;
  meta.textarea = await box.boundingBox();
  meta.askButton = await page.getByRole("button", { name: "Ask about this area" }).boundingBox();
  meta.askHeading = await rect("Or ask in your own words");
  let f = 0;
  for (; f < 10; f += 1) await take(ask, f);
  await box.click();
  for (; f < 14; f += 1) await take(ask, f);
  for (const letter of QUESTION) {
    await page.keyboard.type(letter);
    await take(ask, f);
    f += 1;
  }
  for (let hold = 0; hold < 10; hold += 1, f += 1) await take(ask, f);
  meta.ask = { frames: f, typingFrom: 14, typingTo: 14 + QUESTION.length };
}

// -- 2. The answer: the ground-movement picture comes up, then the panel is read downward ---------------
if (want("answer")) {
  console.log("answer");
  await loadApp(page);
  await page.getByText(VENEZUELA.title, { exact: true }).click();
  await page.getByText("Answer", { exact: true }).waitFor({ timeout: 30_000 });
  await page.waitForTimeout(1500);
  await settle();
  await film(() => window.__film.quiet());
  meta.answerCamera = await film(() => window.__film.camera());
  meta.answerLayers = await film(() => window.__film.overlay(0));
  await look({ ...ARRIVE, padding: PANEL_MARGIN });
  const dir = await shotDir("answer", { fresh: true });
  const REVEAL = 40;
  for (let f = 0; f < REVEAL; f += 1) {
    await film((o) => window.__film.overlay(o), 0.9 * smooth(f / (REVEAL - 1)));
    await settle();
    await take(dir, f);
  }
  meta.figures = await rect("Largest movement toward the satellite");
  meta.quakeChart = await rect("Earthquakes within 150 km");
  const profile = await rect("Motion across the area, south to north");
  const SCROLL = 64;
  const target = Math.max(0, Math.round(profile.y - 150));
  for (let f = 0; f < SCROLL; f += 1) {
    await film((y) => window.__film.scrollTo(y), target * smooth(f / (SCROLL - 1)));
    await take(dir, REVEAL + f);
  }
  meta.answer = { frames: REVEAL + SCROLL, reveal: REVEAL, scrolled: target };
  meta.profileChart = await rect("Motion across the area, south to north");

  // The receipts: the same result opened in full, with what it took to compute and where it came from.
  console.log("receipts");
  await film(() => window.__film.scrollTo(0));
  await page.getByText("Open this result on the map, with all its charts").first().click();
  await page.getByText("radar measurements", { exact: false }).first().waitFor({ timeout: 30_000 });
  await page.waitForTimeout(800);
  await settle();
  const receipts = await shotDir("receipts", { fresh: true });
  meta.effort = await rect("in NASA’s archive");
  await take(receipts, 0);
  await page.getByText("Sources and receipt", { exact: true }).click();
  await page.waitForTimeout(500);
  const sources = await rect("Sources and receipt");
  const down = await film((y) => {
    const el = window.__film.scroller();
    return Math.min(el.scrollHeight - el.clientHeight, Math.max(0, el.scrollTop + y - 130));
  }, sources.y);
  const DOWN = 50;
  for (let f = 0; f < DOWN; f += 1) {
    await film((y) => window.__film.scrollTo(y), down * smooth(f / (DOWN - 1)));
    await take(receipts, 1 + f);
  }
  meta.receipts = { frames: 1 + DOWN, scrolled: down };
  meta.sources = await rect("Sources and receipt");
  meta.receiptText = await film(() => window.__film.scroller()?.innerText.slice(-1500));
}

// -- 3. Kamloops Lake: the change picture comes up while the camera drifts in ---------------------------
if (want("kamloops")) {
  console.log("kamloops");
  await loadApp(page);
  await page.getByText(KAMLOOPS.title, { exact: true }).click();
  await page.getByText("Answer", { exact: true }).waitFor({ timeout: 30_000 });
  await page.waitForTimeout(1500);
  await settle();
  await film(() => window.__film.quiet());
  const home = await film(() => window.__film.camera());
  meta.kamloopsCamera = home;
  meta.kamloopsLayers = await film(() => window.__film.overlay(0));
  meta.kamloopsFigure = await rect("River level at the gauge");
  meta.gaugeChart = await rect("River level at Thompson River at Kamloops");
  const dir = await shotDir("kamloops", { fresh: true });
  const FRAMES = 165;
  const REVEAL = 40;
  for (let f = 0; f < FRAMES; f += 1) {
    await film((o) => window.__film.overlay(o), 0.9 * smooth(clamp01(f / (REVEAL - 1))));
    await look({ center: home.center, zoom: home.zoom + 0.16 * (f / (FRAMES - 1)) });
    await take(dir, f);
  }
  meta.kamloops = { frames: FRAMES, reveal: REVEAL };
}

await browser.close();
const file = path.join(await shotDir("."), `meta-${wanted.length ? wanted.join("-") : "all"}.json`);
await writeFile(file, JSON.stringify(meta, null, 1));
console.log(JSON.stringify(meta, null, 1));

#!/usr/bin/env node
// tmp/drive-full.mjs — CHK04 归因实验 E5：逐行复刻 run.ts wire()（route/routeWebSocket/
// console 记账/addInitScript(new Function(PROBE_JS))）+ autoplay.ts 驱动循环的完整每轮
// evaluate 序列（state→qcTextStates→readProbe→[gestures==0: pfMuted→audio→mediaSample]→
// hint→gesture→waitForTimeout(180)），打印全部迭代与 running 翻转相对手势的时序。
// 用法：node tmp/drive-full.mjs <artifact.html> <tag> [maxSec=45]

import { chromium } from "playwright";
import { readFileSync } from "node:fs";
import { createServer } from "node:http";
import { basename } from "node:path";
import { PROBE_JS } from "../qacore/src/probe.ts";

const [, , artifact, tag, maxSecArg] = process.argv;
const MAX_SEC = Number(maxSecArg ?? 45);
const SETTLE_MS = 400;

const server = createServer((req, res) => {
  res.setHeader("Content-Type", "text/html; charset=utf-8");
  res.end(readFileSync(artifact));
}).listen(0);
await new Promise((r) => server.on("listening", r));
const url = `http://127.0.0.1:${server.address().port}/${basename(artifact)}`;

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({
  viewport: { width: 390, height: 844 }, isMobile: true, deviceScaleFactor: 2, serviceWorkers: "block",
});
const page = await context.newPage();

// ---- wire()（run.ts:188-216 同构）----
const consoleErrors = [];
const blockedUrls = new Set();
const entries = new Map();
page.on("response", (response) => {});
page.on("pageerror", (exc) => consoleErrors.push(`pageerror: ${exc}`));
await page.addInitScript(new Function(PROBE_JS));
await page.route("**/*", (route) => route.continue());
await page.routeWebSocket("**/*", () => {});

await page.goto(url, { waitUntil: "load", timeout: 15000 });
await page.waitForTimeout(SETTLE_MS);

const evl = (src) => page.evaluate(new Function(`return (${src})();`));
const state = () => evl(`() => (window.__PF_QC__ && typeof window.__PF_QC__.state === 'function') ? String(window.__PF_QC__.state()) : 'loading'`);
const pfMuted = () => evl(`() => (window.PF && typeof PF.isMuted === 'function') ? PF.isMuted() : null`);
const readProbe = () => evl(`() => window.__pfprobe || null`);
const qcTextStates = () => evl(`() => (window.__PF_QC__ && typeof window.__PF_QC__.textStates === 'function') ? window.__PF_QC__.textStates() : []`);
const mediaSample = () => evl(`() => (window.__pfprobe && typeof window.__pfprobe.sampleMedia === 'function') ? window.__pfprobe.sampleMedia() : { unmuted: 0, playing: 0, playsBeforeFirst: 0 }`);
const hint = () => evl(`() => { const q = window.__PF_QC__; if (!q || typeof q.hint !== 'function') return null; try { return q.hint(); } catch (e) { return null; } }`);
const SWEEP = { up: [0, -1], down: [0, 1], left: [-1, 0], right: [1, 0] };

const log = [];
let gestures = 0;
const t0 = Date.now();
while (Date.now() - t0 < MAX_SEC * 1000) {
  const st = await state();
  const states = await qcTextStates();
  const probe = await readProbe();
  const entry = {
    t: Date.now() - t0, iter: log.length + 1, gesturesBefore: gestures, state: st,
    running: probe?.audio?.running ?? null, created: probe?.audio?.created ?? null,
    sampled: false,
  };
  if (gestures === 0) {
    entry.sampled = true;
    const m = await pfMuted();
    entry.pfMuted = m;
    entry.runningAtSample = probe?.audio?.running ?? null;
    const ms = await mediaSample();
    entry.mediaUnmuted = ms?.unmuted ?? null;
    log.push(entry);
  } else if (log.length < 200) {
    log.push(entry);
  }
  if (st === "end") break;
  const h = await hint();
  entry.hintType = h ? String(h?.type) : null;
  if (h && typeof h.x === "number" && typeof h.y === "number") {
    const vec = SWEEP[String(h.type)] ?? null;
    await page.mouse.move(h.x, h.y);
    await page.mouse.down();
    if (vec) for (let i = 1; i <= 4; i++) await page.mouse.move(h.x + vec[0] * 80 * i / 4, h.y + vec[1] * 80 * i / 4);
    await page.mouse.up();
    gestures += 1;
  }
  entry.dispatchedGesture = Boolean(h && typeof h.x === "number");
  await page.waitForTimeout(180);
}
const flips = log.filter((e, i) => i > 0 && e.running !== log[i - 1].running && e.sampled);
console.log(JSON.stringify({
  tag, artifact: basename(artifact), totalGestures: gestures,
  sampledEntries: log.filter((e) => e.sampled).map((e) => ({ t: e.t, running: e.running, created: e.created, pfMuted: e.pfMuted, mediaUnmuted: e.mediaUnmuted, state: e.state })),
  firstUnsampledAfterGesture: log.filter((e) => !e.sampled).slice(0, 3).map((e) => ({ t: e.t, running: e.running, state: e.state, hint: e.hintType })),
}, null, 1));
await browser.close();
server.close();

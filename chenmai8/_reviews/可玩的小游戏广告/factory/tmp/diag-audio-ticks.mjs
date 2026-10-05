// 诊断脚本 3（非产品）：复刻 qacore driveAutoplay 的逐 tick 行为并记录每次采样
// （tick 时刻 / 探针 running / gestures），配合 __diag 状态迁移，捕获
// audioRunPre=1 的现场（采样到底看到了什么、何时发生的）。
import { chromium } from "playwright";
import { ArtifactServer } from "../qacore/src/server.ts";
import { state as qcState, qcTextStates, pfMuted, mediaSample, probeInstalled,
         hasQcHooks, DRAG_DISTANCE, PROBE_JS } from "../qacore/src/autoplay.ts";
import { resolve } from "node:path";

const SWEEP_VECTORS = {
  "swap-left": [-1.0, 0.0], "swap-right": [1.0, 0.0],
  "swap-up": [0.0, -1.0], "swap-down": [0.0, 1.0], "drag": [1.0, 0.0],
};
async function gesture(page, h) {
  const x = h.x, y = h.y;
  const vec = SWEEP_VECTORS[h.type];
  await page.mouse.move(x, y);
  await page.mouse.down();
  if (vec) {
    const steps = 4;
    for (let i = 1; i <= steps; i++) {
      await page.mouse.move(x + vec[0] * DRAG_DISTANCE * i / steps, y + vec[1] * DRAG_DISTANCE * i / steps);
    }
  }
  await page.mouse.up();
}
async function hint(page) {
  let raw;
  try {
    raw = await page.evaluate(new Function("return (() => { const q = window.__PF_QC__;"
      + " if (!q || typeof q.hint !== 'function') return null;"
      + " try { return q.hint(); } catch (e) { return null; } })();"));
  } catch { return null; }
  if (raw === null || typeof raw !== "object") return null;
  const x = raw.x, y = raw.y;
  if (typeof x !== "number" || typeof y !== "number") return null;
  return { x, y, type: typeof raw.type === "string" ? raw.type : "tap" };
}

const RECORDER = String.raw`(() => {
  window.__diag = { transitions: [], pointerAt: null };
  document.addEventListener('pointerdown', () => {
    if (window.__diag.pointerAt === null) window.__diag.pointerAt = performance.now();
  }, true);
  const wrap = (name) => {
    const Ctor = window[name];
    if (typeof Ctor !== 'function') return;
    const Wrapped = function (...args) {
      const ctx = new Ctor(...args);
      const rec = () => window.__diag.transitions.push({
        at: Math.round(performance.now()), state: ctx.state });
      rec();
      try { ctx.addEventListener('statechange', rec); } catch (e) {}
      return ctx;
    };
    Wrapped.prototype = Ctor.prototype;
    try { Object.defineProperty(window, name, { value: Wrapped, configurable: true, writable: true }); } catch (e) {}
  };
  wrap('AudioContext');
  wrap('webkitAudioContext');
})();`;

const readProbe = (page) => page.evaluate(new Function("return (() => window.__pfprobe || null)();")) ?? {};

async function driveInstrumented(page, timeoutSec) {
  const ticks = [];
  const facts = {
    reachedState: "loading", gestures: 0,
    firstMutedBeforeInteraction: null, audioRunningBeforeInteraction: null,
    mediaUnmutedBeforeInteraction: null, mediaPlaysBeforeInteraction: null,
    mutedAfterFirstGesture: null, pfEndFired: false, pfEndMs: null,
  };
  const deadline = Date.now() + Math.max(1.0, timeoutSec) * 1000;
  let tick = 0;
  while (Date.now() < deadline) {
    tick += 1;
    const st = await qcState(page);
    facts.reachedState = st;
    await qcTextStates(page);
    const probe = await readProbe(page);
    if (facts.gestures === 0) {
      const m = await pfMuted(page);
      if (m === false) facts.firstMutedBeforeInteraction = false;
      else if (facts.firstMutedBeforeInteraction === null) facts.firstMutedBeforeInteraction = m;
      const run = Number(probe.audio?.running) || 0;
      facts.audioRunningBeforeInteraction =
        Math.max(facts.audioRunningBeforeInteraction ?? 0, Math.trunc(run));
      const ms = (await mediaSample(page)) ?? { unmuted: 0, playing: 0, playsBeforeFirst: 0 };
      facts.mediaUnmutedBeforeInteraction = Math.max(facts.mediaUnmutedBeforeInteraction ?? 0, Math.trunc(ms.unmuted));
      facts.mediaPlaysBeforeInteraction = Math.max(facts.mediaPlaysBeforeInteraction ?? 0, Math.trunc(ms.playsBeforeFirst));
      ticks.push({ tick, t: Math.round(performance.now() - T0), state: st, running: run });
    }
    if (st === "end") break;
    const h = await hint(page);
    if (h !== null) {
      await gesture(page, h);
      facts.gestures += 1;
      if (facts.mutedAfterFirstGesture === null) facts.mutedAfterFirstGesture = await pfMuted(page);
      ticks.push({ tick, t: Math.round(performance.now() - T0), gesture: h.type, gesturesAfter: facts.gestures });
    }
    await page.waitForTimeout(180);
  }
  const probe = await readProbe(page);
  facts.pfEndFired = probe.end !== null && probe.end !== undefined;
  facts.pfEndMs = probe.end ?? null;
  return { facts, ticks };
}

let T0 = 0; // 每轮按"宿主时钟 - 页面时钟"对齐，近似换算页面时刻
const server = new ArtifactServer(resolve("tmp/qacore-eval/templates"), 0);
await server.start();
const browser = await chromium.launch({ headless: true });
for (let r = 0; r < 8 && !globalThis.__caught; r++) {
  const ctx = await browser.newContext({
    viewport: { width: 390, height: 844 },
    isMobile: true, deviceScaleFactor: 2, serviceWorkers: "block",
  });
  const page = await ctx.newPage();
  await page.addInitScript(new Function(PROBE_JS));
  await page.addInitScript(new Function(RECORDER));
  await page.goto(server.url_for("pullpin.html"), { waitUntil: "load", timeout: 15000 });
  await page.waitForTimeout(400);
  T0 = performance.now() - (await page.evaluate(new Function("return (() => performance.now())();")));
  const { facts, ticks } = await driveInstrumented(page, 45);
  const diag = await page.evaluate(new Function("return (() => window.__diag)();"));
  const hit = facts.audioRunningBeforeInteraction === 1;
  console.log(`[r${r}] audioRunPre=${facts.audioRunningBeforeInteraction} gestures=${facts.gestures} ` +
    `pointerAt=${diag.pointerAt === null ? "null" : Math.round(diag.pointerAt)} ` +
    `transitions=${JSON.stringify(diag.transitions)}`);
  console.log("   ticks=" + JSON.stringify(ticks));
  if (hit) globalThis.__caught = true;
  await ctx.close();
}
await browser.close();
await server.stop();

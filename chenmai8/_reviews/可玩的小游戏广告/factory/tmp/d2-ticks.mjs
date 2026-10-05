// d2-ticks.mjs — 驱动 autoplay 并记录：每轮采样时刻(t,gesturesBefore,running) +
// __diag 状态迁移（created/statechange 时刻）+ pointerAt。观察 running=1 何时被采到。
import { chromium } from "playwright";
import { readFileSync } from "node:fs";
import { createServer } from "node:http";
import { basename } from "node:path";
import { PROBE_JS } from "../qacore/src/probe.ts";

const artifact = process.argv[2];
const rounds = Number(process.argv[3] ?? 3);
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
      const rec = (tag) => window.__diag.transitions.push({ at: Math.round(performance.now()), tag, state: ctx.state });
      rec('created:' + name);
      try { ctx.addEventListener('statechange', () => rec('statechange')); } catch (e) {}
      return ctx;
    };
    Wrapped.prototype = Ctor.prototype;
    try { Object.defineProperty(window, name, { value: Wrapped, configurable: true, writable: true }); } catch (e) {}
  };
  wrap('AudioContext');
  wrap('webkitAudioContext');
})();`;

const server = createServer((req, res) => {
  res.setHeader("Content-Type", "text/html; charset=utf-8");
  res.end(readFileSync(artifact));
}).listen(0);
await new Promise((r) => server.on("listening", r));
const url = `http://127.0.0.1:${server.address().port}/${basename(artifact)}`;
const browser = await chromium.launch({ headless: true });
const SWEEP = { "swap-left": [-1,0], "swap-right": [1,0], "swap-up": [0,-1], "swap-down": [0,1], "drag": [1,0], "tap": null };
for (let r = 0; r < rounds; r++) {
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, deviceScaleFactor: 2, serviceWorkers: "block" });
  const page = await ctx.newPage();
  await page.addInitScript(new Function(RECORDER));
  await page.addInitScript(new Function(PROBE_JS));
  await page.goto(url, { waitUntil: "load", timeout: 15000 });
  await page.waitForTimeout(400);
  const samples = [];
  const t0 = Date.now();
  let gestures = 0;
  while (Date.now() - t0 < 30000) {
    const st = await page.evaluate(new Function("return (() => (window.__PF_QC__ && typeof window.__PF_QC__.state === 'function') ? String(window.__PF_QC__.state()) : 'loading')();"));
    const probe = await page.evaluate(new Function("return (() => window.__pfprobe || null)();"));
    if (gestures === 0) samples.push({ t: Date.now() - t0, g: gestures, state: st, running: probe?.audio?.running, created: probe?.audio?.created });
    if (st === "end") break;
    const h = await page.evaluate(new Function("return (() => { const q = window.__PF_QC__; if (!q || typeof q.hint !== 'function') return null; try { return q.hint(); } catch (e) { return null; } })();"));
    if (h && typeof h.x === "number") {
      const vec = SWEEP[String(h.type)] ?? null;
      await page.mouse.move(h.x, h.y);
      await page.mouse.down();
      if (vec) for (let i = 1; i <= 4; i++) await page.mouse.move(h.x + vec[0]*44*i/4, h.y + vec[1]*44*i/4);
      await page.mouse.up();
      gestures += 1;
    }
    await page.waitForTimeout(180);
  }
  const diag = await page.evaluate(new Function("return (() => window.__diag)();"));
  console.log(`r${r}: preGestureSamples=`, JSON.stringify(samples));
  console.log(`   transitions=`, JSON.stringify(diag.transitions), "pointerAt=", diag.pointerAt === null ? "null" : Math.round(diag.pointerAt));
  await ctx.close();
}
await browser.close();
server.close();

// d2-timeline.mjs — 观察指定产物的 AudioContext statechange 时刻（首手势前窗口）。
// 用与 qacore 相同 context 选项+探针语义；不合成手势；记录 3 轮。
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
for (let r = 0; r < rounds; r++) {
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, deviceScaleFactor: 2, serviceWorkers: "block" });
  const page = await ctx.newPage();
  await page.addInitScript(new Function(RECORDER));
  await page.addInitScript(new Function(PROBE_JS));
  await page.goto(url, { waitUntil: "load", timeout: 15000 });
  await page.waitForTimeout(5000);
  const diag = await page.evaluate(new Function("return (() => window.__diag)();"));
  const probe = await page.evaluate(new Function("return (() => window.__pfprobe.audio)();"));
  console.log(`r${r}: transitions=`, JSON.stringify(diag.transitions), "probe.audio=", JSON.stringify(probe), "pointerAt=", diag.pointerAt);
  await ctx.close();
}
await browser.close();
server.close();

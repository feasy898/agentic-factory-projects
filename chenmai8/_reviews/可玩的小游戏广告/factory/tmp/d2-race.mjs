// d2-race.mjs — 精确归因：复刻 run.ts runPass(portrait, autoplay) 完整序列，
// 页内再加 5ms 轮询时钟记录 running 翻转曲线 + pointerdown 时刻，
// 输出「judge 各次 pre-gesture 采样（judge 时钟）/ 页内翻转时刻（页面时钟）」。
import { chromium } from "playwright";
import { readFileSync } from "node:fs";
import { createServer } from "node:http";
import { basename } from "node:path";
import { PROBE_JS } from "../qacore/src/probe.ts";
import { driveAutoplay } from "../qacore/src/autoplay.ts";
import { ev } from "../qacore/src/ev.ts";

const artifact = process.argv[2];
const rounds = Number(process.argv[3] ?? 3);
const RECORDER = String.raw`(() => {
  window.__diag = { transitions: [], pointerAt: null, curve: [] };
  document.addEventListener('pointerdown', () => {
    if (window.__diag.pointerAt === null) window.__diag.pointerAt = performance.now();
  }, true);
  const wrap = (name) => {
    const Ctor = window[name];
    if (typeof Ctor !== 'function') return;
    const Wrapped = function (...args) {
      const ctx = new Ctor(...args);
      const rec = (tag) => window.__diag.transitions.push({ at: performance.now(), tag, state: ctx.state });
      rec('created:' + name);
      try { ctx.addEventListener('statechange', () => rec('statechange')); } catch (e) {}
      return ctx;
    };
    Wrapped.prototype = Ctor.prototype;
    try { Object.defineProperty(window, name, { value: Wrapped, configurable: true, writable: true }); } catch (e) {}
  };
  wrap('AudioContext');
  wrap('webkitAudioContext');
  const timer = setInterval(() => {
    const p = window.__pfprobe;
    const run = p && p.audio ? p.audio.running : null;
    const c = window.__diag.curve;
    if (c.length === 0 || c[c.length-1].running !== run) c.push({ at: performance.now(), running: run });
    if (window.__diag.stop) clearInterval(timer);
  }, 5);
})();`;

const server = createServer((req, res) => {
  res.setHeader("Content-Type", "text/html; charset=utf-8");
  res.end(readFileSync(artifact));
}).listen(0);
await new Promise((r) => server.on("listening", r));
const url = `http://127.0.0.1:${server.address().port}/${basename(artifact)}`;
const browser = await chromium.launch({ headless: true });
for (let r = 0; r < rounds; r++) {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, deviceScaleFactor: 2, serviceWorkers: "block" });
  const page = await context.newPage();
  void page.addInitScript(new Function(PROBE_JS));
  void page.addInitScript(new Function(RECORDER));
  const t0 = performance.now();
  await page.goto(url, { waitUntil: "load", timeout: 15000 });
  const loadMs = performance.now() - t0;
  await page.waitForTimeout(400);
  const facts = await driveAutoplay(page, 45);
  const diag = await ev(page, "() => window.__diag");
  // 对齐锚：judge 的 pfReadyMs 来自 probe.ready（页面时钟）。
  const anchor = { pfReadyPageMs: facts.pfReadyMs, loadJudgeMs: loadMs, gestures: facts.gestures,
                   audioPre: facts.audioRunningBeforeInteraction, pointerPageMs: diag.pointerAt,
                   transitions: diag.transitions.map((t) => ({ at: Math.round(t.at), tag: t.tag, state: t.state })),
                   curve: diag.curve.map((c) => ({ at: Math.round(c.at), running: c.running })) };
  console.log(`r${r}: ` + JSON.stringify(anchor));
  await context.close();
}
await browser.close();
server.close();

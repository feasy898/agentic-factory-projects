// d2-ws-diag.mjs — ws 变体 + 页内状态迁移记录：看 routeWebSocket 下 running 何时翻转。
import { chromium } from "playwright";
import { readFileSync } from "node:fs";
import { createServer } from "node:http";
import { basename } from "node:path";
import { PROBE_JS } from "../qacore/src/probe.ts";
import { driveAutoplay } from "../qacore/src/autoplay.ts";

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
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, deviceScaleFactor: 2, serviceWorkers: "block" });
  const page = await context.newPage();
  void page.addInitScript(new Function(PROBE_JS));
  void page.addInitScript(new Function(RECORDER));
  void page.routeWebSocket("**/*", () => {});
  await page.goto(url, { waitUntil: "load", timeout: 15000 });
  await page.waitForTimeout(400);
  const facts = await driveAutoplay(page, 45);
  const diag = await page.evaluate(new Function("return (() => window.__diag)();"));
  console.log(`r${r}: audioPre=${facts.audioRunningBeforeInteraction} gestures=${facts.gestures} pfReady=${Math.round(facts.pfReadyMs)}`);
  console.log(`   transitions=${JSON.stringify(diag.transitions)} pointerAt=${diag.pointerAt === null ? "null" : Math.round(diag.pointerAt)}`);
  await context.close();
}
await browser.close();
server.close();

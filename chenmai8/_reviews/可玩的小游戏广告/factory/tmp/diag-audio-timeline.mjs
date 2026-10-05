// 诊断脚本（非产品、非 eval）：纯观察 pullpin.html 的 AudioContext 何时变 running。
// 用与 qacore 完全相同的 context 选项与探针语义，但 **不合成任何手势**——
// 记录 pf:ready、每个 AudioContext 的 statechange 时刻（performance.now），
// 判定"首交互前"是否存在 running 上下文（页内自动解锁 vs 需真实手势）。
import { chromium } from "playwright";
import { ArtifactServer } from "../qacore/src/server.ts";
import { resolve } from "node:path";

const RECORDER = String.raw`(() => {
  window.__diag = { readyAt: null, transitions: [], pointerAt: null };
  document.addEventListener('pf:ready', () => {
    if (window.__diag.readyAt === null) window.__diag.readyAt = performance.now();
  });
  document.addEventListener('pointerdown', () => {
    if (window.__diag.pointerAt === null) window.__diag.pointerAt = performance.now();
  }, true);
  const wrap = (name) => {
    const Ctor = window[name];
    if (typeof Ctor !== 'function') return;
    const Wrapped = function (...args) {
      const ctx = new Ctor(...args);
      const rec = (tag) => window.__diag.transitions.push({
        at: Math.round(performance.now()), tag, state: ctx.state });
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

const mode = process.argv[2] ?? "node";
const rounds = Number(process.argv[3] ?? 3);
const server = new ArtifactServer(resolve("tmp/qacore-eval/templates"), 0);
await server.start();
const browser = await chromium.launch({ headless: true });
for (let r = 0; r < rounds; r++) {
  const ctx = await browser.newContext({
    viewport: { width: 390, height: 844 },
    isMobile: true,
    deviceScaleFactor: 2,
    serviceWorkers: "block",
  });
  const page = await ctx.newPage();
  await page.addInitScript(new Function(RECORDER));
  const t0 = performance.now();
  await page.goto(server.url_for("pullpin.html"), { waitUntil: "load", timeout: 15000 });
  const loadMs = Math.round(performance.now() - t0);
  await page.waitForTimeout(3000);
  const diag = await page.evaluate(new Function("return (() => window.__diag)();"));
  console.log(`[${mode} r${r}] load=${loadMs}ms readyAt=${diag.readyAt === null ? "null" : Math.round(diag.readyAt)}`);
  for (const t of diag.transitions) {
    console.log(`   at=${t.at}ms ${t.tag} state=${t.state}`);
  }
  console.log(`   pointerAt=${diag.pointerAt === null ? "null(无手势)" : Math.round(diag.pointerAt)}`);
  await ctx.close();
}
await browser.close();
await server.stop();

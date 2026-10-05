// 诊断脚本 2（非产品）：用 qacore 真实 driveAutoplay 驱动 pullpin.html，
// 同页并行跑 __diag 状态记录，对照"探针 audio.running 采样值"与
// "真实 statechange 时刻 / 首个 pointerdown 时刻"。
import { chromium } from "playwright";
import { ArtifactServer } from "../qacore/src/server.ts";
import { driveAutoplay, probeInstalled, qcTexts, qcTextStates, PROBE_JS } from "../qacore/src/autoplay.ts";
import { resolve } from "node:path";

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

const server = new ArtifactServer(resolve("tmp/qacore-eval/templates"), 0);
await server.start();
const browser = await chromium.launch({ headless: true });
const ONCE = process.argv[2] === "once";
for (let r = 0; r < (ONCE ? 1 : 4); r++) {
  const ctx = await browser.newContext({
    viewport: { width: 390, height: 844 },
    isMobile: true,
    deviceScaleFactor: 2,
    serviceWorkers: "block",
  });
  const page = await ctx.newPage();
  // 复刻 run.ts wire() 的完整顺序：listeners → init scripts → route/WS
  page.on("response", () => {});
  page.on("requestfailed", () => {});
  page.on("console", () => {});
  page.on("pageerror", () => {});
  await page.addInitScript(new Function(PROBE_JS));
  await page.addInitScript(new Function(RECORDER));
  await page.route("**/*", (route) => { void route.continue(); });
  await page.routeWebSocket("**/*", () => {});
  await page.goto(server.url_for("pullpin.html"), { waitUntil: "load", timeout: 15000 });
  await page.waitForTimeout(400);
  // 复刻 runPass 的驱动前步骤（probeInstalled + 教程期文案先采两连）
  const pi = await probeInstalled(page);
  const textsEarly = await qcTexts(page);
  const [, statesEarly] = await qcTextStates(page);
  const t0 = performance.now();
  const facts = await driveAutoplay(page, 45);
  const diag = await page.evaluate(new Function("return (() => window.__diag)();"));
  console.log(`[r${r}] audioRunPre=${facts.audioRunningBeforeInteraction} gestures=${facts.gestures} ` +
    `driveWall=${Math.round(performance.now() - t0)}ms readyMs=${facts.pfReadyMs && Math.round(facts.pfReadyMs)} ` +
    `endMs=${facts.pfEndMs && Math.round(facts.pfEndMs)}`);
  console.log(`   diag transitions=${JSON.stringify(diag.transitions)} pointerAt=${diag.pointerAt === null ? "null" : Math.round(diag.pointerAt)}`);
  await ctx.close();
}
await browser.close();
await server.stop();

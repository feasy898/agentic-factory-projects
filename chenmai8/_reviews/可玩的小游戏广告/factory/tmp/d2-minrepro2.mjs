// d2-minrepro2.mjs — 区分触发面：ws shim / 任意 initScript / probe 内容，对产物页 AudioContext 初始态。
import { chromium } from "playwright";
import { readFileSync } from "node:fs";
import { createServer } from "node:http";
import { basename } from "node:path";

const artifact = "tmp/diff/oracle-matrix/golden-match3/applovin/en/index.html";
const RECORDER = String.raw`(() => {
  window.__diag = [];
  const wrap = (name) => {
    const Ctor = window[name];
    if (typeof Ctor !== 'function') return;
    const Wrapped = function (...args) {
      const ctx = new Ctor(...args);
      window.__diag.push({ at: Math.round(performance.now()), state: ctx.state });
      return ctx;
    };
    Wrapped.prototype = Ctor.prototype;
    try { Object.defineProperty(window, name, { value: Wrapped, configurable: true, writable: true }); } catch (e) {}
  };
  wrap('AudioContext');
})();`;
const server = createServer((req, res) => { res.setHeader("Content-Type", "text/html; charset=utf-8"); res.end(readFileSync(artifact)); }).listen(0);
await new Promise((r) => server.on("listening", r));
const url = `http://127.0.0.1:${server.address().port}/${basename(artifact)}`;
const browser = await chromium.launch({ headless: true });
const variants = {
  bare: async () => {},
  ws: async (page) => { void page.routeWebSocket("**/*", () => {}); },
  plainInit: async (page) => { void page.addInitScript(new Function("(() => {})();")); },
  routeOnly: async (page) => { await page.route("**/*", (r) => void r.continue()); },
};
for (const [name, setup] of Object.entries(variants)) {
  for (let i = 0; i < 2; i++) {
    const context = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, deviceScaleFactor: 2, serviceWorkers: "block" });
    const page = await context.newPage();
    void page.addInitScript(new Function(RECORDER));
    await setup(page);
    await page.goto(url, { waitUntil: "load", timeout: 15000 });
    await page.waitForTimeout(600);
    const diag = await page.evaluate(new Function("return (() => window.__diag)();"));
    console.log(`${name} r${i}: ctxCreations=${JSON.stringify(diag)}`);
    await context.close();
  }
}
await browser.close();
server.close();

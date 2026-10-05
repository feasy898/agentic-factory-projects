// tmp 实验：qacore 同款仿真下，无手势使 AudioContext 达到 running 的策略取证（A-like 夹具设计依据）
import { createServer } from "node:http";
import { readFileSync } from "node:fs";
import { chromium } from "playwright";
import { PROBE_JS } from "../../../qacore/src/probe.ts";

const html = `<!doctype html><html><head><meta charset="utf-8"></head><body>
<script>
  window.__strats = [];
  function mk(name, fn) {
    try {
      const ac = new AudioContext();
      window.__strats.push([name, "created", ac.state]);
      fn(ac, name);
    } catch (e) { window.__strats.push([name, "ERROR", e.message]); }
  }
  // a) 构造即 resume
  mk("a-create-then-resume", (ac, n) => { ac.resume().then(() => window.__strats.push([n, "resume-resolved", ac.state]), (e) => window.__strats.push([n, "resume-rejected", String(e && e.message)])); });
  // b) Phaser onGameVisible 同款：suspend();resume() 于 100ms 定时器
  mk("b-suspend-resume-100ms", (ac, n) => { setTimeout(() => { ac.suspend(); ac.resume().then(() => window.__strats.push([n, "resume-resolved", ac.state]), (e) => window.__strats.push([n, "resume-rejected", String(e && e.message)])); }, 100); });
  // c) load 后 300ms resume
  mk("c-resume-after-load-300ms", (ac, n) => { document.addEventListener("load", () => {}, true); setTimeout(() => { ac.resume().then(() => window.__strats.push([n, "resume-resolved", ac.state]), (e) => window.__strats.push([n, "resume-rejected", String(e && e.message)])); }, 300); });
</script>
</body></html>`;

const server = createServer((req, res) => {
  res.writeHead(200, { "content-type": "text/html; charset=utf-8" });
  res.end(html);
});
await new Promise((res) => server.listen(0, "127.0.0.1", res));
const url = `http://127.0.0.1:${server.address().port}/`;

const browser = await chromium.launch({ headless: true });
for (const ctxOpts of [
  { name: "qacore-exact(isMobile)", opts: { viewport: { width: 390, height: 844 }, isMobile: true, deviceScaleFactor: 2, serviceWorkers: "block" } },
  { name: "plain-default-context", opts: {} },
]) {
  const context = await browser.newContext(ctxOpts.opts);
  const page = await context.newPage();
  void page.addInitScript(new Function(PROBE_JS));
  void page.route("**/*", (route) => void route.continue());
  await page.goto(url, { waitUntil: "load", timeout: 15000 });
  await page.waitForTimeout(1500);
  const out = await page.evaluate(() => ({
    strats: window.__strats,
    probe: window.__pfprobe ? {
      created: window.__pfprobe.audio.created,
      running: window.__pfprobe.audio.running,
      flag: window.__pfprobe.audio.everBeforeFirstGesture,
    } : null,
  }));
  console.log("==", ctxOpts.name);
  console.log("  probe:", JSON.stringify(out.probe));
  for (const s of out.strats) console.log("  strat:", JSON.stringify(s));
  await context.close();
}
await browser.close();
server.close();

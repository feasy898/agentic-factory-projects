// tmp 实验（旗子真值锚定）：qacore 同款仿真 + 现行 PROBE_JS 打开 oracle A 产物，
// 记录 AudioContext created→statechange 时间线 vs pf:ready vs 首指针时刻。
// 只读 oracle 产物（位于 factory 树内的 oracle-matrix 副本），零写入。
import { createServer } from "node:http";
import { readFileSync } from "node:fs";
import { chromium } from "playwright";
import { PROBE_JS } from "../../../qacore/src/probe.ts";

const ART = process.argv[2];
const html = readFileSync(ART);
const server = createServer((req, res) => {
  res.writeHead(200, { "content-type": "text/html; charset=utf-8" });
  res.end(html);
});
await new Promise((res) => server.listen(0, "127.0.0.1", res));
const url = `http://127.0.0.1:${server.address().port}/a.html`;

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({
  viewport: { width: 390, height: 844 }, isMobile: true, deviceScaleFactor: 2,
  serviceWorkers: "block",
});
const page = await context.newPage();
page.on("console", (m) => {
  if (m.type() === "warning" && /AudioContext/i.test(m.text())) console.log("[console]", m.text().slice(0, 120));
});
void page.addInitScript(new Function(PROBE_JS));
void page.route("**/*", (route) => void route.continue());
await page.goto(url, { waitUntil: "load", timeout: 15000 });
// 采样 12 次 × 100ms：观察 running/旗 与 pf:ready 的相对时序（全程无指针事件）
const samples = [];
for (let i = 0; i < 12; i++) {
  await page.waitForTimeout(100);
  samples.push(await page.evaluate(() => {
    const p = window.__pfprobe;
    return p ? { t: Math.round(performance.now()), created: p.audio.created,
      running: p.audio.running, flag: p.audio.everBeforeFirstGesture,
      ready: p.ready } : null;
  }));
}
console.log("artifact:", ART);
for (const s of samples) console.log(" ", JSON.stringify(s));
await browser.close();
server.close();

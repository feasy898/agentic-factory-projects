// d2-bisect.mjs — 复刻 run.ts runPass，逐项加入 wire() 组件，定位哪个组件使 audioPre 翻 1。
// 用法：node tmp/d2-bisect.mjs <artifact> <variant: base|listeners|route|ws|pre|full> [rounds]
import { chromium } from "playwright";
import { readFileSync } from "node:fs";
import { createServer } from "node:http";
import { basename } from "node:path";
import { PROBE_JS } from "../qacore/src/probe.ts";
import { driveAutoplay, probeInstalled, qcTexts, qcTextStates } from "../qacore/src/autoplay.ts";

const artifact = process.argv[2];
const variant = process.argv[3] ?? "full";
const rounds = Number(process.argv[4] ?? 2);

const server = createServer((req, res) => {
  res.setHeader("Content-Type", "text/html; charset=utf-8");
  res.end(readFileSync(artifact));
}).listen(0);
await new Promise((r) => server.on("listening", r));
const url = `http://127.0.0.1:${server.address().port}/${basename(artifact)}`;
const browser = await chromium.launch({ headless: true });
const out = [];
for (let r = 0; r < rounds; r++) {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, deviceScaleFactor: 2, serviceWorkers: "block" });
  const page = await context.newPage();
  void page.addInitScript(new Function(PROBE_JS));
  if (variant === "listeners" || variant === "full") {
    page.on("response", () => {});
    page.on("requestfailed", () => {});
    page.on("console", () => {});
    page.on("pageerror", () => {});
  }
  if (variant === "route" || variant === "full") {
    await page.route("**/*", (route) => {
      const u = route.request().url();
      if (u.endsWith("mraid.js")) {
        void route.fulfill({ status: 200, contentType: "application/javascript", body: "/* pf-qacore: 渠道容器运行时脚本本地桩（投放时由渠道容器提供，非包体内容） */\n" });
        return;
      }
      void route.continue();
    });
  }
  if (variant === "ws" || variant === "full") {
    void page.routeWebSocket("**/*", () => {});
  }
  await page.goto(url, { waitUntil: "load", timeout: 15000 });
  await page.waitForTimeout(400);
  if (variant === "pre" || variant === "full") {
    await probeInstalled(page);
    await qcTexts(page);
    await qcTextStates(page);
  }
  const facts = await driveAutoplay(page, 45);
  out.push({ r, audioPre: facts.audioRunningBeforeInteraction, gestures: facts.gestures, pfReady: facts.pfReadyMs });
  await context.close();
}
await browser.close();
server.close();
console.log(variant, JSON.stringify(out));

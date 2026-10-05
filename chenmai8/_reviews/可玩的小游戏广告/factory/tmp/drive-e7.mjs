#!/usr/bin/env node
// tmp/drive-e7.mjs — CHK04 归因二分 E7：E1 基座（无手势）+ run.ts 的真实页面包配置
// （ArtifactServer / route+abort-external+mraid-stub fulfill / routeWebSocket / console 记账 /
// addInitScript(new Function(PROBE_JS))），仅把驱动循环换成纯观测（每 100ms 读探针+激活态）。
// 若 running 无手势翻转 → 该配置本身使然；若不翻转 → 差异在驱动循环的 evaluate 形态。
// 用法：node tmp/drive-e7.mjs <artifact.html> <tag> [sec=8]

import { chromium } from "playwright";
import { readFileSync, existsSync, statSync } from "node:fs";
import { basename, dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { PROBE_JS } from "../qacore/src/probe.ts";
import { ArtifactServer } from "../qacore/src/server.ts";

const [, , artifact, tag, secArg] = process.argv;
const SEC = Number(secArg ?? 8);
const artifactAbs = resolve(artifact);

const server = new ArtifactServer(dirname(artifactAbs), 0);
await server.start();
const url = server.url_for(basename(artifactAbs));

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({
  viewport: { width: 390, height: 844 }, isMobile: true, deviceScaleFactor: 2, serviceWorkers: "block",
});
const page = await context.newPage();
await page.addInitScript(new Function(PROBE_JS));
const externals = [];
await page.route("**/*", (route) => {
  const u = route.request().url();
  let parsed;
  try { parsed = new URL(u); } catch { parsed = new URL("about:blank"); }
  const local = (parsed.hostname === "127.0.0.1" || parsed.hostname === "localhost") && parsed.port === String(server.port);
  if (!local) { externals.push(u); void route.abort(); return; }
  const name = parsed.pathname.split("/").pop();
  // mraid.js 桩（applovin 渠道 runtime 声明；本地缺失 → fulfill 桩）
  if (name === "mraid.js" && !existsSync(resolve(dirname(artifactAbs), name))) {
    void route.fulfill({ status: 200, contentType: "application/javascript", body: "/* stub */window.mraid=window.mraid||{};" });
    return;
  }
  void route.continue();
});
await page.routeWebSocket("**/*", () => {});
page.on("console", () => {});
page.on("pageerror", () => {});

await page.goto(url, { waitUntil: "load", timeout: 15000 });
await page.waitForTimeout(400);

const evl = (src) => page.evaluate(new Function(`return (${src})();`));
const samples = [];
const t0 = Date.now();
while (Date.now() - t0 < SEC * 1000) {
  const s = await evl(`() => JSON.stringify({ c: window.__pfprobe && window.__pfprobe.audio.created, r: window.__pfprobe && window.__pfprobe.audio.running, ua: !!(navigator.userActivation && navigator.userActivation.hasBeenActive), ready: window.__pfprobe && window.__pfprobe.ready })`);
  samples.push({ t: Date.now() - t0, ...JSON.parse(s) });
  await page.waitForTimeout(100);
}
const firstRun = samples.find((x) => x.r > 0);
console.log(JSON.stringify({ tag, url, externals, maxRunning: Math.max(0, ...samples.map((x) => x.r)),
  everActive: samples.some((x) => x.ua), firstRunning: firstRun ?? null, sampleCount: samples.length }, null, 1));
await browser.close();
await server.stop();

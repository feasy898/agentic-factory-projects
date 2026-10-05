#!/usr/bin/env node
// tmp/drive-replica.mjs — CHK04 归因实验 E4：逐行复刻 qacore/src/run.ts + autoplay.ts 的
// 真实驱动序列（wire(route/routeWebSocket/addInitScript(new Function(PROBE_JS)))/context 选项/
// goto/waitForTimeout(SETTLE)/驱动循环次序），仅追加逐轮采样日志（页内只读，不改变行为面）。
// 用法：node tmp/drive-replica.mjs <artifact.html> <tag> [maxSec=45]

import { chromium } from "playwright";
import { readFileSync } from "node:fs";
import { createServer } from "node:http";
import { basename } from "node:path";
import { PROBE_JS } from "../qacore/src/probe.ts";

const [, , artifact, tag, maxSecArg] = process.argv;
const MAX_SEC = Number(maxSecArg ?? 45);
const SETTLE_MS = 400;

const server = createServer((req, res) => {
  res.setHeader("Content-Type", "text/html; charset=utf-8");
  res.end(readFileSync(artifact));
}).listen(0);
await new Promise((r) => server.on("listening", r));
const url = `http://127.0.0.1:${server.address().port}/${basename(artifact)}`;

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({
  viewport: { width: 390, height: 844 }, isMobile: true, deviceScaleFactor: 2, serviceWorkers: "block",
});
const page = await context.newPage();
// 与 run.ts wire() 同一注入形态：addInitScript(new Function(PROBE_JS))
await page.addInitScript(new Function(PROBE_JS));

await page.goto(url, { waitUntil: "load", timeout: 15000 });
await page.waitForTimeout(SETTLE_MS);

const log = [];
const t0 = Date.now();
let gestures = 0;
const SWEEP = { tap: null, up: [0, -1], down: [0, 1], left: [-1, 0], right: [1, 0] };
const DRAG_DISTANCE = 80;
while (Date.now() - t0 < MAX_SEC * 1000) {
  const st = await page.evaluate(() => (window.__PF_QC__ && typeof window.__PF_QC__.state === "function") ? String(window.__PF_QC__.state()) : "loading");
  const probe = await page.evaluate(() => window.__pfprobe || null);
  const entry = {
    t: Date.now() - t0, iter: log.length + 1, gesturesBefore: gestures, state: st,
    running: probe ? probe.audio.running : null, created: probe ? probe.audio.created : null,
  };
  if (gestures === 0) log.push(entry);
  if (st === "end") break;
  const h = await page.evaluate(() => { const q = window.__PF_QC__; if (!q || typeof q.hint !== "function") return null; try { return q.hint(); } catch { return null; } });
  entry.hintType = h ? String(h.type) : null;
  if (h && typeof h.x === "number" && typeof h.y === "number") {
    const vec = SWEEP[String(h.type)] ?? null;
    await page.mouse.move(h.x, h.y);
    await page.mouse.down();
    if (vec) for (let i = 1; i <= 4; i++) await page.mouse.move(h.x + vec[0] * DRAG_DISTANCE * i / 4, h.y + vec[1] * DRAG_DISTANCE * i / 4);
    await page.mouse.up();
    gestures += 1;
    // 手势后立即复查 running（观察激活→running 的翻转延迟与计数器可见性）
    const after = await page.evaluate(() => window.__pfprobe ? window.__pfprobe.audio : null);
    log.push({ t: Date.now() - t0, iter: log.length + 1, event: "post-gesture", gestureNo: gestures, running: after.running, created: after.created });
  }
  await page.waitForTimeout(180);
}
console.log(JSON.stringify({ tag, artifact: basename(artifact), totalGestures: gestures, preGestureSamples: log }, null, 1));
await browser.close();
server.close();

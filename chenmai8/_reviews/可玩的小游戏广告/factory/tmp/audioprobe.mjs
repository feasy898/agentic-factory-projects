#!/usr/bin/env node
// tmp/audioprobe.mjs — CHK04 差异归因实验（差分专用，非产品代码）。
// 载入产物 HTML + 冻结 PROBE_JS（qacore/src/probe.ts 原文注入），不派发任何手势，
// 每 200ms 采样 __pfprobe.audio（created/running），持续 12s，输出翻转时间线。
// 目的：判定 oracle 产物在冻结探针下是否于首手势前出现 running AudioContext（引擎
// +100ms suspend→resume 特性），以及 factory 产物（noAudio）是否恒 0。
//
// 用法：node tmp/audioprobe.mjs <artifact.html> <tag> [sampleSec=12]

import { chromium } from "playwright";
import { readFileSync } from "node:fs";
import { createServer } from "node:http";
import { dirname, join, basename, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const [, , artifact, tag, secArg] = process.argv;
const SAMPLE_SEC = Number(secArg ?? 12);
// PROBE_JS：与 qacore 运行时同一冻结文本（从源码模块原文 import）
const { PROBE_JS } = await import(new URL("../qacore/src/probe.ts", import.meta.url).href);

const server = createServer((req, res) => {
  const data = readFileSync(artifact);
  res.setHeader("Content-Type", "text/html; charset=utf-8");
  res.end(data);
}).listen(0);
await new Promise((r) => server.on("listening", r));
const url = `http://127.0.0.1:${server.address().port}/${basename(artifact)}`;

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({
  viewport: { width: 390, height: 844 }, isMobile: true, deviceScaleFactor: 2, serviceWorkers: "block",
});
const page = await context.newPage();
await page.addInitScript(PROBE_JS);
await page.goto(url, { waitUntil: "load", timeout: 30000 });

const timeline = [];
const t0 = Date.now();
while (Date.now() - t0 < SAMPLE_SEC * 1000) {
  const s = await page.evaluate(() => {
    const p = window.__pfprobe;
    return p ? { created: p.audio.created, running: p.audio.running, ready: p.ready } : null;
  });
  timeline.push({ t: Date.now() - t0, ...s });
  await page.waitForTimeout(200);
}
const flips = timeline.filter((x, i) => i > 0 && x.running !== timeline[i - 1].running);
console.log(JSON.stringify({ tag, artifact: basename(artifact), probeChars: PROBE_JS.length,
  first: timeline[0], last: timeline[timeline.length - 1],
  maxRunning: Math.max(...timeline.map((x) => x.running || 0)),
  flips: flips.slice(0, 6),
  createdAt: timeline.find((x) => x.created > 0)?.t ?? null,
  runningAt: timeline.find((x) => x.running > 0)?.t ?? null,
}, null, 1));
await browser.close();
server.close();

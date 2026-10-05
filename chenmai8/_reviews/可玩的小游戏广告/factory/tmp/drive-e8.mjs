#!/usr/bin/env node
// tmp/drive-e8.mjs — CHK04 归因 E8：E7 页面包 + 真实 qacore 助手函数逐个调用（无手势），
// 每步之间读探针（created/running/userActivation），把翻转钉到具体调用。
// 用法：node tmp/drive-e8.mjs <artifact.html> <tag> [watchSec=6]

import { chromium } from "playwright";
import { existsSync } from "node:fs";
import { basename, dirname, resolve } from "node:path";
import { PROBE_JS } from "../qacore/src/probe.ts";
import { ArtifactServer } from "../qacore/src/server.ts";
import * as A from "../qacore/src/autoplay.ts";

const [, , artifact, tag, secArg] = process.argv;
const WATCH = Number(secArg ?? 6);
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
await page.route("**/*", (route) => {
  const u = route.request().url();
  let parsed; try { parsed = new URL(u); } catch { parsed = new URL("about:blank"); }
  const local = (parsed.hostname === "127.0.0.1" || parsed.hostname === "localhost") && parsed.port === String(server.port);
  if (!local) { void route.abort(); return; }
  const name = parsed.pathname.split("/").pop();
  if (name === "mraid.js" && !existsSync(resolve(dirname(artifactAbs), name))) {
    void route.fulfill({ status: 200, contentType: "application/javascript", body: A.CONTAINER_STUB_JS });
    return;
  }
  void route.continue();
});
await page.routeWebSocket("**/*", () => {});

await page.goto(url, { waitUntil: "load", timeout: 15000 });
await page.waitForTimeout(400);

const read = () => page.evaluate(new Function(`return (() => JSON.stringify({ c: window.__pfprobe && window.__pfprobe.audio.created, r: window.__pfprobe && window.__pfprobe.audio.running, ua: !!(navigator.userActivation && navigator.userActivation.hasBeenActive) }))();`)).then((s) => JSON.parse(s));
const steps = [];
async function step(label, fn) {
  const before = await read();
  let out = null;
  try { out = fn ? await fn() : null; } catch (e) { out = "ERR:" + e.message; }
  const after = await read();
  steps.push({ label, before, after, out: Array.isArray(out) ? `list[${out.length}]` : (typeof out === "string" ? String(out).slice(0, 40) : out) });
  return out;
}
await step("probeInstalled", () => A.probeInstalled(page));
await step("qcTexts", () => A.qcTexts(page));
await step("qcTextStates", () => A.qcTextStates(page));
await step("hasQcHooks+hasPf", () => A.hasPf(page));
await step("state", () => A.state(page));
await step("qcTextStates#2", () => A.qcTextStates(page));
await step("readProbe", () => page.evaluate(new Function(`return (() => window.__pfprobe || null)();`)));
await step("pfMuted", () => A.pfMuted(page));
await step("mediaSample", () => A.mediaSample(page));
await step("hint", () => page.evaluate(new Function(`return (() => { const q = window.__PF_QC__; if (!q || typeof q.hint !== 'function') return null; try { return q.hint(); } catch (e) { return null; } })();`)));
// 无手势挂机观察
const t0 = Date.now();
while (Date.now() - t0 < WATCH * 1000) {
  steps.push({ label: "watch", ...(await read()) });
  await page.waitForTimeout(200);
}
console.log(JSON.stringify({ tag, steps }, null, 1));
await browser.close();
await server.stop();

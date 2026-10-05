// tmp 实验：逐字复刻 runPass 非 autoplay 读序列（goto→settle400→等桥(字符串/真函数)→
// mediaSample→pfMuted→旗→audioRunning），取证 CLI 读到 0 的时刻差
import { createServer } from "node:http";
import { readFileSync } from "node:fs";
import { chromium } from "playwright";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { PROBE_JS } from "../../../qacore/src/probe.ts";

const FIXTURE = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..",
  "qacore", "tests", "fixtures", "audio-a-like.html");
const html = readFileSync(FIXTURE);
const server = createServer((req, res) => {
  res.writeHead(200, { "content-type": "text/html; charset=utf-8" });
  res.end(html);
});
await new Promise((res) => server.listen(0, "127.0.0.1", res));
const url = `http://127.0.0.1:${server.address().port}/a.html`;

const ev = (page, src) => page.evaluate(new Function(`return (${src})();`));

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({
  viewport: { width: 390, height: 844 }, isMobile: true, deviceScaleFactor: 2,
  serviceWorkers: "block",
});
const page = await context.newPage();
void page.addInitScript(new Function(PROBE_JS));
void page.route("**/*", (route) => void route.continue());
const t0 = Date.now();
await page.goto(url, { waitUntil: "load", timeout: 15000 });
console.log("load done at", Date.now() - t0, "ms");
await page.waitForTimeout(400);
console.log("settle done at", Date.now() - t0, "ms");

const t1 = Date.now();
await page.waitForFunction("() => !!(window.PF && typeof PF.isMuted === 'function')", null, { timeout: 5000 }).catch(() => {});
console.log("string waitForFunction:", Date.now() - t1, "ms");

const flag = await ev(page, "() => { const p = window.__pfprobe; return p && p.audio ? p.audio.everBeforeFirstGesture === true : null; }");
const running = await ev(page, "() => { const p = window.__pfprobe; return p && p.audio ? p.audio.running : null; }");
const created = await ev(page, "() => window.__pfprobe.audio.created");
const now = await ev(page, "() => Math.round(performance.now())");
console.log("at page-t", now, "ms: flag=", flag, "running=", running, "created=", created);

// 等到翻转后再读一次
await page.waitForTimeout(500);
console.log("at page-t", await ev(page, "() => Math.round(performance.now())"), "ms: flag=",
  await ev(page, "() => window.__pfprobe.audio.everBeforeFirstGesture"),
  "running=", await ev(page, "() => window.__pfprobe.audio.running"));

await browser.close();
server.close();

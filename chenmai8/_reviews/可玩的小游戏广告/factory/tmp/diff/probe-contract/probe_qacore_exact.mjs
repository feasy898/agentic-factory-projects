// tmp 实验：qacore 同款上下文（viewport/isMobile/DPR2/serviceWorkers block/route/WS 拦截/
// addInitScript(PROBE_JS)）伺服 A-like 夹具，读旗取证
import { createServer } from "node:http";
import { readFileSync } from "node:fs";
import { chromium } from "playwright";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { PROBE_JS } from "../../../qacore/src/probe.ts";

const FIXTURE = join(dirname(fileURLToPath(import.meta.url)),
  "..", "..", "..", "qacore", "tests", "fixtures", "audio-a-like.html");
const html = readFileSync(FIXTURE);

const server = createServer((req, res) => {
  res.writeHead(200, { "content-type": "text/html; charset=utf-8" });
  res.end(html);
});
await new Promise((res) => server.listen(0, "127.0.0.1", res));
const port = server.address().port;
const url = `http://127.0.0.1:${port}/audio-a-like.html`;

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({
  viewport: { width: 390, height: 844 },
  isMobile: true,
  deviceScaleFactor: 2,
  serviceWorkers: "block",
});
const page = await context.newPage();
page.on("console", (m) => console.log("[console]", m.type(), m.text().slice(0, 160)));
page.on("pageerror", (e) => console.log("[pageerror]", e.message.slice(0, 160)));
page.on("requestfailed", (r) => console.log("[reqfail]", r.url(), r.failure()?.errorText));
void page.addInitScript(new Function(PROBE_JS) );
void page.route("**/*", (route) => void route.continue());

await page.goto(url, { waitUntil: "load", timeout: 15000 });
await page.waitForTimeout(1200);

const snap = await page.evaluate(() => {
  const p = window.__pfprobe;
  return {
    typeofAudioContext: typeof window.AudioContext,
    acIsWrapped: String(window.AudioContext).includes("Wrapped") || !/native code/.test(String(window.AudioContext)),
    probe: p ? {
      created: p.audio.created,
      running: p.audio.running,
      flag: p.audio.everBeforeFirstGesture,
    } : null,
    pfBridge: !!(window.PF && typeof window.PF.isMuted === "function"),
  };
});
console.log(JSON.stringify(snap, null, 2));

await browser.close();
server.close();

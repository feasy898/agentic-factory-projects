// tmp 实验：解析期创建（suspended）→ load 后 100ms resume() 是否确定性翻转 running
import { createServer } from "node:http";
import { chromium } from "playwright";
import { PROBE_JS } from "../../../qacore/src/probe.ts";

const html = `<!doctype html><html><head><meta charset="utf-8"></head><body>
<script>
  window.__log = [];
  const ac = new AudioContext();
  window.__log.push(["parse-time create", ac.state]);
  window.addEventListener("load", function () {
    setTimeout(function () {
      window.__log.push(["pre-resume", ac.state]);
      ac.resume().then(function () { window.__log.push(["resume-resolved", ac.state]); },
                       function (e) { window.__log.push(["resume-rejected", String(e && e.message).slice(0, 80)]); });
    }, 100);
  });
</script>
</body></html>`;
const server = createServer((req, res) => {
  res.writeHead(200, { "content-type": "text/html; charset=utf-8" });
  res.end(html);
});
await new Promise((res) => server.listen(0, "127.0.0.1", res));
const url = `http://127.0.0.1:${server.address().port}/`;

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({
  viewport: { width: 390, height: 844 }, isMobile: true, deviceScaleFactor: 2,
  serviceWorkers: "block",
});
const page = await context.newPage();
void page.addInitScript(new Function(PROBE_JS));
void page.route("**/*", (route) => void route.continue());
await page.goto(url, { waitUntil: "load", timeout: 15000 });
await page.waitForTimeout(1200);
console.log(JSON.stringify(await page.evaluate(() => ({
  log: window.__log,
  probe: { created: window.__pfprobe.audio.created, running: window.__pfprobe.audio.running,
           flag: window.__pfprobe.audio.everBeforeFirstGesture },
}))));
await browser.close();
server.close();

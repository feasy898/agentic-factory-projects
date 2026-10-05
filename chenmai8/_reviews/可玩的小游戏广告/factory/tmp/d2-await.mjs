// d2-await.mjs — 验证：await routeWebSocket（武装完成后再 goto）是否消除 AudioContext 翻转。
import { readFileSync } from "node:fs";
import { chromium } from "playwright";
import { createServer } from "node:http";
const html = readFileSync("tmp/diff/oracle-matrix/golden-match3/applovin/en/index.html", "utf8");
const RECORDER = `(() => { window.__diag = []; const wrap=(name)=>{const C=window[name];if(typeof C!=='function')return;const W=function(...a){const c=new C(...a);window.__diag.push({at:Math.round(performance.now()),state:c.state});return c;};W.prototype=C.prototype;try{Object.defineProperty(window,name,{value:W,configurable:true,writable:true})}catch(e){}};wrap('AudioContext');})();`;
const server = createServer((q, s) => { s.setHeader("Content-Type", "text/html; charset=utf-8"); s.end(html); }).listen(0);
await new Promise((r) => server.on("listening", r));
const url = `http://127.0.0.1:${server.address().port}/index.html`;
const browser = await chromium.launch({ headless: true });
for (let i = 0; i < 4; i++) {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, deviceScaleFactor: 2, serviceWorkers: "block" });
  const page = await context.newPage();
  void page.addInitScript(new Function(RECORDER));
  await page.routeWebSocket("**/*", () => {});   // 关键：await 武装完成
  await page.goto(url, { waitUntil: "load", timeout: 15000 });
  await page.waitForTimeout(400);
  const diag = await page.evaluate(() => window.__diag);
  const mock = await page.evaluate(() => typeof window.__pwWebSocketDispatch);
  console.log(`await-ws r${i}: ${JSON.stringify(diag)} dispatch=${mock}`);
  await context.close();
}
await browser.close();
server.close();

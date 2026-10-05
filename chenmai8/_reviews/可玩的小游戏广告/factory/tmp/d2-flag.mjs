// d2-flag.mjs — 验证 --autoplay-policy 启动旗标能否中和 node routeWebSocket 的 AudioContext 副作用。
import { chromium } from "playwright";
import { readFileSync } from "node:fs";
import { createServer } from "node:http";
const html = readFileSync("tmp/diff/oracle-matrix/golden-match3/applovin/en/index.html", "utf8");
const RECORDER = `(() => { window.__diag = []; const wrap=(name)=>{const C=window[name];if(typeof C!=='function')return;const W=function(...a){const c=new C(...a);window.__diag.push({at:Math.round(performance.now()),state:c.state});return c;};W.prototype=C.prototype;try{Object.defineProperty(window,name,{value:W,configurable:true,writable:true})}catch(e){}};wrap('AudioContext');})();`;
const server = createServer((q, s) => { s.setHeader("Content-Type", "text/html; charset=utf-8"); s.end(html); }).listen(0);
await new Promise((r) => server.on("listening", r));
const url = `http://127.0.0.1:${server.address().port}/index.html`;
const variants = [
  ["default", []],
  ["user-gesture-required", ["--autoplay-policy=user-gesture-required"]],
  ["document-user-activation-required", ["--autoplay-policy=document-user-activation-required"]],
];
for (const [name, args] of variants) {
  const browser = await chromium.launch({ headless: true, args });
  for (let i = 0; i < 2; i++) {
    const context = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, deviceScaleFactor: 2, serviceWorkers: "block" });
    const page = await context.newPage();
    void page.addInitScript(new Function(RECORDER));
    void page.routeWebSocket("**/*", () => {});
    await page.goto(url, { waitUntil: "load", timeout: 15000 });
    await page.waitForTimeout(500);
    const diag = await page.evaluate(() => window.__diag);
    console.log(`${name} r${i}: ${JSON.stringify(diag)}`);
    await context.close();
  }
  await browser.close();
}
await server.close();

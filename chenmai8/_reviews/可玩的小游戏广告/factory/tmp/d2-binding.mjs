// d2-binding.mjs — 分解 routeWebSocket 的注入面：exposeBinding 单独是否翻转 AudioContext 初始态。
import { chromium } from "playwright";
import { readFileSync } from "node:fs";
import { createServer } from "node:http";
const html = readFileSync("tmp/diff/oracle-matrix/golden-match3/applovin/en/index.html", "utf8");
const RECORDER = `(() => { window.__diag = []; const wrap=(name)=>{const C=window[name];if(typeof C!=='function')return;const W=function(...a){const c=new C(...a);window.__diag.push({at:Math.round(performance.now()),state:c.state});return c;};W.prototype=C.prototype;try{Object.defineProperty(window,name,{value:W,configurable:true,writable:true})}catch(e){}};wrap('AudioContext');})();`;
const server = createServer((q, s) => { s.setHeader("Content-Type", "text/html; charset=utf-8"); s.end(html); }).listen(0);
await new Promise((r) => server.on("listening", r));
const browser = await chromium.launch({ headless: true });
const variants = {
  binding: async (ctx) => { await ctx.exposeBinding("__d2probe", () => {}); },
  bindingPage: async (ctx, page) => { await page.exposeBinding("__d2probe2", () => {}); },
  initFuncOnly: async (ctx, page) => { void page.addInitScript(() => {}); },
};
for (const [name, setup] of Object.entries(variants)) {
  for (let i = 0; i < 2; i++) {
    const context = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, deviceScaleFactor: 2, serviceWorkers: "block" });
    const page = await context.newPage();
    void page.addInitScript(new Function(RECORDER));
    await setup(context, page);
    await page.goto(`http://127.0.0.1:${server.address().port}/index.html`, { waitUntil: "load" });
    await page.waitForTimeout(400);
    const diag = await page.evaluate(() => window.__diag);
    console.log(`${name} r${i}: ${JSON.stringify(diag)}`);
    await context.close();
  }
}
await browser.close();
server.close();

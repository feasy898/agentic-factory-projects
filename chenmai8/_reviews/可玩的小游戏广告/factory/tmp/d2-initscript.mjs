// d2-initscript.mjs — 归因收窄：是 mock 源本身还是“会抛错的 init script”翻转 AudioContext？
import { readFileSync } from "node:fs";
import { chromium } from "playwright";
import { createServer } from "node:http";

// 与 playwright-core 生成的 webSocketMockSource 相同形态的最小 mock 源（会抛 TypeError）：
// (inject())(globalThis) —— inject() 返回 undefined，undefined(globalThis) 抛错。
const THROWING_MOCK = `
(() => {
  const module = {};
  module.exports = { inject: function (globalThis2) {
    if (globalThis2.__pwWebSocketDispatch) return;
    const NativeWebSocket = globalThis2.WebSocket;
    globalThis2.__pwWebSocketDispatch = (request) => {};
    globalThis2.WebSocket = class WebSocket extends EventTarget {};
  } };
  (module.exports.inject())(globalThis);
})();
`;
const NO_THROW_MOCK = THROWING_MOCK.replace("(module.exports.inject())(globalThis);", "module.exports.inject()(globalThis);");

const html = readFileSync("tmp/diff/oracle-matrix/golden-match3/applovin/en/index.html", "utf8");
const RECORDER = `(() => { window.__diag = []; const wrap=(name)=>{const C=window[name];if(typeof C!=='function')return;const W=function(...a){const c=new C(...a);window.__diag.push({at:Math.round(performance.now()),state:c.state});return c;};W.prototype=C.prototype;try{Object.defineProperty(window,name,{value:W,configurable:true,writable:true})}catch(e){}};wrap('AudioContext');})();`;
const server = createServer((q, s) => { s.setHeader("Content-Type", "text/html; charset=utf-8"); s.end(html); }).listen(0);
await new Promise((r) => server.on("listening", r));
const url = `http://127.0.0.1:${server.address().port}/index.html`;
const browser = await chromium.launch({ headless: true });
const variants = {
  throwingMock: async (page) => { void page.addInitScript(THROWING_MOCK); },
  noThrowMock: async (page) => { void page.addInitScript(NO_THROW_MOCK); },
};
for (const [name, setup] of Object.entries(variants)) {
  for (let i = 0; i < 2; i++) {
    const context = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, deviceScaleFactor: 2, serviceWorkers: "block" });
    const page = await context.newPage();
    void page.addInitScript(new Function(RECORDER));
    await setup(page);
    await page.goto(url, { waitUntil: "load", timeout: 15000 });
    await page.waitForTimeout(400);
    const diag = await page.evaluate(() => window.__diag);
    const wsState = await page.evaluate(() => ({ mocked: typeof window.__pwWebSocketDispatch }));
    console.log(`${name} r${i}: ${JSON.stringify(diag)} dispatch=${wsState.mocked}`);
    await context.close();
  }
}
await browser.close();
server.close();

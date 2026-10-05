// d2-cdp.mjs — 记录 routeWebSocket 注册后 playwright 注入的脚本与 CDP 调用面。
import { chromium } from "playwright";
import { readFileSync } from "node:fs";
import { createServer } from "node:http";
const html = readFileSync("tmp/diff/oracle-matrix/golden-match3/applovin/en/index.html", "utf8");
const RECORDER = `(() => { window.__diag = []; const wrap=(name)=>{const C=window[name];if(typeof C!=='function')return;const W=function(...a){const c=new C(...a);window.__diag.push({at:Math.round(performance.now()),state:c.state});return c;};W.prototype=C.prototype;try{Object.defineProperty(window,name,{value:W,configurable:true,writable:true})}catch(e){}};wrap('AudioContext');})();`;
const server = createServer((q, s) => { s.setHeader("Content-Type", "text/html; charset=utf-8"); s.end(html); }).listen(0);
await new Promise((r) => server.on("listening", r));
const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, deviceScaleFactor: 2, serviceWorkers: "block" });
const page = await context.newPage();
const cdp = await context.newCDPSession(page);
const cdpCalls = [];
cdp.on("send", (m) => cdpCalls.push({ dir: "send", method: m.method, params: JSON.stringify(m.params ?? {}).slice(0, 300) }));
cdp.on("message", (m) => cdpCalls.push({ dir: "recv", method: m.method ?? "", params: JSON.stringify(m.params ?? m.result ?? {}).slice(0, 200) }));
void page.addInitScript(new Function(RECORDER));
void page.routeWebSocket("**/*", () => {});
await page.goto(`http://127.0.0.1:${server.address().port}/index.html`, { waitUntil: "load" });
await page.waitForTimeout(500);
console.log("myCDP calls around ws:", JSON.stringify(cdpCalls.filter(c => /Script|Emulation|Network|Binding|WebSocket|Audio|Media|Autoplay/i.test(c.method + c.params)), null, 1).slice(0, 3000));
// 直接查 window.WebSocket 是否被 mock、__pwWebSocketDispatch 是否在
const probe = await page.evaluate(() => ({
  wsIsMock: String(window.WebSocket).includes("WebSocketMock") || !window.WebSocket.toString().includes("[native code]"),
  wsSrc: String(window.WebSocket).slice(0, 120),
  hasDispatch: typeof window.__pwWebSocketDispatch,
  hasBinding: typeof window.__pwWebSocketBinding,
  diag: window.__diag,
}));
console.log("probe:", JSON.stringify(probe, null, 1));
await browser.close();
server.close();

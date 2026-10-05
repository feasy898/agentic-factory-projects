// d2-cdp-capture.mjs — 抓取 node playwright 在「产物页 + ws 拦截」下的完整 CDP 命令序列。
import { readFileSync, writeFileSync } from "node:fs";
import { chromium } from "playwright";
import { createServer } from "node:http";

const html = readFileSync("tmp/diff/oracle-matrix/golden-match3/applovin/en/index.html", "utf8");
const server = createServer((q, s) => { s.setHeader("Content-Type", "text/html; charset=utf-8"); s.end(html); }).listen(0);
await new Promise((r) => server.on("listening", r));
const url = `http://127.0.0.1:${server.address().port}/index.html`;

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, deviceScaleFactor: 2, serviceWorkers: "block" });
const page = await context.newPage();
void page.routeWebSocket("**/*", () => {});
await page.goto(url, { waitUntil: "load", timeout: 15000 });
await page.waitForTimeout(600);
const probe = await page.evaluate(() => ({
  wsMocked: typeof window.__pwWebSocketDispatch,
  binding: typeof window.__pwWebSocketBinding,
}));
console.log("probe:", JSON.stringify(probe));
await browser.close();
server.close();

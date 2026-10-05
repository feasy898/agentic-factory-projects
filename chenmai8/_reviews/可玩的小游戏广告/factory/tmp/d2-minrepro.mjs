// d2-minrepro.mjs — 最小复现：routeWebSocket 注册与 AudioContext 初始 state 的关系（node 侧）。
import { chromium } from "playwright";
const browser = await chromium.launch({ headless: true });
for (const variant of ["none", "ws", "route"]) {
  for (let i = 0; i < 2; i++) {
    const context = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, deviceScaleFactor: 2, serviceWorkers: "block" });
    const page = await context.newPage();
    if (variant === "ws") void page.routeWebSocket("**/*", () => {});
    if (variant === "route") await page.route("**/*", (r) => void r.continue());
    await page.goto("about:blank");
    const st = await page.evaluate(() => new AudioContext().state);
    console.log(`node variant=${variant} r${i}: AudioContext.state=${st}`);
    await context.close();
  }
}
await browser.close();

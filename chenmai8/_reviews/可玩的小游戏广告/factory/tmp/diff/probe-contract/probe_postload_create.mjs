// tmp 实验：http 产物页上"load 后创建 AudioContext"是否免手势达到 running（A-like 夹具路径）
import { createServer } from "node:http";
import { chromium } from "playwright";

const html = `<!doctype html><html><head><meta charset="utf-8"></head><body>ok</body></html>`;
const server = createServer((req, res) => {
  res.writeHead(200, { "content-type": "text/html; charset=utf-8" });
  res.end(html);
});
await new Promise((res) => server.listen(0, "127.0.0.1", res));
const url = `http://127.0.0.1:${server.address().port}/`;

const browser = await chromium.launch({ headless: true });
for (const name of ["qacore-exact(isMobile)", "plain-default"]) {
  const context = await browser.newContext(...(name.startsWith("qacore")
    ? [{ viewport: { width: 390, height: 844 }, isMobile: true, deviceScaleFactor: 2, serviceWorkers: "block" }]
    : [{}]));
  const page = await context.newPage();
  await page.goto(url, { waitUntil: "load", timeout: 15000 });
  const r = await page.evaluate(async () => {
    const out = [];
    const ac1 = new AudioContext();
    out.push(["post-load create", ac1.state]);
    const ac2 = new AudioContext();
    const p = ac2.resume();
    const raced = await Promise.race([p.then(() => "resolved", (e) => "rejected"),
      new Promise((res) => setTimeout(() => res("pending>1500"), 1500))]);
    out.push(["post-load create+resume", ac2.state, raced]);
    return out;
  });
  console.log("==", name, JSON.stringify(r));
  await context.close();
}
await browser.close();
server.close();

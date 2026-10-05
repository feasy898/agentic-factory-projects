// tmp 实验：AudioContext 在该 chromium 构造/suspend/resume 行为逐项取证
import { chromium } from "playwright";

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage();
page.on("console", (m) => console.log("[console]", m.type(), m.text()));
page.on("pageerror", (e) => console.log("[pageerror]", e.message));

await page.goto("about:blank");
const r = await page.evaluate(async () => {
  const out = { typeofAC: typeof AudioContext, steps: [] };
  try {
    const ac = new AudioContext();
    out.steps.push(["constructed", ac.state]);
    const p = ac.resume();
    out.steps.push(["resume() called", ac.state]);
    const racing = await Promise.race([p.then(() => "resolved", (e) => "rejected:" + e.message),
      new Promise((res) => setTimeout(() => res("pending>3000ms"), 3000))]);
    out.steps.push(["resume promise", racing, ac.state]);
    await new Promise((res) => setTimeout(res, 300));
    out.steps.push(["after 300ms", ac.state]);
    out.sampleRate = ac.sampleRate;
  } catch (e) {
    out.steps.push(["ERROR", e.message]);
  }
  return out;
});
console.log(JSON.stringify(r, null, 2));
await browser.close();

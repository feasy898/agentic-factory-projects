// tmp 实验脚本（不动产品树）：直连 playwright 验证
//  1) 字符串页函数在 waitForFunction 的表达式语义（CLI-B 等桥等待失效根因）
//  2) AudioContext 无手势时 resume() 是否翻转 running（A-like 旗机制前提）
import { chromium } from "playwright";

const A_URL = "file:///" + process.argv[1].replace(/\\/g, "/");

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage();
await page.addInitScript(new Function(String.raw`
(() => {
  const probe = { audio: { created: 0, running: 0, everBeforeFirstGesture: false }, timeline: [] };
  window.__pfprobe = probe;
  let firstGestureAt = null;
  document.addEventListener('pointerdown', () => {
    if (firstGestureAt === null) firstGestureAt = performance.now();
  }, true);
  const running = new Set();
  const wrap = (name) => {
    const Ctor = window[name];
    if (typeof Ctor !== 'function') return;
    const Wrapped = function (...args) {
      const ctx = new Ctor(...args);
      probe.audio.created += 1;
      probe.timeline.push([performance.now(), 'constructed', ctx.state]);
      const upd = () => {
        if (ctx.state === 'running') {
          running.add(ctx);
          if (firstGestureAt === null) probe.audio.everBeforeFirstGesture = true;
          probe.timeline.push([performance.now(), 'running', 'flag=' + probe.audio.everBeforeFirstGesture]);
        } else {
          running.delete(ctx);
          probe.timeline.push([performance.now(), 'state:' + ctx.state]);
        }
        probe.audio.running = running.size;
      };
      try { if (ctx.addEventListener) ctx.addEventListener('statechange', upd); } catch (e) {}
      upd();
      return ctx;
    };
    Wrapped.prototype = Ctor.prototype;
    try { Object.defineProperty(window, name, { value: Wrapped, configurable: true, writable: true }); } catch (e) {}
  };
  wrap('AudioContext');
  wrap('webkitAudioContext');
})();
`));

await page.goto(A_URL, { waitUntil: "load", timeout: 15000 });

// 实验1：字符串 "() => X" 作为 waitForFunction 页函数 —— 表达式语义下返回函数对象（truthy）
const t0 = Date.now();
await page.waitForFunction("() => !!(window.PF && typeof PF.isMuted === 'function')", null, { timeout: 5000 }).catch(() => {});
console.log("string-arrow waitForFunction resolved in", Date.now() - t0, "ms (no PF bridge on this page -> immediate resolve proves expression-truthy bug)");

// 实验1b：真函数语义
const t1 = Date.now();
await page.waitForFunction(() => !!(window.PF && typeof window.PF.isMuted === "function"), null, { timeout: 3000 }).catch(() => {});
console.log("real-fn waitForFunction resolved in", Date.now() - t1, "ms (expect ~3000 timeout, no bridge on fixture)");

// 实验2：等待音频状态演化后读旗与时间线
await page.waitForTimeout(1500);
const state = await page.evaluate(() => ({
  created: window.__pfprobe.audio.created,
  running: window.__pfprobe.audio.running,
  flag: window.__pfprobe.audio.everBeforeFirstGesture,
  timeline: window.__pfprobe.timeline,
}));
console.log("audio probe:", JSON.stringify(state));

await browser.close();

// tmp/hook.cjs — 观测用 preload：直接 require('playwright') 并包装 chromium.launch→
// newContext→newPage，记录 mouse/evaluate/addInitScript 时序到 PF_TRACE_OUT（只读观测）。
// Node 的 --require 先于 ESM 加载执行；CJS exports 对象被 ESM 具名导入透传，补丁对
// qacore 的 `import { chromium } from "playwright"` 生效。
const fs = require("fs");
const path = require("path");
const t0Global = Date.now();
try {
  const pw = require("playwright");
  const chrom = pw.chromium;
  const origLaunch = chrom.launch.bind(chrom);
  chrom.launch = async (...a) => {
    const b = await origLaunch(...a);
    const origNewCtx = b.newContext.bind(b);
    b.newContext = async (...c) => {
      const ctx = await origNewCtx(...c);
      const origNewPage = ctx.newPage.bind(ctx);
      ctx.newPage = async (...d) => {
        const p = await origNewPage(...d);
        const t0 = Date.now();
        const log = (globalThis.__PFTRACE = globalThis.__PFTRACE || []);
        for (const k of ["move", "down", "up", "click"]) {
          const f = p.mouse[k].bind(p.mouse);
          p.mouse[k] = async (...e) => {
            log.push({ t: Date.now() - t0, ev: "mouse." + k });
            return f(...e);
          };
        }
        const origEval = p.evaluate.bind(p);
        let n = 0;
        p.evaluate = (fn, ...e) => {
          const rec = { t: Date.now() - t0, ev: "evaluate", src: (() => { try { return String(fn).slice(0, 100).replace(/\s+/g, " "); } catch { return "?"; } })() };
          const r = origEval(fn, ...e);
          if (n++ < 500) {
            log.push(rec);
            Promise.resolve(r).then(
              (v) => { rec.val = typeof v === "object" && v !== null ? JSON.stringify(v).slice(0, 120) : v; },
              (err) => { rec.err = String(err).slice(0, 120); });
          }
          return r;
        };
        const origInit = p.addInitScript.bind(p);
        p.addInitScript = (s) => {
          log.push({ t: Date.now() - t0, ev: "addInitScript", kind: typeof s });
          return origInit(s);
        };
        // 附加页内审计：每 50ms 记录 userActivation / AudioContext running 翻转时刻（只读）。
        origInit(`(() => {
          const a = (window.__PFAUDIT = { samples: [] });
          const tick = () => {
            const ua = navigator.userActivation || {};
            const probe = window.__pfprobe;
            a.samples.push({
              t: Math.round(performance.now()),
              hasBeenActive: !!ua.hasBeenActive,
              isActive: !!ua.isActive,
              created: probe ? probe.audio.created : null,
              running: probe ? probe.audio.running : null,
              vis: document.visibilityState,
            });
            if (a.samples.length < 1200) setTimeout(tick, 50);
          };
          tick();
        })();`);
        return p;
      };
      return ctx;
    };
    return b;
  };
} catch (e) {
  console.error("[hook] patch failed:", e.message);
}
process.on("exit", () => {
  if (globalThis.__PFTRACE && process.env.PF_TRACE_OUT) {
    fs.writeFileSync(process.env.PF_TRACE_OUT, JSON.stringify(globalThis.__PFTRACE, null, 1));
  }
});

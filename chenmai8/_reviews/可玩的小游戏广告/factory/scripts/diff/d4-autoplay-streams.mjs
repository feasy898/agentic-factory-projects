#!/usr/bin/env node
// scripts/diff/d4-autoplay-streams.mjs — 差分维度 F4：自动试玩行为流对比（任务 D-2①）。
//
// 设 O=oracle 实现（repo 冻结模板 build.mjs + 冻结 packager bin.mjs 出的产物），
//    N=新实现（factory 同链路产物）。四模板（match3/merge/pullpin/sort）各取
//    3 个 seed（seed 变体先经 双实现 validate 同判受理：golden 基准 seed+1..+k 中
//    取前 3 个两侧 validate 都 exit 0 的），同 seed 出双实现产物，再以同一
//    「驱动复刻器」跑真实 pointer 自动试玩，采集事件流：
//      pf:ready → pf:start → pf:first-interaction → [手势序列] → pf:end{win,gestures}
// 判等（任务给定）：
//   硬线 1 胜负必等：pf:end 的 endWin 两侧严格相等；
//   硬线 2 手势数 ±1 容差：|gestures_N - gestures_O| ≤ 1；
//   硬线 3 事件链等价：两侧 ready/start/first/end 全部触发，且各侧按时间排序的
//          相对次序两侧一致（次序具体形态由模板决定，判两侧同序）；
//   登记 4 手势序列结构：按 (type,x,y) 连续重复折叠后逐元素全等（掉手抖动吸收）；
//          不等 → 按回归登记（不静默）。
// 纪律：oracle 只读（其构建/打包 CLI 以子进程调用，产物写 factory/tmp）；驱动语义与
// 两判官 driveAutoplay 相同（SWEEP_VECTORS/DRAG_DISTANCE=44/180ms 轮询/45s 预算），
// 同一宿主同一驱动跑两侧产物，消除驱动侧时序差；同一 (模板,seed) 的失败允许对称
// 单重试一次（两侧同跑，两次全留痕，与 crossqc 抖动口径一致）。
//
// 用法：node scripts/diff/d4-autoplay-streams.mjs [jobs=1]
// 退出码：0 全格等价；1 有回归级不等；2 用法/环境错误。
// 证据：tmp/diff/d4-autoplay/（逐流 JSON + evidence）→ 汇总 artifacts/diff/d4-autoplay-streams.json。

import { spawn, spawnSync } from "node:child_process";
import { copyFileSync, existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import process from "node:process";

import { chromium } from "playwright";

import { PROBE_JS } from "../../qacore/src/probe.ts";

const FACTORY = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
const ORACLE = resolve(FACTORY, "..", "repo");
const JOBS = Math.max(1, Math.min(4, Number(process.argv[2] ?? 1)));

const WORK = join(FACTORY, "tmp", "diff", "d4-autoplay");
const STREAMS = join(WORK, "streams");
const BUILD = join(WORK, "build");
const SPEC_DIR = join(WORK, "specs");
const TEMPLATES = ["match3", "merge", "pullpin", "sort"];
const SEEDS_PER_TEMPLATE = 3;
const LOCALE = "en";
const CHANNEL = "preview";
const GOTO_TIMEOUT_MS = 15_000;
const SETTLE_MS = 400;
const LOOP_WAIT_MS = 180;
const AUTOPLAY_TIMEOUT_SEC = 45;
const DRAG_DISTANCE = 44.0;
const SWEEP_VECTORS = {
  "swap-left": [-1.0, 0.0],
  "swap-right": [1.0, 0.0],
  "swap-up": [0.0, -1.0],
  "swap-down": [0.0, 1.0],
  "drag": [1.0, 0.0],
  "tap": null,
};

const TEMPLATE_BUILDER = (root, t) => join(root, "packages", "templates", `tmpl-${t}`, "build.mjs");
const PACKAGER_BIN = (root) => join(root, "packages", "packager", "bin.mjs");

function runSync(cmd, opts = {}) {
  const r = spawnSync(cmd[0], cmd.slice(1), {
    encoding: "utf8", windowsHide: true, cwd: opts.cwd ?? FACTORY,
    env: opts.env ?? process.env, timeout: (opts.timeoutSec ?? 180) * 1000,
    maxBuffer: 64 * 1024 * 1024,
  });
  return { exit: r.status, stdout: r.stdout ?? "", stderr: r.stderr ?? "" };
}

// ---------------------------------------------------------------- seed 变体（双 validate 受理）
function deriveSpecs() {
  mkdirSync(SPEC_DIR, { recursive: true });
  const out = [];
  for (const t of TEMPLATES) {
    const baseSpec = join(FACTORY, "specs-eval", `golden-${t}.json`);
    const base = JSON.parse(readFileSync(baseSpec, "utf8"));
    const baseSeed = Number(base.meta?.seed);
    if (!Number.isInteger(baseSeed) || baseSeed <= 0) throw new Error(`golden-${t}.json meta.seed 缺失`);
    const chosen = [];
    for (let k = 1; chosen.length < SEEDS_PER_TEMPLATE && k <= 80; k++) {
      const seed = baseSeed + k;
      if (seed > 0x7fffffff) break;
      const specPath = join(SPEC_DIR, `golden-${t}-seed${seed}.json`);
      const spec = JSON.parse(JSON.stringify(base));
      spec.meta.seed = seed;
      writeFileSync(specPath, JSON.stringify(spec, null, 2) + "\n", "utf8");
      // 双实现 validate 同判受理（都 0 才收；任一拒绝=不可解/非法盘面，换下一候选）
      const n = runSync([process.execPath, join(FACTORY, "pf", "pf.mjs"), "validate", specPath], { cwd: FACTORY });
      const o = runSync([join(ORACLE, "python", ".venv", "Scripts", "python.exe"), "-m", "pfcore", "validate", specPath],
        { cwd: ORACLE, env: { ...process.env, PYTHONUTF8: "1" } });
      const accepted = n.exit === 0 && o.exit === 0;
      console.log(`  [seed] ${t} seed=${seed} validate N=${n.exit} O=${o.exit}${accepted ? " 受理" : " 跳过"}`);
      if (accepted) chosen.push({ seed, specPath });
    }
    if (chosen.length < SEEDS_PER_TEMPLATE) throw new Error(`golden-${t}: 只受理 ${chosen.length}/3 个 seed 变体`);
    for (const c of chosen) out.push({ template: t, ...c });
  }
  return out;
}

// ---------------------------------------------------------------- 双实现产物构建
function buildProducts(cells) {
  for (const c of cells) {
    const id = `${c.template}-seed${c.seed}`;
    for (const [side, root] of [["N", FACTORY], ["O", ORACLE]]) {
      const outRoot = join(BUILD, side, id);
      rmSync(outRoot, { recursive: true, force: true });
      mkdirSync(outRoot, { recursive: true });
      const previewHtml = join(outRoot, "preview-src.html");
      const b = runSync(["node", TEMPLATE_BUILDER(root, c.template), "--spec", c.specPath, "--locale", LOCALE, "--out", previewHtml],
        { cwd: root });
      if (b.exit !== 0 || !existsSync(previewHtml)) {
        throw new Error(`模板构建失败 ${side}/${id}: exit=${b.exit} ${b.stderr.slice(0, 300)}`);
      }
      const distLocale = join(outRoot, c.template === "match3" ? "golden-match3" : `golden-${c.template}`, "dist", LOCALE);
      mkdirSync(distLocale, { recursive: true });
      copyFileSync(previewHtml, join(distLocale, "index.html"));
      const dist = dirname(distLocale);
      const p = runSync(["node", PACKAGER_BIN(root), "build", "--spec", c.specPath, "--dist", dist,
        "--channel", CHANNEL, "--locale", LOCALE, "--out", outRoot], { cwd: root });
      const project = JSON.parse(readFileSync(c.specPath, "utf8")).meta.projectId;
      const artifact = join(outRoot, project, CHANNEL, LOCALE, "index.html");
      if (p.exit !== 0 || !existsSync(artifact)) {
        throw new Error(`打包失败 ${side}/${id}: exit=${p.exit} ${p.stderr.slice(0, 300)}`);
      }
      c.artifact ??= {};
      c.artifact[side] = artifact;
    }
  }
}

// ---------------------------------------------------------------- 驱动复刻器（与两判官 driveAutoplay 同语义 + 事件流记录）
async function driveStream(artifact) {
  const server = (await import("node:http")).createServer((req, res) => {
    res.setHeader("Content-Type", "text/html; charset=utf-8");
    res.end(readFileSync(artifact));
  }).listen(0);
  await new Promise((r) => server.on("listening", r));
  const url = `http://127.0.0.1:${server.address().port}/index.html`;
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 390, height: 844 }, isMobile: true, deviceScaleFactor: 2, serviceWorkers: "block",
  });
  const page = await context.newPage();
  // 与修复后判官 run.ts wire 同序：武装 await 完成后再 goto（QC-02 竞态教训）。
  await page.addInitScript(new Function(PROBE_JS));
  await page.route("**/*", (route) => {
    let parsed;
    try { parsed = new URL(route.request().url()); } catch { parsed = new URL("about:blank"); }
    const local = (parsed.hostname === "127.0.0.1" || parsed.hostname === "localhost")
      && parsed.port === String(server.address().port);
    if (!local) { void route.abort(); return; }
    void route.continue();
  });
  await page.routeWebSocket("**/*", () => {});
  const t0 = Date.now();
  await page.goto(url, { waitUntil: "load", timeout: GOTO_TIMEOUT_MS });
  await page.waitForTimeout(SETTLE_MS);

  const ev = (src) => page.evaluate(new Function(`return (${src})();`));
  const gestures = [];
  let finalState = "loading";
  const deadline = t0 + Math.max(1.0, AUTOPLAY_TIMEOUT_SEC) * 1000;
  while (Date.now() < deadline) {
    const st = await ev("() => (window.__PF_QC__ && typeof window.__PF_QC__.state === 'function')"
      + " ? String(window.__PF_QC__.state()) : 'loading'");
    finalState = st;
    if (st === "end") break;
    let h = null;
    try {
      h = await ev("() => { const q = window.__PF_QC__;"
        + " if (!q || typeof q.hint !== 'function') return null;"
        + " try { return q.hint(); } catch (e) { return null; } }");
    } catch { h = null; }
    if (h !== null && typeof h === "object" && typeof h.x === "number" && typeof h.y === "number") {
      const type = typeof h.type === "string" ? h.type : "tap";
      gestures.push({ i: gestures.length + 1, t: Date.now() - t0, stateBefore: st, type, x: h.x, y: h.y });
      const vec = SWEEP_VECTORS[type] ?? null;
      await page.mouse.move(h.x, h.y);
      await page.mouse.down();
      if (vec) {
        for (let i = 1; i <= 4; i++) {
          await page.mouse.move(h.x + vec[0] * DRAG_DISTANCE * i / 4, h.y + vec[1] * DRAG_DISTANCE * i / 4);
        }
      }
      await page.mouse.up();
    }
    await page.waitForTimeout(LOOP_WAIT_MS);
  }
  const probe = (await ev("() => window.__pfprobe || null")) ?? {};
  let endScreenVisible = null;
  try {
    endScreenVisible = Boolean(await ev("() => (window.__PF_QC__ && typeof window.__PF_QC__.endScreenVisible === 'function')"
      + " ? !!window.__PF_QC__.endScreenVisible() : null"));
  } catch { endScreenVisible = null; }
  const stream = {
    artifact: artifact.split(/[\\/]/).slice(-4).join("/"),
    pfEvents: {
      ready: probe.ready ?? null, start: probe.start ?? null, first: probe.first ?? null,
      cta: probe.cta ?? null, end: probe.end ?? null, endWin: probe.endWin ?? null,
    },
    gesturesCount: gestures.length,
    gestures,
    finalState,
    endScreenVisible,
    wallSec: Math.round((Date.now() - t0) / 100) / 10,
  };
  await context.close();
  await browser.close();
  await new Promise((r) => server.close(r));
  return stream;
}

// ---------------------------------------------------------------- 判等
function collapse(seq) {
  const out = [];
  for (const g of seq) {
    const prev = out[out.length - 1];
    if (prev && prev.type === g.type && prev.x === g.x && prev.y === g.y) continue;
    out.push({ type: g.type, x: g.x, y: g.y });
  }
  return out;
}

function judgePair(o, n) {
  // 事件链判等（决策 §3.2 F4「事件序 ready→start→first→end 等价」）：四事件双侧
  // 全触发，且各侧按时间戳排序后的相对次序两侧一致（模板实际次序由模板决定——
  // 实测 match3 为 ready→first→start→end，教程交互先于正式开局——判等不看具体
  // 次序，只看两侧同序）。
  const chainOf = (s) => {
    const e = s.pfEvents;
    const items = [["ready", e.ready], ["first", e.first], ["start", e.start], ["end", e.end]];
    const present = items.every(([, v]) => typeof v === "number");
    const order = items.slice().sort((a, b) => a[1] - b[1]).map(([k]) => k);
    return { present, order };
  };
  const co = chainOf(o), cn = chainOf(n);
  const findings = [];
  if (!co.present || !cn.present) findings.push("事件链缺失（ready/start/first/end 任一未触发）");
  else if (JSON.stringify(co.order) !== JSON.stringify(cn.order)) {
    findings.push(`事件链次序不等：O=${co.order.join("<")} N=${cn.order.join("<")}`);
  }
  const winEq = o.pfEvents.endWin === n.pfEvents.endWin;
  if (!winEq) findings.push(`胜负不等：O=${o.pfEvents.endWin} N=${n.pfEvents.endWin}`);
  const delta = Math.abs(o.gesturesCount - n.gesturesCount);
  if (delta > 1) findings.push(`手势数超 ±1 容差：O=${o.gesturesCount} N=${n.gesturesCount}（Δ=${delta}）`);
  const oSeq = collapse(o.gestures), nSeq = collapse(n.gestures);
  const seqEq = JSON.stringify(oSeq) === JSON.stringify(nSeq);
  if (!seqEq) findings.push(`折叠手势序列不等：O ${oSeq.length} 步 vs N ${nSeq.length} 步（首个分歧 index=${
    oSeq.findIndex((g, i) => !nSeq[i] || nSeq[i].type !== g.type || nSeq[i].x !== g.x || nSeq[i].y !== g.y)})`);
  return {
    winEq, delta, seqEq,
    chainOk: co.present && cn.present && JSON.stringify(co.order) === JSON.stringify(cn.order),
    findings,
  };
}

// ---------------------------------------------------------------- 主流程
console.log(`d4-autoplay-streams: 4 模板 × ${SEEDS_PER_TEMPLATE} seed × {O,N}，jobs=${JOBS}（驱动=复刻器，同语义同宿主）`);
mkdirSync(STREAMS, { recursive: true });
mkdirSync(dirname(join(FACTORY, "artifacts", "diff", "x")), { recursive: true });
const t0 = Date.now();

const cells = deriveSpecs();
console.log(`d4: seed 变体受理 ${cells.length} 格（每模板 ${SEEDS_PER_TEMPLATE}）`);
buildProducts(cells);
console.log("d4: 双实现产物构建完成");

// 驱动（jobs 并发池，缺省 1 串行——行为流对负载敏感）
let next = 0;
const runRecords = new Map();
async function lane() {
  while (next < cells.length) {
    const c = cells[next++];
    const id = `${c.template}-seed${c.seed}`;
    const attempts = [];
    for (let attempt = 1; attempt <= 2; attempt++) {
      const o = await driveStream(c.artifact.O);
      const n = await driveStream(c.artifact.N);
      const judged = judgePair(o, n);
      attempts.push({ attempt, o, n, judged });
      const streamDir = join(STREAMS, id);
      mkdirSync(streamDir, { recursive: true });
      writeFileSync(join(streamDir, `O-a${attempt}.json`), JSON.stringify(o, null, 1) + "\n", "utf8");
      writeFileSync(join(streamDir, `N-a${attempt}.json`), JSON.stringify(n, null, 1) + "\n", "utf8");
      console.log(`  [drive] ${id} a${attempt}: O gestures=${o.gesturesCount} win=${o.pfEvents.endWin} end=${o.pfEvents.end === null ? "未触发" : Math.round(o.pfEvents.end) + "ms"}`
        + ` | N gestures=${n.gesturesCount} win=${n.pfEvents.endWin} end=${n.pfEvents.end === null ? "未触发" : Math.round(n.pfEvents.end) + "ms"}`
        + ` | Δ=${judged.delta} winEq=${judged.winEq} seqEq=${judged.seqEq}${judged.findings.length ? " ✗" + judged.findings[0] : ""}`);
      if (judged.findings.length === 0) break;
      console.log(`  [retry] ${id} 对称单重试（两侧同跑，抖动口径）`);
    }
    runRecords.set(id, { cell: id, template: c.template, seed: c.seed, attempts });
  }
}
await Promise.all(Array.from({ length: JOBS }, lane));

// ---------------------------------------------------------------- 汇总
const perCell = [...runRecords.values()].map((rec) => {
  const last = rec.attempts[rec.attempts.length - 1];
  return {
    cell: rec.cell, template: rec.template, seed: rec.seed,
    attempts: rec.attempts.map((a) => ({
      attempt: a.attempt,
      o: { win: a.o.pfEvents.endWin, gestures: a.o.gesturesCount, end: a.o.pfEvents.end, ready: a.o.pfEvents.ready, finalState: a.o.finalState },
      n: { win: a.n.pfEvents.endWin, gestures: a.n.gesturesCount, end: a.n.pfEvents.end, ready: a.n.pfEvents.ready, finalState: a.n.finalState },
      delta: a.judged.delta, winEq: a.judged.winEq, seqEq: a.judged.seqEq, chainOk: a.judged.chainOk,
      findings: a.judged.findings,
    })),
    verdict: last.judged.findings.length === 0 ? "equal" : "regression",
    retried: rec.attempts.length > 1,
  };
});
const regressions = perCell.filter((c) => c.verdict !== "equal");
const evidence = {
  capturedAt: new Date().toISOString(),
  method: {
    driver: "复刻器（与两判官 driveAutoplay 同手势语义：SWEEP_VECTORS/DRAG_DISTANCE=44/180ms 轮询/45s 预算），同一 node 宿主跑两侧产物",
    arming: "addInitScript(PROBE_JS)+route+routeWebSocket 均 await 后 goto（QC-02 竞态修复后语义）",
    products: "每 (模板,seed) 双实现产物 = 各自冻结模板 build.mjs + 冻结 packager bin.mjs（e2e-matrix 同链路），oracle 仓只读",
    seeds: "golden 基准 seed+1..+k 中取前 3 个双实现 validate 同判受理的变体（不可解盘面被两侧一致拒绝）",
    criteria: "硬线：胜负必等 / 手势数 ±1 / ready、first、start、end 全触发且两侧相对次序一致；折叠手势序列全等（不等=回归登记）",
    retry: "同格失败对称单重试一次（两侧同跑，两次全留痕）",
  },
  wallSec: Math.round((Date.now() - t0) / 100) / 10,
  totals: { cells: perCell.length, equal: perCell.length - regressions.length, regressions: regressions.length, retried: perCell.filter((c) => c.retried).length },
  perCell,
  verdict: regressions.length === 0 ? "PASS（行为流等价）" : "FAIL（存在回归）",
};
writeFileSync(join(WORK, "d4-evidence.json"), JSON.stringify(evidence, null, 2) + "\n", "utf8");
writeFileSync(join(FACTORY, "artifacts", "diff", "d4-autoplay-streams.json"), JSON.stringify(evidence, null, 2) + "\n", "utf8");
console.log(`d4-autoplay-streams: cells=${perCell.length} equal=${evidence.totals.equal} regressions=${regressions.length} retried=${evidence.totals.retried} wall=${evidence.wallSec}s`);
for (const r of regressions) {
  const f = r.attempts[r.attempts.length - 1].findings;
  console.error(`  回归 ${r.cell}: ${f.join("；")}`);
}
console.log(`d4-autoplay-streams: ${evidence.verdict}`);
process.exit(regressions.length === 0 ? 0 : 1);

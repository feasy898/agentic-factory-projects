#!/usr/bin/env node
// gate-m3.mjs — 批次 3 出口门（差分终审门；决策 §5 批次 3 出口门 + 任务 D-2②）。
// 用法：node scripts/gate-m3.mjs （或 npm run gate:m3）。全过 exit 0；任一门项失败 exit 1。
//
// 门项（差分终审）：
//   1/4 GATE-M1 回归：node scripts/gate-m1.mjs → exit 0（批次 1 三包冻结测试 + 资产 sha）
//   2/4 GATE-M2 回归：node scripts/gate-m2.mjs → exit 0（批次 2 四模板 logic/autoplay
//                     + 全量 48 包矩阵 + 中性名；含 M1 全量回归）
//   3/4 差分报告：docs/diff/differential-report.json 存在、summary.regressions==0
//                     （零回归=D 硬线无违反）、summary.pass==true、ledger 与 summary 一致；
//                     且任务 D-2① 行为流差分证据 artifacts/diff/d4-autoplay-streams.json
//                     存在：verdict PASS（4 模板 × 3 seed 全格等价，胜负必等、手势数 ±1）
//   4/4 中性名扫描：入库树零上游名命中（与 gate-m1/m2 共用 scripts/lib/neutral-scan.mjs）
//
// 纪律（AGENTS.md）：eval 真实执行 exit 0 才算过；skip 不算过；本脚本只跑断言不修改任何产物。

import { spawnSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const M1_TIMEOUT_MS = 600_000;      // gate-m1 历史 ~4min + 余量
const M2_TIMEOUT_MS = 2_400_000;    // gate-m2（内含 48 包矩阵 ≤1200s 预算）历史 ~22min + 余量

// ---------------------------------------------------------------- 门禁框架（与 gate-m1/m2 同形）
let gateFailed = false;

function mark(ok, text) {
  console.log(`  [${ok ? "PASS" : "FAIL"}] ${text}`);
  if (!ok) gateFailed = true;
}

async function gateItem(idx, total, label, run) {
  console.log(`\n[${idx}/${total}] ${label}`);
  const t0 = Date.now();
  const r = run();
  if (r && typeof r.then === "function") await r;
  console.log(`  （本门项 ${((Date.now() - t0) / 1000).toFixed(1)}s）`);
}

function runNode(args, { cwd = ROOT, timeout = 600_000 } = {}) {
  const r = spawnSync(process.execPath, args, { cwd, encoding: "utf8", timeout, maxBuffer: 128 * 1024 * 1024 });
  if (r.error) return { status: null, stdout: r.stdout ?? "", stderr: String(r.error) };
  return { status: r.status, stdout: r.stdout ?? "", stderr: r.stderr ?? "" };
}

function assertRan(ok, label, r) {
  mark(ok, `${label}：exit ${r.status}（0=过）`);
  if (r.status !== 0 && r.stderr.trim()) {
    for (const line of r.stderr.trim().split(/\r?\n/).slice(0, 5)) mark(false, `stderr: ${line}`);
  }
}

// ---------------------------------------------------------------- 1/4 GATE-M1 回归
function gateM1() {
  const r = runNode(["scripts/gate-m1.mjs"], { timeout: M1_TIMEOUT_MS });
  assertRan(r.status === 0, "gate-m1.mjs（批次 1 出口门全量子进程回归）", r);
  const passLine = r.stdout.match(/GATE-M1: PASS（(\d+)\/(\d+) 门项全绿/);
  mark(Boolean(passLine) && Number(passLine[1]) === 5,
    `GATE-M1 横幅对账：5/5 门项全绿（实际 ${passLine ? `${passLine[1]}/${passLine[2]}` : "横幅缺失"}）`);
}

// ---------------------------------------------------------------- 2/4 GATE-M2 回归
function gateM2() {
  const r = runNode(["scripts/gate-m2.mjs"], { timeout: M2_TIMEOUT_MS });
  assertRan(r.status === 0, "gate-m2.mjs（批次 2 出口门全量子进程回归：logic/autoplay + 48 包矩阵）", r);
  const passLine = r.stdout.match(/GATE-M2: PASS（(\d+)\/(\d+) 门项全绿/);
  mark(Boolean(passLine) && Number(passLine[1]) === 4,
    `GATE-M2 横幅对账：4/4 门项全绿（实际 ${passLine ? `${passLine[1]}/${passLine[2]}` : "横幅缺失"}）`);
  // 48 包矩阵规模双重对账（数字不看口号）。
  const gridLine = r.stdout.match(/summary totals：pass=(\d+)\/fail=(\d+)\/skip=(\d+)/);
  mark(Boolean(gridLine) && Number(gridLine[1]) === 48 && Number(gridLine[2]) === 0 && Number(gridLine[3]) === 0,
    `矩阵 totals 对账：48/0/0（实际 ${gridLine ? `${gridLine[1]}/${gridLine[2]}/${gridLine[3]}` : "行缺失"}）`);
}

// ---------------------------------------------------------------- 3/4 差分报告（零回归）+ D-2① 行为流证据
function gateDiffReport() {
  const reportPath = join(ROOT, "docs", "diff", "differential-report.json");
  if (!existsSync(reportPath)) {
    mark(false, `差分报告缺失：${reportPath}（先跑 node scripts/diff/assemble-report.mjs）`);
    return;
  }
  let report = null;
  try {
    report = JSON.parse(readFileSync(reportPath, "utf8"));
  } catch (err) {
    mark(false, `差分报告不可解析：${String(err)}`);
    return;
  }
  mark(true, `差分报告存在：docs/diff/differential-report.json（生成于 ${report.generatedAt ?? "??"}）`);

  const summary = report.summary ?? {};
  const ledger = Array.isArray(report.ledger) ? report.ledger : null;
  const ledgerRegressions = ledger ? ledger.filter((l) => l.classification === "regression") : null;
  mark(summary.regressions === 0 && summary.pass === true,
    `差分 summary 零回归：regressions=${summary.regressions} pass=${summary.pass}（应 0/true）`);
  mark(Array.isArray(ledgerRegressions) && ledgerRegressions.length === (summary.regressions ?? -1),
    `台账与 summary 一致：ledger regression 分类 ${ledgerRegressions ? ledgerRegressions.length : "缺"} 项`
    + ` = summary.regressions=${summary.regressions}`);
  for (const l of ledgerRegressions ?? []) mark(false, `  回归条目：${l.id}（${l.dimension}）`);
  // 关键维度证据在位（F1/D1 校验裁定、F4 行为流、F7 退出码）。
  const byId = new Set((ledger ?? []).map((l) => l.id));
  mark(byId.has("M1-01"), "F1/D1 校验裁定差分条目在位（M1-01）");
  mark(byId.has("D2-01"), "F4/D-2① 行为流差分条目在位（D2-01）");
  mark(byId.has("CLI-A") && byId.has("CLI-B"), "F7 退出码差分条目在位（CLI-A/CLI-B）");

  // D-2① 行为流证据：4 模板 × 3 seed 全格等价。
  const d4Path = join(ROOT, "artifacts", "diff", "d4-autoplay-streams.json");
  if (!existsSync(d4Path)) {
    mark(false, `行为流差分证据缺失：${d4Path}（先跑 node scripts/diff/d4-autoplay-streams.mjs）`);
    return;
  }
  let d4 = null;
  try {
    d4 = JSON.parse(readFileSync(d4Path, "utf8"));
  } catch (err) {
    mark(false, `行为流证据不可解析：${String(err)}`);
    return;
  }
  const totals = d4.totals ?? {};
  mark(typeof d4.verdict === "string" && d4.verdict.startsWith("PASS")
    && totals.cells === 12 && totals.equal === 12 && totals.regressions === 0,
    `行为流差分（4 模板 × 3 seed）：verdict=${d4.verdict} cells=${totals.cells} equal=${totals.equal}`
    + ` regressions=${totals.regressions}（应 PASS/12/12/0；胜负必等 + 手势数 ±1 + 事件链有序 + 折叠序列全等）`);
  for (const c of (d4.perCell ?? []).filter((c) => c.verdict !== "equal")) {
    mark(false, `  行为流不等格：${c.cell}`);
  }
}

// ---------------------------------------------------------------- 4/4 中性名扫描
async function gateNeutralNames() {
  const { scanNeutralNames } = await import("./lib/neutral-scan.mjs");
  const r = scanNeutralNames(ROOT);
  if (r.wordlistMissing) {
    mark(false, r.hits[0] ?? "词表缺失");
    return;
  }
  mark(r.ok, `扫描 ${r.scanned} 个入库文件（共 ${r.fileCount}）× ${r.words} 词（大小写不敏感子串，路径+内容）：命中 ${r.hits.length} 处`);
  for (const h of r.hits.slice(0, 10)) mark(false, `命中：${h}`);
  if (r.hits.length > 10) mark(false, `……另有 ${r.hits.length - 10} 处（只报告不修改——改名/声明问题不碰，法务裁定）`);
}

// ---------------------------------------------------------------- 主流程
async function main() {
  const t0 = Date.now();
  console.log("=".repeat(72));
  console.log("批次 3 出口门（gate-m3 · 差分终审门）：M1/M2 回归 + 差分报告零回归 + 行为流差分 + 中性名");
  console.log(`仓库根   : ${ROOT}`);
  console.log(`Node     : ${process.version}`);
  console.log(`启动时刻 : ${new Date().toISOString()}`);
  console.log("=".repeat(72));

  await gateItem(1, 4, "GATE-M1 回归（批次 1 出口门全量子进程）", gateM1);
  await gateItem(2, 4, "GATE-M2 回归（批次 2 出口门全量子进程，含 48 包矩阵）", gateM2);
  await gateItem(3, 4, "差分报告零回归 + D-2① 行为流差分证据（4×3 全等）", gateDiffReport);
  await gateItem(4, 4, "中性名扫描（入库树零上游名命中）", gateNeutralNames);

  const secs = ((Date.now() - t0) / 1000).toFixed(1);
  console.log(`\n${"=".repeat(72)}`);
  if (gateFailed) {
    console.log(`GATE-M3: FAIL（存在 FAIL 门项，墙钟 ${secs}s）`);
    console.log("批次 3 出口门不通过：差分终审存在回归或证据缺失；不得静默放宽断言。");
    process.exitCode = 1;
  } else {
    console.log(`GATE-M3: PASS（4/4 门项全绿，墙钟 ${secs}s）`);
    console.log("批次 3 出口门通过：M1/M2 全量回归绿 + 差分报告零回归 + 四模板×3 seed 行为流等价 + 中性名零命中。");
  }
}

main();

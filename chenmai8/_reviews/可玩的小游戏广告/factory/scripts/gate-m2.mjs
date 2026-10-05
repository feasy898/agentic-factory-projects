#!/usr/bin/env node
// gate-m2.mjs — 批次 2 出口门（决策 §5 批次 2；D5/D6 承载体 + 批次 1 回归 + 法务红线）。
// 用法：node scripts/gate-m2.mjs （或 npm run gate:m2）。全过 exit 0；任一门项失败 exit 1。
//
// 门项（与开发任务 M2.3 一致）：
//   1/4 批次 1 三包回归：node scripts/gate-m1.mjs → exit 0（spec/bridge/packager 冻结测试
//                       全量 + 数据资产 sha 清单复验，GATE-M1: PASS 横幅对账）
//   2/4 四模板 logic+autoplay：四包冻结 logic-test 数值向量（字节复用 eval）真实执行
//                       + 判官本器四模板 --autoplay 复验（qacore/tests/templates.test.mjs，
//                       pf:end ≤45s、结束页可见、CHK10 demo-zh 实装层）+ 判官/编排 tsc strict
//   3/4 全量 48 包矩阵：node scripts/e2e-matrix.mjs --budget-sec 1200 → exit 0
//                       （4 golden × {en,zh} × 6 冻结渠道 = 4×2×6 = 48 包全部真实
//                       构建→打包→逐包质检，决策硬预算 ≤1200s）+ 读
//                       artifacts/matrix/summary.json 双重对账：totals={pass:48,fail:0,skip:0}
//                       /mode=full/wallSec≤1200（同 oracle gate_phase2 门项 4 口径）
//   4/4 中性名扫描：入库树（git ls-files）路径+内容对仓外词表大小写不敏感子串零命中
//                       （与 gate-m1 共用 scripts/lib/neutral-scan.mjs，防两份漂移）
//
// 纪律（AGENTS.md）：eval 真实执行 exit 0 才算过；skip 不算过；本脚本只跑断言不修改任何产物；
// 首检 FAIL 的格由 e2e-matrix 全量的抖动单重试吸收（同一判官重跑一次，两跑皆 FAIL 仍 FAIL）。

import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const TSC = join(ROOT, "node_modules", "typescript", "bin", "tsc");
const E2E_EXPECT_PASS = 48;
const E2E_BUDGET_SEC = 1200.0;
const SUBGATE_TIMEOUT_MS = 2_400_000; // gate-m1 三包冻结测试全量（历史 ~4min）+ 余量
const E2E_TIMEOUT_MS = 1_800_000;     // e2e 预算 1200s + 余量（同 oracle gate_phase2）

// ---------------------------------------------------------------- 门禁框架（与 gate-m1 同形）
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

function tapSummary(out) {
  const grab = (re) => {
    const m = out.match(re);
    return m ? Number(m[1]) : null;
  };
  return {
    tests: grab(/^# tests (\d+)/m),
    pass: grab(/^# pass (\d+)/m),
    fail: grab(/^# fail (\d+)/m),
  };
}

function assertRan(ok, label, r) {
  mark(ok, `${label}：exit ${r.status}（0=过）`);
  if (r.status !== 0 && r.stderr.trim()) {
    for (const line of r.stderr.trim().split(/\r?\n/).slice(0, 5)) mark(false, `stderr: ${line}`);
  }
}

// ---------------------------------------------------------------- 1/4 批次 1 三包回归
function gateBatch1Regression() {
  const r = runNode(["scripts/gate-m1.mjs"], { timeout: SUBGATE_TIMEOUT_MS });
  assertRan(r.status === 0, "gate-m1.mjs（批次 1 出口门全量子进程回归）", r);
  const passLine = r.stdout.match(/GATE-M1: PASS（(\d+)\/(\d+) 门项全绿/);
  mark(Boolean(passLine) && Number(passLine[1]) === 5,
    `GATE-M1 横幅对账：5/5 门项全绿（实际 ${passLine ? `${passLine[1]}/${passLine[2]}` : "横幅缺失"}）`);
  // 三包冻结测试规模逐包钉死（缩水即回归）：spec 21+ / bridge 26 / packager 46+12。
  mark((r.stdout.match(/\[PASS\] ajv-check\.mjs（冻结 eval 原样）/) ?? []).length === 1,
    "spec 冻结 ajv-check 在位（D1 前置）");
  mark(/冻结用例数钉死 26\/26\/0/.test(r.stdout), "bridge 冻结 26 用例在位（D3）");
  mark(/冻结断言数钉死 46 全过/.test(r.stdout), "packager 冻结 46 断言在位（D2）");
}

// ---------------------------------------------------------------- 2/4 四模板 logic+autoplay
const LOGIC_TESTS = [
  "packages/templates/tmpl-match3/tests/logic-test.ts",
  "packages/templates/tmpl-merge/tests/logic-test.ts",
  "packages/templates/tmpl-pullpin/tests/logic-test.ts",
  "packages/templates/tmpl-sort/tests/logic-test.ts",
];

function gateTemplates() {
  // 2a. 四模板冻结 logic-test 数值向量（F6 承载体之一；字节复用 eval 原样执行）。
  const t = runNode(["--test", ...LOGIC_TESTS]);
  assertRan(t.status === 0, `node --test 四模板 logic-test.ts（冻结数值向量 ${LOGIC_TESTS.length} 件）`, t);
  const s = tapSummary(t.stdout);
  mark(s.fail === 0 && s.tests === LOGIC_TESTS.length && s.pass === LOGIC_TESTS.length,
    `逻辑层用例全过：pass=${s.pass} fail=${s.fail} tests=${s.tests}（每模板 1 件，钉死 ${LOGIC_TESTS.length}——缩水即差分失败）`);

  // 2b. 判官本器四模板 --autoplay 复验（D5 前置：本判官×本模板全绿；含 CHK10 demo-zh 实装层）。
  const a = runNode(["--test", "qacore/tests/templates.test.mjs"], { timeout: 900_000 });
  assertRan(a.status === 0, "node --test qacore/tests/templates.test.mjs（四模板 autoplay 复验）", a);
  const sa = tapSummary(a.stdout);
  mark(sa.fail === 0 && sa.tests === 5 && sa.pass === 5,
    `autoplay 用例全过：pass=${sa.pass} fail=${sa.fail} tests=${sa.tests}（M2.2 基线钉死 5 = 四模板 + CHK10 demo-zh 实装层）`);

  // 2c. 判官/编排 tsc strict（双交付纪律：两模块类型层零漂移）。
  for (const proj of ["qacore", "pf"]) {
    const ts = runNode([TSC, "--noEmit", "-p", proj]);
    assertRan(ts.status === 0, `tsc --noEmit -p ${proj}（strict）`, ts);
  }
}

// ---------------------------------------------------------------- 3/4 全量 48 包矩阵
function gateMatrix() {
  // --jobs 2（登记）：本机为多代理共享（windev-01 常驻多个 ZCode/协同进程，实测
  // 2026-09-30 多核 100%）。jobs=4（oracle 缺省）时 4 路 chromium 并发把冻结的 CHK09
  // 本地加载墙钟顶破（load_ms 3.4-8.4s vs 阈值 2.0s，pf.readyMs 同步膨胀——纯宿主
  // 争用，非产物缺陷：单格 canary load 777ms / 同产物轻载全绿），抖动单重试也吸不动
  // 持续争用。--jobs 是 runner 的文档化调度旋钮（oracle e2e_matrix --jobs 同义），
  // 断言面不变：0 FAIL + totals 对账 + ≤1200s 预算逐项保持。
  const r = runNode(["scripts/e2e-matrix.mjs", "--budget-sec", String(E2E_BUDGET_SEC), "--jobs", "2"],
    { timeout: E2E_TIMEOUT_MS });
  assertRan(r.status === 0, `e2e-matrix 全量 --budget-sec ${E2E_BUDGET_SEC}（真实构建→打包→逐包质检）`, r);
  if (r.status !== 0) {
    const tail = r.stdout.trim().split(/\r?\n/).slice(-12);
    for (const line of tail) console.log(`      | ${line}`);
    return;
  }
  const passLine = r.stdout.match(/PASS：全矩阵全绿（exit 0）/);
  mark(Boolean(passLine), "e2e 收官横幅在位（PASS：全矩阵全绿）");

  // 双重对账：summary.json 的 totals/wallSec/mode（质检是唯一裁判，看数字不看口号）。
  const summaryPath = join(ROOT, "artifacts", "matrix", "summary.json");
  let summary = null;
  try {
    summary = JSON.parse(readFileSync(summaryPath, "utf8"));
  } catch (err) {
    mark(false, `summary.json 不可读：${String(err)}（${summaryPath}）`);
    return;
  }
  const totals = summary.totals ?? {};
  const gridOk = totals.pass === E2E_EXPECT_PASS && totals.fail === 0 && totals.skip === 0;
  mark(gridOk,
    `summary totals：pass=${totals.pass}/fail=${totals.fail}/skip=${totals.skip}`
    + `（期望 ${E2E_EXPECT_PASS}/0/0 = 4 模板×{en,zh}×6 渠道 = ${E2E_EXPECT_PASS} 包）`);
  const wallSec = summary.wallSec;
  mark(typeof wallSec === "number" && wallSec > 0 && wallSec <= E2E_BUDGET_SEC,
    `summary wallSec=${wallSec}s ≤ ${E2E_BUDGET_SEC}s 决策预算（硬线 D7 口径）`);
  mark(summary.mode === "full", `summary mode=${JSON.stringify(summary.mode)}（应 full）`);
  const failCells = (summary.cells ?? []).filter((c) => c.status === "fail");
  for (const c of failCells.slice(0, 12)) {
    mark(false, `fail 格：${c.spec}×${c.locale}×${c.channel}`);
  }
  const retried = totals.retried ?? 0;
  if (retried > 0) console.log(`  （首检抖动单重试 ${retried} 格，summary retried 字段留痕）`);
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
  console.log("批次 2 出口门（gate-m2）：批次1回归 + 四模板logic+autoplay + 48包全矩阵 + 中性名");
  console.log(`仓库根   : ${ROOT}`);
  console.log(`Node     : ${process.version}`);
  console.log(`启动时刻 : ${new Date().toISOString()}`);
  console.log("=".repeat(72));

  await gateItem(1, 4, "批次 1 三包回归（gate-m1 子进程：spec/bridge/packager 冻结测试 + 资产 sha）", gateBatch1Regression);
  await gateItem(2, 4, "四模板 logic+autoplay（冻结数值向量 + 判官本器复验 + tsc strict）", gateTemplates);
  await gateItem(3, 4, `全量 ${E2E_EXPECT_PASS} 包矩阵（4 golden×{en,zh}×6 渠道，预算 ≤${E2E_BUDGET_SEC}s）`, gateMatrix);
  await gateItem(4, 4, "中性名扫描（入库树零上游名命中）", gateNeutralNames);

  const secs = ((Date.now() - t0) / 1000).toFixed(1);
  console.log(`\n${"=".repeat(72)}`);
  if (gateFailed) {
    console.log(`GATE-M2: FAIL（存在 FAIL 门项，墙钟 ${secs}s）`);
    console.log("批次 2 出口门不通过：D5/D6 未达成即不得进入批次 3；不得静默放宽断言。");
    process.exitCode = 1;
  } else {
    console.log(`GATE-M2: PASS（4/4 门项全绿，墙钟 ${secs}s）`);
    console.log("批次 2 出口门通过：批次1三包回归全绿 + 四模板 logic/autoplay 全绿 + 48 包全矩阵 0 FAIL 且在决策预算内 + 中性名零命中。");
  }
}

main();

#!/usr/bin/env node
// scripts/diff/d2-crossqc.mjs — 差分维度 F3/D5：交叉质检矩阵补全 48 格（决策 §3.3）。
//
// 设 O=oracle 判官（repo venv python -m qacore），N=新判官（factory qacore/cli.mjs），
//    A=oracle 产物，B=新产物（同 spec×channel×locale）。
// 本 harness 补全（M2.2 已做 4 件之外的）48 格：
//   qacore_N(A)：新判官 × oracle 产物  → 与该格 O(A) 报告逐 CHK 对比
//   qacore_O(B)：oracle 判官 × 新产物  → 与该格 N(B) 报告逐 CHK 对比
// 判等（F3）：逐 CHK pass/fail/skip 状态全等；facts 键集合相等；load_ms/endMs 同量级（记录比值）；
// 且 qacore_N(B) 全 pass（48 格，读 B 侧既有矩阵报告核实）。
// CHK10 判定输入与各侧矩阵 runner 同源：required_texts/required_sprites 取自该格既有报告 facts
// （矩阵 runner 已按 spec 推导并传入，facts 里留了原值，避免二次推导漂移）。
// 纪律：质检是唯一裁判；瞬态抖动允许同判官单重试（与两侧矩阵 runner 同语义），两次全留痕。
//
// 用法：node scripts/diff/d2-crossqc.mjs <oracleMatrixDir> <factoryMatrixDir> <outDir>
//         [jobs=2] [--legs NA,OB,NB] [--ob-dir <冻结OB目录>] [--det-cells <格csv>]
//   腿：NA=新判官×oracle产物；OB=oracle判官×新产物（默认 NA,OB，与原行为一致）；
//       NB=新判官×新产物（新跑），与 --ob-dir 冻结 OB 报告逐 CHK 对比（2026-09-30 QC-02
//       修复后复跑新增，qacore-amendments.md chk04-determinism）。
//   --det-cells：NA 腿跑完后对列出的格再独立重跑一轮（写入 <outDir>/NA-run2/，先清空
//       防续跑假等），两次逐 CHK 判定全等性记入 evidence.determinism（确定性验证）。
// 退出码：0 无回归级不等；1 有回归级不等；2 用法/环境错误。

import { spawn } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, readdirSync, unlinkSync, writeFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import process from "node:process";

const _argv = process.argv.slice(2);
const _pos = [];
let _legsArg = null, _obDirArg = null, _detCellsArg = null;
for (let i = 0; i < _argv.length; i++) {
  const a = _argv[i];
  if (a === "--legs") _legsArg = _argv[++i];
  else if (a === "--ob-dir") _obDirArg = _argv[++i];
  else if (a === "--det-cells") _detCellsArg = _argv[++i];
  else _pos.push(a);
}
const [oracleMatrix, factoryMatrix, outDir, jobsArg] = _pos;
const JOBS = Math.max(1, Math.min(4, Number(jobsArg ?? 2)));
const LEGS = new Set((_legsArg ?? "NA,OB").split(",").map((s) => s.trim()).filter(Boolean));
for (const l of LEGS) {
  if (!["NA", "OB", "NB"].includes(l)) {
    console.error(`d2-crossqc: 未知腿 ${l}（可选 NA,OB,NB）`);
    process.exit(2);
  }
}
const DET_CELLS = (_detCellsArg ?? "").split(",").map((s) => s.trim()).filter(Boolean);
if (!oracleMatrix || !factoryMatrix || !outDir) {
  console.error("用法：node scripts/diff/d2-crossqc.mjs <oracleMatrixDir> <factoryMatrixDir> <outDir> [jobs=2] [--legs NA,OB,NB] [--ob-dir <冻结OB目录>] [--det-cells <格csv>]");
  process.exit(2);
}
// outDir 必须绝对化：O 判官子进程 cwd=repo，相对 outPath 会被写进 oracle 仓（封存只读
// 红线），且 harness 自身的续跑读取也对不上。2026-09-30 D-2 实测修正。
const OUT_DIR = resolve(outDir);
const FACTORY_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
const ORACLE_ROOT = resolve(FACTORY_ROOT, "..", "repo");
const PY = join(ORACLE_ROOT, "python", ".venv", "Scripts", "python.exe");
const QACORE_N = join(FACTORY_ROOT, "qacore", "cli.mjs");
if (!existsSync(PY)) { console.error("d2-crossqc: oracle venv python 不存在:", PY); process.exit(2); }

const fSummary = JSON.parse(readFileSync(join(factoryMatrix, "summary.json"), "utf8"));
const oSummary = JSON.parse(readFileSync(join(oracleMatrix, "summary.json"), "utf8"));
const oByCell = new Map(oSummary.cells.map((c) => [`${c.project}|${c.locale}|${c.channel}`, c]));

const NA_DIR = join(OUT_DIR, "NA"), OB_DIR = join(OUT_DIR, "OB");
const NB_DIR = join(OUT_DIR, "NB"), NA2_DIR = join(OUT_DIR, "NA-run2");
mkdirSync(NA_DIR, { recursive: true });
if (LEGS.has("OB")) mkdirSync(OB_DIR, { recursive: true });
if (LEGS.has("NB")) mkdirSync(NB_DIR, { recursive: true });
// NB 腿对比基准：冻结 OB 腿报告（默认取首轮 crossqc 的 OB 目录；oracle 判官冻结，
// 该基准与判官修复无关，可跨轮复用）。
const OB_FROZEN_DIR = resolve(_obDirArg ?? join(FACTORY_ROOT, "tmp", "diff", "crossqc", "OB"));

// ---------------------------------------------------------------- 单格解析
function resolveCell(matrixDir, cell) {
  const reportPath = join(matrixDir, cell.report.replaceAll("/", "\\"));
  if (!existsSync(reportPath)) return { error: `report 缺失: ${reportPath}` };
  const report = JSON.parse(readFileSync(reportPath, "utf8"));
  let qaTarget;
  if (cell.format === "zip") {
    const dir = join(matrixDir, "extract", `${cell.project}-${cell.locale}-${cell.channel}`);
    if (!existsSync(dir)) return { error: `extract 目录缺失: ${dir}` };
    // 入口名按规则库（mintegral=Template.html，其余 index.html），兜底取目录内任一 html
    const rules = JSON.parse(readFileSync(join(FACTORY_ROOT, "channel-rules", "channel-rules.json"), "utf8"));
    const entry = rules.channels?.[cell.channel]?.package?.entry;
    qaTarget = entry && existsSync(join(dir, entry)) ? join(dir, entry)
      : existsSync(join(dir, "index.html")) ? join(dir, "index.html")
        : join(dir, readdirSync(dir).find((f) => f.endsWith(".html")) ?? "");
  } else {
    qaTarget = join(matrixDir, cell.project, cell.channel, cell.locale, "index.html");
  }
  if (!existsSync(qaTarget)) return { error: `qaTarget 缺失: ${qaTarget}` };
  return { report, qaTarget, texts: report.facts?.required_texts ?? [], sprites: report.facts?.required_sprites ?? [] };
}

// ---------------------------------------------------------------- QC 执行（并发池 + 单重试）
function runQc(impl, qaTarget, channel, texts, sprites, outPath) {
  const cmd = impl === "N"
    ? [process.execPath, QACORE_N, "run", qaTarget]
    : [PY, "-m", "qacore", "run", qaTarget];
  cmd.push("--channel", channel, "--autoplay",
    "--max-load-sec", "2", "--autoplay-timeout", "45", "--out", outPath);
  for (const t of texts) cmd.push("--require-text", t);
  for (const k of sprites) cmd.push("--require-sprite", k);
  return new Promise((res) => {
    const t0 = performance.now();
    const child = spawn(cmd[0], cmd.slice(1), {
      cwd: impl === "N" ? FACTORY_ROOT : ORACLE_ROOT,
      env: impl === "N" ? process.env : { ...process.env, PYTHONUTF8: "1" },
      encoding: "utf8", windowsHide: true,
    });
    let out = "", err = "";
    child.stdout.on("data", (d) => { out += d; });
    child.stderr.on("data", (d) => { err += d; });
    const kill = setTimeout(() => { try { child.kill(); } catch {} }, 180000);
    child.on("close", (code) => {
      clearTimeout(kill);
      res({ code, wall: (performance.now() - t0) / 1000, tail: (err || out).trim().split(/\r?\n/).slice(-4).join(" | ") });
    });
  });
}

async function runWithRetry(impl, id, qaTarget, channel, texts, sprites, outPath) {
  // 断点续跑：已存在可解析的报告即为完整判定（含 fail 判定——fail 也是裁判结论，且
  // 崩溃前的运行已按抖动单重试语义给足两跑），仅补跑缺失/损坏的。
  try {
    const prev = JSON.parse(readFileSync(outPath, "utf8"));
    if (Array.isArray(prev.checks) && prev.checks.length > 0) {
      const pf = (prev.checks ?? []).filter((c) => c.status === "fail").map((c) => c.id);
      return [{ attempt: 0, exit: pf.length ? 1 : 0, wallSec: null, fails: pf, resumed: true }];
    }
  } catch {}
  const attempts = [];
  for (let i = 1; i <= 2; i++) {
    const r = await runQc(impl, qaTarget, channel, texts, sprites, outPath);
    let rep = null;
    try { rep = JSON.parse(readFileSync(outPath, "utf8")); } catch {}
    const fails = rep ? (rep.checks ?? []).filter((c) => c.status === "fail").map((c) => c.id) : null;
    attempts.push({ attempt: i, exit: r.code, wallSec: Math.round(r.wall * 10) / 10, fails, tail: r.code === 0 ? undefined : r.tail });
    if (r.code === 0 && rep && (fails ?? []).length === 0) break;
    if (i === 1) console.log(`  [retry] ${impl}(${id}) attempt1 exit=${r.code} fails=${JSON.stringify(fails)}`);
  }
  return attempts;
}

async function pool(items, worker) {
  const results = new Array(items.length);
  let next = 0;
  async function lane() {
    while (next < items.length) {
      const i = next++;
      results[i] = await worker(items[i], i);
    }
  }
  await Promise.all(Array.from({ length: JOBS }, lane));
  return results;
}

// ---------------------------------------------------------------- 主流程
console.log(`d2-crossqc: 48 格 × 腿{${[...LEGS].join(",")}}，并发 ${JOBS}（oracle 判官=venv python -m qacore；新判官=qacore/cli.mjs）`);
const t0 = performance.now();

const tasks = [];
for (const fc of fSummary.cells) {
  const id = `${fc.project}|${fc.locale}|${fc.channel}`;
  const oc = oByCell.get(id);
  if (!oc) { console.error(`d2-crossqc: oracle 侧缺格 ${id}`); process.exit(2); }
  tasks.push({ id, fileKey: `${fc.project}-${fc.locale}-${fc.channel}`, fc, oc });
}
if (LEGS.has("NB")) {
  const missing = tasks.filter((t) => !existsSync(join(OB_FROZEN_DIR, `${t.fileKey}.report.json`)));
  if (missing.length > 0) {
    console.error(`d2-crossqc: 冻结 OB 目录缺 ${missing.length} 份报告（首例 ${missing[0].fileKey}.report.json，目录 ${OB_FROZEN_DIR}）`);
    process.exit(2);
  }
}

const results = await pool(tasks, async (t) => {
  const A = resolveCell(oracleMatrix, t.oc);   // oracle 产物
  const B = resolveCell(factoryMatrix, t.fc);  // 新产物
  const rec = { cell: t.id, errors: [] };
  for (const [side, r, need] of [["A", A, LEGS.has("NA")], ["B", B, LEGS.has("OB") || LEGS.has("NB")]]) {
    if (need && r.error) rec.errors.push(`${side}: ${r.error}`);
  }
  if (rec.errors.length) return rec;

  if (LEGS.has("NA")) rec.NA = await runWithRetry("N", `${t.id}×N(A)`, A.qaTarget, t.fc.channel, A.texts, A.sprites, join(NA_DIR, `${t.fileKey}.report.json`));
  if (LEGS.has("OB")) rec.OB = await runWithRetry("O", `${t.id}×O(B)`, B.qaTarget, t.fc.channel, B.texts, B.sprites, join(OB_DIR, `${t.fileKey}.report.json`));
  if (LEGS.has("NB")) rec.NB = await runWithRetry("N", `${t.id}×N(B)新跑`, B.qaTarget, t.fc.channel, B.texts, B.sprites, join(NB_DIR, `${t.fileKey}.report.json`));
  return rec;
});

// ---------------------------------------------------------------- 判等
const findings = [];
function loadReport(p) {
  try { return JSON.parse(readFileSync(p, "utf8")); } catch { return null; }
}
const chkStatuses = (r) => (r?.checks ?? []).map((c) => `${c.id}:${c.status}`);
const factsKeys = (r) => ({
  top: Object.keys(r?.facts ?? {}).sort(),
  muteLoadTime: Object.keys(r?.facts?.muteLoadTime ?? {}).sort(),
  portrait: Object.keys(r?.facts?.viewport_shots?.portrait ?? {}).sort(),
});
function ratio(a, b) { return a > 0 && b > 0 ? a / b : null; }

const perCell = [];
// 对偶分歧归类：仅 CHK04 状态不同 → QC-02 已归因分歧（判官旗驱动真值 vs oracle 判官
// 早采样假阴性，qacore-amendments.md chk04-determinism），记 expected-qc02 不算回归；
// 其余任何不等 → regression。
function divergedChks(pd) {
  const sx = pd.statuses ?? [], sy = pd.statusesO ?? [];
  const diff = new Set();
  for (let k = 0; k < Math.max(sx.length, sy.length); k++) {
    if (sx[k] !== sy[k]) diff.add(String(sx[k] ?? sy[k] ?? "").split(":")[0]);
  }
  return [...diff];
}
for (let i = 0; i < tasks.length; i++) {
  const t = tasks[i], rec = results[i];
  const id = t.id;
  const out = { cell: id, run: {} };
  for (const leg of ["NA", "OB", "NB"]) {
    if (rec[leg]) out.run[leg] = rec[leg].map(({ attempt, exit, wallSec, fails }) => ({ attempt, exit, wallSec, fails }));
  }
  if (rec.errors?.length) { out.equal = false; out.regression = true; findings.push({ cell: id, item: "inputs", severity: "regression", detail: rec.errors.join("; ") }); perCell.push(out); continue; }

  const oA = loadReport(join(oracleMatrix, t.oc.report.replaceAll("/", "\\")));
  const nB = loadReport(join(factoryMatrix, t.fc.report.replaceAll("/", "\\")));
  const nA = loadReport(join(NA_DIR, `${t.fileKey}.report.json`));
  const oB = LEGS.has("OB") ? loadReport(join(OB_DIR, `${t.fileKey}.report.json`)) : null;
  const nb = LEGS.has("NB") ? loadReport(join(NB_DIR, `${t.fileKey}.report.json`)) : null;
  const obFrozen = LEGS.has("NB") ? loadReport(join(OB_FROZEN_DIR, `${t.fileKey}.report.json`)) : null;
  const pairs = [];
  if (LEGS.has("NA")) pairs.push(["N(A)≡O(A)", nA, oA]);
  if (LEGS.has("OB")) pairs.push(["N(B)≡O(B)", nB, oB]);
  if (LEGS.has("NB")) pairs.push(["N(B)≡OB(冻结)", nb, obFrozen]);
  out.pairs = {};
  for (const [name, x, y] of pairs) {
    const pd = { name };
    if (!x || !y) { pd.statusEq = false; pd.detail = `报告缺失 N=${!!x} O=${!!y}`; }
    else {
      const sx = chkStatuses(x), sy = chkStatuses(y);
      pd.statusEq = JSON.stringify(sx) === JSON.stringify(sy);
      pd.statuses = sx;
      pd.statusesO = sy;
      pd.factsKeysEq = JSON.stringify(factsKeys(x)) === JSON.stringify(factsKeys(y));
      if (!pd.factsKeysEq) {
        const fx = factsKeys(x), fy = factsKeys(y);
        pd.factsKeysDetail = {
          topOnlyInN: fx.top.filter((k) => !fy.top.includes(k)), topOnlyInO: fy.top.filter((k) => !fx.top.includes(k)),
          muteOnlyInN: fx.muteLoadTime.filter((k) => !fy.muteLoadTime.includes(k)), muteOnlyInO: fy.muteLoadTime.filter((k) => !fx.muteLoadTime.includes(k)),
        };
      }
      pd.loadMs = { n: x.facts?.load_ms, o: y.facts?.load_ms, ratio: ratio(x.facts?.load_ms, y.facts?.load_ms) };
      pd.endMs = { n: x.pf?.endMs, o: y.pf?.endMs, ratio: ratio(x.pf?.endMs, y.pf?.endMs) };
    }
    const bad = !pd.statusEq || !pd.factsKeysEq;
    if (bad) {
      const onlyChk04 = pd.statusEq === false && divergedChks(pd).every((c) => c === "CHK04");
      const severity = pd.statusEq === false && onlyChk04 ? "expected-qc02" : "regression";
      pd.divergedChks = pd.statusEq === false ? divergedChks(pd) : [];
      findings.push({
        cell: id, item: `F3:${name}`, severity,
        detail: pd.detail ?? JSON.stringify({ statusEq: pd.statusEq, divergedChks: pd.divergedChks, factsKeysEq: pd.factsKeysEq, factsKeysDetail: pd.factsKeysDetail, statuses: pd.statuses }),
      });
    }
    out.pairs[name] = pd;
  }
  // N(B) 全 pass 核实
  // N(B) 全 pass（§3.3）＝ 0 fail（CHK02/CHK06 的 skip 为合法语义，与矩阵判定同口径）
  const nbAllPass = (nB?.checks ?? []).every((c) => c.status !== "fail");
  out.nbAllPass = nbAllPass;
  if (!nbAllPass) findings.push({ cell: id, item: "N(B)全pass", severity: "regression", detail: JSON.stringify(chkStatuses(nB)) });
  // NB 腿新跑全 pass（判官修复后复跑的出口门语义，同 §3.3 口径）
  if (nb) {
    const nbFreshAllPass = (nb.checks ?? []).every((c) => c.status !== "fail");
    out.nbFreshAllPass = nbFreshAllPass;
    if (!nbFreshAllPass) findings.push({ cell: id, item: "N(B)新跑全pass", severity: "regression", detail: JSON.stringify(chkStatuses(nb)) });
  }
  // 数值同量级登记（比值带外 → diff，逐格给数据）
  for (const [k, num] of [["load_ms", out.pairs["N(A)≡O(A)"]?.loadMs], ["endMs", out.pairs["N(A)≡O(A)"]?.endMs]]) {
    if (num?.ratio != null && (num.ratio > 3 || num.ratio < 1 / 3)) {
      findings.push({ cell: id, item: `量级:${k}(N(A)/O(A))`, severity: "diff", detail: `ratio=${num.ratio.toFixed(2)} n=${num.n} o=${num.o}` });
    }
  }
  perCell.push(out);
}

// ---------------------------------------------------------------- 确定性验证（NA 双跑）
let determinism = null;
if (DET_CELLS.length > 0) {
  const byKey = new Map(tasks.map((t) => [t.fileKey, t]));
  const detTasks = [];
  for (const k of DET_CELLS) {
    const t = byKey.get(k.includes("|") ? k.replaceAll("|", "-") : k);
    if (!t) { console.error(`d2-crossqc: --det-cells 未知格 ${k}`); process.exit(2); }
    detTasks.push(t);
  }
  mkdirSync(NA2_DIR, { recursive: true });
  // 清空旧报告：确定性验证必须是两次独立全跑，不允许续跑把 run2 折叠成 run1 的副本。
  for (const f of readdirSync(NA2_DIR)) if (f.endsWith(".report.json")) unlinkSync(join(NA2_DIR, f));
  console.log(`d2-crossqc: 确定性验证 NA 双跑 ${detTasks.length} 格 → ${NA2_DIR}`);
  const detResults = await pool(detTasks, async (t) => {
    const A = resolveCell(oracleMatrix, t.oc);
    if (A.error) return { cell: t.id, error: A.error };
    await runWithRetry("N", `det×2 ${t.id}`, A.qaTarget, t.fc.channel, A.texts, A.sprites, join(NA2_DIR, `${t.fileKey}.report.json`));
    const r1 = loadReport(join(NA_DIR, `${t.fileKey}.report.json`));
    const r2 = loadReport(join(NA2_DIR, `${t.fileKey}.report.json`));
    const s1 = chkStatuses(r1), s2 = chkStatuses(r2);
    const a1 = r1?.facts?.autoplay ?? r1?.facts?.muteLoadTime ?? {};
    const a2 = r2?.facts?.autoplay ?? r2?.facts?.muteLoadTime ?? {};
    return {
      cell: t.id, statusesEq: JSON.stringify(s1) === JSON.stringify(s2),
      statusesRun1: s1, statusesRun2: s2,
      audioRunningRun1: a1.audioRunningBeforeInteraction ?? null,
      audioRunningRun2: a2.audioRunningBeforeInteraction ?? null,
    };
  });
  determinism = {
    cells: detResults,
    cellsTotal: detResults.length,
    cellsConsistent: detResults.filter((r) => r.statusesEq === true).length,
    allEq: detResults.every((r) => r.statusesEq === true),
  };
  if (!determinism.allEq) {
    findings.push({
      cell: "-", item: "确定性:NA双跑逐CHK不等", severity: "regression",
      detail: JSON.stringify(detResults.filter((r) => !r.statusesEq)),
    });
  }
}

const regressions = findings.filter((f) => f.severity === "regression");
const expectedQc02 = findings.filter((f) => f.severity === "expected-qc02");
const diffs = findings.filter((f) => f.severity === "diff");
// 汇总数字（题述出口门口径）
const naChk04FailCells = perCell.filter((c) => (c.pairs["N(A)≡O(A)"]?.statuses ?? []).includes("CHK04:fail")).length;
const naCells = LEGS.has("NA") ? perCell.length : 0;
const nbFreshFailCells = perCell.filter((c) => c.nbFreshAllPass === false).length;
const nbPair = LEGS.has("NB") ? perCell.filter((c) => c.pairs["N(B)≡OB(冻结)"]?.statusEq === true).length : null;
const nbCells = LEGS.has("NB") ? perCell.length : null;
const evidence = {
  capturedAt: new Date().toISOString(),
  inputs: {
    oracleMatrix, factoryMatrix, jobs: JOBS,
    legs: [...LEGS],
    obFrozenDir: LEGS.has("NB") ? OB_FROZEN_DIR : undefined,
    detCells: DET_CELLS.length > 0 ? DET_CELLS : undefined,
    wallSec: Math.round((performance.now() - t0) / 100) / 10,
  },
  meta: {
    naChk04FailCells, naCells,
    nbFreshFailCells, nbFreshAllPassCells: nbCells === null ? null : nbCells - nbFreshFailCells,
    nbEqFrozenObCells: nbPair, nbCells,
    detCellsTotal: determinism?.cellsTotal ?? null, detCellsConsistent: determinism?.cellsConsistent ?? null,
  },
  perCell, findings, regressions, expectedQc02, diffs, determinism,
  verdict: regressions.length === 0 ? "PASS（零回归）" : "FAIL（存在回归）",
};
writeFileSync(join(OUT_DIR, "crossqc-evidence.json"), JSON.stringify(evidence, null, 2) + "\n", "utf8");
console.log(`d2-crossqc: cells=${perCell.length} wallSec=${evidence.inputs.wallSec} regressions=${regressions.length} expectedQc02=${expectedQc02.length} diffs=${diffs.length}`);
console.log(`d2-crossqc: meta NA_CHK04_fail=${naChk04FailCells}/${naCells} NB新跑fail格=${nbFreshFailCells} NB≡冻结OB=${nbPair ?? "-"}/${nbCells ?? "-"} det=${determinism?.cellsConsistent ?? "-"}/${determinism?.cellsTotal ?? "-"}`);
for (const r of regressions) console.error(`  回归 ${r.cell} ${r.item}: ${String(r.detail).slice(0, 300)}`);
for (const q of expectedQc02) console.log(`  QC02已归因分歧 ${q.cell} ${q.item}`);
for (const d of diffs) console.log(`  登记差异 ${d.cell} ${d.item}: ${d.detail}`);
console.log(`d2-crossqc: ${evidence.verdict} → ${join(OUT_DIR, "crossqc-evidence.json")}`);
process.exit(regressions.length === 0 ? 0 : 1);

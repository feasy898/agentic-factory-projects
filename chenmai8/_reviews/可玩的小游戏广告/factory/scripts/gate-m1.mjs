#!/usr/bin/env node
// gate-m1.mjs — 批次 1 出口门（决策 §5 批次 1；D1/D2/D3/D4 的前置闸 + 法务红线）。
// 用法：node scripts/gate-m1.mjs （或 npm run gate:m1）。全过 exit 0；任一门项失败 exit 1。
//
// 门项（与开发任务 M1.3 一致）：
//   1/5 packages/spec     冻结测试全量：ajv-check.mjs（冻结 eval 原样，golden 1 + bad 6）
//                         + node:test 三件（eval-matrix / schema / invariants）+ tsc strict
//   2/5 packages/engine-bridge 冻结测试全量：26 用例（byte-reused 冻结套件，数目钉死）
//                         + c8 --check-coverage 行覆盖 ≥80%（D3）+ tsc --noEmit
//   3/5 packages/packager 冻结测试全量：46 断言自验收（D2，数目钉死）+ 七渠道结构断言
//   4/5 数据资产 sha 清单复验：verify-reused-assets.mjs 真实执行（REUSED-ASSETS.md 登记册逐项重算）
//   5/5 中性名扫描：入库树（git ls-files）路径+内容对仓外词表大小写不敏感子串匹配零命中
//                   ——语义照抄 oracle repo/scripts/gate_mainpath.py check_neutral_names；
//                      词表含上游名、永不入库（本仓位置见 AGENTS.md：D:/upstream-refs/neutral-words.txt）
//
// 纪律（AGENTS.md）：eval 真实执行 exit 0 才算过；skip 不算过；本脚本只跑断言不修改任何产物。
// 跨包 node --test 一律显式列出文件（坑 4）；c8 --include 写执行 cwd 相对路径（坑 16，
// 此处 c8 的 cwd=包目录、include=src/**，与包内 npm run coverage 完全同形）。

import { spawnSync } from "node:child_process";
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const TSC = join(ROOT, "node_modules", "typescript", "bin", "tsc");
const C8 = join(ROOT, "node_modules", "c8", "bin", "c8.js");
const TEST_TIMEOUT_MS = 600_000;

// ---------------------------------------------------------------- 门禁框架
let gateFailed = false;

function mark(ok, text) {
  console.log(`  [${ok ? "PASS" : "FAIL"}] ${text}`);
  if (!ok) gateFailed = true;
}

function gateItem(idx, total, label, run) {
  console.log(`\n[${idx}/${total}] ${label}`);
  const t0 = Date.now();
  run();
  console.log(`  （本门项 ${((Date.now() - t0) / 1000).toFixed(1)}s）`);
}

/** 运行子进程；返回 {status, stdout, stderr}，spawn 失败折算为 status=null。 */
function runNode(args, { cwd = ROOT, timeout = TEST_TIMEOUT_MS } = {}) {
  const r = spawnSync(process.execPath, args, { cwd, encoding: "utf8", timeout });
  if (r.error) return { status: null, stdout: r.stdout ?? "", stderr: String(r.error) };
  return { status: r.status, stdout: r.stdout ?? "", stderr: r.stderr ?? "" };
}

/** 解析 node --test TAP 摘要（# tests / # pass / # fail）。 */
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

// ---------------------------------------------------------------- 1/5 spec
const SPEC_TESTS = [
  "packages/spec/test/eval-matrix.test.mjs",
  "packages/spec/test/schema.test.mjs",
  "packages/spec/test/invariants.test.mjs",
];

function gateSpec() {
  // 1a. 冻结 eval ajv-check.mjs 原样执行（D1 前置；bad 样本属规格，期望值在冻结文件内）。
  const ajv = runNode(["packages/spec/test/ajv-check.mjs"]);
  assertRan(ajv.status === 0, "ajv-check.mjs（冻结 eval 原样）", ajv);
  const frozenLine = ajv.stdout.match(/AJV-CHECK: PASS（golden (\d+) 通过，bad (\d+) 全拒）/);
  mark(Boolean(frozenLine) && Number(frozenLine[1]) === 1 && Number(frozenLine[2]) === 6,
    `冻结裁定规模不变：golden 1 通过 + bad 6 全拒（实际 ${frozenLine ? `${frozenLine[1]}/${frozenLine[2]}` : "摘要行缺失"}）`);
  mark(!/\[FAIL\]/.test(ajv.stdout), "ajv-check 零 [FAIL] 行");

  // 1b. node:test 三件全量（显式列文件——坑 4：不传目录）。
  const t = runNode(["--test", ...SPEC_TESTS]);
  assertRan(t.status === 0, `node --test ${SPEC_TESTS.length} 件（eval-matrix/schema/invariants）`, t);
  const s = tapSummary(t.stdout);
  mark(s.fail === 0 && (s.pass ?? 0) > 0 && s.tests !== null,
    `用例全过：pass=${s.pass} fail=${s.fail} tests=${s.tests}（M1.2a 基线 21，新增只增不减）`);

  // 1c. tsc strict（M1.2a 双交付之一）。
  const ts = runNode([TSC, "-p", "packages/spec/tsconfig.json"]);
  assertRan(ts.status === 0, "tsc -p packages/spec/tsconfig.json（strict）", ts);
}

// ---------------------------------------------------------------- 2/5 bridge
function gateBridge() {
  // 2a. 冻结 26 用例（byte-reused 套件，用例数钉死——缩水即差分失败）。
  const run = runNode(["packages/engine-bridge/test/run.mjs"]);
  assertRan(run.status === 0, "test/run.mjs（冻结 26 用例）", run);
  const s = tapSummary(run.stdout);
  mark(s.tests === 26 && s.pass === 26 && s.fail === 0,
    `冻结用例数钉死 26/26/0（实际 tests=${s.tests} pass=${s.pass} fail=${s.fail}）`);

  // 2b. c8 行覆盖 ≥80%（D3）。cwd=包目录、include=src/**（坑 16 同形于包内 coverage 脚本）；
  //     --check-coverage 使覆盖不足时 c8 自身非零退出（skip 不算过）。
  const pkg = join(ROOT, "packages", "engine-bridge");
  const cov = runNode([C8, "--include", "src/**", "--check-coverage", "--lines", "80",
    "--reporter", "text", "node", "--test", "test/"], { cwd: pkg });
  assertRan(cov.status === 0, "c8 --check-coverage --lines 80（行覆盖门槛）", cov);
  const covLine = cov.stdout.match(/All files\s*\|[^\n]*\|\s*([\d.]+)\s*\|/);
  const covSummary = tapSummary(cov.stdout);
  mark(covSummary.fail === 0 && (covSummary.pass ?? 0) > 0,
    `覆盖运行内用例全过：pass=${covSummary.pass} fail=${covSummary.fail}`);
  mark(Boolean(covLine), `行覆盖实测 ${covLine ? `${covLine[1]}%` : "??"}（≥80 由 --check-coverage 强制）`);

  // 2c. tsc strict（D3 三件套之一）。
  const ts = runNode([TSC, "--noEmit"], { cwd: pkg });
  assertRan(ts.status === 0, "tsc --noEmit（strict）", ts);
}

// ---------------------------------------------------------------- 3/5 packager
function gatePackager() {
  // 3a. 冻结 46 断言自验收（D2；含负向 3 条与字节可复现）。断言数钉死。
  const run = runNode(["packages/packager/test/run.mjs"]);
  assertRan(run.status === 0, "test/run.mjs（冻结自验收）", run);
  const passCount = (run.stdout.match(/\[PASS\]/g) ?? []).length;
  const failCount = (run.stdout.match(/\[FAIL\]/g) ?? []).length;
  mark(passCount === 46 && failCount === 0,
    `冻结断言数钉死 46 全过（实际 PASS=${passCount} FAIL=${failCount}）`);
  mark(run.stdout.includes("全部自验收断言通过"), "自验收收官行在位（全部自验收断言通过）");

  // 3b. 七渠道结构断言（node:test，显式列文件）。
  const st = runNode(["--test", "packages/packager/test/structure.test.mjs"]);
  assertRan(st.status === 0, "node --test test/structure.test.mjs（七渠道结构）", st);
  const s = tapSummary(st.stdout);
  mark(s.fail === 0 && (s.pass ?? 0) > 0 && s.tests !== null,
    `用例全过：pass=${s.pass} fail=${s.fail} tests=${s.tests}（M1.2 基线 12，新增只增不减）`);
}

// ---------------------------------------------------------------- 4/5 数据资产 sha 清单复验
function gateAssets() {
  // 登记册项数直接读 REUSED-ASSETS.md（与 verify 脚本同一正则，防误取其他 json 围栏）。
  const md = readFileSync(join(ROOT, "REUSED-ASSETS.md"), "utf8");
  const reg = JSON.parse(md.match(/### 机器可读登记册[\s\S]*?```json\r?\n([\s\S]*?)```/)[1]);
  const expect = reg.assets.length;

  const v = runNode(["scripts/verify-reused-assets.mjs"]);
  assertRan(v.status === 0, "verify-reused-assets.mjs（登记册逐项 sha256+字节数重算）", v);
  const matchCount = (v.stdout.match(/MATCH /g) ?? []).length;
  const declared = Number((v.stdout.match(/(\d+) 项已核对/) ?? [])[1]);
  mark(matchCount === expect && declared === expect && matchCount > 0,
    `MATCH ${matchCount} = 登记册 ${expect} = 脚本申报 ${declared}（漂移/缺失即 0 命中失败）`);
  mark(v.stdout.trimEnd().endsWith("verify-reused-assets: OK"), "收官行 OK 在位");
}

// ---------------------------------------------------------------- 5/5 中性名扫描
const NEUTRAL_WORDLIST = process.env.PF_NEUTRAL_WORDS || "D:/upstream-refs/neutral-words.txt";
const FALLBACK_SKIP_DIRS = new Set([
  ".git", "node_modules", ".mimosa", "tmp", "artifacts", "coverage", ".venv", "__pycache__", "_vendor",
]);

function trackedFiles() {
  // 入库树以 git ls-files 为准；git 不可用时退化为目录枚举（跳过依赖/产物目录）——同 oracle。
  const g = spawnSync("git", ["ls-files", "-z"], { cwd: ROOT, encoding: "buffer", timeout: 60_000 });
  if (!g.error && g.status === 0) {
    return Buffer.from(g.stdout).toString("utf8").split("\0").filter(Boolean)
      .map((n) => resolve(ROOT, ...n.split("/")));
  }
  const out = [];
  const walk = (dir) => {
    for (const name of readdirSync(dir)) {
      const p = join(dir, name);
      let st;
      try { st = statSync(p); } catch { continue; }
      if (st.isDirectory()) {
        if (!FALLBACK_SKIP_DIRS.has(name)) walk(p);
      } else out.push(p);
    }
  };
  try { walk(ROOT); } catch { return null; }
  return out;
}

function gateNeutralNames() {
  const wlDisp = relative(ROOT, resolve(NEUTRAL_WORDLIST)).split("\\").join("/") || NEUTRAL_WORDLIST;
  console.log(`  （词表 ${NEUTRAL_WORDLIST}，在仓库外、永不入库——法务红线）`);

  if (!existsSync(NEUTRAL_WORDLIST)) {
    mark(false, `词表不存在：${NEUTRAL_WORDLIST}（含上游名不入库，需在本机仓外补建后重跑本门）`);
    return;
  }
  const words = readFileSync(NEUTRAL_WORDLIST, "utf8").split(/\r?\n/)
    .map((l) => l.trim().toLowerCase())
    .filter((l) => l && !l.startsWith("#"));
  mark(words.length > 0, `词表非空：${words.length} 个词`);

  const files = trackedFiles();
  mark(Array.isArray(files) && files.length > 0,
    `入库树枚举：${Array.isArray(files) ? files.length : "失败"} 个文件（git ls-files）`);
  if (!Array.isArray(files)) return;

  const hits = [];
  let scanned = 0;
  for (const f of files) {
    const rel = relative(ROOT, f).split("\\").join("/");
    const relLow = rel.toLowerCase();
    const pathHits = words.filter((w) => relLow.includes(w));
    if (pathHits.length > 0) {
      hits.push(`${rel}: 路径命中 ${JSON.stringify(pathHits)}`);
      continue; // 路径已命中，内容不必再扫（同 oracle）
    }
    let text;
    try {
      if (!statSync(f).isFile()) continue;
      text = readFileSync(f, "utf8"); // 非法字节按 U+FFFD 替换（≈errors="replace"）
      scanned += 1;
    } catch { continue; }
    const lines = text.split(/\r?\n/);
    for (let i = 0; i < lines.length; i++) {
      const low = lines[i].toLowerCase();
      const hitWords = words.filter((w) => low.includes(w));
      if (hitWords.length > 0) hits.push(`${rel}:${i + 1}: 命中 ${JSON.stringify(hitWords)}：${lines[i].trim().slice(0, 80)}`);
    }
  }

  mark(hits.length === 0,
    `扫描 ${scanned} 个入库文件 × ${words.length} 词（大小写不敏感子串，路径+内容）：命中 ${hits.length} 处`);
  for (const h of hits.slice(0, 10)) mark(false, `命中：${h}`);
  if (hits.length > 10) mark(false, `……另有 ${hits.length - 10} 处（只报告不修改——改名/声明问题不碰，法务裁定）`);
}

// ---------------------------------------------------------------- 主流程
function main() {
  const t0 = Date.now();
  console.log("=".repeat(72));
  console.log("批次 1 出口门（gate-m1）：三包冻结测试全量 + 数据资产 sha 复验 + 中性名扫描");
  console.log(`仓库根   : ${ROOT}`);
  console.log(`Node     : ${process.version}`);
  console.log(`启动时刻 : ${new Date().toISOString()}`);
  console.log("=".repeat(72));

  gateItem(1, 5, "packages/spec 冻结测试全量（ajv-check + node:test×3 + tsc strict）", gateSpec);
  gateItem(2, 5, "packages/engine-bridge 冻结测试全量（26 用例 + 覆盖≥80% + tsc strict）", gateBridge);
  gateItem(3, 5, "packages/packager 冻结测试全量（46 断言 + 七渠道结构）", gatePackager);
  gateItem(4, 5, "数据资产 sha 清单复验（REUSED-ASSETS.md 登记册）", gateAssets);
  gateItem(5, 5, "中性名扫描（入库树零上游名命中）", gateNeutralNames);

  const secs = ((Date.now() - t0) / 1000).toFixed(1);
  console.log("\n" + "=" .repeat(72));
  if (gateFailed) {
    console.log(`GATE-M1: FAIL（存在 FAIL 门项，墙钟 ${secs}s）`);
    console.log("批次 1 出口门不通过：任一门项失败即不承认 D1–D4 前置达成；不得静默放宽断言。");
    process.exitCode = 1;
  } else {
    console.log(`GATE-M1: PASS（5/5 门项全绿，墙钟 ${secs}s）`);
    console.log("批次 1 出口门通过：三包冻结 eval 真实执行全过 + 数据资产零漂移 + 中性名零命中。");
  }
}

main();

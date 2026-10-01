// scripts/diff/spec-eval-diff.mjs — M1 校验器差分 harness（决策 §3：契约层差分 F1 + 数值向量 F6 的 M1 子集）。
//
// 对齐点：
//   F1 校验裁定：specs-eval 11 件（golden×4 + bad×6 + demo-zh）逐件判定 ok 全等 +
//     issue 集 {path, code} 集合相等（消息人读不锁，spec-contract §2.5）。
//   F6-M1 数值向量：规范生成器（Lcg/match3Board/match3FindMove/pullpinLevelRoles/
//     sortScramble/sortSolvedBoard）新 TS 实现 vs oracle Python 权威逐值结构全等。
// oracle 只读：JS 镜像 import；Python 权威经 repo 的冻结 venv 子进程（决策 §3.1：
// venv python 保留在本机仅作 oracle 参照）。本 harness 非 npm test 一部分；
// oracle 缺失时 exit 2（不静默绿）。
// 证据落 artifacts/diff/M1.2a-spec-eval.json（artifacts/ 已 gitignore，决策 §3.5）。
//
// 用法：node scripts/diff/spec-eval-diff.mjs   （在 factory 根执行）

import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const ROOT = join(here, "..", "..");                    // factory 根
const ORACLE = join(ROOT, "..", "repo");                // oracle 仓（只读）

// 新实现（TS 单源，经冻结测试同一入口壳）。
const { validateSpec } = await import(new URL("../../packages/spec/src/validate.mjs", import.meta.url).href);
const inv = await import(new URL("../../packages/spec/src/invariants.ts", import.meta.url).href);

// oracle JS 镜像（只读 import）。
const oracleMirror = await import(new URL("../../../repo/packages/spec/src/validate.mjs", import.meta.url).href);

const EVAL_FILES = [
  "specs-eval/golden-match3.json",
  "specs-eval/golden-merge.json",
  "specs-eval/golden-pullpin.json",
  "specs-eval/golden-sort.json",
  "specs-eval/demo-zh.json",
  "specs-eval/bad/01-missing-field.json",
  "specs-eval/bad/02-pullpin-unsolvable.json",
  "specs-eval/bad/03-duration-over-budget.json",
  "specs-eval/bad/04-missing-locale-strings.json",
  "specs-eval/bad/05-bad-url.json",
  "specs-eval/bad/06-unknown-template.json",
];

const problems = [];
const evidence = { capturedAt: new Date().toISOString(), f1: [], f6: {} };

// ---------------------------------------------------------------- F1: JS 双实现逐件比对

function issueSet(errors) {
  return errors.map((e) => `${e.path} [${e.code}]`).sort();
}

for (const rel of EVAL_FILES) {
  const spec = JSON.parse(readFileSync(join(ROOT, rel), "utf8"));
  const mine = validateSpec(spec);
  const theirs = oracleMirror.validateSpec(spec);
  const setA = issueSet(mine.errors);
  const setB = issueSet(theirs.errors);
  const okEq = mine.ok === theirs.ok && JSON.stringify(setA) === JSON.stringify(setB);
  evidence.f1.push({ file: rel, ok: mine.ok, issues: setA, oracleOk: theirs.ok, oracleIssues: setB, equal: okEq });
  if (!okEq) problems.push(`F1 ${rel}: 判定/issue 集不等 新=${JSON.stringify(setA)} oracle=${JSON.stringify(setB)}`);
}

// ---------------------------------------------------------------- F1: oracle Python 权威逐件比对

const pyExe = join(ORACLE, "python", ".venv", "Scripts", "python.exe");
if (!existsSync(pyExe)) {
  console.error("spec-eval-diff: oracle venv python 不存在（差分不可执行，不静默通过）:", pyExe);
  process.exit(2);
}
const pyScript = `
import json, sys
sys.stdout.reconfigure(encoding="utf-8")
from pfcore.validation import validate_spec_file
files = json.loads(sys.argv[1])
out = {}
for f in files:
    issues = validate_spec_file(f)
    out[f] = {"ok": len(issues) == 0, "issues": sorted(f"{i.path} [{i.code}]" for i in issues)}
print(json.dumps(out, ensure_ascii=False))
`;
const py = spawnSync(pyExe, ["-c", pyScript, JSON.stringify(EVAL_FILES.map((f) => join(ORACLE, f)))],
  { encoding: "utf8", cwd: ORACLE });
if (py.status !== 0) {
  console.error("spec-eval-diff: oracle python 校验失败:", py.stderr);
  process.exit(2);
}
const pyOut = JSON.parse(py.stdout.trim());
for (const rel of EVAL_FILES) {
  const ref = pyOut[join(ORACLE, rel)];
  const mine = validateSpec(JSON.parse(readFileSync(join(ROOT, rel), "utf8")));
  const setA = issueSet(mine.errors);
  const okEq = mine.ok === ref.ok && JSON.stringify(setA) === JSON.stringify(ref.issues);
  evidence.f1.find((e) => e.file === rel).pythonOk = ref.ok;
  evidence.f1.find((e) => e.file === rel).pythonIssues = ref.issues;
  evidence.f1.find((e) => e.file === rel).pythonEqual = okEq;
  if (!okEq) problems.push(`F1(py) ${rel}: 判定/issue 集不等 新=${JSON.stringify(setA)} oracle-py=${JSON.stringify(ref.issues)}`);
}

// ---------------------------------------------------------------- F6-M1: 规范生成器逐值比对（Python 权威）

const pyVecScript = `
import json, sys
sys.stdout.reconfigure(encoding="utf-8")
from pfcore.invariants import Lcg, match3_board, match3_find_move, pullpin_level_roles, sort_scramble, sort_solved_board
out = {}
r = Lcg(1); out["lcg1_first5"] = [r.next_u32() for _ in range(5)]
r2 = Lcg(424242); out["lcg424242_below3_x2"] = [r2.below(3) for _ in range(2)]
r3 = Lcg(20260930); out["lcg20260930_first8"] = [r3.next_u32() for _ in range(8)]
out["roles_424242_2_3"] = pullpin_level_roles(424242, 2, 3)
out["roles_20260930_3_3"] = pullpin_level_roles(20260930, 3, 3)
out["board_20260930"] = match3_board(20260930, 6, 6, 5)
out["findmove_20260930"] = match3_find_move(match3_board(20260930, 6, 6, 5))
out["board_424242"] = match3_board(424242, 6, 6, 5)
out["findmove_424242"] = match3_find_move(match3_board(424242, 6, 6, 5))
b, t = sort_scramble(20260930, 5, 4, 4)
out["scramble_20260930_5_4_4"] = {"board": b, "trace": t}
b2, t2 = sort_scramble(424242, 4, 4, 4)
out["scramble_424242_4_4_4"] = {"board": b2, "trace": t2}
out["solved_4_4_4"] = sort_solved_board(4, 4, 4)
print(json.dumps(out, ensure_ascii=False))
`;
const py2 = spawnSync(pyExe, ["-c", pyVecScript], { encoding: "utf8", cwd: ORACLE });
if (py2.status !== 0) {
  console.error("spec-eval-diff: oracle python 向量生成失败:", py2.stderr);
  process.exit(2);
}
const pv = JSON.parse(py2.stdout.trim());

function check(name, actual, expected) {
  const eq = JSON.stringify(actual) === JSON.stringify(expected);
  evidence.f6[name] = { equal: eq, actual, expected };
  if (!eq) problems.push(`F6 ${name}: 向量不等 新=${JSON.stringify(actual)} oracle-py=${JSON.stringify(expected)}`);
}

check("lcg1_first5", (() => { const r = new inv.Lcg(1); return Array.from({ length: 5 }, () => r.nextU32()); })(), pv.lcg1_first5);
check("lcg424242_below3_x2", (() => { const r = new inv.Lcg(424242); return [r.below(3), r.below(3)]; })(), pv.lcg424242_below3_x2);
check("lcg20260930_first8", (() => { const r = new inv.Lcg(20260930); return Array.from({ length: 8 }, () => r.nextU32()); })(), pv.lcg20260930_first8);
check("roles_424242_2_3", inv.pullpinLevelRoles(424242, 2, 3), pv.roles_424242_2_3);
check("roles_20260930_3_3", inv.pullpinLevelRoles(20260930, 3, 3), pv.roles_20260930_3_3);
check("board_20260930", inv.match3Board(20260930, 6, 6, 5), pv.board_20260930);
check("findmove_20260930", inv.match3FindMove(inv.match3Board(20260930, 6, 6, 5)), pv.findmove_20260930);
check("board_424242", inv.match3Board(424242, 6, 6, 5), pv.board_424242);
check("findmove_424242", inv.match3FindMove(inv.match3Board(424242, 6, 6, 5)), pv.findmove_424242);
{
  const [b, t] = inv.sortScramble(20260930, 5, 4, 4);
  check("scramble_20260930_5_4_4.board", b, pv.scramble_20260930_5_4_4.board);
  check("scramble_20260930_5_4_4.trace", t, pv.scramble_20260930_5_4_4.trace);
}
{
  const [b, t] = inv.sortScramble(424242, 4, 4, 4);
  check("scramble_424242_4_4_4.board", b, pv.scramble_424242_4_4_4.board);
  check("scramble_424242_4_4_4.trace", t, pv.scramble_424242_4_4_4.trace);
}
check("solved_4_4_4", inv.sortSolvedBoard(4, 4, 4), pv.solved_4_4_4);

// ---------------------------------------------------------------- 结论与证据

mkdirSync(join(ROOT, "artifacts", "diff"), { recursive: true });
writeFileSync(join(ROOT, "artifacts", "diff", "M1.2a-spec-eval.json"), JSON.stringify(evidence, null, 2) + "\n", "utf8");

if (problems.length > 0) {
  console.error("spec-eval-diff: FAIL ——");
  for (const p of problems) console.error("  -", p);
  process.exit(1);
}
console.log(`spec-eval-diff: PASS（F1 11/11 与 oracle 双侧全等；F6-M1 向量 ${Object.keys(evidence.f6).length} 组逐值全等）`);
console.log("spec-eval-diff: 证据 → artifacts/diff/M1.2a-spec-eval.json");

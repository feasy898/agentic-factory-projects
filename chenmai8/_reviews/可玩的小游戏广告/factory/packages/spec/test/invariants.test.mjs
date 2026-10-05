// packages/spec/test/invariants.test.mjs — M1.2a 算例逐值对齐测试（冻结数值向量，决策 §3.2 F6 的 M1 子集）。
//
// 向量来源：
//   [spec-contract §2.3]  LCG 三自由度算例（"已过真实 gate"的发布值）：bad02 seed=424242
//     首两抽 %3=[2,0] → L0 rescuee=2/hazard=0；golden seed=20260930 的 6×6×5 盘面
//     find_move=(0,2,1,2)。
//   [match3 规则卡 §12]   算例 B（恰一合法步盘）与 C（死局拉丁方）——校验器侧
//     match3FindMove 与模板 allMoves 同扫描语义（right/down 去重）的逐值对齐。
//   [oracle 权威实测]     其余向量为 repo Python 权威 pfcore.invariants 实跑输出
//     （2026-09-30，只读 venv），并经 scripts/diff/spec-eval-diff.mjs 与新 TS 实现
//     程序化逐值比对全等后冻结于此。
// 注：mulberry32/deriveRng、FNV 形状调色板等模板侧向量属 M3 模板包逻辑测试
//   （决策 §2.1 M3 行、批次 2），不在本模块。

import { test } from "node:test";
import assert from "node:assert/strict";
import {
  Lcg,
  match3Board,
  match3FindMove,
  pullpinLevelRoles,
  pullpinSimulate,
  sortSolvedBoard,
  sortLegalMoves,
  sortApplyMove,
  sortInverseLegal,
  sortScramble,
  checkInvariants,
  registerTemplateCheck,
  listTemplateChecks,
  clearTemplateChecks,
  LCG_A,
  LCG_C,
  MASK32,
  REQUIRED_STRING_KEYS,
  MATCH3_DEFAULTS,
  MERGE_DEFAULTS,
  PULLPIN_DEFAULTS,
  SORT_DEFAULTS,
  MAX_DURATION_SEC,
  PULLPIN_REROLL_MAX,
} from "../src/invariants.ts";

// ---------------------------------------------------------------- LCG 三自由度（spec-contract §2.3）

test("常量冻结值（与 oracle pfcore.invariants 逐项同值）", () => {
  assert.equal(LCG_A, 1664525);
  assert.equal(LCG_C, 1013904223);
  assert.equal(MASK32, 0xffffffff);
  assert.deepEqual([...REQUIRED_STRING_KEYS], ["cta", "tutorial", "win", "lose", "score"]);
  assert.deepEqual(MATCH3_DEFAULTS, {
    cols: 6, rows: 6, moves: 15, colors: 5,
    goalType: "clear-jelly", goalCount: 30,
    spriteKeys: ["piece-0", "piece-1", "piece-2", "piece-3", "piece-4"],
  });
  assert.deepEqual(MERGE_DEFAULTS, {
    cols: 5, rows: 5, maxTier: 5, spawnTierMax: 2, goalTier: 4,
    spriteKeys: ["tier-1", "tier-2", "tier-3", "tier-4", "tier-5"],
  });
  assert.deepEqual(PULLPIN_DEFAULTS, { levels: 3, pinsPerLevel: 3, hazard: "lava", rescuee: "character" });
  assert.deepEqual(SORT_DEFAULTS, { rods: 4, layersPerRod: 4, colors: 4, screwMode: false });
  assert.equal(PULLPIN_REROLL_MAX, 16);
  assert.equal(MAX_DURATION_SEC, 30);
});

test("自由度①先推进后取值：bad02 seed=424242 首两抽 %3 = [2,0]（§2.3 发布算例）", () => {
  const rng = new Lcg(424242);
  assert.deepEqual([rng.below(3), rng.below(3)], [2, 0]);
  // 同一 seed 的 nextU32 原始序列（Python 权威实测冻结）。
  const r = new Lcg(1);
  assert.deepEqual(Array.from({ length: 5 }, () => r.nextU32()),
    [1015568748, 1586005467, 2165703038, 3027450565, 217083232]);
});

test("自由度②单流跨关卡：pullpinLevelRoles 连抽共享一流（Python 权威实测冻结）", () => {
  assert.deepEqual(pullpinLevelRoles(424242, 2, 3), [[2, 0], [0, 2]]);
  assert.deepEqual(pullpinLevelRoles(20260930, 3, 3), [[2, 1], [1, 0], [1, 0]]);
});

test("自由度③各生成器独立建流：同一 seed 下各生成器输出其自有流（Python 权威实测冻结）", () => {
  // golden-match3 seed=20260930 的 6×6×5 LCG 盘面（整盘逐值）。
  assert.deepEqual(match3Board(20260930, 6, 6, 5), [
    [1, 0, 0, 3, 1, 4],
    [3, 2, 1, 4, 3, 2],
    [0, 4, 0, 1, 1, 2],
    [3, 3, 0, 3, 3, 4],
    [3, 1, 2, 1, 3, 1],
    [1, 2, 1, 3, 2, 4],
  ]);
  assert.deepEqual(match3FindMove(match3Board(20260930, 6, 6, 5)), [0, 2, 1, 2]);
  // bad02 同 seed 下 match3 盘面与 pullpin 角色互不干扰（独立建流的可观测差异）。
  assert.deepEqual(match3Board(424242, 6, 6, 5), [
    [4, 2, 4, 2, 1, 4],
    [4, 0, 2, 4, 4, 4],
    [4, 1, 2, 2, 4, 3],
    [3, 0, 1, 1, 1, 3],
    [1, 2, 0, 4, 0, 1],
    [2, 3, 1, 2, 1, 3],
  ]);
  assert.deepEqual(match3FindMove(match3Board(424242, 6, 6, 5)), [0, 0, 0, 1]);
  // sortScramble 独立建流：整迹逐值（golden-sort 参数 5×4×4，seed=20260930）。
  const [board, trace] = sortScramble(20260930, 5, 4, 4);
  assert.deepEqual(board, [[2, 2, 2, 2], [1, 1, 1, 1], [], [3, 3, 3, 3], [0, 0, 0, 0]]);
  assert.equal(trace.length, 20);
  assert.deepEqual(trace.slice(0, 4), [[1, 4, 4], [0, 1, 4], [4, 0, 4], [2, 4, 4]]); // 整迹经 diff harness 与 Python 全等
  // 退化边界（colors == rods、无空柱 → 首步无候选即停）：trace 0、盘面不动（Python 权威实测冻结）。
  const [b2, t2] = sortScramble(424242, 4, 4, 4);
  assert.deepEqual(b2, [[0, 0, 0, 0], [1, 1, 1, 1], [2, 2, 2, 2], [3, 3, 3, 3]]);
  assert.equal(t2.length, 0);
});

// ---------------------------------------------------------------- 规则卡 §12 算例 B/C（校验器侧逐值对齐）

test("规则卡 §12 算例 B（恰一合法步盘）：find_move 命中唯一可行步 (0,1)-(1,1)", () => {
  const B = [
    [1, 0, 1],
    [2, 1, 2],
    [0, 0, 2],
  ];
  // 卡面：allMoves 恰为 {x:1, y:0, dir:"down"}（交换 (0,1)-(1,1) 后 row0 成 [1,1,1]）；
  // 校验器扫描序（行优先、dir right→down）下首个可行步即该唯一步。
  assert.deepEqual(match3FindMove(B), [0, 1, 1, 1]);
  // 探测后盘面必须复原（幂等，可重复调用）。
  assert.deepEqual(match3FindMove(B), [0, 1, 1, 1]);
});

test("规则卡 §12 算例 C（死局拉丁方）：任何相邻交换不成 run → null", () => {
  const C = [
    [0, 1, 2],
    [1, 2, 0],
    [2, 0, 1],
  ];
  assert.equal(match3FindMove(C), null);
});

// ---------------------------------------------------------------- I1/I2 语义单元

test("I1 模拟与 bad02 逐值复现：L0 rescuee=针2/hazard=针0，order [0,1,2] 首拔即机关针", () => {
  const roles = pullpinLevelRoles(424242, 2, 3);
  assert.deepEqual(roles[0], [2, 0]); // rescuee=2, hazard=0
  const [solved, reason] = pullpinSimulate([0, 1, 2], roles[0][0], roles[0][1]);
  assert.equal(solved, false);
  assert.equal(reason, "机关针在救援针之前被拔出");
  // 正例：先拔 rescuee → 成；未拔到 → 败。
  assert.deepEqual(pullpinSimulate([2, 0], 2, 0)[0], true);
  assert.deepEqual(pullpinSimulate([0, 1], 2, 0)[0], false);
});

test("I2 基元：已解盘面 / 合法走法 / 逆步判据（Python 权威实测冻结）", () => {
  assert.deepEqual(sortSolvedBoard(4, 4, 4), [[0, 0, 0, 0], [1, 1, 1, 1], [2, 2, 2, 2], [3, 3, 3, 3]]);
  assert.deepEqual(sortSolvedBoard(3, 4, 5), [[0, 0, 0, 0], [1, 1, 1, 1], [2, 2, 2, 2]]); // filled=min(5,3)
  assert.deepEqual(sortLegalMoves([[0, 0], [1, 1], []], 2), [[0, 2, 2], [1, 2, 2]]);
  const board = [[0, 0], [1, 1], []];
  sortApplyMove(board, 1, 2, 1);
  assert.deepEqual(board, [[0, 0], [1], [1]]);
  assert.equal(sortInverseLegal(board, 2, 1, 1, 2), true);  // 搬回：src 空位够、dst 顶同色
  assert.equal(sortInverseLegal([[0], [1, 1]], 1, 0, 2, 2), false); // 超容量
});

// ---------------------------------------------------------------- 内建不变式分支（默认值解析 + 错误码路径）

test("merge 轻量不变式：三条码与路径（缺省值经 *_DEFAULTS 解析）", () => {
  const spec = { game: { template: "merge", params: { maxTier: 6, spawnTierMax: 0, goalTier: 7 } } };
  const got = checkInvariants(spec).map((e) => [e.path, e.code]).sort();
  assert.deepEqual(got, [
    ["$.game.params.goalTier", "I-merge-goal"],
    ["$.game.params.maxTier", "I-merge-sprites"],
    ["$.game.params.spawnTierMax", "I-merge-spawn"],
  ]);
});

test("I4 双保险：target > max → I4-duration-target（max ≤ 30 由 I4 层复算）", () => {
  const spec = { game: { template: "match3", params: {}, durationBudgetSec: { target: 25, max: 20 } } };
  const got = checkInvariants(spec).map((e) => [e.path, e.code]).sort();
  assert.deepEqual(got, [
    ["$.game.durationBudgetSec.target", "I4-duration-target"],
  ]);
});

test("I5：rtl ⊄ locales 与 defaultLocale ∉ locales 的码与路径", () => {
  const spec = {
    game: { template: "match3", params: {} },
    i18n: { defaultLocale: "fr", locales: ["en"], strings: { en: { cta: "x", tutorial: "x", win: "x", lose: "x", score: "x" } }, rtl: ["ar", "en"] },
  };
  const got = checkInvariants(spec).map((e) => [e.path, e.code]).sort();
  assert.deepEqual(got, [
    ["$.i18n.defaultLocale", "I5-i18n-default"],
    ["$.i18n.rtl[0]", "I5-i18n-rtl"],
  ]);
});

// ---------------------------------------------------------------- P1 接缝：模板 check(spec) 注册制

test("注册制：新增玩法只改模板包一处（P1 目标形态演示，决策 §3.4）", () => {
  clearTemplateChecks();
  assert.deepEqual(listTemplateChecks(), []);
  const hits = [];
  registerTemplateCheck({
    template: "fifth",
    check: (spec) => { hits.push(spec); return [{ path: "$.game.params", message: "第 5 玩法模板侧校验命中", code: "T5-demo" }]; },
  });
  registerTemplateCheck({
    template: "match3",
    check: () => [{ path: "$", message: "不该触发", code: "T5-misfire" }],
  });
  assert.deepEqual(listTemplateChecks(), ["fifth", "match3"]);
  const spec = { game: { template: "fifth", params: {} }, i18n: { locales: [], strings: {} } };
  const got = checkInvariants(spec);
  assert.deepEqual(got.map((e) => [e.path, e.code]), [["$.game.params", "T5-demo"]]);
  assert.equal(hits.length, 1); // 仅 template 匹配者被调用
  clearTemplateChecks();
  assert.deepEqual(listTemplateChecks(), []);
  // 清空后恢复内建语义（fifth 无内建分支 → 无 issue）。
  assert.deepEqual(checkInvariants(spec), []);
});

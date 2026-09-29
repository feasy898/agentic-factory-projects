// sort 逻辑自测（开发期临时文件，不入构建产物；纯逻辑、无 DOM，Node 直跑）：
//  node --experimental-strip-types tests/logic-test.ts
//  冻结数值向量按 oracle tests/logic-test.ts 原样复用（"语义冻结、宿主移植"——
//  Python 权威侧实算回填的期望值逐值不动；宿主从 oracle 五重镜像改为 @pf/spec 单源，
//  决策 §2.1 P1）：
//  1) 规范扰动镜像冻结向量：golden seed 与 pfcore.invariants.sort_scramble（Python
//     权威侧）盘面一致（python -c "from pfcore.invariants import sort_scramble; \
//     print(sort_scramble(20260930, 5, 4, 4)[0])"
//     → [[2, 2, 2, 2], [1, 1, 1, 1], [], [3, 3, 3, 3], [0, 0, 0, 0]]，20 步迹）；
//  2) LCG 与 Python 同余（seed 12345 前三拍 + 扰动流延续 20 拍后，实算回填）；
//  3) 冻结走法语义：legalMoves 与 Python 权威侧一致，BFS 最优解可回放至胜；
//  4) 规范扰动性质证明：从已解态出发的扰动盘面恒为"每柱单色"（深化发牌的依据）；
//  5) 深化发牌：golden seed 确定性产出真实谜题（非开局即胜、BFS 可解、步数达标）；
//  6) 跨 seed/参数批量：发牌可解 + 最优步数 ≤ moveLimit + 解可回放；
//  7) moveLimit 严格生效：小预算（=6）下收下的发牌最优步数必 ≤ 6；
//  8) isSolved/completedColors/topRun 判定单测。
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { Lcg } from "@pf/spec";
import {
  applyMove,
  cloneBoard,
  completedColors,
  isSolved,
  legalMoves,
  solvedBoard,
  sortScramble,
  topRun,
  type Board,
} from "../src/board.ts";
import { solveOptimal, greedyMove, SolutionCache } from "../src/solver.ts";
import { dealInitialBoard } from "../src/deal.ts";
import { normalizeSpec } from "../src/spec.ts";

let pass = 0, fail = 0;
const check = (name: string, ok: boolean) => {
  ok ? pass++ : fail++;
  console.log(`${ok ? "PASS" : "FAIL"} ${name}`);
};

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../../..");

// 1) 规范扰动镜像冻结向量（golden seed 实算回填，逐值不动）
const [goldenCanonical, goldenTrace] = sortScramble(20260930, 5, 4, 4);
check(
  "golden seed 规范扰动盘面与 pfcore.invariants 一致（20 步迹）",
  JSON.stringify(goldenCanonical) === "[[2,2,2,2],[1,1,1,1],[],[3,3,3,3],[0,0,0,0]]" &&
    goldenTrace.length === 20,
);

// 2) LCG 与 Python 同余（seed 12345 前三拍，python 实算回填）
const lcg = new Lcg(12345);
const seq = [lcg.nextU32(), lcg.nextU32(), lcg.nextU32()];
check(
  "LCG 与 Python 同余（seed 12345 前三拍）",
  JSON.stringify(seq) === JSON.stringify([87628868, 71072467, 2332836374]),
);
// 扰动流延续：golden seed 消费 20 拍后的后三拍（python 实算回填
// → [2324266125, 919565448, 246287943]），深化发牌与镜像同源有序的根据
const rng2 = new Lcg(20260930);
for (let i = 0; i < 20; i++) rng2.nextU32();
check(
  "LCG 扰动流延续与 Python 同余（golden seed 消费 20 拍后）",
  JSON.stringify([rng2.nextU32(), rng2.nextU32(), rng2.nextU32()]) ===
    JSON.stringify([2324266125, 919565448, 246287943]),
);

// 3) 冻结走法语义（与 python sort_legal_moves 对固定盘面的实算一致）：
//    [[0,1],[1,0],[]] layers=2 → [(0,2,1),(1,2,1)]；最优解恰 3 步且可回放至胜
const fixture: Board = [[0, 1], [1, 0], []];
const fixtureMoves = legalMoves(fixture, 2).map((m) => [m.src, m.dst, m.k]);
check(
  "legalMoves 与 Python 权威侧一致（固定盘面）",
  JSON.stringify(fixtureMoves) === "[[0,2,1],[1,2,1]]",
);
const fixtureSol = solveOptimal(fixture, 2);
const replay = cloneBoard(fixture);
if (fixtureSol) for (const m of fixtureSol) applyMove(replay, m.src, m.dst, m.k);
check(
  "BFS 最优解恰 3 步且逐回放至胜（同 M1 走法语义）",
  !!fixtureSol && fixtureSol.length === 3 && isSolved(replay, 2),
);

// 4) 规范扰动性质证明：从已解态出发的扰动盘面恒为"每柱单色或空"
//    （整柱搬运保持单色柱性质——这正是模板深化发牌存在的原因）
let mono = true;
for (let s = 0; s < 40 && mono; s++) {
  const [b] = sortScramble(1 + s * 7919, 5, 4, 4);
  for (const rod of b) {
    if (rod.length && rod.some((c) => c !== rod[0])) mono = false;
  }
}
check("40 seed 规范扰动盘面恒为每柱单色（深化发牌依据的运行期证明）", mono);

// 5) 深化发牌（golden）：确定性、非开局即胜、可解、步数 ≤ moveLimit
const goldenRaw = JSON.parse(readFileSync(path.join(ROOT, "specs-eval", "golden-sort.json"), "utf8"));
const goldenSpec = normalizeSpec(goldenRaw);
check(
  "golden normalizeSpec：rods=5 layersPerRod=4 colors=4 moveLimit=30 screwMode=false",
  goldenSpec.params.rods === 5 && goldenSpec.params.layersPerRod === 4 &&
    goldenSpec.params.colors === 4 && goldenSpec.params.moveLimit === 30 &&
    goldenSpec.params.screwMode === false,
);
const dealA = dealInitialBoard(goldenSpec.seed, {
  rods: goldenSpec.params.rods,
  layersPerRod: goldenSpec.params.layersPerRod,
  colors: goldenSpec.params.colors,
  moveLimit: goldenSpec.params.moveLimit,
});
const dealB = dealInitialBoard(goldenSpec.seed, {
  rods: goldenSpec.params.rods,
  layersPerRod: goldenSpec.params.layersPerRod,
  colors: goldenSpec.params.colors,
  moveLimit: goldenSpec.params.moveLimit,
});
const dealReplay = cloneBoard(dealA.board);
if (dealA.optimal) for (const m of dealA.optimal) applyMove(dealReplay, m.src, m.dst, m.k);
check(
  "golden 发牌：确定性 + 深化真实谜题 + 最优解回放至胜 + 步数 ≤ moveLimit",
  JSON.stringify(dealA.board) === JSON.stringify(dealB.board) &&
    dealA.deepened === true &&
    !isSolved(dealA.board, 4) &&
    dealA.optimal.length >= 2 && dealA.optimal.length <= 30 &&
    isSolved(dealReplay, 4),
);
console.log(
  `       (golden 发牌最优 ${dealA.optimal.length} 步：${dealA.optimal.map((m) => `${m.src}->${m.dst}x${m.k}`).join(" ")})`,
);

// 6) 跨 seed/参数批量：发牌可解 + 深化成功 + 最优步数 ≤ 预算 + 贪心兜底不崩
const PARAMS: Array<[number, number, number]> = [[4, 4, 3], [5, 4, 4], [6, 4, 5], [4, 3, 3]];
let sweepOk = true;
let sweepSolved = 0;
outer: for (let s = 0; s < 60; s++) {
  const seed = 1 + s * 7919;
  for (const [rods, layers, colors] of PARAMS) {
    const d = dealInitialBoard(seed, { rods, layersPerRod: layers, colors, moveLimit: 40 });
    if (!d.deepened) { sweepOk = false; break outer; }
    if (isSolved(d.board, layers)) { sweepOk = false; break outer; }
    const rp = cloneBoard(d.board);
    for (const m of d.optimal) applyMove(rp, m.src, m.dst, m.k);
    if (!isSolved(rp, layers) || d.optimal.length > 40) { sweepOk = false; break outer; }
    if (d.optimal.length >= 2) sweepSolved++;
    if (!greedyMove(d.board, layers)) { sweepOk = false; break outer; }
  }
}
check("60 seed × 4 组参数：发牌全深化可解、最优 ≤ 40、解可回放、贪心兜底有解", sweepOk);

// 7) moveLimit 严格生效：预算 6 下收下的发牌最优步数必 ≤ 6
let limitOk = true;
for (let s = 0; s < 30 && limitOk; s++) {
  const d = dealInitialBoard(1 + s * 104729, { rods: 5, layersPerRod: 4, colors: 4, moveLimit: 6 });
  if (d.deepened && d.optimal.length > 6) limitOk = false;
}
check("moveLimit=6：深化发牌最优步数全部 ≤ 6（预算内必可胜）", limitOk);

// 8) 判定单测：solvedBoard/isSolved/completedColors/topRun
const sb = solvedBoard(5, 4, 4);
check(
  "solvedBoard：4 色满柱 + 1 空柱，isSolved=true，completedColors=4",
  JSON.stringify(sb) === "[[0,0,0,0],[1,1,1,1],[2,2,2,2],[3,3,3,3],[]]" &&
    isSolved(sb, 4) && completedColors(sb, 4) === 4,
);
const partial: Board = [[0, 0], [], [1, 1, 1]];
check(
  "isSolved：未满的同色柱不算完成（严格满柱判定）",
  !isSolved(partial, 4) && completedColors(partial, 4) === 0 && topRun(partial[2])?.run === 3,
);

// 9) SolutionCache：同盘面复用同一解
const cache = new SolutionCache();
const s1 = cache.solution(fixture, 2);
const s2 = cache.solution(fixture, 2);
check("SolutionCache：同盘面返回同一解（缓存命中）", s1 === s2 && !!s1 && s1.length === 3);

console.log(`logic-test: ${pass} pass / ${fail} fail`);
if (fail) process.exit(1);

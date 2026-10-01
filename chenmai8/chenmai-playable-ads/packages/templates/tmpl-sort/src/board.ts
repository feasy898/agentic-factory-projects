// 排序盘面纯逻辑 —— python/pfcore/invariants.py sort 段与
// packages/spec/src/invariants.mjs 的模板侧镜像（LCG 参数、合法走法、
// apply/逆步判定、规范扰动逐行对应，任何一侧改动都视为破坏 schema v1 冻结契约）。
//
// 冻结走法语义（开发指令 §4.1 + M1 不变式 I2）：
//   - 一半是"倾倒"：把 src 顶部的同色连续段（run）整段倒向 dst，
//     k = min(run, dst 空位)；dst 必须为空或顶同色。
//   - 规范扰动 sortScramble：从已解盘面出发，只挑"逆步合法"的走法
//     （把刚搬的 k 个原路搬回也必须是合法走法），由 LCG 确定性迭代
//     rods*layersPerRod 步——可逆 ⇒ 与已解态连通 ⇒ 必有解。
// 全部函数无 DOM 依赖，可在 Node 下单测。

import { Lcg } from "./rng.ts";

/** 盘面：rods 根柱，每柱自底向上的颜色下标栈。 */
export type Board = number[][];

/** 一步倾倒：把 src 顶部同色段搬 k 层到 dst。 */
export interface SortMove {
  src: number;
  dst: number;
  k: number;
}

/** 已解状态：前 min(colors, rods) 根各为一色满柱，其余为空柱（冻结生成器基态）。 */
export function solvedBoard(rods: number, layersPerRod: number, colors: number): Board {
  const filled = Math.min(colors, rods);
  const board: Board = [];
  for (let c = 0; c < filled; c++) board.push(Array(layersPerRod).fill(c));
  while (board.length < rods) board.push([]);
  return board;
}

/** 顶部同色段：{color, run}；空柱返回 null。 */
export function topRun(rod: number[]): { color: number; run: number } | null {
  if (!rod.length) return null;
  const color = rod[rod.length - 1];
  let run = 1;
  while (run < rod.length && rod[rod.length - 1 - run] === color) run++;
  return { color, run };
}

/** 合法走法表（同色顶段整体搬移，k = min(顶段长, 空位)——与 M1 冻结一致）。 */
export function legalMoves(board: Board, layersPerRod: number): SortMove[] {
  const moves: SortMove[] = [];
  board.forEach((rod, src) => {
    const top = topRun(rod);
    if (!top) return;
    for (let dst = 0; dst < board.length; dst++) {
      if (dst === src) continue;
      const drod = board[dst];
      const space = layersPerRod - drod.length;
      if (space <= 0) continue;
      if (drod.length && drod[drod.length - 1] !== top.color) continue;
      moves.push({ src, dst, k: Math.min(top.run, space) });
    }
  });
  return moves;
}

/** 原地应用一步（假定已合法；调用方负责先查 legalMoves）。 */
export function applyMove(board: Board, src: number, dst: number, k: number): void {
  const color = board[src][board[src].length - 1];
  for (let i = 0; i < k; i++) {
    board[src].pop();
    board[dst].push(color);
  }
}

/** 逆步（把刚搬的 k 个从 dst 原路搬回 src）是否为合法走法——可逆性判据。 */
export function inverseLegal(
  board: Board,
  src: number,
  dst: number,
  k: number,
  layersPerRod: number,
): boolean {
  const color = board[dst][board[dst].length - k];
  const s = board[src];
  if (s.length + k > layersPerRod) return false;
  return s.length === 0 || s[s.length - 1] === color;
}

/**
 * 规范扰动（M1 I2 权威镜像）：由已解状态经"逆步合法"走法扰动出初始盘面。
 * 返回 [盘面, 步迹]；M1 validator 逐步重放步迹做栈可逆校验。
 *
 * 注（模板深化发牌的依据，见 deal.ts）：从已解态出发，合法走法只能整柱搬运
 * （顶段 run = 满柱层数、空位 = 满柱层数 ⇒ k 取满），单色柱性质在扰动下保持，
 * 因此规范扰动盘面恒为"每柱单色"的已解态排列——真实谜题由深化发牌生成，
 * 规范扰动保留为冻结镜像基线与兜底。
 */
export function sortScramble(
  seed: number,
  rods: number,
  layersPerRod: number,
  colors: number,
): [Board, SortMove[]] {
  const rng = new Lcg(seed);
  const board = solvedBoard(rods, layersPerRod, colors);
  const trace: SortMove[] = [];
  for (let step = 0; step < rods * layersPerRod; step++) {
    const cands = legalMoves(board, layersPerRod).filter((m) => {
      const trial = board.map((rod) => rod.slice());
      applyMove(trial, m.src, m.dst, m.k);
      return inverseLegal(trial, m.src, m.dst, m.k, layersPerRod);
    });
    if (!cands.length) break;
    const mv = cands[rng.below(cands.length)];
    applyMove(board, mv.src, mv.dst, mv.k);
    trace.push(mv);
  }
  return [board, trace];
}

/** 胜利判定（经典排序规则）：每根柱要么为空，要么是单色满柱。 */
export function isSolved(board: Board, layersPerRod: number): boolean {
  return board.every(
    (rod) => rod.length === 0 || (rod.length === layersPerRod && rod.every((c) => c === rod[0])),
  );
}

/** 已完成色数：存在"该色满柱"的颜色个数（HUD 进度/得分用）。 */
export function completedColors(board: Board, layersPerRod: number): number {
  const done = new Set<number>();
  for (const rod of board) {
    if (rod.length === layersPerRod && rod.every((c) => c === rod[0])) done.add(rod[0]);
  }
  return done.size;
}

/** 盘面规范化键（柱集合无序化——同构状态在求解器备忘表中命中同一键）。 */
export function boardKey(board: Board): string {
  return board.map((rod) => rod.join(",")).sort().join("|");
}

/** 深拷贝。 */
export function cloneBoard(board: Board): Board {
  return board.map((rod) => rod.slice());
}

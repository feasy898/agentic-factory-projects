// 初始盘面发牌：冻结规范扰动镜像（基线）+ 同流深化发牌（真实谜题）+ BFS 验收。
//
// 为什么需要"深化发牌"（如实留档的设计决定）：
//   M1 冻结的 sortScramble（@pf/spec 单源，见 board.ts）从已解态出发、只走"逆步合法"
//   的走法。从已解态看，每根柱要么满柱单色要么空 ⇒ 顶段 run=满柱层数、任意 dst 空位
//   ≥ 该值 ⇒ k 恒取满柱层数，即每步都是整柱搬运；单色柱性质在整柱搬运下保持。
//   由归纳法，规范扰动盘面恒为"每柱单色"的已解态排列——对它开局即胜（isSolved=true）。
//   因此模板在冻结镜像之上，用同一 LCG 流的延续做确定性"洗牌发牌"，并用与冻结
//   走法同源的 BFS 求解器验收"可解 + 非开局即胜 + 最优步数 ≤ moveLimit"——
//   与 tmpl-match3 的"生成期可玩性校验 + 64 次重生成"同一先例。发牌算法属模板
//   内部实现（M1 不变式约束的是种子扰动过程的良构性，不向模板传递盘面——
//   spec 里没有初始盘面字段），渲染盘面的可解性由模板自查兜底。
//
// 确定性：seed 相同 ⇒ 发牌相同（LCG 洗牌 + 固定验收序），跨实现可复现。

import { sortScramble, isSolved, type Board, type SortMove } from "./board.ts";
import { solveOptimal } from "./solver.ts";
// invariants 叶子（@pf/spec 桶入口含 ajv 校验器，不得打进游戏 HTML——零外链红线）。
import { Lcg } from "@pf/spec/invariants";

/** 发牌重试上限（与 match3 的 64 次重生成同一先例）。 */
export const DEAL_RETRY_MAX = 64;

/** 发牌质量下限：最优解至少这么多步（防"一步倒完"的平庸开局）。 */
export const MIN_OPTIMAL_LEN = 2;

/** 发牌验收条件。 */
export interface DealOptions {
  rods: number;
  layersPerRod: number;
  colors: number;
  /** 0 = 不限步数；>0 时要求最优解 ≤ moveLimit（保证步数预算内可胜）。 */
  moveLimit: number;
}

/** 发牌结果：盘面 + 该盘面的最优解（发牌期已算好，hint 直接复用）。 */
export interface DealResult {
  board: Board;
  optimal: SortMove[];
  /** 是否为深化发牌（false = 回退冻结规范扰动盘面，开局即胜的诚实兜底）。 */
  deepened: boolean;
  /** 发牌尝试次数（诊断用）。 */
  attempts: number;
}

function fisherYatesPieces(rng: Lcg, layersPerRod: number, colors: number): number[] {
  const pieces: number[] = [];
  for (let c = 0; c < colors; c++) {
    for (let i = 0; i < layersPerRod; i++) pieces.push(c);
  }
  for (let i = pieces.length - 1; i > 0; i--) {
    const j = rng.below(i + 1);
    const t = pieces[i];
    pieces[i] = pieces[j];
    pieces[j] = t;
  }
  return pieces;
}

function dealOnce(rng: Lcg, rods: number, layersPerRod: number, colors: number): Board {
  const pieces = fisherYatesPieces(rng, layersPerRod, colors);
  const board: Board = [];
  for (let r = 0; r < rods; r++) {
    const from = r * layersPerRod;
    board.push(from < pieces.length ? pieces.slice(from, from + layersPerRod) : []);
  }
  return board;
}

/**
 * 由 seed 确定性产出初始盘面：
 *   1) 消费冻结规范扰动的 LCG 拍数（镜像基线，见 sortScramble）；
 *   2) 同一 LCG 流延续驱动洗牌发牌（逐柱装满前 colors 根，其余空柱）；
 *   3) BFS 验收：可解 && 非开局即胜 && 最优步数 ≥ MIN_OPTIMAL_LEN &&
 *      （moveLimit>0 时）最优步数 ≤ moveLimit；不合格换一把重发（≤64 次）。
 *   4) 64 次仍无（病态参数）→ 回退冻结规范扰动盘面并如实返回 deepened=false
 *      （开局即胜的诚实兜底，场景 create() 会即时胜出并告警）。
 */
export function dealInitialBoard(seed: number, opts: DealOptions): DealResult {
  const { rods, layersPerRod, colors, moveLimit } = opts;
  // 1) 冻结镜像基线（同时计量其 LCG 消耗，保证深化流与镜像同源有序）
  const [canonical, trace] = sortScramble(seed, rods, layersPerRod, colors);
  const rng = new Lcg(seed);
  for (let i = 0; i < trace.length; i++) rng.nextU32();

  // 2)+3) 同流深化发牌 + BFS 验收
  for (let attempt = 1; attempt <= DEAL_RETRY_MAX; attempt++) {
    const board = dealOnce(rng, rods, layersPerRod, colors);
    if (isSolved(board, layersPerRod)) continue;
    const optimal = solveOptimal(board, layersPerRod);
    if (!optimal || optimal.length < MIN_OPTIMAL_LEN) continue;
    if (moveLimit > 0 && optimal.length > moveLimit) continue;
    return { board, optimal, deepened: true, attempts: attempt };
  }

  // 4) 诚实兜底：回退冻结规范扰动盘面（每柱单色，开局即胜）
  return { board: canonical, optimal: [], deepened: false, attempts: DEAL_RETRY_MAX };
}

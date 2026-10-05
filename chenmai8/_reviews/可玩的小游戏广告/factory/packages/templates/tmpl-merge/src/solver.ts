// 提示求解器（templates.md §7.1）：枚举全部有效合成并完整结算，取
// "新阶×1000（向 goalTier 收敛）+ 得分×2" 最高的那步。hint() 返回的就是
// 这里的真实最优步坐标。游戏侧=模拟侧单实现，随机流天然一致。
//
// 随机流调度（冻结）：第 k 次玩家合成（1 起）的补位流 = deriveRng(seed, SPAWN_SALT ^ k)，
// 死局重排流 = deriveRng(seed, RESHUFFLE_SALT ^ k)。生成期 simulatePlay 按
// 同一调度推进，因此"贪心模拟可胜" ⇔ "hint 引导可胜"。

import {
  allMerges,
  rearrangeGrid,
  resolveMerge,
  type MergeMove,
  type MergeResult,
} from "./board.ts";
import { deriveRng } from "./rng.ts";

/** 第 k 次玩家合成的补位随机流盐（游戏侧与模拟侧共用同一常量）。 */
export const SPAWN_SALT = 0x4c7a11e5;
/** 第 k 次死局重排的随机流盐（游戏侧与模拟侧共用同一常量）。 */
export const RESHUFFLE_SALT = 0x5117;

export interface SolverContext {
  cols: number;
  rows: number;
  maxTier: number;
  spawnTierMax: number;
  seed: number;
  /** 目标阶（达成即胜）。 */
  goalTier: () => number;
  /** 下一次玩家合成的 k（1 起），决定补位随机流。 */
  salt: () => number;
}

export interface MergeEval {
  move: MergeMove;
  result: MergeResult;
  value: number;
}

/** 给定盐下取最优合成步：每个候选各自从 deriveRng(seed, salt) 新建流
 *  （候选间同流、逐候选重置，保证可比）；并列时严格更大才替换（取枚举序靠前）。 */
function pickBest(ctx: SolverContext, grid: number[], salt: number): MergeEval | null {
  let best: MergeEval | null = null;
  for (const move of allMerges(grid, ctx.cols, ctx.rows, ctx.maxTier)) {
    const simRng = deriveRng(ctx.seed, salt);
    const result = resolveMerge(grid, ctx.cols, ctx.rows, ctx.maxTier, ctx.spawnTierMax, move, simRng);
    if (!result) continue;
    const value = result.newTier * 1000 + result.score * 2;
    if (best === null || value > best.value) best = { move, result, value };
  }
  return best;
}

/** 当前盘面的最优合成步（真实最优：完整结算全部候选）。 */
export function bestMerge(ctx: SolverContext, grid: number[]): MergeEval | null {
  return pickBest(ctx, grid, ctx.salt());
}

/**
 * 贪心模拟整局（生成期可玩性校验）：每步取最优，直至盘面出现 goalTier 或步数
 * 用尽。补位/重排流调度与真实游玩一致：第 k 步 SPAWN_SALT ^ k / RESHUFFLE_SALT ^ k。
 */
export function simulatePlay(
  ctx: SolverContext,
  grid0: number[],
  moveBudget: number,
): { win: boolean; movesUsed: number; score: number; maxTier: number } {
  let grid = grid0.slice();
  let score = 0;
  let maxTier = grid.reduce((m, t) => Math.max(m, t), 0);
  let k = 1;
  let reshuffles = 0;
  const goal = ctx.goalTier();
  while (k <= moveBudget && reshuffles < 16) {
    if (maxTier >= goal) return { win: true, movesUsed: k - 1, score, maxTier };
    const best = pickBest(ctx, grid, SPAWN_SALT ^ k);
    if (!best) {
      // 死局：保留棋子重排（不消耗步数）。
      grid = rearrangeGrid(
        grid, ctx.cols, ctx.rows, ctx.maxTier, ctx.spawnTierMax,
        deriveRng(ctx.seed, RESHUFFLE_SALT ^ k),
      );
      reshuffles++;
      continue;
    }
    grid = best.result.finalGrid;
    score += best.result.score;
    maxTier = Math.max(maxTier, best.result.newTier);
    if (maxTier >= goal) return { win: true, movesUsed: k, score, maxTier };
    k++;
  }
  return { win: false, movesUsed: Math.min(k - 1, moveBudget), score, maxTier };
}

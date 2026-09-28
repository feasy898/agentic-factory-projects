// 提示求解器：枚举全部可行交换并完整模拟连消，取“果冻进度×大权重 +
// 得分 + 连消奖励”最高的那步。hint() 返回的就是这里的真实最优步坐标。
//
// 随机流约定（与游戏侧 playResolve 完全一致，保证 hint 的投影=真实结算）：
// 第 k 次玩家交换（1 起）的补位流 = deriveRng(seed, SPAWN_SALT ^ k)。
// 生成期 simulatePlay 按同一调度推进，因此“贪心模拟可胜”⇔“hint 引导可胜”。

import { Board, type Move, type ResolveResult } from "./board.ts";
import { deriveRng, type Rng } from "./rng.ts";

export type GoalType = "clear-jelly" | "score";

/** 第 k 次玩家交换的补位随机流盐（与游戏侧共用同一常量）。 */
export const SPAWN_SALT = 0x51ed270b;

export interface SolverContext {
  cols: number;
  rows: number;
  colors: number;
  seed: number;
  goalType: GoalType;
  /** 当前进度（已清果冻数或已得分数）。 */
  progress: () => number;
  /** 目标值（goalCount）。 */
  goal: () => number;
  /** 下一次玩家交换的 k（1 起），决定补位随机流。 */
  salt: () => number;
}

export interface MoveEval {
  move: Move;
  jellyCleared: number;
  score: number;
  cascades: number;
  value: number;
}

function countJelly(result: ResolveResult, jelly: boolean[]): number {
  let n = 0;
  for (const i of result.cleared) if (jelly[i]) n++;
  return n;
}

function evaluateMove(
  ctx: SolverContext,
  grid: number[],
  jelly: boolean[],
  move: Move,
  simRng: Rng,
): MoveEval | null {
  const swapped = Board.swap(grid, ctx.cols, ctx.rows, move);
  if (!swapped) return null;
  const mask = Board.matchMask(swapped, ctx.cols, ctx.rows);
  if (!mask.some(Boolean)) return null; // 非法交换不参与
  const result = Board.resolve(swapped, ctx.cols, ctx.rows, ctx.colors, simRng, jelly);
  const jellyGain = countJelly(result, jelly);
  const value =
    ctx.goalType === "clear-jelly"
      ? jellyGain * 1000 + result.score * 2 + result.cascades * 15
      : result.score * 10 + result.cascades * 15;
  return { move, jellyCleared: jellyGain, score: result.score, cascades: result.cascades, value };
}

/** 在给定补位流盐下取最优步（候选间同流，保证可比、逐回合确定性）。 */
function pickBest(ctx: SolverContext, grid: number[], jelly: boolean[], salt: number): MoveEval | null {
  let best: MoveEval | null = null;
  for (const move of Board.allMoves(grid, ctx.cols, ctx.rows)) {
    const simRng = deriveRng(ctx.seed, salt);
    const ev = evaluateMove(ctx, grid, jelly, move, simRng);
    if (ev && (best === null || ev.value > best.value)) best = ev;
  }
  return best;
}

/** 当前盘面的最优步（真实最优：完整模拟全部候选，含连消与补位）。 */
export function bestMove(ctx: SolverContext, grid: number[], jelly: boolean[]): MoveEval | null {
  return pickBest(ctx, grid, jelly, ctx.salt());
}

/**
 * 贪心模拟整局（生成期可玩性校验）：每步取最优，直至达成目标或步数用尽。
 * 补位流调度与真实游玩一致：第 k 步用 SPAWN_SALT ^ k。
 */
export function simulatePlay(
  ctx: SolverContext,
  grid0: number[],
  jelly0: boolean[],
  moveBudget: number,
): { win: boolean; movesUsed: number; progress: number; score: number } {
  let grid = grid0.slice();
  let jelly = jelly0.slice();
  let progress = ctx.progress();
  let score = 0;
  let k = 1;
  let reshuffles = 0;
  while (k <= moveBudget && reshuffles < 16) {
    const localCtx: SolverContext = { ...ctx, progress: () => progress };
    const best = pickBest(localCtx, grid, jelly, SPAWN_SALT ^ k);
    if (!best) {
      // 死局：重摆（保留果冻）；重排不消耗步数
      grid = reshuffleGrid(grid, ctx.cols, ctx.rows, ctx.colors, deriveRng(ctx.seed, 0x5117 ^ k));
      reshuffles++;
      continue;
    }
    const swapped = Board.swap(grid, ctx.cols, ctx.rows, best.move)!;
    const result = Board.resolve(
      swapped, ctx.cols, ctx.rows, ctx.colors,
      deriveRng(ctx.seed, SPAWN_SALT ^ k), jelly,
    );
    const nextJelly = jelly.slice();
    for (const i of result.cleared) nextJelly[i] = false;
    jelly = nextJelly;
    grid = result.finalGrid;
    progress += best.jellyCleared;
    score += best.score;
    const reached =
      ctx.goalType === "clear-jelly" ? progress >= ctx.goal() : ctx.progress() + score >= ctx.goal();
    if (reached) return { win: true, movesUsed: k, progress, score };
    k++;
  }
  return { win: false, movesUsed: k - 1, progress, score };
}

function reshuffleGrid(
  grid: number[],
  cols: number,
  rows: number,
  colors: number,
  rng: Rng,
): number[] {
  for (let guard = 0; guard < 200; guard++) {
    const next = grid.map(() => Math.floor(rng() * colors));
    // 去初始三连
    let bad = false;
    for (let y = 0; y < rows && !bad; y++) {
      for (let x = 2; x < cols; x++) {
        const i = y * cols + x;
        if (next[i] === next[i - 1] && next[i] === next[i - 2]) { bad = true; break; }
      }
    }
    for (let x = 0; x < cols && !bad; x++) {
      for (let y = 2; y < rows; y++) {
        const i = y * cols + x;
        if (next[i] === next[i - cols] && next[i] === next[i - 2 * cols]) { bad = true; break; }
      }
    }
    if (bad) continue;
    if (!Board.hasAnyMove(next, cols, rows)) continue;
    return next;
  }
  return grid;
}

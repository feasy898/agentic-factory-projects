// 排序求解器：BFS 最优解（状态同构去重 + 访问上限）+ 贪心兜底。
// 走法语义经 board.ts 全部落在 @pf/spec 冻结单源（sortLegalMoves/sortApplyMove），
// 因此"求解器认为可解/最优"与校验器的走法判定同源。
//
// hint()（__PF_QC__ 契约）返回当前最优解的第一步真实坐标——自动试玩走
// 最优线必胜；生成期发牌（deal.ts）也用本求解器验收"可解且步数 ≤ moveLimit"。

import {
  applyMove,
  boardKey,
  cloneBoard,
  isSolved,
  legalMoves,
  type Board,
  type SortMove,
} from "./board.ts";

/** BFS 访问状态上限：小盘面（默认 5×4×4 ≈ 数千态）远达不到；超限返回 null。 */
export const SOLVE_VISIT_CAP = 400_000;

/** 已解态的最短解；不可解/超上限返回 null。 */
export function solveOptimal(
  board: Board,
  layersPerRod: number,
  visitCap: number = SOLVE_VISIT_CAP,
): SortMove[] | null {
  if (isSolved(board, layersPerRod)) return [];
  const startKey = boardKey(board);
  const parent = new Map<string, { key: string; move: SortMove }>();
  const visited = new Set<string>([startKey]);
  let frontier: string[] = [startKey];
  const states = new Map<string, Board>([[startKey, cloneBoard(board)]]);
  let solvedKey: string | null = null;

  while (frontier.length && !solvedKey) {
    const next: string[] = [];
    for (const key of frontier) {
      const state = states.get(key)!;
      for (const mv of legalMoves(state, layersPerRod)) {
        const trial = cloneBoard(state);
        applyMove(trial, mv.src, mv.dst, mv.k);
        const trialKey = boardKey(trial);
        if (visited.has(trialKey)) continue;
        visited.add(trialKey);
        states.set(trialKey, trial);
        parent.set(trialKey, { key, move: mv });
        if (isSolved(trial, layersPerRod)) {
          solvedKey = trialKey;
          break;
        }
        next.push(trialKey);
      }
      states.delete(key); // 已展开的层不再保留盘面（省内存；父指针仍在）
      if (solvedKey) break;
      if (visited.size > visitCap) return null;
    }
    frontier = next;
  }
  if (!solvedKey) return null;

  // 回溯路径
  const path: SortMove[] = [];
  let cur = solvedKey;
  while (cur !== startKey) {
    const step = parent.get(cur);
    if (!step) return null; // 理论不可达（父链断裂），按失败处理
    path.push(step.move);
    cur = step.key;
  }
  return path.reverse();
}

/** 贪心兜底步（BFS 超限时的运行期降线）：优先同色合并，其次倒空柱。 */
export function greedyMove(board: Board, layersPerRod: number): SortMove | null {
  const moves = legalMoves(board, layersPerRod);
  if (!moves.length) return null;
  let best: SortMove | null = null;
  let bestScore = -1;
  for (const mv of moves) {
    const trial = cloneBoard(board);
    applyMove(trial, mv.src, mv.dst, mv.k);
    let score = 0;
    if (isSolved(trial, layersPerRod)) score += 100;
    // 目标柱同色合并/柱变空 +2；纯搬家 +1
    const dst = board[mv.dst];
    if (dst.length) score += 2;
    if (trial[mv.src].length === 0) score += 2;
    if (mv.k > 1) score += 1;
    if (score > bestScore) {
      bestScore = score;
      best = mv;
    }
  }
  return best;
}

/** 带缓存的"当前最优解"查询（hint 每手势轮询，BFS 结果按盘面键复用）。 */
export class SolutionCache {
  private cache = new Map<string, SortMove[] | null>();

  /** 取当前盘面最优解；BFS 超限返回 null（调用方走贪心兜底）。 */
  solution(board: Board, layersPerRod: number): SortMove[] | null {
    const key = boardKey(board);
    if (this.cache.has(key)) return this.cache.get(key)!;
    const sol = solveOptimal(board, layersPerRod);
    if (this.cache.size > 32) this.cache.clear(); // 简易防膨胀（一盘面一解，局内键数有限）
    this.cache.set(key, sol);
    return sol;
  }

  clear(): void {
    this.cache.clear();
  }
}

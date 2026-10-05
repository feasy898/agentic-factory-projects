// 合成盘面纯逻辑（templates.md §7.1）：生成（必有可行合成）、拖动合成
// （相邻同阶 → 升一阶）、源列重力补位、死局重排。视图层回放 steps 做动画，
// 求解器只取汇总数字——单一实现两处复用；全部函数无 DOM 依赖，Node 可单测。
//
// 模型约定（冻结）：
// - tier 取值 1..maxTier；出生棋子 tier ∈ 1..spawnTierMax（恒 < maxTier）；
// - 一步 = 从 (x,y) 向 dir 拖动：仅当相邻格为**同阶**且升阶不超 maxTier 时有效；
//   效果 = 目标格 tier+1（升级弹跳），源格清空 → 源列重力下落 → 列顶补 1 个出生棋子；
// - 盘面恒满（补位立回）——与三消模板同一"画面=逻辑"布局前提。

import { type Rng } from "./rng.ts";

export type Dir = "up" | "down" | "left" | "right";

/** 一步合成：把 (x,y) 的棋子向 dir 方向的相邻格拖动。 */
export interface MergeMove {
  x: number;
  y: number;
  dir: Dir;
}

export const DIR_DELTAS: Record<Dir, [number, number]> = {
  up: [0, -1],
  down: [0, 1],
  left: [-1, 0],
  right: [1, 0],
};

export const EMPTY = -1;

/** 结算回放步：merge（含升级）→ fall（源列下落）→ spawn（列顶出生）。 */
export type Step =
  | { t: "merge"; from: number; to: number; toTier: number }
  | { t: "fall"; moves: Array<{ from: number; to: number }> }
  | { t: "spawn"; cells: Array<{ index: number; tier: number }> };

export interface MergeResult {
  steps: Step[];
  /** 合成落点格（升级后的棋子所在）。 */
  mergedTo: number;
  /** 升级后的阶。 */
  newTier: number;
  /** 本步得分：升阶数 × 20。 */
  score: number;
  finalGrid: number[];
}

/** 硬步数预算（§4.1 merge 无 moves 参数；预算只作真实收束，最优线远用不到）：
 *  盘面格数 × 2。耗尽未达 goalTier 判真实败局（pf:end {win:false}）。 */
export function maxMoves(cols: number, rows: number): number {
  return cols * rows * 2;
}

/** 一步合成结算：无效（越界/不同阶/超 maxTier）返回 null。
 *  rng 仅用于补位新棋子（调用方按"第 k 步盐"派生，见 solver.ts 约定）。 */
export function resolveMerge(
  grid: number[],
  cols: number,
  rows: number,
  maxTier: number,
  spawnTierMax: number,
  mv: MergeMove,
  rng: Rng,
): MergeResult | null {
  const [dx, dy] = DIR_DELTAS[mv.dir];
  const nx = mv.x + dx;
  const ny = mv.y + dy;
  if (mv.x < 0 || mv.y < 0 || mv.x >= cols || mv.y >= rows) return null;
  if (nx < 0 || ny < 0 || nx >= cols || ny >= rows) return null;
  const src = mv.y * cols + mv.x;
  const dst = ny * cols + nx;
  const fromTier = grid[src];
  if (fromTier <= 0 || grid[dst] !== fromTier) return null; // 不同阶不合成
  const newTier = fromTier + 1;
  if (newTier > maxTier) return null; // 满阶棋子为终态，不再合成

  const cur = grid.slice();
  cur[dst] = newTier;
  cur[src] = EMPTY;
  const steps: Step[] = [{ t: "merge", from: src, to: dst, toTier: newTier }];

  // 重力：源格所在列自空格向上整体下落（记录位移，含刚升级的棋子）。
  const col = mv.x;
  const falls: Array<{ from: number; to: number }> = [];
  for (let y = mv.y; y >= 1; y--) {
    const from = (y - 1) * cols + col;
    const to = y * cols + col;
    if (cur[from] !== EMPTY) {
      cur[to] = cur[from];
      cur[from] = EMPTY;
      falls.push({ from, to });
    }
  }
  if (falls.length) steps.push({ t: "fall", moves: falls });

  // 补位：源列顶格生成 1 个出生棋子（tier ∈ 1..spawnTierMax）。
  const tier = 1 + Math.floor(rng() * spawnTierMax);
  cur[col] = tier;
  steps.push({ t: "spawn", cells: [{ index: col, tier }] });

  return { steps, mergedTo: dst, newTier, score: newTier * 20, finalGrid: cur };
}

/** 是否存在可行合成（相邻同阶且可升阶）。 */
export function hasAnyMerge(grid: number[], cols: number, rows: number, maxTier: number): boolean {
  return allMerges(grid, cols, rows, maxTier).length > 0;
}

/** 枚举全部有效合成步（确定性顺序：行优先逐格 × up/down/left/right）。 */
export function allMerges(grid: number[], cols: number, rows: number, maxTier: number): MergeMove[] {
  const moves: MergeMove[] = [];
  for (let y = 0; y < rows; y++) {
    for (let x = 0; x < cols; x++) {
      for (const dir of ["up", "down", "left", "right"] as Dir[]) {
        const mv: MergeMove = { x, y, dir };
        const nx = x + DIR_DELTAS[dir][0];
        const ny = y + DIR_DELTAS[dir][1];
        if (nx < 0 || ny < 0 || nx >= cols || ny >= rows) continue;
        const a = grid[y * cols + x];
        if (a <= 0 || a !== grid[ny * cols + nx]) continue;
        if (a + 1 > maxTier) continue;
        moves.push(mv);
      }
    }
  }
  return moves;
}

/** 死局重排：保留既有棋子（进度不丢），洗牌位置直至存在可行合成。
 *  200 次仍不行（全盘无同阶对，理论极端参数）才重发出生阶盘面。 */
export function rearrangeGrid(
  grid: number[],
  cols: number,
  rows: number,
  maxTier: number,
  spawnTierMax: number,
  rng: Rng,
): number[] {
  const n = cols * rows;
  for (let guard = 0; guard < 200; guard++) {
    const next = grid.slice();
    for (let i = n - 1; i > 0; i--) {
      const j = Math.floor(rng() * (i + 1));
      const tmp = next[i];
      next[i] = next[j];
      next[j] = tmp;
    }
    if (hasAnyMerge(next, cols, rows, maxTier)) return next;
  }
  return dealGrid(cols, rows, spawnTierMax, maxTier, rng);
}

/** 发一张出生阶盘面（保证存在可行合成）。 */
export function dealGrid(
  cols: number,
  rows: number,
  spawnTierMax: number,
  maxTier: number,
  rng: Rng,
): number[] {
  let guard = 0;
  let grid: number[];
  do {
    grid = new Array<number>(cols * rows);
    for (let i = 0; i < grid.length; i++) {
      grid[i] = 1 + Math.floor(rng() * spawnTierMax);
    }
    guard++;
  } while (!hasAnyMerge(grid, cols, rows, maxTier) && guard < 200);
  return grid;
}

/** 合成盘面（实例侧：持有 rng 流，供游戏侧与重排复用）。 */
export class MergeBoard {
  readonly cols: number;
  readonly rows: number;
  readonly maxTier: number;
  readonly spawnTierMax: number;
  grid: number[];
  private rng: Rng;

  constructor(cols: number, rows: number, maxTier: number, spawnTierMax: number, rng: Rng) {
    this.cols = cols;
    this.rows = rows;
    this.maxTier = maxTier;
    this.spawnTierMax = spawnTierMax;
    this.rng = rng;
    this.grid = new Array<number>(cols * rows).fill(1);
  }

  idx(x: number, y: number): number {
    return y * this.cols + x;
  }

  at(x: number, y: number): number {
    return this.grid[this.idx(x, y)];
  }

  /** 生成初始盘面：全出生阶，必有可行合成（不变式）。 */
  generate(): void {
    this.grid = dealGrid(this.cols, this.rows, this.spawnTierMax, this.maxTier, this.rng);
  }

  /** 死局重排：保留棋子重摆（必有可行合成）。 */
  reshuffle(): void {
    this.grid = rearrangeGrid(this.grid, this.cols, this.rows, this.maxTier, this.spawnTierMax, this.rng);
  }

  /** 换入新 rng 流（供派生流复用）。 */
  setRng(rng: Rng): void {
    this.rng = rng;
  }

  get rngStream(): Rng {
    return this.rng;
  }
}

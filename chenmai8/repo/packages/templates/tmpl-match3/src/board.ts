// 三消盘面纯逻辑：生成（无初始三连且必有可行步）、交换、消除波次、重力补位、
// 死局重排。视图层逐步回放 steps 做动画，求解器只取汇总数字——单一实现两处复用。
// 全部函数无 DOM 依赖，可在 Node 下单测。

import { type Rng } from "./rng.ts";

export type Dir = "up" | "down" | "left" | "right";

/** 一步交换：交换 (x,y) 与其 dir 方向的相邻格。 */
export interface Move {
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

export type Step =
  | { t: "match"; cells: number[] }
  | { t: "fall"; moves: Array<{ from: number; to: number }> }
  | { t: "spawn"; cells: Array<{ index: number; piece: number }> };

export interface ResolveResult {
  steps: Step[];
  /** 本次连消中所有被移除的格（去重）。 */
  cleared: number[];
  /** 连消波数（1 = 仅首波）。 */
  cascades: number;
  /** 得分：第 w 波每格 10*w 分。 */
  score: number;
  finalGrid: number[];
}

export class Board {
  readonly cols: number;
  readonly rows: number;
  readonly colors: number;
  grid: number[];
  jelly: boolean[];
  private rng: Rng;

  constructor(cols: number, rows: number, colors: number, rng: Rng) {
    this.cols = cols;
    this.rows = rows;
    this.colors = colors;
    this.rng = rng;
    this.grid = new Array<number>(cols * rows).fill(0);
    this.jelly = new Array<boolean>(cols * rows).fill(false);
  }

  idx(x: number, y: number): number {
    return y * this.cols + x;
  }

  at(x: number, y: number): number {
    return this.grid[this.idx(x, y)];
  }

  /** 生成初始盘面：无初始三连，且至少存在一个可行步（不变式）。 */
  generate(jellyCount: number): void {
    let guard = 0;
    do {
      this.fillNoMatches();
      guard++;
    } while (!Board.hasAnyMove(this.grid, this.cols, this.rows) && guard < 200);
    this.placeJelly(jellyCount);
  }

  private fillNoMatches(): void {
    const { cols, rows, colors } = this;
    for (let y = 0; y < rows; y++) {
      for (let x = 0; x < cols; x++) {
        const i = this.idx(x, y);
        let piece = 0;
        for (let attempt = 0; attempt < 32; attempt++) {
          piece = Math.floor(this.rng() * colors);
          const badLeft = x >= 2 && this.grid[i - 1] === piece && this.grid[i - 2] === piece;
          const badUp = y >= 2 && this.grid[i - cols] === piece && this.grid[i - 2 * cols] === piece;
          if (!badLeft && !badUp) break;
        }
        this.grid[i] = piece;
      }
    }
  }

  private placeJelly(count: number): void {
    this.jelly.fill(false);
    const total = this.cols * this.rows;
    const n = Math.max(0, Math.min(count, total));
    // 洗牌取前 n 个格子（Fisher-Yates，用同一种子流，确定性）。
    const order = new Array<number>(total);
    for (let i = 0; i < total; i++) order[i] = i;
    for (let i = total - 1; i > 0; i--) {
      const j = Math.floor(this.rng() * (i + 1));
      const tmp = order[i];
      order[i] = order[j];
      order[j] = tmp;
    }
    for (let i = 0; i < n; i++) this.jelly[order[i]] = true;
  }

  /** 死局重排：保留果冻，重摆棋子（无初始三连 + 必有可行步）。 */
  reshuffle(): void {
    let guard = 0;
    do {
      this.fillNoMatches();
      guard++;
    } while (!Board.hasAnyMove(this.grid, this.cols, this.rows) && guard < 200);
  }

  // ------------------------------------------------------------ 静态纯函数

  static swap(grid: number[], cols: number, rows: number, mv: Move): number[] | null {
    const [dx, dy] = DIR_DELTAS[mv.dir];
    const nx = mv.x + dx;
    const ny = mv.y + dy;
    if (mv.x < 0 || mv.y < 0 || mv.x >= cols || mv.y >= rows) return null;
    if (nx < 0 || ny < 0 || nx >= cols || ny >= rows) return null;
    const next = grid.slice();
    const a = ny * cols + nx;
    const b = mv.y * cols + mv.x;
    const tmp = next[b];
    next[b] = next[a];
    next[a] = tmp;
    return next;
  }

  static matchMask(grid: number[], cols: number, rows: number): boolean[] {
    const mask = new Array<boolean>(grid.length).fill(false);
    for (let y = 0; y < rows; y++) {
      let run = 1;
      for (let x = 1; x <= cols; x++) {
        const cur = x < cols ? grid[y * cols + x] : -1;
        const prev = grid[y * cols + x - 1];
        if (cur === prev && prev >= 0) {
          run++;
        } else {
          if (run >= 3) {
            for (let k = x - run; k < x; k++) mask[y * cols + k] = true;
          }
          run = 1;
        }
      }
    }
    for (let x = 0; x < cols; x++) {
      let run = 1;
      for (let y = 1; y <= rows; y++) {
        const cur = y < rows ? grid[y * cols + x] : -1;
        const prev = grid[(y - 1) * cols + x];
        if (cur === prev && prev >= 0) {
          run++;
        } else {
          if (run >= 3) {
            for (let k = y - run; k < y; k++) mask[k * cols + x] = true;
          }
          run = 1;
        }
      }
    }
    return mask;
  }

  /**
   * 完整结算：反复消除→重力→补位，直到无消除。
   * rng 仅用于补位新棋子；传 rngClone 供模拟器隔离使用。
   */
  static resolve(
    grid: number[],
    cols: number,
    rows: number,
    colors: number,
    rng: Rng,
    jelly: boolean[] | null,
  ): ResolveResult {
    let cur = grid.slice();
    const jellyLeft = jelly ? jelly.slice() : null;
    const steps: Step[] = [];
    const clearedSet = new Set<number>();
    const jellyCleared: number[] = [];
    let cascades = 0;
    let score = 0;

    for (let wave = 1; wave <= 64; wave++) {
      const mask = Board.matchMask(cur, cols, rows);
      const cells: number[] = [];
      for (let i = 0; i < mask.length; i++) {
        if (mask[i]) {
          cells.push(i);
          clearedSet.add(i);
          if (jellyLeft && jellyLeft[i]) {
            jellyLeft[i] = false;
            jellyCleared.push(i);
          }
        }
      }
      if (cells.length === 0) break;
      cascades = wave;
      score += cells.length * 10 * wave;
      steps.push({ t: "match", cells });

      // 重力：每列自底向上压实，记录位移。
      const falls: Array<{ from: number; to: number }> = [];
      for (let x = 0; x < cols; x++) {
        let write = rows - 1;
        for (let y = rows - 1; y >= 0; y--) {
          const from = y * cols + x;
          if (!mask[from]) {
            const to = write * cols + x;
            if (to !== from) {
              cur[to] = cur[from];
              falls.push({ from, to });
            }
            write--;
          }
        }
        for (let y = write; y >= 0; y--) {
          cur[y * cols + x] = -1; // 待补位
        }
      }
      if (falls.length) steps.push({ t: "fall", moves: falls });

      // 补位：扫描每个仍为空的格子生成新棋子（每列顶部空洞）。
      const spawns: Array<{ index: number; piece: number }> = [];
      for (let x = 0; x < cols; x++) {
        for (let y = 0; y < rows; y++) {
          const i = y * cols + x;
          if (cur[i] === -1) {
            const piece = Math.floor(rng() * colors);
            cur[i] = piece;
            spawns.push({ index: i, piece });
          }
        }
      }
      if (spawns.length) steps.push({ t: "spawn", cells: spawns });
    }

    return { steps, cleared: [...clearedSet], cascades, score, finalGrid: cur };
  }

  /** 是否存在可行步（交换后有消除）。 */
  static hasAnyMove(grid: number[], cols: number, rows: number): boolean {
    return Board.allMoves(grid, cols, rows).length > 0;
  }

  static allMoves(grid: number[], cols: number, rows: number): Move[] {
    const moves: Move[] = [];
    const dirs: Dir[] = ["right", "down"];
    for (let y = 0; y < rows; y++) {
      for (let x = 0; x < cols; x++) {
        for (const dir of dirs) {
          const swapped = Board.swap(grid, cols, rows, { x, y, dir });
          if (!swapped) continue;
          const mask = Board.matchMask(swapped, cols, rows);
          if (mask.some(Boolean)) moves.push({ x, y, dir });
        }
      }
    }
    return moves;
  }

  /** 换入新 rng 流（供模拟器派生流复用 Board 静态函数）。 */
  setRng(rng: Rng): void {
    this.rng = rng;
  }

  get rngStream(): Rng {
    return this.rng;
  }
}

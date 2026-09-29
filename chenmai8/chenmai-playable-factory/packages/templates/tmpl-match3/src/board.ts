// 三消盘面纯逻辑（规则卡 §2/§4）：生成（无初始三连 + 必有可行步）、交换、
// 消除波次 → 重力 → 补位的完整结算、死局重排。视图层回放 steps 做动画，
// 求解器只取汇总数字——单一实现两处复用；全部函数无 DOM 依赖，Node 可单测。
//
// 坐标约定（规则卡 §2 回炉钉死）：扁平索引 idx = y*cols + x（行优先，原点左上）。

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

/** 结算回放步（三型交替；fall/spawn 为空时整步省略——规则卡 §4）。 */
export type Step =
  | { t: "match"; cells: number[] }
  | { t: "fall"; moves: Array<{ from: number; to: number }> }
  | { t: "spawn"; cells: Array<{ index: number; piece: number }> };

export interface ResolveResult {
  steps: Step[];
  /** 本轮连消全部被清格（去重，按首次清除顺序）。 */
  cleared: number[];
  /** 连消波数（最后一个成消波的波号）。 */
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

  /**
   * 生成初始盘面：无初始三连且至少存在一个可行步（不变式）。
   * 注意：不重置 rng——生成期 64 次重试共用一条主流顺序消耗（规则卡 §2）。
   */
  generate(jellyCount: number): void {
    let guard = 0;
    do {
      this.fillNoMatches();
      guard++;
    } while (!Board.hasAnyMove(this.grid, this.cols, this.rows) && guard < 200);
    this.placeJelly(jellyCount);
  }

  /** 行优先逐格取色；与左侧两格或上方两格同色则重抽（至多 32 次，超限接受末次）。 */
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

  /** 果冻摆放：Fisher-Yates 洗牌 [0..total)（同一 rng 流），前 n 格为果冻。 */
  private placeJelly(count: number): void {
    this.jelly.fill(false);
    const total = this.cols * this.rows;
    const n = Math.max(0, Math.min(count, total));
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

  /** 死局重排：保留果冻，重摆棋子（无初始三连 + 必有可行步，guard ≤200）。 */
  reshuffle(): void {
    let guard = 0;
    do {
      this.fillNoMatches();
      guard++;
    } while (!Board.hasAnyMove(this.grid, this.cols, this.rows) && guard < 200);
  }

  // ------------------------------------------------------------ 静态纯函数

  /** 交换后的新盘面；越界返回 null。 */
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

  /** 消除掩码：行、列各扫一遍，同色 run ≥3 即标记（交叉处都算）。 */
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
   * 完整结算：反复"消除 → 重力 → 补位"直至无消除（至多 64 波防死循环）。
   * rng 只用于补位新棋子，消耗顺序 = 补位扫描顺序（列优先、每列自上而下）——
   * 这是补位流可复现的关键（规则卡 §4/§7）。
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
          }
        }
      }
      if (cells.length === 0) break;
      cascades = wave;
      score += cells.length * 10 * wave;
      steps.push({ t: "match", cells });

      // 重力：每列自底向上压实被清格，记录 {from,to} 位移；顶部空位先置 -1。
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

      // 补位：列优先（x 外层）、每列自上而下（y 内层）扫描空格，逐格当场出子。
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

  /** 是否存在可行步（任一相邻交换能成消）。 */
  static hasAnyMove(grid: number[], cols: number, rows: number): boolean {
    return Board.allMoves(grid, cols, rows).length > 0;
  }

  /** 全部可行交换（只扫 right/down 去重；扫描序 = 行优先 y 外层、x 内层，dir 内层 right→down）。 */
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

  /** 换入新 rng 流（死局重排用派生流复用本类生成逻辑）。 */
  setRng(rng: Rng): void {
    this.rng = rng;
  }

  get rngStream(): Rng {
    return this.rng;
  }
}

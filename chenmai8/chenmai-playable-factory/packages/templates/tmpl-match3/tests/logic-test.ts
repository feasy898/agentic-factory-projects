// 逻辑自测（开发期临时文件，不入构建产物）：
//  1) 盘面生成不变式（无初始三连、必有可行步、果冻数=goalCount）
//  2) 求解器最优步坐标合法
//  3) 核心不变式：hint 驱动（按游戏侧盐调度逐回合调用 bestMove）与
//     生成期 simulatePlay 完全一致 → 生成期重试即可保证可胜。
import { Board } from "../src/board.ts";
import { mulberry32, deriveRng } from "../src/rng.ts";
import { bestMove, simulatePlay, SPAWN_SALT, type SolverContext } from "../src/solver.ts";

const cols = 6, rows = 6, colors = 5, goal = 30, moves = 15;
let pass = 0, fail = 0;
const check = (name: string, ok: boolean) => { ok ? pass++ : fail++; console.log(`${ok ? "PASS" : "FAIL"} ${name}`); };

const mkCtx = (seed: number, progress: number): SolverContext => ({
  cols, rows, colors, seed, goalType: "clear-jelly",
  progress: () => progress, goal: () => goal,
  salt: () => SPAWN_SALT ^ (moves - (moves - 0) + 1), // 占位，hint 线中逐回合覆盖
});

// 1) 生成不变式
const rng = mulberry32(20260930);
const board = new Board(cols, rows, colors, rng);
board.generate(goal);
check("初始盘面无三连", Board.matchMask(board.grid, cols, rows).every((m) => !m));
check("初始盘面存在可行步", Board.hasAnyMove(board.grid, cols, rows));
check(`果冻数=goalCount(${goal})`, board.jelly.filter(Boolean).length === goal);

// 2) 最优步坐标合法
const ctx0 = mkCtx(20260930, 0);
const best = bestMove(ctx0, board.grid, board.jelly);
check("bestMove 非空且坐标合法", !!best && best.move.x >= 0 && best.move.x < cols && best.move.y >= 0 && best.move.y < rows);

// 3) hint 驱动线（复刻 game.ts 盐调度）与 simulatePlay 一致性 + 可胜率
let maxAttempts = 0;
let hintWins = 0, simWins = 0;
const N = 30;
for (let s = 0; s < N; s++) {
  const seed = 20260930 + s * 7;
  // 生成期：与 game.ts 相同的 64 次重试
  let attempts = 0, simWin = false, grid0: number[] = [], jelly0: boolean[] = [];
  const b = new Board(cols, rows, colors, mulberry32(seed));
  while (attempts < 64) {
    b.generate(goal);
    attempts++;
    const sim = simulatePlay(mkCtx(seed, 0), b.grid, b.jelly, moves);
    if (sim.win) { simWin = true; grid0 = b.grid.slice(); jelly0 = b.jelly.slice(); break; }
  }
  maxAttempts = Math.max(maxAttempts, attempts);
  if (!simWin) continue;
  simWins++;
  // hint 驱动线：k 从 1 起，每回合用游戏侧同一盐流重算最优步
  let grid = grid0.slice(), jelly = jelly0.slice(), progress = 0, k = 1;
  let dead = false;
  while (k <= moves) {
    const localCtx: SolverContext = { ...mkCtx(seed, 0), progress: () => progress, salt: () => SPAWN_SALT ^ k };
    const mv = bestMove(localCtx, grid, jelly);
    if (!mv) { grid = grid.map(() => Math.floor(deriveRng(seed, 0x5117 ^ k)() * colors)); continue; }
    const swapped = Board.swap(grid, cols, rows, mv.move)!;
    const result = Board.resolve(swapped, cols, rows, colors, deriveRng(seed, SPAWN_SALT ^ k), jelly);
    for (const i of result.cleared) jelly[i] = false;
    grid = result.finalGrid;
    progress += mv.jellyCleared;
    if (progress >= goal) break;
    k++;
  }
  if (progress >= goal) hintWins++;
}
check(`生成期 64 次重试全部找到可胜盘面（${simWins}/${N}，最大重试 ${maxAttempts}）`, simWins === N);
check(`hint 驱动线与模拟线一致全部可胜（${hintWins}/${simWins}）`, hintWins === simWins && simWins > 0);
console.log(`logic-test: ${pass} pass / ${fail} fail`);
if (fail) process.exit(1);

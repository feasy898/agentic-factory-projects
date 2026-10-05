// 逻辑自测（开发期临时文件，不入构建产物；与 tmpl-match3 同一纪律）：
//  1) 盘面生成不变式（必有可行合成、tier 全部落在出生阶域内）
//  2) 合成结算有效性（不同阶/满阶不可合成；结算后盘面恒满）
//  3) 核心不变式：hint 驱动（按游戏侧盐调度逐回合调用 bestMerge）与
//     生成期 simulatePlay 完全一致 → 生成期重试即可保证可胜。
import {
  allMerges,
  dealGrid,
  hasAnyMerge,
  maxMoves,
  rearrangeGrid,
  resolveMerge,
} from "../src/board.ts";
import { mulberry32, deriveRng } from "../src/rng.ts";
import {
  bestMerge,
  simulatePlay,
  SPAWN_SALT,
  RESHUFFLE_SALT,
  type SolverContext,
} from "../src/solver.ts";

let pass = 0, fail = 0;
const check = (name: string, ok: boolean) => {
  ok ? pass++ : fail++;
  console.log(`${ok ? "PASS" : "FAIL"} ${name}`);
};

const COLS = 5, ROWS = 5, MAX_TIER = 5, SPAWN_MAX = 2, GOAL = 4;

const mkCtx = (seed: number, salt: number): SolverContext => ({
  cols: COLS, rows: ROWS, maxTier: MAX_TIER, spawnTierMax: SPAWN_MAX, seed,
  goalTier: () => GOAL,
  salt: () => salt,
});

// 1) 生成不变式（30 个 seed 全查）
let genOk = true;
for (let s = 0; s < 30; s++) {
  const seed = 20261001 + s * 13;
  const grid = dealGrid(COLS, ROWS, SPAWN_MAX, MAX_TIER, mulberry32(seed));
  if (!hasAnyMerge(grid, COLS, ROWS, MAX_TIER)) genOk = false;
  if (grid.some((t) => t < 1 || t > SPAWN_MAX)) genOk = false;
}
check("生成盘面必有可行合成且 tier 全在出生域（30 seeds）", genOk);

// 2) 合成结算有效性
{
  const grid = [1, 1, 2, 3, 3, 5, 5, 1, 2, 2, 1, 2, 1, 2, 1, 2, 1, 2, 1, 2, 1, 2, 1, 2, 1];
  const r = resolveMerge(grid, COLS, ROWS, MAX_TIER, SPAWN_MAX, { x: 0, y: 0, dir: "right" }, mulberry32(1));
  check("同阶相邻可合成（新阶=2，落点=目标格）", !!r && r.newTier === 2 && r.mergedTo === 1);
  check("结算后盘面恒满", !!r && r.finalGrid.every((t) => t >= 1));
  check("满阶（maxTier）同阶不可合成",
    resolveMerge(grid, COLS, ROWS, MAX_TIER, SPAWN_MAX, { x: 0, y: 1, dir: "right" }, mulberry32(1)) === null);
  check("不同阶不可合成",
    resolveMerge(grid, COLS, ROWS, MAX_TIER, SPAWN_MAX, { x: 0, y: 0, dir: "down" }, mulberry32(1)) === null);
  const moves = allMerges(grid, COLS, ROWS, MAX_TIER);
  check("allMerges 与逐点验证一致（>0 且坐标合法）",
    moves.length > 0 && moves.every((m) => m.x >= 0 && m.x < COLS && m.y >= 0 && m.y < ROWS));
}

// 3) hint 驱动线（复刻 game.ts 盐调度）与 simulatePlay 一致性 + 可胜率
let maxAttempts = 0;
let hintWins = 0, simWins = 0, movesAgree = 0;
const N = 30;
for (let s = 0; s < N; s++) {
  const seed = 20261001 + s * 13;
  const budget = Math.min(24, maxMoves(COLS, ROWS) - 2);
  // 生成期：与 game.ts 相同的 64 次重试
  let attempts = 0, simWin = false, grid0: number[] = [];
  while (attempts < 64) {
    const g = dealGrid(COLS, ROWS, SPAWN_MAX, MAX_TIER, mulberry32(seed + attempts));
    attempts++;
    if (g.reduce((m, t) => Math.max(m, t), 0) >= GOAL) continue;
    const sim = simulatePlay(mkCtx(seed, SPAWN_SALT), g, budget);
    if (sim.win) { simWin = true; grid0 = g; break; }
  }
  maxAttempts = Math.max(maxAttempts, attempts);
  if (!simWin) continue;
  simWins++;
  const sim2 = simulatePlay(mkCtx(seed, SPAWN_SALT), grid0, budget);
  // hint 驱动线：k 从 1 起，每回合用游戏侧同一盐流重算最优步
  let grid = grid0.slice(), k = 1, reshuffles = 0, score = 0, top = 0, movesUsed = 0;
  while (k <= budget && reshuffles < 16) {
    if (top >= GOAL) break;
    const mv = bestMerge(mkCtx(seed, SPAWN_SALT ^ k), grid);
    if (!mv) {
      grid = rearrangeGrid(grid, COLS, ROWS, MAX_TIER, SPAWN_MAX, deriveRng(seed, RESHUFFLE_SALT ^ k));
      reshuffles++;
      continue;
    }
    const res = resolveMerge(grid, COLS, ROWS, MAX_TIER, SPAWN_MAX, mv.move, deriveRng(seed, SPAWN_SALT ^ k))!;
    grid = res.finalGrid;
    score += res.score;
    top = Math.max(top, res.newTier);
    movesUsed = k;
    if (top >= GOAL) break;
    k++;
  }
  if (top >= GOAL) hintWins++;
  if (movesUsed === sim2.movesUsed && score === sim2.score) movesAgree++;
}
check(`生成期 64 次重试全部找到可胜盘面（${simWins}/${N}，最大重试 ${maxAttempts}）`, simWins === N);
check(`hint 驱动线与模拟线一致全部可胜（${hintWins}/${simWins}）`, hintWins === simWins && simWins > 0);
check(`hint 线步数/得分与 simulatePlay 逐局一致（${movesAgree}/${simWins}）`, movesAgree === simWins);

// 4) 紧参数（3×3、全 1 阶出生、goal 3）也可胜——spec 驱动鲁棒性
{
  const cols = 3, rows = 3, goal = 3;
  const ctx: SolverContext = {
    cols, rows, maxTier: 4, spawnTierMax: 1, seed: 77,
    goalTier: () => goal, salt: () => SPAWN_SALT,
  };
  let ok = false;
  for (let a = 0; a < 64 && !ok; a++) {
    const g = dealGrid(cols, rows, 1, 4, mulberry32(77 + a));
    if (g.reduce((m, t) => Math.max(m, t), 0) >= goal) continue;
    ok = simulatePlay(ctx, g, Math.min(24, maxMoves(cols, rows) - 2)).win;
  }
  check("紧参数 3×3/spawn1/goal3 生成期可胜", ok);
}

console.log(`logic-test: ${pass} pass / ${fail} fail`);
if (fail) process.exit(1);

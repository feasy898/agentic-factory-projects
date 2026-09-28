// PlayableSpec v1 语义不变式与规范生成器 —— python/pfcore/invariants.py 的 JS 镜像。
//
// 两侧算法逐行对应（LCG 参数、生成规则、模拟步序），对同一 spec 的判定必须一致；
// 这是 schema v1 冻结契约的一部分，任何一侧改动都视为破坏契约。
// 不变式：I1 pullpin 模拟可解 / I2 sort 栈可逆 / I3 match3 存在可行步 /
//        I4 时长预算 <= 30 / I5 i18n 键全覆盖。

export const LCG_A = 1664525;
export const LCG_C = 1013904223;
export const MASK32 = 0xffffffff;

export const REQUIRED_STRING_KEYS = ["cta", "tutorial", "win", "lose", "score"];

export const MATCH3_DEFAULTS = {
  cols: 6, rows: 6, moves: 15, colors: 5,
  goalType: "clear-jelly", goalCount: 30,
  spriteKeys: ["piece-0", "piece-1", "piece-2", "piece-3", "piece-4"],
};
export const MERGE_DEFAULTS = {
  cols: 5, rows: 5, maxTier: 5, spawnTierMax: 2, goalTier: 4,
  spriteKeys: ["tier-1", "tier-2", "tier-3", "tier-4", "tier-5"],
};
export const PULLPIN_DEFAULTS = { levels: 3, pinsPerLevel: 3, hazard: "lava", rescuee: "character" };
export const SORT_DEFAULTS = { rods: 4, layersPerRod: 4, colors: 4, screwMode: false };

export const PULLPIN_REROLL_MAX = 16;
export const MAX_DURATION_SEC = 30;

/** 32 位 LCG：state = (1664525*state + 1013904223) mod 2^32（与 Python 同余）。 */
export class Lcg {
  constructor(seed) {
    this.state = Number(seed) >>> 0;
  }

  nextU32() {
    this.state = (Math.imul(LCG_A, this.state) + LCG_C) >>> 0;
    return this.state;
  }

  below(n) {
    return this.nextU32() % n;
  }
}

// ---------------------------------------------------------------- 规范生成器

export function match3Board(seed, rows, cols, colors) {
  const rng = new Lcg(seed);
  const board = [];
  for (let r = 0; r < rows; r++) {
    const row = [];
    for (let c = 0; c < cols; c++) row.push(rng.below(colors));
    board.push(row);
  }
  return board;
}

function boardHasMatch(b, rows, cols) {
  for (let r = 0; r < rows; r++) {
    let run = 1;
    for (let c = 1; c < cols; c++) {
      run = b[r][c] === b[r][c - 1] ? run + 1 : 1;
      if (run >= 3) return true;
    }
  }
  for (let c = 0; c < cols; c++) {
    let run = 1;
    for (let r = 1; r < rows; r++) {
      run = b[r][c] === b[r - 1][c] ? run + 1 : 1;
      if (run >= 3) return true;
    }
  }
  return false;
}

/** 返回一个可行步 [r1,c1,r2,c2]，无则 null。 */
export function match3FindMove(board) {
  const rows = board.length;
  const cols = rows ? board[0].length : 0;
  if (!rows || !cols) return null;
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      for (const [dr, dc] of [[0, 1], [1, 0]]) {
        const r2 = r + dr;
        const c2 = c + dc;
        if (r2 >= rows || c2 >= cols || board[r][c] === board[r2][c2]) continue;
        [board[r][c], board[r2][c2]] = [board[r2][c2], board[r][c]];
        const ok = boardHasMatch(board, rows, cols);
        [board[r][c], board[r2][c2]] = [board[r2][c2], board[r][c]];
        if (ok) return [r, c, r2, c2];
      }
    }
  }
  return null;
}

/** 每关 [rescueeIdx, hazardIdx]；重抽规则与 Python 一致。 */
export function pullpinLevelRoles(seed, levels, pinsPerLevel) {
  const rng = new Lcg(seed);
  const roles = [];
  for (let i = 0; i < levels; i++) {
    const rescuee = rng.below(pinsPerLevel);
    let hazard = -1;
    for (let t = 0; t < PULLPIN_REROLL_MAX; t++) {
      const h = rng.below(pinsPerLevel);
      if (h !== rescuee) { hazard = h; break; }
    }
    if (hazard < 0) hazard = (rescuee + 1) % pinsPerLevel;
    roles.push([rescuee, hazard]);
  }
  return roles;
}

export function pullpinSimulate(order, rescuee, hazard) {
  for (const pin of order) {
    if (pin === hazard) return [false, "机关针在救援针之前被拔出"];
    if (pin === rescuee) return [true, "角色逃出"];
  }
  return [false, "救援针未被拔出"];
}

export function sortSolvedBoard(rods, layersPerRod, colors) {
  const filled = Math.min(colors, rods);
  const board = [];
  for (let c = 0; c < filled; c++) board.push(Array(layersPerRod).fill(c));
  while (board.length < rods) board.push([]);
  return board;
}

export function sortLegalMoves(board, layersPerRod) {
  const moves = [];
  board.forEach((rod, src) => {
    if (!rod.length) return;
    const color = rod[rod.length - 1];
    let run = 1;
    while (run < rod.length && rod[rod.length - 1 - run] === color) run++;
    board.forEach((drod, dst) => {
      if (dst === src) return;
      const space = layersPerRod - drod.length;
      if (space <= 0) return;
      if (drod.length && drod[drod.length - 1] !== color) return;
      moves.push([src, dst, Math.min(run, space)]);
    });
  });
  return moves;
}

export function sortApplyMove(board, src, dst, k) {
  const color = board[src][board[src].length - 1];
  for (let i = 0; i < k; i++) {
    board[src].pop();
    board[dst].push(color);
  }
}

export function sortInverseLegal(board, src, dst, k, layersPerRod) {
  const color = board[dst][board[dst].length - k];
  const s = board[src];
  if (s.length + k > layersPerRod) return false;
  return s.length === 0 || s[s.length - 1] === color;
}

/** 由已解状态经"逆步合法"走法扰动出初始盘面，返回 [盘面, 步迹]。 */
export function sortScramble(seed, rods, layersPerRod, colors) {
  const rng = new Lcg(seed);
  const board = sortSolvedBoard(rods, layersPerRod, colors);
  const trace = [];
  for (let step = 0; step < rods * layersPerRod; step++) {
    const cands = sortLegalMoves(board, layersPerRod).filter(([s, d, k]) => {
      const trial = board.map((rod) => rod.slice());
      sortApplyMove(trial, s, d, k);
      return sortInverseLegal(trial, s, d, k, layersPerRod);
    });
    if (!cands.length) break;
    const mv = cands[rng.below(cands.length)];
    sortApplyMove(board, ...mv);
    trace.push(mv);
  }
  return [board, trace];
}

// ---------------------------------------------------------------- 不变式检查

function resolved(params, defaults, key) {
  return key in params ? params[key] : defaults[key];
}

/**
 * schema 通过后执行；返回 SpecIssue[]（path 为 json-path 风格字段路径）。
 * @returns {{path: string, message: string, code: string}[]}
 */
export function checkInvariants(spec) {
  const issues = [];
  if (typeof spec !== "object" || spec === null || Array.isArray(spec)) {
    return [{ path: "$", message: `顶层必须是 JSON object`, code: "schema-type" }];
  }
  const game = spec.game ?? {};
  const params = game.params ?? {};
  const template = game.template;
  const seed = (spec.meta && Number.isInteger(spec.meta.seed)) ? spec.meta.seed : 0;

  // I4 时长预算。
  const dur = game.durationBudgetSec ?? {};
  if (typeof dur.max === "number" && dur.max > MAX_DURATION_SEC) {
    issues.push({ path: "$.game.durationBudgetSec.max",
      message: `max=${dur.max} 超过 ${MAX_DURATION_SEC} 秒预算上限`, code: "I4-duration-max" });
  }
  if (typeof dur.target === "number" && typeof dur.max === "number" && dur.target > dur.max) {
    issues.push({ path: "$.game.durationBudgetSec.target",
      message: `target=${dur.target} 不得超过 max=${dur.max}`, code: "I4-duration-target" });
  }

  if (template === "match3" && typeof params === "object" && params !== null) {
    const colors = resolved(params, MATCH3_DEFAULTS, "colors");
    const rows = resolved(params, MATCH3_DEFAULTS, "rows");
    const cols = resolved(params, MATCH3_DEFAULTS, "cols");
    const spriteKeys = resolved(params, MATCH3_DEFAULTS, "spriteKeys");
    if (colors > spriteKeys.length) {
      issues.push({ path: "$.game.params.colors",
        message: `colors=${colors} 超过 spriteKeys 数量 ${spriteKeys.length}`,
        code: "I3-sprites-cover-colors" });
    }
    const board = match3Board(seed, rows, cols, colors);
    if (match3FindMove(board) === null) {
      issues.push({ path: "$.meta.seed",
        message: `seed=${spec.meta?.seed} 生成的 match3 初始盘面无可行步，请换 seed`,
        code: "I3-match3-feasible-move" });
    }
  } else if (template === "merge" && typeof params === "object" && params !== null) {
    const maxTier = resolved(params, MERGE_DEFAULTS, "maxTier");
    const spawnMax = resolved(params, MERGE_DEFAULTS, "spawnTierMax");
    const goalTier = resolved(params, MERGE_DEFAULTS, "goalTier");
    const spriteKeys = resolved(params, MERGE_DEFAULTS, "spriteKeys");
    if (maxTier > spriteKeys.length) {
      issues.push({ path: "$.game.params.maxTier",
        message: `maxTier=${maxTier} 超过 spriteKeys 数量 ${spriteKeys.length}`,
        code: "I-merge-sprites" });
    }
    if (!(spawnMax >= 1 && spawnMax < maxTier)) {
      issues.push({ path: "$.game.params.spawnTierMax",
        message: `spawnTierMax=${spawnMax} 须满足 1 <= spawnTierMax < maxTier=${maxTier}`,
        code: "I-merge-spawn" });
    }
    if (goalTier > maxTier) {
      issues.push({ path: "$.game.params.goalTier",
        message: `goalTier=${goalTier} 不得超过 maxTier=${maxTier}`, code: "I-merge-goal" });
    }
  } else if (template === "pullpin" && typeof params === "object" && params !== null) {
    const levels = resolved(params, PULLPIN_DEFAULTS, "levels");
    const pins = resolved(params, PULLPIN_DEFAULTS, "pinsPerLevel");
    const order = params.orderSolution;
    if (!Array.isArray(order)) {
      issues.push({ path: "$.game.params.orderSolution",
        message: "缺少 orderSolution（每关拔针顺序数组）", code: "I1-pullpin-order" });
    } else {
      if (order.length !== levels) {
        issues.push({ path: "$.game.params.orderSolution",
          message: `orderSolution 关数 ${order.length} 与 levels=${levels} 不一致`,
          code: "I1-pullpin-order" });
      }
      const roles = pullpinLevelRoles(seed, levels, pins);
      order.forEach((levelOrder, li) => {
        const base = `$.game.params.orderSolution[${li}]`;
        if (!Array.isArray(levelOrder) || levelOrder.length === 0 ||
            !levelOrder.every((p) => Number.isInteger(p))) {
          issues.push({ path: base, message: "拔针顺序须为非空整数数组", code: "I1-pullpin-order" });
          return;
        }
        if (new Set(levelOrder).size !== levelOrder.length) {
          issues.push({ path: base, message: "同一针不可重复拔", code: "I1-pullpin-order" });
          return;
        }
        if (levelOrder.some((p) => p < 0 || p >= pins)) {
          issues.push({ path: base,
            message: `针下标须在 0..${pins - 1}（pinsPerLevel=${pins}）`, code: "I1-pullpin-order" });
          return;
        }
        const [rescuee, hazard] = li < roles.length ? roles[li] : [0, 1];
        const [solved, reason] = pullpinSimulate(levelOrder, rescuee, hazard);
        if (!solved) {
          issues.push({ path: base,
            message: `第 ${li} 关不可解：${reason}（rescuee=针${rescuee}, hazard=针${hazard}，布局由 seed 确定性生成）`,
            code: "I1-pullpin-unsolvable" });
        }
      });
    }
  } else if (template === "sort" && typeof params === "object" && params !== null) {
    const rods = resolved(params, SORT_DEFAULTS, "rods");
    const layers = resolved(params, SORT_DEFAULTS, "layersPerRod");
    const colors = resolved(params, SORT_DEFAULTS, "colors");
    if (colors > rods) {
      issues.push({ path: "$.game.params.colors",
        message: `colors=${colors} 不得超过 rods=${rods}（每色需一柱）`, code: "I2-sort-colors" });
    } else {
      // I2 栈可逆校验：重放扰动步迹，每步须为合法走法且逆步合法。
      const [board, trace] = sortScramble(seed, rods, layers, colors);
      const replay = sortSolvedBoard(rods, layers, colors);
      let ok = true;
      for (let i = 0; i < trace.length; i++) {
        const [s, d, k] = trace[i];
        const legal = sortLegalMoves(replay, layers);
        if (!legal.some(([ls, ld, lk]) => ls === s && ld === d && lk === k)) {
          issues.push({ path: "$.meta.seed",
            message: `sort 扰动步 ${i} (${s}->${d}x${k}) 不是合法走法`, code: "I2-sort-scramble" });
          ok = false;
          break;
        }
        sortApplyMove(replay, s, d, k);
        if (!sortInverseLegal(replay, s, d, k, layers)) {
          issues.push({ path: "$.meta.seed",
            message: `sort 扰动步 ${i} (${s}->${d}x${k}) 逆步不合法（破坏可逆性）`,
            code: "I2-sort-reversible" });
          ok = false;
          break;
        }
      }
      if (ok && JSON.stringify(replay) !== JSON.stringify(board)) {
        issues.push({ path: "$.meta.seed", message: "sort 盘面重放结果与生成器不一致",
          code: "I2-sort-scramble" });
      }
    }
  }

  // I5 i18n。
  const i18n = spec.i18n ?? {};
  const locales = Array.isArray(i18n.locales) ? i18n.locales : [];
  const strings = (typeof i18n.strings === "object" && i18n.strings !== null) ? i18n.strings : {};
  for (const locale of locales) {
    const entry = strings[locale];
    if (typeof entry !== "object" || entry === null) {
      issues.push({ path: `$.i18n.strings.${locale}`,
        message: `语言 '${locale}' 缺少 strings 条目`, code: "I5-i18n-coverage" });
      continue;
    }
    for (const key of REQUIRED_STRING_KEYS) {
      const val = entry[key];
      if (typeof val !== "string" || val.trim().length === 0) {
        issues.push({ path: `$.i18n.strings.${locale}.${key}`,
          message: `语言 '${locale}' 缺少字符串键 '${key}'`, code: "I5-i18n-coverage" });
      }
    }
  }
  if (typeof i18n.defaultLocale === "string" && !locales.includes(i18n.defaultLocale)) {
    issues.push({ path: "$.i18n.defaultLocale",
      message: `defaultLocale='${i18n.defaultLocale}' 不在 locales 中`, code: "I5-i18n-default" });
  }
  const rtl = Array.isArray(i18n.rtl) ? i18n.rtl : [];
  rtl.forEach((lang, i) => {
    if (!locales.includes(lang)) {
      issues.push({ path: `$.i18n.rtl[${i}]`,
        message: `RTL 语言 '${lang}' 不在 locales 中`, code: "I5-i18n-rtl" });
    }
  });

  return issues;
}

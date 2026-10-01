// packages/spec/src/invariants.ts — PlayableSpec v1 语义不变式与规范生成器（TS 单一真源）。
//
// 决策裁定（plan/模式M-技术选型决策.md §0/§1.2-2/§2.1，预declare P1）：oracle 的
// "Python 权威 + JS 镜像"双实现废除，pfcore invariants 的全部逻辑（LCG 生成器、
// 四模板不变式 I1–I5）以本文件为**唯一实现**；数值契约不变（spec-contract §2.2/§2.3 冻结）：
//   - 32 位 LCG：state = (1664525*state + 1013904223) mod 2^32，取值 next() % n；
//     JS 侧 Math.imul + >>>0 复刻同余结果。
//   - 三个自由度（spec-contract §2.3）：①先推进后取值（首抽 = LCG 一步后的状态）；
//     ②单流跨关卡（pullpin_level_roles 用一个从 meta.seed 新建的 LCG 连抽全部关卡）；
//     ③各生成器独立建流（match3Board/sortScramble/pullpinLevelRoles 各自从 meta.seed
//     新建；variants[].seed 不参与校验器生成器）。
//   - 算例逐值对齐：bad02 seed=424242 首两抽 %3=[2,0]（L0 rescuee=2/hazard=0）；
//     golden seed=20260930 的 6×6×5 盘面 find_move=(0,2,1,2)；match3 规则卡 §12
//     算例 B（恰一可行步）/C（死局拉丁方）——见 test/invariants.test.mjs 逐值断言。
// 不变式清单（语义冻结，spec-contract §2.2）：
//   I1 pullpin 逐关拔针模拟必须可解；
//   I2 sort 栈可逆（重放方向钉死：从已解盘面正向应用 trace）；
//   I3 match3 seed 盘面存在可行步（且 colors ≤ len(spriteKeys)）；
//   I4 durationBudgetSec.max ≤ 30（schema maximum 的第二层兜底）且 target ≤ max；
//   I5 i18n 每语言 strings 五键非空；defaultLocale ∈ locales；rtl ⊆ locales。
// 校验次序（spec-contract §2.4，冻结）：schema 结构 → 本文件；任一阶段失败即止，
// 不合并报告。错误码集与路径约定照抄（缺字段补名在 schema 层，见 src/validate.ts）。

import type { SpecError, TemplateCheck } from "./types.ts";

// ---------------------------------------------------------------- 常量（冻结）

export const LCG_A = 1664525;
export const LCG_C = 1013904223;
export const MASK32 = 0xffffffff;

/** I5：i18n 每语言必须齐全的字符串键。 */
export const REQUIRED_STRING_KEYS = ["cta", "tutorial", "win", "lose", "score"];

/** 与 schema default 注解一致的模板参数默认值（校验器侧解析缺省用）。 */
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

/** pullpin hazard 重抽的最大尝试次数（全撞则取 (rescuee+1)%pins）。 */
export const PULLPIN_REROLL_MAX = 16;

/** I4：时长预算上限（schema maximum=30 的第二层兜底，spec-contract §3）。 */
export const MAX_DURATION_SEC = 30;

// ---------------------------------------------------------------- 确定性随机源

/** 32 位 LCG（Math.imul + >>>0 复刻 mod 2^32；与 oracle pfcore.Lcg 同余）。 */
export class Lcg {
  state: number;

  constructor(seed: number) {
    this.state = Number(seed) >>> 0;
  }

  nextU32(): number {
    this.state = (Math.imul(LCG_A, this.state) + LCG_C) >>> 0;
    return this.state;
  }

  below(n: number): number {
    return this.nextU32() % n;
  }
}

// ---------------------------------------------------------------- 规范生成器

type Row = number[];
type Board = Row[];
/** sort 走法 (src, dst, k)：把 src 柱顶的同色段 k 格整体搬到 dst。 */
type Move = [number, number, number];

/** 按 seed 生成 match3 初始盘面（行优先逐格 below(colors)，独立建流）。 */
export function match3Board(seed: number, rows: number, cols: number, colors: number): Board {
  const rng = new Lcg(seed);
  const board: Board = [];
  for (let r = 0; r < rows; r++) {
    const row: Row = [];
    for (let c = 0; c < cols; c++) row.push(rng.below(colors));
    board.push(row);
  }
  return board;
}

function boardHasMatch(b: Board, rows: number, cols: number): boolean {
  for (let r = 0; r < rows; r++) {
    let run = 1;
    for (let c = 1; c < cols; c++) {
      run = b[r]![c] === b[r]![c - 1] ? run + 1 : 1;
      if (run >= 3) return true;
    }
  }
  for (let c = 0; c < cols; c++) {
    let run = 1;
    for (let r = 1; r < rows; r++) {
      run = b[r]![c] === b[r - 1]![c] ? run + 1 : 1;
      if (run >= 3) return true;
    }
  }
  return false;
}

/** 返回一个可行步 [r1,c1,r2,c2]（扫相邻交换，方向 (0,1)/(1,0)），无则 null。 */
export function match3FindMove(board: Board): [number, number, number, number] | null {
  const rows = board.length;
  const cols = rows > 0 ? board[0]!.length : 0;
  if (rows === 0 || cols === 0) return null;
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      for (const [dr, dc] of [[0, 1], [1, 0]] as const) {
        const r2 = r + dr;
        const c2 = c + dc;
        if (r2 >= rows || c2 >= cols || board[r]![c] === board[r2]![c2]) continue;
        const tmp = board[r]![c]!;
        board[r]![c] = board[r2]![c2]!;
        board[r2]![c2] = tmp;
        const ok = boardHasMatch(board, rows, cols);
        board[r2]![c2] = board[r]![c]!;
        board[r]![c] = tmp;
        if (ok) return [r, c, r2, c2];
      }
    }
  }
  return null;
}

/** 每关 [rescueeIdx, hazardIdx]；单流跨关卡，重抽至多 PULLPIN_REROLL_MAX 次。 */
export function pullpinLevelRoles(seed: number, levels: number, pinsPerLevel: number): [number, number][] {
  const rng = new Lcg(seed);
  const roles: [number, number][] = [];
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

/** 对一关按 order 逐针模拟：返回 [是否救出, 原因]。 */
export function pullpinSimulate(order: readonly number[], rescuee: number, hazard: number): [boolean, string] {
  for (const pin of order) {
    if (pin === hazard) return [false, "机关针在救援针之前被拔出"];
    if (pin === rescuee) return [true, "角色逃出"];
  }
  return [false, "救援针未被拔出"];
}

/** 已解状态：前 min(colors,rods) 根柱各为一色满柱，其余为空柱。 */
export function sortSolvedBoard(rods: number, layersPerRod: number, colors: number): Board {
  const filled = Math.min(colors, rods);
  const board: Board = [];
  for (let c = 0; c < filled; c++) board.push(Array<number>(layersPerRod).fill(c));
  while (board.length < rods) board.push([]);
  return board;
}

/** 合法走法（同色顶段整体搬移，k = min(顶段长, 空位)，目标柱顶同色或空）。 */
export function sortLegalMoves(board: Board, layersPerRod: number): Move[] {
  const moves: Move[] = [];
  for (let src = 0; src < board.length; src++) {
    const rod = board[src]!;
    if (rod.length === 0) continue;
    const color = rod[rod.length - 1]!;
    let run = 1;
    while (run < rod.length && rod[rod.length - 1 - run] === color) run++;
    for (let dst = 0; dst < board.length; dst++) {
      if (dst === src) continue;
      const drod = board[dst]!;
      const space = layersPerRod - drod.length;
      if (space <= 0) continue;
      if (drod.length > 0 && drod[drod.length - 1] !== color) continue;
      moves.push([src, dst, Math.min(run, space)]);
    }
  }
  return moves;
}

/** 就地把 src 柱顶 k 格搬到 dst（调用方保证合法）。 */
export function sortApplyMove(board: Board, src: number, dst: number, k: number): void {
  const color = board[src]![board[src]!.length - 1]!;
  for (let i = 0; i < k; i++) {
    board[src]!.pop();
    board[dst]!.push(color);
  }
}

/** 逆步（把刚搬的 k 个从 dst 搬回 src）是否为合法走法——可逆性判据。 */
export function sortInverseLegal(board: Board, src: number, dst: number, k: number, layersPerRod: number): boolean {
  const color = board[dst]![board[dst]!.length - k]!;
  const s = board[src]!;
  if (s.length + k > layersPerRod) return false;
  return s.length === 0 || s[s.length - 1] === color;
}

/** 由已解状态经"逆步合法"走法扰动出初始盘面，返回 [盘面, 步迹]（独立建流）。 */
export function sortScramble(seed: number, rods: number, layersPerRod: number, colors: number): [Board, Move[]] {
  const rng = new Lcg(seed);
  const board = sortSolvedBoard(rods, layersPerRod, colors);
  const trace: Move[] = [];
  for (let step = 0; step < rods * layersPerRod; step++) {
    const cands: Move[] = [];
    for (const mv of sortLegalMoves(board, layersPerRod)) {
      const [s, d, k] = mv;
      const trial = board.map((rod) => rod.slice());
      sortApplyMove(trial, s, d, k);
      if (sortInverseLegal(trial, s, d, k, layersPerRod)) cands.push(mv);
    }
    if (cands.length === 0) break;
    const mv = cands[rng.below(cands.length)]!;
    sortApplyMove(board, mv[0], mv[1], mv[2]);
    trace.push(mv);
  }
  return [board, trace];
}

// ---------------------------------------------------------------- 模板 check 注册制（P1 接缝）

const templateChecks: TemplateCheck[] = [];

/** 注册模板包 check(spec)（追加语义，注册序即执行序）。 */
export function registerTemplateCheck(entry: TemplateCheck): void {
  templateChecks.push(entry);
}

/** 已注册 check 的模板名（注册序）。 */
export function listTemplateChecks(): string[] {
  return templateChecks.map((t) => t.template);
}

/** 清空全部已注册 check（测试隔离用）。 */
export function clearTemplateChecks(): void {
  templateChecks.length = 0;
}

// ---------------------------------------------------------------- 不变式检查

function isObj(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

type ParamValue = number | string | boolean | string[];

function resolved(defaults: Record<string, ParamValue>, params: Record<string, unknown>, key: string): ParamValue {
  const v = params[key];
  return (v === undefined ? defaults[key] : v) as ParamValue;
}

/**
 * schema 通过后执行；返回 SpecIssue[]（path 为 json-path 风格字段路径，空列表 = 通过）。
 * 之后追加已注册模板 check（template 匹配者，注册序）。
 */
export function checkInvariants(spec: unknown): SpecError[] {
  const issues: SpecError[] = [];
  if (!isObj(spec)) {
    return [{ path: "$", message: "顶层必须是 JSON object", code: "schema-type" }];
  }
  const game = isObj(spec.game) ? spec.game : {};
  const params = isObj(game.params) ? game.params : {};
  const template = game.template;
  const seed = isObj(spec.meta) && Number.isInteger(spec.meta.seed) ? (spec.meta.seed as number) : 0;

  // I4 时长预算：max <= 30（schema maximum 的第二层兜底），target <= max。
  const dur = isObj(game.durationBudgetSec) ? game.durationBudgetSec : {};
  const mx = dur.max;
  const tg = dur.target;
  if (typeof mx === "number" && mx > MAX_DURATION_SEC) {
    issues.push({ path: "$.game.durationBudgetSec.max",
      message: `max=${mx} 超过 ${MAX_DURATION_SEC} 秒预算上限`, code: "I4-duration-max" });
  }
  if (typeof tg === "number" && typeof mx === "number" && tg > mx) {
    issues.push({ path: "$.game.durationBudgetSec.target",
      message: `target=${tg} 不得超过 max=${mx}`, code: "I4-duration-target" });
  }

  // 模板级不变式（schema 已过，这里放心取字段，仍做类型防御；分支序 match3→merge→pullpin→sort）。
  if (template === "match3" && isObj(params)) {
    const colors = resolved(MATCH3_DEFAULTS, params, "colors") as number;
    const rows = resolved(MATCH3_DEFAULTS, params, "rows") as number;
    const cols = resolved(MATCH3_DEFAULTS, params, "cols") as number;
    const spriteKeys = resolved(MATCH3_DEFAULTS, params, "spriteKeys") as string[];
    if (colors > spriteKeys.length) {
      issues.push({ path: "$.game.params.colors",
        message: `colors=${colors} 超过 spriteKeys 数量 ${spriteKeys.length}`,
        code: "I3-sprites-cover-colors" });
    }
    const board = match3Board(seed, rows, cols, colors);
    if (match3FindMove(board) === null) {
      issues.push({ path: "$.meta.seed",
        message: `seed=${isObj(spec.meta) ? spec.meta.seed : undefined} 生成的 match3 初始盘面无可行步，请换 seed`,
        code: "I3-match3-feasible-move" });
    }
  } else if (template === "merge" && isObj(params)) {
    const maxTier = resolved(MERGE_DEFAULTS, params, "maxTier") as number;
    const spawnMax = resolved(MERGE_DEFAULTS, params, "spawnTierMax") as number;
    const goalTier = resolved(MERGE_DEFAULTS, params, "goalTier") as number;
    const spriteKeys = resolved(MERGE_DEFAULTS, params, "spriteKeys") as string[];
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
  } else if (template === "pullpin" && isObj(params)) {
    const levels = resolved(PULLPIN_DEFAULTS, params, "levels") as number;
    const pins = resolved(PULLPIN_DEFAULTS, params, "pinsPerLevel") as number;
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
      order.forEach((levelOrderUnknown, li) => {
        const base = `$.game.params.orderSolution[${li}]`;
        const levelOrder = Array.isArray(levelOrderUnknown) ? levelOrderUnknown : null;
        if (levelOrder === null || levelOrder.length === 0 ||
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
        const [rescuee, hazard] = li < roles.length ? roles[li]! : [0, 1];
        const [solved, reason] = pullpinSimulate(levelOrder, rescuee, hazard);
        if (!solved) {
          issues.push({ path: base,
            message: `第 ${li} 关不可解：${reason}（rescuee=针${rescuee}, hazard=针${hazard}，布局由 seed 确定性生成）`,
            code: "I1-pullpin-unsolvable" });
        }
      });
    }
  } else if (template === "sort" && isObj(params)) {
    const rods = resolved(SORT_DEFAULTS, params, "rods") as number;
    const layers = resolved(SORT_DEFAULTS, params, "layersPerRod") as number;
    const colors = resolved(SORT_DEFAULTS, params, "colors") as number;
    if (colors > rods) {
      // I2 侧唯一前置域检查；其余域约束（colors≥2、rods≥3、layersPerRod≥2 等）属 schema 层。
      issues.push({ path: "$.game.params.colors",
        message: `colors=${colors} 不得超过 rods=${rods}（每色需一柱）`, code: "I2-sort-colors" });
    } else {
      // I2 栈可逆校验（重放方向钉死）：从已解盘面正向重放扰动步迹，
      // 每步须 ∈ sortLegalMoves 且逆步合法；重放完与生成器盘面逐柱比对。
      const [board, trace] = sortScramble(seed, rods, layers, colors);
      const replay = sortSolvedBoard(rods, layers, colors);
      let ok = true;
      for (let i = 0; i < trace.length; i++) {
        const [s, d, k] = trace[i]!;
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

  // I5 i18n：locales 每语言 strings 五键非空；defaultLocale ∈ locales；rtl ⊆ locales。
  const i18n = isObj(spec.i18n) ? spec.i18n : {};
  const locales = Array.isArray(i18n.locales) ? i18n.locales : [];
  const strings = isObj(i18n.strings) ? i18n.strings : {};
  for (const locale of locales) {
    const entry = strings[locale as string];
    if (!isObj(entry)) {
      issues.push({ path: `$.i18n.strings.${String(locale)}`,
        message: `语言 '${String(locale)}' 缺少 strings 条目`, code: "I5-i18n-coverage" });
      continue;
    }
    for (const key of REQUIRED_STRING_KEYS) {
      const val = entry[key];
      if (typeof val !== "string" || val.trim().length === 0) {
        issues.push({ path: `$.i18n.strings.${String(locale)}.${key}`,
          message: `语言 '${String(locale)}' 缺少字符串键 '${key}'`, code: "I5-i18n-coverage" });
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
        message: `RTL 语言 '${String(lang)}' 不在 locales 中`, code: "I5-i18n-rtl" });
    }
  });

  // 注册制（P1 接缝）：内建四模板之后追加已注册 check(spec)（template 匹配、注册序）。
  if (typeof template === "string") {
    for (const entry of templateChecks) {
      if (entry.template === template) {
        issues.push(...entry.check(spec));
      }
    }
  }

  return issues;
}

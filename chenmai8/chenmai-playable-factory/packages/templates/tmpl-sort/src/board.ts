// 排序盘面纯逻辑：模板侧视图/判定 + 冻结走法适配。
//
// 决策 §2.1 P1（可解性单一真源）：oracle 模板包内的 LCG/合法走法/apply/逆步/
// 规范扰动五重镜像废除——冻结算法唯一实现在 @pf/spec（src/invariants.ts；与
// oracle pfcore.invariants sort 段逐值同余，由 spec 包冻结测试锁定）。本文件只做：
//   - SortMove 对象视图（@pf/spec 内部为 [src,dst,k] 元组）；
//   - 模板侧判定/键函数 topRun / isSolved / completedColors / boardKey / cloneBoard
//     （模板内部实现，非冻结面）。
//
// 冻结走法语义（不变式 I2，语义面照抄模板资产 spec §7.3）：
//   - 一半是"倾倒"：把 src 顶部的同色连续段（run）整段倒向 dst，
//     k = min(run, dst 空位)；dst 必须为空或顶同色。
//   - 规范扰动 sortScramble：从已解盘面出发，只挑"逆步合法"的走法
//     （把刚搬的 k 个原路搬回也必须是合法走法），由 LCG 确定性迭代
//     rods*layersPerRod 步——可逆 ⇒ 与已解态连通 ⇒ 必有解。
// 全部函数无 DOM 依赖，可在 Node 下单测。

// 运行期引用一律走 invariants 叶子（@pf/spec 桶入口含 ajv 校验器——打包进游戏 HTML
// 会触打包器零外链红线；invariants.ts 纯逻辑零依赖，tsc/esbuild 同图解析）。
import {
  sortSolvedBoard,
  sortLegalMoves as frozenLegalMoves,
  sortApplyMove as frozenApplyMove,
  sortInverseLegal as frozenInverseLegal,
  sortScramble as frozenScramble,
} from "@pf/spec/invariants";

/** 盘面：rods 根柱，每柱自底向上的颜色下标栈。 */
export type Board = number[][];

/** 一步倾倒：把 src 顶部同色段搬 k 层到 dst。 */
export interface SortMove {
  src: number;
  dst: number;
  k: number;
}

/** 已解状态：前 min(colors, rods) 根各为一色满柱，其余为空柱（冻结生成器基态）。 */
export function solvedBoard(rods: number, layersPerRod: number, colors: number): Board {
  return sortSolvedBoard(rods, layersPerRod, colors);
}

/** 顶部同色段：{color, run}；空柱返回 null。 */
export function topRun(rod: number[]): { color: number; run: number } | null {
  if (!rod.length) return null;
  const color = rod[rod.length - 1];
  let run = 1;
  while (run < rod.length && rod[rod.length - 1 - run] === color) run++;
  return { color, run };
}

/** 合法走法表（同色顶段整体搬移，k = min(顶段长, 空位)——冻结走法 @pf/spec 单源）。 */
export function legalMoves(board: Board, layersPerRod: number): SortMove[] {
  return frozenLegalMoves(board, layersPerRod).map(([src, dst, k]) => ({ src, dst, k }));
}

/** 原地应用一步（假定已合法；调用方负责先查 legalMoves）。 */
export function applyMove(board: Board, src: number, dst: number, k: number): void {
  frozenApplyMove(board, src, dst, k);
}

/** 逆步（把刚搬的 k 个从 dst 原路搬回 src）是否为合法走法——可逆性判据。 */
export function inverseLegal(
  board: Board,
  src: number,
  dst: number,
  k: number,
  layersPerRod: number,
): boolean {
  return frozenInverseLegal(board, src, dst, k, layersPerRod);
}

/**
 * 规范扰动（M1 I2 权威单源）：由已解状态经"逆步合法"走法扰动出初始盘面。
 * 返回 [盘面, 步迹]；validator 逐步重放步迹做栈可逆校验。
 *
 * 注（模板深化发牌的依据，见 deal.ts）：从已解态出发，合法走法只能整柱搬运
 * （顶段 run = 满柱层数、空位 = 满柱层数 ⇒ k 取满），单色柱性质在扰动下保持，
 * 因此规范扰动盘面恒为"每柱单色"的已解态排列——真实谜题由深化发牌生成，
 * 规范扰动保留为冻结镜像基线与兜底。
 */
export function sortScramble(
  seed: number,
  rods: number,
  layersPerRod: number,
  colors: number,
): [Board, SortMove[]] {
  const [board, trace] = frozenScramble(seed, rods, layersPerRod, colors);
  return [board, trace.map(([src, dst, k]) => ({ src, dst, k }))];
}

/** 胜利判定（经典排序规则）：每根柱要么为空，要么是单色满柱。 */
export function isSolved(board: Board, layersPerRod: number): boolean {
  return board.every(
    (rod) => rod.length === 0 || (rod.length === layersPerRod && rod.every((c) => c === rod[0])),
  );
}

/** 已完成色数：存在"该色满柱"的颜色个数（HUD 进度/得分用）。 */
export function completedColors(board: Board, layersPerRod: number): number {
  const done = new Set<number>();
  for (const rod of board) {
    if (rod.length === layersPerRod && rod.every((c) => c === rod[0])) done.add(rod[0]);
  }
  return done.size;
}

/** 盘面规范化键（柱集合无序化——同构状态在求解器备忘表中命中同一键）。 */
export function boardKey(board: Board): string {
  return board.map((rod) => rod.join(",")).sort().join("|");
}

/** 深拷贝。 */
export function cloneBoard(board: Board): Board {
  return board.map((rod) => rod.slice());
}

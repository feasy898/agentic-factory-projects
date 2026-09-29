// pullpin 关卡纯逻辑：针角色视图适配 + 拔针模拟 + 规范解/兜底方案。
//
// 决策 §2.1 P1（可解性单一真源）：oracle 模板包内的 LCG/角色生成/拔针模拟
// 双镜像废除——冻结算法唯一实现在 @pf/spec（src/invariants.ts；与 oracle
// pfcore.invariants pullpin 段逐值同余，由 spec 包冻结测试锁定）。本文件只做：
//   - LevelRoles 视图适配（neutrals 由 (rescuee, hazard) 派生，升序）；
//   - 模板侧兜底方案 canonicalOrder / effectiveOrders（模板内部实现，非冻结面）。
//
// 冻结语义（不变式 I1，语义面照抄模板资产 spec §7.2）：
//   - 每关恰有一个救援针（拔掉即角色逃出）与一个机关针（先于救援针拔掉则角色
//     遇难），其余为中性针（引流，安全）。
//   - 拔针模拟：按顺序逐针拔；先拔到机关针 → 失败；拔到救援针 → 成功；
//     顺序走完仍没拔到救援针 → 失败。
// 全部函数无 DOM 依赖，可在 Node 下单测。

import {
  pullpinLevelRoles as frozenLevelRoles,
  pullpinSimulate as frozenPullpinSimulate,
  PULLPIN_REROLL_MAX,
} from "@pf/spec";

/** 与 @pf/spec 常量一致：角色针重抽的最大尝试次数（再导出供冻结测试对照）。 */
export { PULLPIN_REROLL_MAX };

/** 一关的针角色（针下标 → 角色）。 */
export interface LevelRoles {
  rescuee: number;
  hazard: number;
  /** 中性针下标（升序）。 */
  neutrals: number[];
}

/** 按 seed 生成每关角色（冻结生成器 @pf/spec 单源 + neutrals 派生）。 */
export function pullpinLevelRoles(seed: number, levels: number, pinsPerLevel: number): LevelRoles[] {
  return frozenLevelRoles(seed, levels, pinsPerLevel).map(([rescuee, hazard]) => {
    const neutrals: number[] = [];
    for (let p = 0; p < pinsPerLevel; p++) {
      if (p !== rescuee && p !== hazard) neutrals.push(p);
    }
    return { rescuee, hazard, neutrals };
  });
}

/** 拔针模拟（冻结模拟器 @pf/spec 单源）：返回 [是否救出, 原因]。 */
export function pullpinSimulate(
  order: readonly number[],
  rescuee: number,
  hazard: number,
): [boolean, string] {
  return frozenPullpinSimulate(order, rescuee, hazard);
}

/** 规范解：先拔全部中性针（引流）再拔救援针——对任意合法角色必可解。 */
export function canonicalOrder(roles: LevelRoles): number[] {
  return [...roles.neutrals, roles.rescuee];
}

/**
 * 每关生效的拔针方案：优先用 spec 的 orderSolution（M1 已验证可解）；
 * 形状不安全（空/越界/重复/不可解）时回退规范解——模板永不因 spec
 * 缺陷而不可玩（可解性主责在 @pf/spec 校验器，这里只是运行期兜底）。
 */
export function effectiveOrders(
  specOrders: number[][],
  roles: LevelRoles[],
  pinsPerLevel: number,
): number[][] {
  return roles.map((role, li) => {
    const order = Array.isArray(specOrders[li]) ? specOrders[li] : [];
    const inRange = order.every((p) => Number.isInteger(p) && p >= 0 && p < pinsPerLevel);
    const noDup = new Set(order).size === order.length;
    if (order.length > 0 && inRange && noDup) {
      const [solved] = pullpinSimulate(order, role.rescuee, role.hazard);
      if (solved) return order.slice();
    }
    return canonicalOrder(role);
  });
}

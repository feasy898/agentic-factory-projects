// pullpin 关卡纯逻辑：针角色规范生成器 + 拔针模拟 —— python/pfcore/invariants.py
// 的 pullpin 段与 packages/spec/src/invariants.mjs 的模板侧镜像（LCG 参数、重抽
// 规则、模拟步序逐行对应，任何一侧改动都视为破坏 schema v1 冻结契约）。
//
// 冻结语义（开发指令 §4.1 + M1 不变式 I1）：
//   - 每关恰有一个救援针（拔掉即角色逃出）与一个机关针（先于救援针拔掉则角色
//     遇难），其余为中性针（引流，安全）。
//   - 针角色由 seed 确定性生成：每关先抽 rescuee，再重抽（至多 16 次）不等于
//     rescuee 的 hazard；16 次全撞则取 (rescuee+1) % pinsPerLevel。
//   - 拔针模拟：按顺序逐针拔；先拔到机关针 → 失败；拔到救援针 → 成功；
//     顺序走完仍没拔到救援针 → 失败。
// 全部函数无 DOM 依赖，可在 Node 下单测。

import { Lcg } from "./rng.ts";

/** 与 invariants 常量一致：角色针重抽的最大尝试次数。 */
export const PULLPIN_REROLL_MAX = 16;

/** 一关的针角色（针下标 → 角色）。 */
export interface LevelRoles {
  rescuee: number;
  hazard: number;
  /** 中性针下标（升序）。 */
  neutrals: number[];
}

/** 按 seed 生成每关角色（与 pfcore.invariants.pullpin_level_roles 同余一致）。 */
export function pullpinLevelRoles(seed: number, levels: number, pinsPerLevel: number): LevelRoles[] {
  const rng = new Lcg(seed);
  const roles: LevelRoles[] = [];
  for (let i = 0; i < levels; i++) {
    const rescuee = rng.below(pinsPerLevel);
    let hazard = -1;
    for (let t = 0; t < PULLPIN_REROLL_MAX; t++) {
      const h = rng.below(pinsPerLevel);
      if (h !== rescuee) {
        hazard = h;
        break;
      }
    }
    if (hazard < 0) hazard = (rescuee + 1) % pinsPerLevel;
    const neutrals: number[] = [];
    for (let p = 0; p < pinsPerLevel; p++) {
      if (p !== rescuee && p !== hazard) neutrals.push(p);
    }
    roles.push({ rescuee, hazard, neutrals });
  }
  return roles;
}

/** 拔针模拟（与 pfcore.invariants.pullpin_simulate 一致）：返回 [是否救出, 原因]。 */
export function pullpinSimulate(
  order: number[],
  rescuee: number,
  hazard: number,
): [boolean, string] {
  for (const pin of order) {
    if (pin === hazard) return [false, "机关针在救援针之前被拔出"];
    if (pin === rescuee) return [true, "角色逃出"];
  }
  return [false, "救援针未被拔出"];
}

/** 规范解：先拔全部中性针（引流）再拔救援针——对任意合法角色必可解。 */
export function canonicalOrder(roles: LevelRoles): number[] {
  return [...roles.neutrals, roles.rescuee];
}

/**
 * 每关生效的拔针方案：优先用 spec 的 orderSolution（M1 已验证可解）；
 * 形状不安全（空/越界/重复/首针即机关针）时回退规范解——模板永不因 spec
 * 缺陷而不可玩（可解性主责在 M1 校验器，这里只是运行期兜底）。
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

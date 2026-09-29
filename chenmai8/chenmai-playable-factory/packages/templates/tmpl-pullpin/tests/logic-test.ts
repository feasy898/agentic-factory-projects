// pullpin 逻辑自测（开发期临时文件，不入构建产物；纯逻辑、无 DOM，Node 直跑）：
//  node --experimental-strip-types tests/logic-test.ts
//  冻结数值向量按 oracle tests/logic-test.ts 原样复用（"语义冻结、宿主移植"——
//  Python 权威侧实算回填的期望值逐值不动；宿主从 oracle 双镜像改为 @pf/spec 单源，
//  决策 §2.1 P1）：
//  1) 针角色生成器冻结向量：golden seed 与 pfcore.invariants（Python 权威侧）同余
//     （python -c "from pfcore.invariants import pullpin_level_roles; \
//                 print(pullpin_level_roles(20260930, 3, 3))"  →  [(2, 1), (1, 0), (1, 0)]）；
//  2) M1 冻结模拟（I1）：golden spec 的 orderSolution 逐关可解；
//  3) hint 线不变式：直接拔救援针必过关（autoplay 正确性的根）；
//  4) 跨 seed 批量：角色合法（hazard≠rescuee、范围内）、规范解恒可解；
//  5) effectiveOrders 兜底：坏形状（空/越界/重复/不可解）回退规范解；
//  6) LCG 冻结向量（seed 12345 前三拍，Python 实算回填）。
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { Lcg } from "@pf/spec";
import {
  effectiveOrders,
  pullpinLevelRoles,
  pullpinSimulate,
  canonicalOrder,
} from "../src/levels.ts";
import { normalizeSpec } from "../src/spec.ts";

let pass = 0, fail = 0;
const check = (name: string, ok: boolean) => {
  ok ? pass++ : fail++;
  console.log(`${ok ? "PASS" : "FAIL"} ${name}`);
};

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../../..");

// 1) 针角色生成器冻结向量（golden seed 实算回填，逐值不动）
const goldenRoles = pullpinLevelRoles(20260930, 3, 3);
check(
  "golden seed 针角色与 pfcore.invariants 一致（[(2,1),(1,0),(1,0)]）",
  JSON.stringify(goldenRoles.map((r) => [r.rescuee, r.hazard])) === "[[2,1],[1,0],[1,0]]",
);

// 2) golden spec 的 orderSolution 逐关可解（I1 镜像）
const goldenRaw = JSON.parse(readFileSync(path.join(ROOT, "specs-eval", "golden-pullpin.json"), "utf8"));
const goldenSpec = normalizeSpec(goldenRaw);
check(
  "golden normalizeSpec：levels=3 pinsPerLevel=3 hazard=lava",
  goldenSpec.params.levels === 3 && goldenSpec.params.pinsPerLevel === 3 && goldenSpec.params.hazard === "lava",
);
const goldenOrdersOk = goldenRoles.every((r, li) => {
  const order = goldenSpec.params.orderSolution[li] ?? [];
  const [solved] = pullpinSimulate(order, r.rescuee, r.hazard);
  return solved;
});
check("golden orderSolution 逐关可解（I1）", goldenOrdersOk);

// 3) hint 线不变式：直接拔救援针必过关
check(
  "直接拔救援针必过关（hint 线 = M1 可解判定）",
  goldenRoles.every((r) => pullpinSimulate([r.rescuee], r.rescuee, r.hazard)[0]),
);

// 4) 跨 seed 批量：角色合法 + 规范解恒可解（含 pinsPerLevel 3..5）
let sweepOk = true;
for (let s = 0; s < 300 && sweepOk; s++) {
  const seed = 1 + s * 7919;
  for (const pins of [3, 4, 5]) {
    const roles = pullpinLevelRoles(seed, 4, pins);
    for (const r of roles) {
      if (r.rescuee < 0 || r.rescuee >= pins || r.hazard < 0 || r.hazard >= pins) sweepOk = false;
      if (r.rescuee === r.hazard) sweepOk = false;
      if (r.neutrals.length !== pins - 2) sweepOk = false;
      if (!pullpinSimulate(canonicalOrder(r), r.rescuee, r.hazard)[0]) sweepOk = false;
    }
  }
}
check("300 seed × pinsPerLevel{3,4,5}：角色合法且规范解恒可解", sweepOk);

// 5) effectiveOrders 兜底：坏形状回退规范解
const roles3 = pullpinLevelRoles(20260930, 3, 3);
const bad = effectiveOrders(
  [[], [9, 9], [1, 1], ...[]], // 空 / 越界 / 重复（第 1 关 hazard=0 首针也不可解的场景由 [1,1] 覆盖形状坏）
  roles3,
  3,
);
check(
  "effectiveOrders：坏形状逐关回退规范解",
  bad.every((order, li) => JSON.stringify(order) === JSON.stringify(canonicalOrder(roles3[li]))),
);
const unsolvable = effectiveOrders([[roles3[0].hazard, roles3[0].rescuee], [1], [1]], roles3, 3);
check(
  "effectiveOrders：不可解顺序（第 0 关机关针先拔）回退规范解；可解的 [1]（直拔救援针）原样保留",
  JSON.stringify(unsolvable[0]) === JSON.stringify(canonicalOrder(roles3[0])) &&
    JSON.stringify(unsolvable[1]) === "[1]" &&
    JSON.stringify(unsolvable[2]) === "[1]",
);
const good = effectiveOrders(goldenSpec.params.orderSolution, roles3, 3);
check(
  "effectiveOrders：合法可解顺序原样保留",
  good.every((order, li) => JSON.stringify(order) === JSON.stringify(goldenSpec.params.orderSolution[li])),
);

// 6) LCG 冻结向量（seed 12345 前三拍；python 实算回填：
//    [s:=(1664525*s+1013904223)&0xffffffff for _ in range(3)] → [87628868, 71072467, 2332836374]）
const lcg = new Lcg(12345);
const seq = [lcg.nextU32(), lcg.nextU32(), lcg.nextU32()];
check(
  "LCG 与 Python 同余（seed 12345 前三拍）",
  JSON.stringify(seq) === JSON.stringify([87628868, 71072467, 2332836374]),
);

console.log(`logic-test: ${pass} pass / ${fail} fail`);
if (fail) process.exit(1);

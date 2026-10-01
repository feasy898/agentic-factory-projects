// 确定性随机源：32 位 LCG（numrecipes 经典参数）。
// 这是 python/pfcore/invariants.py 与 packages/spec/src/invariants.mjs 同一套冻结
// 算法的模板侧镜像（state = (1664525*state + 1013904223) mod 2^32，取值 next() % n），
// 用于由 spec.meta.seed 确定性推导每关针角色——模板盘面与 M1 校验器判定的可解性
// 必须一致（schema v1 冻结契约）。

export const LCG_A = 1664525;
export const LCG_C = 1013904223;
export const MASK32 = 0xffffffff;

export class Lcg {
  private state: number;

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

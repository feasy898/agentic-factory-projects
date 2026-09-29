// 确定性随机源（mulberry32，模板族共享约定，与 tmpl-match3 同一权威定义）。
// 同一 spec seed 生成同一盘面，保证评测可复现；salt 派生流语义见 solver.ts。
export type Rng = () => number;

export function mulberry32(seed: number): Rng {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** 由主种子派生子流（模拟器等场合用独立流，避免消耗主流状态）。 */
export function deriveRng(seed: number, salt: number): Rng {
  return mulberry32((seed ^ Math.imul(salt, 0x9e3779b9)) >>> 0);
}

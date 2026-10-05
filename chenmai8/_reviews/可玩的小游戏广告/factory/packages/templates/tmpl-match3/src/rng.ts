// 确定性随机源（mulberry32，模板族共享约定）。同一 spec seed 生成同一盘面，
// 保证"逻辑层强等"（规则卡 §7 内联块为唯一权威定义，第二乘数是 t|61 而非常数 61）。
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

/** 由主种子派生子流：模拟/结算/hint 各用独立流，互不消耗彼此状态。 */
export function deriveRng(seed: number, salt: number): Rng {
  return mulberry32((seed ^ Math.imul(salt, 0x9e3779b9)) >>> 0);
}

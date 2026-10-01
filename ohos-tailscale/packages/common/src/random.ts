/**
 * 随机源注入接口（P4：核心 src 禁 Math.random()/crypto.getRandomValues 等非确定来源）。
 *
 * 命名说明：constraints P4 示例中的 RandomSource 在本架构定名为 Rng，
 * 方法签名保持 P4 原样（randomBytes(into: Uint8Array): void）—— 见 docs/architecture.md §注入接口。
 *
 * 本文件是全仓共享注入接口，公开 API 已冻结。
 * 密码学实现（真机 cryptoFramework / Node node:crypto 包装）放 app/ 侧 adapter；
 * 本包只提供确定性测试实现。
 */

export interface Rng {
  /** 把 into 数组填满密码学安全随机字节；实现必须填满整个数组。 */
  randomBytes(into: Uint8Array): void;
}

/**
 * 测试用确定性随机源：按内部游标从 pool 循环取字节填充。
 * 构造时对 pool 做拷贝，后续外部修改不影响本实例。
 */
export class ArrayRng implements Rng {
  private pool: Uint8Array;
  private cursor: number = 0;

  constructor(pool: Uint8Array) {
    this.pool = pool.slice();
  }

  public randomBytes(into: Uint8Array): void {
    if (this.pool.length === 0) {
      throw new Error('ArrayRng: empty pool');
    }
    for (let i: number = 0; i < into.length; i += 1) {
      into[i] = this.pool[this.cursor];
      this.cursor = (this.cursor + 1) % this.pool.length;
    }
  }
}

/**
 * 时钟注入接口（P4：核心 src 禁 Date.now()/performance.now()，一律构造注入）。
 *
 * 本文件是全仓共享注入接口，公开 API 已冻结（docs/architecture.md §注入接口）。
 * 平台实现（真机系统时钟、Node 侧 Date.now 包装）不在核心库内 —— 放 app/ 侧 adapter，
 * 避免 P3（src 禁 node:*）与 P4 的实现位置冲突（constraints §6-U7）。
 */

export interface Clock {
  /** 挂钟毫秒（协议时间戳、LastSeen 等用；可能被用户调整、可能回拨） */
  wallMs(): number;
  /** 单调毫秒（超时、重传间隔计算用；不回拨） */
  monotonicMs(): number;
}

/**
 * 测试用确定性时钟：wall 与 mono 两轴同步推进。
 * advanceMs 只允许前进（保持单调契约）；setWallMs 仅平移挂钟轴（模拟时钟跳变）。
 */
export class FixedClock implements Clock {
  private wall: number;
  private mono: number = 0;

  constructor(startWallMs: number = 0) {
    this.wall = startWallMs;
  }

  public wallMs(): number {
    return this.wall;
  }

  public monotonicMs(): number {
    return this.mono;
  }

  /** 沿两轴同时前进 delta 毫秒；delta 为负抛 Error。 */
  public advanceMs(delta: number): void {
    if (delta < 0) {
      throw new Error('FixedClock.advanceMs: negative delta ' + String(delta));
    }
    this.wall += delta;
    this.mono += delta;
  }

  /** 把挂钟轴平移到指定值（模拟用户改时钟）；单调轴不受影响。 */
  public setWallMs(v: number): void {
    this.wall = v;
  }
}

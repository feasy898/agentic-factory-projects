/**
 * DERP region/节点数据结构与 home region 选择（架构契约 §8.2）。
 *
 * 取证对齐（docs/oracle/protocol-notes.md §3/§5）：
 * - CertName 在实测 derp-map 中全部缺省：TLS 校验层必须实现"CertName 优先、HostName 回退"，
 *   本结构只保证字段语义（certName = '' 表示未配置）；
 * - stunPort/derpPort = 0 表示未显式下发，消费方按 STUN_DEFAULT_PORT(3478)/DERP_DEFAULT_PORT(443) 兜底；
 * - latencyMs = -1 表示未测出延迟，region 选择必须能兜底（实测 region 999 测不出延迟仍可通信）。
 */

import { DerpError } from './frame.ts';

export interface DerpNode {
  name: string;
  hostName: string; // DNS 解析 + TLS SNI
  certName: string; // '' = 未配置 → TLS 校验回退 hostName
  ipv4: string; // '' = 无
  ipv6: string; // '' = 无
  stunPort: number; // 0 = 未显式下发（按 STUN_DEFAULT_PORT）；负值 = 该节点不做 STUN
  derpPort: number; // 0 = 未显式下发（按 DERP_DEFAULT_PORT）
  canPort80: boolean;
}

export interface DerpRegion {
  regionId: number;
  regionCode: string; // status --json 的 Relay 字段取值
  regionName: string;
  nodes: DerpNode[];
  latencyMs: number; // -1 = 未测出
}

/**
 * home region 选择器（构造时持有 region 列表；setLatency 覆盖值存内部表，不改调用方对象）。
 */
export class DerpRegionPicker {
  private regions: DerpRegion[];
  private latencies: Map<number, number> = new Map<number, number>();

  constructor(regions: DerpRegion[]) {
    this.regions = regions.slice(); // 数组浅拷贝；region/node 对象与调用方共享
  }

  /** 记录某 region 实测延迟；regionId 未知抛 DerpError('RANGE')。 */
  public setLatency(regionId: number, latencyMs: number): void {
    const target: DerpRegion | null = this.regionById(regionId);
    if (target === null) {
      throw new DerpError('RANGE', 'unknown derp region id: ' + String(regionId)) as Error;
    }
    this.latencies.set(regionId, latencyMs);
  }

  /**
   * home region：最小非负 latencyMs（并列取先声明者）；
   * 全部未测出（<0）→ nodes 非空的第一个 region；
   * 无 region → null。
   */
  public homeRegion(): DerpRegion | null {
    let best: DerpRegion | null = null;
    let bestLatency: number = -1;
    for (const r of this.regions) {
      const latency: number = this.latencyOf(r);
      if (latency < 0) {
        continue;
      }
      if (best === null || latency < bestLatency) {
        best = r;
        bestLatency = latency;
      }
    }
    if (best !== null) {
      return best;
    }
    for (const r of this.regions) {
      if (r.nodes.length > 0) {
        return r;
      }
    }
    return null;
  }

  /** 按 id 查 region；无则 null。 */
  public regionById(id: number): DerpRegion | null {
    for (const r of this.regions) {
      if (r.regionId === id) {
        return r;
      }
    }
    return null;
  }

  /** region 内选节点：一期固定 nodes[0]（随机挑选策略二期注入 Rng 后启用）；空 region 抛 DerpError('RANGE')。 */
  public pickNode(region: DerpRegion): DerpNode {
    if (region.nodes.length === 0) {
      throw new DerpError('RANGE', 'derp region ' + String(region.regionId) + ' has no nodes') as Error;
    }
    return region.nodes[0];
  }

  private latencyOf(r: DerpRegion): number {
    const override: number | undefined = this.latencies.get(r.regionId);
    if (override !== undefined) {
      return override;
    }
    return r.latencyMs;
  }
}

/**
 * StunTransaction：netcheck 引擎的单次探测事务配对核心（确定性、可注入）。
 *
 * 职责：生成 TxID（经注入 Rng，P4）→ 产出请求字节 → 对收到的 UDP 载荷做
 * "是 STUN 且 TxID 匹配"配对并解出 XOR-MAPPED 地址 → 经注入 Clock 的单调轴
 * 算 RTT。UDP socket/定时调度/多 server 编排属引擎层，留二期
 * （src/stun.ts 头注"引擎边界"）。
 */

import { type Rng } from '@ohos-tailscale/common';
import {
  STUN_TXID_LEN_BYTES,
  type StunParsedResponse,
  stunIs,
  stunParseResponse,
  stunRequest,
  stunTxid,
} from './stun.ts';

/** 时钟最小接口（与 common.Clock 的单调轴同形；避免对 common 之外的新依赖）。 */
export interface MonoClock {
  monotonicMs(): number;
}

export class StunTransaction {
  public readonly txid: Uint8Array;
  private readonly sentMonoMs: number;
  private readonly clock: MonoClock;

  constructor(rng: Rng, clock: MonoClock) {
    const tx: Uint8Array = new Uint8Array(STUN_TXID_LEN_BYTES);
    rng.randomBytes(tx);
    this.txid = tx;
    this.clock = clock;
    this.sentMonoMs = clock.monotonicMs();
  }

  /** 产出 Binding Request 字节（40B）。 */
  public requestBytes(): Uint8Array {
    return stunRequest(this.txid);
  }

  /**
   * 配对一条收到的 UDP 载荷：非 STUN 或 TxID 不匹配 → null；
   * 解析失败（NOT_SUCCESS/MALFORMED 等）按上游语义上抛 StunError。
   */
  public matchResponse(buf: Uint8Array): StunParsedResponse | null {
    if (!stunIs(buf)) {
      return null;
    }
    const rxid: Uint8Array = stunTxid(buf);
    let same: boolean = rxid.length === this.txid.length;
    for (let i: number = 0; same && i < rxid.length; i += 1) {
      if (rxid[i] !== this.txid[i]) {
        same = false;
      }
    }
    if (!same) {
      return null;
    }
    return stunParseResponse(buf);
  }

  /** 收到响应时刻的单调 RTT（毫秒）。 */
  public rttMs(): number {
    return this.clock.monotonicMs() - this.sentMonoMs;
  }
}

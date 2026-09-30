/**
 * ShellDiscoClient / ShellStunProbe —— 壳侧发现面（disco 打洞 + STUN 公网映射）会话门面。
 *
 * 定位（worker-A 纯 TS 推进面第 2 轮）：把「壳 ↔ disco/netcheck 新包」的注入形状用
 * mock UDP 总线（mock-udp-bus.ts）钉死并测试。真机形态：UdpSocket → @ohos.net.socket
 * （fd 经 conn.protect 防环路，见 VpnExtensionAbility.ets 步骤 4 注释）；disco/netcheck
 * 包的协议逻辑零改动（只 import，D4/A29 边界不变）。
 *
 * 语义对齐（上游实读，见 packages/disco|netcheck 头注）：
 * - disco wrapper："TS💬" magic ‖ 发端公钥 ‖ nonce24 ‖ secretbox；发端公钥是身份
 *   （与 NAT 观察端点无关）；Pong 的 srcIp16/srcPort = Ping 发起端被 Pong 发送端
 *   观察到的地址（发起端据此学得自己的公网映射，上游 disco.Pong 语义）；
 * - STUN：Binding Request（SOFTWARE+FINGERPRINT）→ XOR-MAPPED 回包 = NAT 公网映射。
 * ArkTS 无联合类型：ShellDiscoEvent 用可空字段载体（与 disco 包 DiscoDecodedMessage 同式）。
 */

import {
  type Clock,
  type Rng,
} from '@ohos-tailscale/common';
import {
  DISCO_NONCE_LEN_BYTES,
  DISCO_TXID_LEN_BYTES,
  DiscoMessageType,
  callMeMaybeEncode,
  discoMessageParse,
  discoOpen,
  discoSeal,
  pingEncode,
  pongEncode,
  type DiscoCallMeMaybe,
  type DiscoPing,
  type DiscoPong,
} from '@ohos-tailscale/disco';
import { StunTransaction } from '@ohos-tailscale/netcheck';
import {
  mapIp16FromV4,
  parseEndpoint,
  type UdpInbound,
  type UdpSocket,
} from './mock-udp-bus.ts';

/** 事件类别常量表（禁 enum，常量对象；0 = 无事件）。 */
export interface ShellDiscoEventKindE {
  None: number;
  Ping: number;
  Pong: number;
  CallMeMaybe: number;
}

export const ShellDiscoEventKind: ShellDiscoEventKindE = {
  None: 0,
  Ping: 1,
  Pong: 2,
  CallMeMaybe: 3,
};

/** 一次 poll 的事件载体（对应字段挂载荷，其余 null）。 */
export interface ShellDiscoEvent {
  kind: number;
  ping: DiscoPing | null;
  pong: DiscoPong | null;
  callMeMaybe: DiscoCallMeMaybe | null;
  /** 发端 disco 公钥（wrapper 携带的身份；None 事件为 null）。 */
  senderPublic: Uint8Array | null;
  /** 发端公网观察端点（"ip:port"，总线 NAT 视图）。 */
  fromEndpoint: string;
}

const noneEvent = (fromEndpoint: string): ShellDiscoEvent => {
  const ev: ShellDiscoEvent = {
    kind: ShellDiscoEventKind.None,
    ping: null,
    pong: null,
    callMeMaybe: null,
    senderPublic: null,
    fromEndpoint: fromEndpoint,
  };
  return ev;
};

export interface ShellDiscoClientParams {
  /** 已绑定的本地 UDP socket（总线 mock；真机为 @ohos.net.socket 适配）。 */
  socket: UdpSocket;
  /** 对端 disco 公钥（32B；wrapper 密封目标）。 */
  peerDiscoPublic: Uint8Array;
  /** 本端 disco 私钥（32B；解封对端来报）。 */
  myDiscoPrivate: Uint8Array;
  /** 本端 WireGuard node 公钥（可空 = Ping 不带 NodeKey，与上游 IsZero 语义一致）。 */
  nodeKey: Uint8Array | null;
  /** 随机源注入（nonce24 与 txid 消费方；P4）。 */
  rng: Rng;
}

export class ShellDiscoClient {
  private params: ShellDiscoClientParams;
  /** 对端 UDP 端点（真机来自 netmap 的 peer endpoint；构造后由 shell 设置）。 */
  public peerEndpoint: string = '';

  public constructor(params: ShellDiscoClientParams) {
    this.params = params;
  }

  /** 对对端发一条密封 disco Ping；返回本次 txid（12B，供 Pong 配对）。 */
  public sendPing(): Uint8Array {
    const txid: Uint8Array = new Uint8Array(DISCO_TXID_LEN_BYTES);
    this.params.rng.randomBytes(txid);
    const ping: DiscoPing = { txid: txid, nodeKey: this.params.nodeKey, padding: 0 };
    this.sendSealed(pingEncode(ping));
    return txid;
  }

  /** 对对端发 CallMeMaybe（本端候选端点列表；ip16 为线上原样 16B）。 */
  public sendCallMeMaybe(endpoints: DiscoCallMeMaybe): void {
    this.sendSealed(callMeMaybeEncode(endpoints));
  }

  /**
   * 收一条入站报文并归类：非 disco 形态/解封失败（含错钥）→ None（不抛错，对齐
   * 上游 Open 返回 !ok 的宽松语义）；是 Ping 且 autoPong 开 → 自动回 Pong
   * （src = 发端在总线上的观察端点，即 NAT 公网视图）。
   */
  public poll(autoPong: boolean = true): ShellDiscoEvent {
    const pkt: UdpInbound | null = this.params.socket.receive();
    if (pkt === null) {
      return noneEvent('');
    }
    const opened = discoOpen(pkt.data, this.params.myDiscoPrivate);
    if (opened === null) {
      return noneEvent(pkt.from);
    }
    // 宽松语义：未知类型/截断报文（discoMessageParse 抛 'TYPE'/'SHORT'）按上游 Parse
    // 容错精神归为 None，不让单条坏报文打断壳侧轮询循环。
    const tryParse = (): ReturnType<typeof discoMessageParse> | null => {
      try {
        return discoMessageParse(opened.message);
      } catch {
        return null;
      }
    };
    const msg = tryParse();
    if (msg === null) {
      return noneEvent(pkt.from);
    }
    if (msg.kind === DiscoMessageType.Ping && msg.ping !== null) {
      if (autoPong) {
        this.sendPongFor(msg.ping, pkt.from);
      }
      const ev: ShellDiscoEvent = {
        kind: ShellDiscoEventKind.Ping,
        ping: msg.ping,
        pong: null,
        callMeMaybe: null,
        senderPublic: opened.senderPublic,
        fromEndpoint: pkt.from,
      };
      return ev;
    }
    const ev: ShellDiscoEvent = {
      kind: msg.kind === DiscoMessageType.Pong
        ? ShellDiscoEventKind.Pong
        : msg.kind === DiscoMessageType.CallMeMaybe
          ? ShellDiscoEventKind.CallMeMaybe
          : ShellDiscoEventKind.None,
      ping: null,
      pong: msg.pong,
      callMeMaybe: msg.callMeMaybe,
      senderPublic: opened.senderPublic,
      fromEndpoint: pkt.from,
    };
    return ev;
  }

  private sendPongFor(ping: DiscoPing, observedFrom: string): void {
    const parts = parseEndpoint(observedFrom);
    const srcIp16: Uint8Array = parts === null ? new Uint8Array(16) : mapIp16FromV4(parts.ip);
    const srcPort: number = parts === null ? 0 : parts.port;
    const pong: DiscoPong = { txid: ping.txid, srcIp16: srcIp16, srcPort: srcPort };
    this.sendSealed(pongEncode(pong));
  }

  private sendSealed(inner: Uint8Array): void {
    const nonce24: Uint8Array = new Uint8Array(DISCO_NONCE_LEN_BYTES);
    this.params.rng.randomBytes(nonce24);
    const sealed = discoSeal(inner, this.params.myDiscoPrivate, this.params.peerDiscoPublic, nonce24);
    this.params.socket.send(this.peerEndpoint, sealed.wrapper);
  }
}

export interface ShellStunProbeParams {
  /** 已绑定的本地 UDP socket。 */
  socket: UdpSocket;
  /** STUN 服务端端点（"ip:port"，例 MockStunServer 挂载点）。 */
  stunEndpoint: string;
  /** 随机源注入（TxID 生成）。 */
  rng: Rng;
  /** 单调时钟注入（RTT）。 */
  clock: Clock;
}

/** 一次探测结果（配对成功时）。 */
export interface ShellStunResult {
  txid: Uint8Array;
  /** 映射后公网地址（去映射原始字节：4B=IPv4 / 16B=IPv6）。 */
  ip: Uint8Array;
  port: number;
  /** 单调 RTT（毫秒）。 */
  rttMs: number;
}

export class ShellStunProbe {
  private params: ShellStunProbeParams;

  public constructor(params: ShellStunProbeParams) {
    this.params = params;
  }

  /**
   * 发起一次 Binding 探测并在总线上等响应。
   * betweenPolls：每次轮询间的推进钩子（测试用 FixedClock.advanceMs 模拟网络时延；
   * 真机形态为异步等待）。maxPolls 次内未配对到响应 → null（超时语义）。
   */
  public run(betweenPolls: (() => void) | null = null, maxPolls: number = 8): ShellStunResult | null {
    const tx: StunTransaction = new StunTransaction(this.params.rng, this.params.clock);
    this.params.socket.send(this.params.stunEndpoint, tx.requestBytes());
    for (let i: number = 0; i < maxPolls; i += 1) {
      if (betweenPolls !== null) {
        betweenPolls();
      }
      const pkt: UdpInbound | null = this.params.socket.receive();
      if (pkt === null) {
        continue;
      }
      const parsed = tx.matchResponse(pkt.data);
      if (parsed !== null) {
        const result: ShellStunResult = {
          txid: tx.txid,
          ip: parsed.ip,
          port: parsed.port,
          rttMs: tx.rttMs(),
        };
        return result;
      }
    }
    return null;
  }
}

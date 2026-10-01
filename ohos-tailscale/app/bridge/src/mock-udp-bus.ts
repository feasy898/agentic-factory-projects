/**
 * UdpDatagramBus —— 数据面发现层（disco/STUN）的壳侧确定性 mock UDP。
 *
 * 定位：VpnExtensionAbility 数据面的网络出口注入点（README-app.md §4：核心库不碰 socket，
 * UDP 由 app 侧注入；真机 = @ohos.net.socket + conn.protect(fd)）。本文件把该注入点做成
 * 内存数据报总线：bind 端点 → send/receive 字节报，同步、确定性、可复现。
 *
 * NAT 仿真：bind 可选 natPublic（公网映射端点）——总线上投递时 fromEndpoint 一律呈现
 * 公网映射（对端看到的源=公网视图），本地端点不出网。这正是 STUN 探测要测的映射、
 * 也是 disco Pong src 字段应回填的观察地址。
 *
 * 形态说明：同步队列（send 入队、receive 出队）为 mock 简化；真机实现按事件/回调适配，
 * 接口语义（端点字符串 + 裸字节报）保持不变。
 */

import { stunParseBindingRequest, stunResponse } from '@ohos-tailscale/netcheck';

/** "ip:port" 端点解析（仅 IPv4 字面量；v6/域名为引擎二期范围）。 */
export interface EndpointParts {
  ip: Uint8Array;
  port: number;
}

export const parseEndpoint = (endpoint: string): EndpointParts | null => {
  const idx: number = endpoint.lastIndexOf(':');
  if (idx < 0) {
    return null;
  }
  const ipText: string = endpoint.slice(0, idx);
  const portText: string = endpoint.slice(idx + 1);
  const port: number = Number(portText);
  const octets: string[] = ipText.split('.');
  if (octets.length !== 4 || !Number.isInteger(port) || port < 0 || port > 65535) {
    return null;
  }
  const ip: Uint8Array = new Uint8Array(4);
  for (let i: number = 0; i < 4; i += 1) {
    const v: number = Number(octets[i]);
    if (!Number.isInteger(v) || v < 0 || v > 255) {
      return null;
    }
    ip[i] = v;
  }
  const parts: EndpointParts = { ip: ip, port: port };
  return parts;
};

/** IPv4 4B → v4-mapped ip16（10×0x00 ‖ 0xff 0xff ‖ 4B；disco 线上原样形态）。 */
export const mapIp16FromV4 = (ip4: Uint8Array): Uint8Array => {
  const out: Uint8Array = new Uint8Array(16);
  out[10] = 0xff;
  out[11] = 0xff;
  out[12] = ip4[0];
  out[13] = ip4[1];
  out[14] = ip4[2];
  out[15] = ip4[3];
  return out;
};

export interface UdpSocketParams {
  /** 本地绑定端点（"ip:port"；仅作总线寻址标识）。 */
  endpoint: string;
  /** 公网映射端点（NAT 仿真；缺省 = 本地端点直连）。 */
  natPublic?: string;
}

export class UdpDatagramBus {
  private sockets: Map<string, UdpSocket> = new Map();
  private natMap: Map<string, string> = new Map();
  /** NAT 公网端点 → 本地端点反查（对端按公网视图寻址）。 */
  private natReverse: Map<string, string> = new Map();
  /** 送达报文计数（按目的端点）。 */
  public delivered: number = 0;
  /** 弃报计数（目的端点未绑定）。 */
  public dropped: number = 0;

  public bind(params: UdpSocketParams): UdpSocket {
    if (this.sockets.has(params.endpoint)) {
      throw new Error('udp bus: endpoint already bound: ' + params.endpoint);
    }
    const socket: UdpSocket = new UdpSocket(this, params.endpoint);
    this.sockets.set(params.endpoint, socket);
    if (params.natPublic !== undefined) {
      this.natMap.set(params.endpoint, params.natPublic);
      this.natReverse.set(params.natPublic, params.endpoint);
    }
    return socket;
  }

  public socketOf(endpoint: string): UdpSocket | null {
    const s: UdpSocket | undefined = this.sockets.get(endpoint);
    return s === undefined ? null : s;
  }

  /**
   * 总线投递：目的端点先按本地绑定解析，未命中再按 NAT 公网端点反查（对端只见公网视图）；
   * 均未命中则弃报计数。源呈现为 NAT 公网映射（或本地端点直连）。
   */
  public deliver(fromEndpoint: string, toEndpoint: string, data: Uint8Array): void {
    const direct: UdpSocket | undefined = this.sockets.get(toEndpoint);
    const viaNat: string | undefined = direct === undefined ? this.natReverse.get(toEndpoint) : undefined;
    const localTarget: string | undefined = direct === undefined ? viaNat : direct.endpoint;
    if (localTarget === undefined) {
      this.dropped += 1;
      return;
    }
    const target: UdpSocket = this.sockets.get(localTarget) as UdpSocket;
    const natPublic: string | undefined = this.natMap.get(fromEndpoint);
    const observedFrom: string = natPublic === undefined ? fromEndpoint : natPublic;
    target.inbound.push({ from: observedFrom, data: data.slice() });
    this.delivered += 1;
  }
}

/** 总线上的一条入站报文（from = 发端公网观察视图）。 */
export interface UdpInbound {
  from: string;
  data: Uint8Array;
}

export class UdpSocket {
  public readonly endpoint: string;
  public readonly bus: UdpDatagramBus;
  /** 入站队列（FIFO；receive 逐条取）。 */
  public readonly inbound: UdpInbound[] = [];
  /** 发出报文计数。 */
  public sent: number = 0;

  public constructor(bus: UdpDatagramBus, endpoint: string) {
    this.bus = bus;
    this.endpoint = endpoint;
  }

  public send(remoteEndpoint: string, data: Uint8Array): void {
    this.sent += 1;
    this.bus.deliver(this.endpoint, remoteEndpoint, data);
  }

  /** 取一条入站报文；队空返回 null。 */
  public receive(): UdpInbound | null {
    const next: UdpInbound | undefined = this.inbound.shift();
    return next === undefined ? null : next;
  }
}

/**
 * MockStunServer —— 挂在总线上的 STUN Binding 服务端（netcheck stun.ts 承载编解码）。
 * 行为：解析 Binding Request（含 FINGERPRINT 校验）→ 以「发端在总线上的观察端点」
 * 回 Binding Success Response——即该端的 NAT 公网映射，与真实 STUN 语义一致。
 */
export class MockStunServer {
  public readonly endpoint: string;
  public readonly socket: UdpSocket;
  /** 已响应请求数。 */
  public responded: number = 0;
  /** 非 STUN/解析失败收包数。 */
  public rejected: number = 0;

  public constructor(bus: UdpDatagramBus, endpoint: string) {
    this.endpoint = endpoint;
    this.socket = bus.bind({ endpoint: endpoint });
  }

  /** 处理一条入站报文；是合法 Binding Request 则回响应。 */
  public handleInbound(): void {
    for (;;) {
      const pkt: UdpInbound | null = this.socket.receive();
      if (pkt === null) {
        return;
      }
      const tryParseTxid = (): Uint8Array | null => {
        try {
          return stunParseBindingRequest(pkt.data);
        } catch {
          return null;
        }
      };
      const txid: Uint8Array | null = tryParseTxid();
      if (txid === null) {
        this.rejected += 1;
        continue;
      }
      const parts: EndpointParts | null = parseEndpoint(pkt.from);
      if (parts === null) {
        this.rejected += 1;
        continue;
      }
      this.socket.send(pkt.from, stunResponse(txid, parts.ip, parts.port));
      this.responded += 1;
    }
  }
}

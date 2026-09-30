/**
 * DERP 客户端状态机骨架（AU2 对齐后的真实协议流）。
 *
 * 状态机：Idle → connect() → Connecting → Ready → close()/协议失败 → Closed。
 * - connect()：dialer.dial → 读 ServerKey 帧（Magic(8B)+服务器公钥(32B)）→ 发 ClientInfo 帧
 *   （本端公钥(32B) + nonce(24B) + naclbox(json)）→ 读 ServerInfo 帧（跳过）→ Ready；
 * - 按 key 订阅：subscribePeer/unsubscribePeer 维护感兴趣的 peer 公钥集合（按内容去重，保序）；
 *   receive() 只上抛来自已订阅 srcKey 的 RecvPacket，未订阅来源的帧静默跳过；
 * - 收发：sendPacket（SendPacket 帧）、receive（上抛 RecvPacket/Pong/PeerGone 事件；
 *   KeepAlive/ServerInfo/PeerPresent/Health/Restarting 静默消费；Ping 自动回 Pong；
 *   其余帧类型（含未知类型）视为协议错误拒绝）；
 * - 时钟/随机数经 common 的 Clock/Rng 构造注入（P4），网络 IO 经 DerpDialer 注入（D4）；
 * - ClientInfo 的 naclbox（AU2）：naclboxSeal(nodePrivate, serverKey, nonce24, json)，
 *   JSON 为 {"Version":2,"MeshKey":"","CanAckPings":false,"IsProber":false,"AppName":"ohos-tailscale"}。
 *
 * 错误约定（R7/A25）：协议/结构错误 DerpError('FRAME')，数值越界 DerpError('RANGE')，
 * 状态机非法迁移与拨号失败 DerpError('STATE')（架构 §10.3 v1.1 裁定的 code 增补）。
 * receive() 抛出协议错误后连接不可继续，应由调用方 close()。
 */

import { KEY_LEN_BYTES, utf8Encode, hexEncode, type Clock, type Rng } from '@ohos-tailscale/common';
import { naclboxSeal } from '@ohos-tailscale/crypto';
import {
  DERP_MAGIC,
  DerpError,
  type DerpFrame,
  DerpFrameReader,
  DerpFrameType,
  derpFrameEncode,
} from './frame.ts';
import { type DerpConnection, type DerpDialer } from './connection.ts';
import { type DerpNode } from './region.ts';

export interface DerpClientStateE {
  Idle: number;
  Connecting: number;
  Ready: number;
  Closed: number;
}

export const DerpClientState: DerpClientStateE = {
  Idle: 1,
  Connecting: 2,
  Ready: 3,
  Closed: 4,
};

export interface DerpClientEventKindE {
  RecvPacket: number;
  Pong: number;
  PeerGone: number;
}

export const DerpClientEventKind: DerpClientEventKindE = {
  RecvPacket: 1,
  Pong: 2,
  PeerGone: 3,
};

/**
 * receive() 上抛的事件。不相关的字段统一为零长度数组（避免可空字段），rttMs 仅 Pong 有意义
 * （匹配到 pending Ping 时为单调时钟差，否则 -1）。srcKey/packet/data 均为独立拷贝。
 */
export interface DerpClientEvent {
  kind: number;
  srcKey: Uint8Array;
  packet: Uint8Array;
  data: Uint8Array;
  rttMs: number;
}

export interface DerpClientConfig {
  node: DerpNode; // 目标 DERP 节点（host/port 信息交给 dialer）
  nodeKey: Uint8Array; // 本端 node 公钥（32B，ClientInfo 载荷前段）
  nodePrivateKey: Uint8Array; // 本端 node 私钥（32B，ClientInfo 的 naclbox 封装）
  dialer: DerpDialer; // 注入：TLS 拨号（app/ 侧实现）
  clock: Clock; // 注入：单调时钟（Ping RTT）
  rng: Rng; // 注入：随机数（Ping 探测数据 + ClientInfo nonce）
}

/** Ping 探测数据长度（上游 derp.go FramePing 载荷 8B）。 */
const PING_DATA_LEN: number = 8;

/**
 * ClientInfo 的 JSON 载荷（上游 derp_client.go ClientInfo 的最小形态）。
 * ⚠ 实测锚定（headscale v0.29.4）：MeshKey 字段在类型上是 DERPMesh（32B），空串
 * 无法反序列化（"incorrect size mesh key len: 0, must be 32"）——无 mesh key 时必须
 * 整字段省略，不能发空串。
 */
const CLIENT_INFO_JSON: string =
  '{"Version":2,"CanAckPings":false,"IsProber":false,"AppName":"ohos-tailscale"}';

export class DerpClient {
  private node: DerpNode;
  private nodeKey: Uint8Array;
  private nodePrivateKey: Uint8Array;
  private dialer: DerpDialer;
  private clock: Clock;
  private rng: Rng;
  private state: number = DerpClientState.Idle;
  private conn: DerpConnection | null = null;
  private serverKeyBytes: Uint8Array | null = null;
  private frameReader: DerpFrameReader = new DerpFrameReader();
  private frameQueue: DerpFrame[] = [];
  private peerOrder: string[] = [];
  private peers: Map<string, Uint8Array> = new Map<string, Uint8Array>();
  private pendingPings: Map<string, number> = new Map<string, number>();

  constructor(cfg: DerpClientConfig) {
    if (cfg.nodeKey.length !== KEY_LEN_BYTES) {
      throw new DerpError(
        'RANGE',
        'nodeKey must be ' + String(KEY_LEN_BYTES) + ' bytes, got ' + String(cfg.nodeKey.length),
      ) as Error;
    }
    if (cfg.nodePrivateKey.length !== KEY_LEN_BYTES) {
      throw new DerpError(
        'RANGE',
        'nodePrivateKey must be ' + String(KEY_LEN_BYTES) + ' bytes, got ' + String(cfg.nodePrivateKey.length),
      ) as Error;
    }
    this.node = cfg.node;
    this.nodeKey = cfg.nodeKey.slice();
    this.nodePrivateKey = cfg.nodePrivateKey.slice();
    this.dialer = cfg.dialer;
    this.clock = cfg.clock;
    this.rng = cfg.rng;
  }

  public getState(): number {
    return this.state;
  }

  /** 服务器公钥（connect 成功后有值；返回独立拷贝）。 */
  public serverKey(): Uint8Array | null {
    const k: Uint8Array | null = this.serverKeyBytes;
    if (k === null) {
      return null;
    }
    return k.slice();
  }

  /** 建立连接并完成握手（ServerKey ← / ClientInfo →）。失败抛错且状态归 Closed。 */
  public async connect(): Promise<void> {
    this.checkState(DerpClientState.Idle, 'connect');
    this.state = DerpClientState.Connecting;
    let conn: DerpConnection | null = null;
    let dialText: string = '';
    try {
      conn = await this.dialer.dial(this.node);
    } catch (e) {
      dialText = String(e);
    }
    if (conn === null) {
      this.state = DerpClientState.Closed;
      throw new Error('derp dial failed: ' + dialText);
    }
    this.conn = conn;
    try {
      const keyFrame: DerpFrame = await this.expectFrame(DerpFrameType.ServerKey, 'ServerKey');
      // AU2：ServerKey 载荷 = Magic(8B) || 服务器公钥(32B)
      if (keyFrame.payload.length < DERP_MAGIC.length + KEY_LEN_BYTES) {
        throw new DerpError(
          'FRAME',
          'ServerKey payload too short: ' + String(keyFrame.payload.length),
        ) as Error;
      }
      for (let i: number = 0; i < DERP_MAGIC.length; i += 1) {
        if (keyFrame.payload[i] !== DERP_MAGIC[i]) {
          throw new DerpError('FRAME', 'ServerKey magic mismatch (not a DERP greeting)') as Error;
        }
      }
      this.serverKeyBytes = keyFrame.payload.slice(DERP_MAGIC.length, DERP_MAGIC.length + KEY_LEN_BYTES);
      await this.sendClientInfo(this.serverKeyBytes);
      // 服务器随后发 ServerInfo（0x03）：本端无 mesh key，跳过不消费内容
      await this.expectFrame(DerpFrameType.ServerInfo, 'ServerInfo');
    } catch (e) {
      const err: Error = e as Error;
      this.close();
      throw err;
    }
    this.state = DerpClientState.Ready;
  }

  /** ClientInfo 帧（AU2）：本端公钥(32B) || nonce(24B) || naclbox(json)。 */
  private async sendClientInfo(serverKey: Uint8Array): Promise<void> {
    const nonce: Uint8Array = new Uint8Array(24);
    this.rng.randomBytes(nonce);
    const sealed: Uint8Array = naclboxSeal(this.nodePrivateKey, serverKey, nonce, utf8Encode(CLIENT_INFO_JSON));
    const payload: Uint8Array = new Uint8Array(KEY_LEN_BYTES + sealed.length);
    payload.set(this.nodeKey, 0);
    payload.set(sealed, KEY_LEN_BYTES);
    await this.writeFrame(DerpFrameType.ClientInfo, payload);
  }

  /** 发送数据包：SendPacket 帧，payload = dstKey(32B) || packet。 */
  public async sendPacket(dstKey: Uint8Array, packet: Uint8Array): Promise<void> {
    this.checkState(DerpClientState.Ready, 'sendPacket');
    if (dstKey.length !== KEY_LEN_BYTES) {
      throw new DerpError('RANGE', 'dstKey must be 32 bytes, got ' + String(dstKey.length)) as Error;
    }
    const payload: Uint8Array = new Uint8Array(KEY_LEN_BYTES + packet.length);
    payload.set(dstKey, 0);
    payload.set(packet, KEY_LEN_BYTES);
    await this.writeFrame(DerpFrameType.SendPacket, payload);
  }

  /** 发送回显探测：Ping 帧携带 8 字节注入随机数；返回探测数据用于匹配 Pong。 */
  public async sendPing(): Promise<Uint8Array> {
    this.checkState(DerpClientState.Ready, 'sendPing');
    const data: Uint8Array = new Uint8Array(PING_DATA_LEN);
    this.rng.randomBytes(data);
    this.pendingPings.set(hexEncode(data), this.clock.monotonicMs());
    await this.writeFrame(DerpFrameType.Ping, data);
    return data.slice();
  }

  /** 发送保活帧（空 payload）。 */
  public async sendKeepAlive(): Promise<void> {
    this.checkState(DerpClientState.Ready, 'sendKeepAlive');
    await this.writeFrame(DerpFrameType.KeepAlive, new Uint8Array(0));
  }

  /** 上报 home DERP 偏好：NotePreferred 帧，payload = 单字节 0/1。 */
  public async notePreferred(preferred: boolean): Promise<void> {
    this.checkState(DerpClientState.Ready, 'notePreferred');
    const v: number = preferred ? 1 : 0;
    await this.writeFrame(DerpFrameType.NotePreferred, Uint8Array.from([v]));
  }

  /**
   * 读取并处理下一帧，直到产出事件或连接结束：
   * - RecvPacket：srcKey 已订阅 → 上抛事件；未订阅 → 静默跳过；
   * - Pong：匹配 pending Ping → rttMs = 单调时钟差；无匹配 → rttMs = -1；
   * - PeerGone：上抛事件（订阅表由调用方决定是否清理）；
   * - ServerPing：自动回 Pong（原 payload 回显）后继续读；
   * - KeepAlive：静默消费后继续读；
   * - 其余帧类型（含未知类型、客户端→服务器方向的帧）→ DerpError('FRAME')。
   * 连接结束（EOF）返回 null。
   */
  public async receive(): Promise<DerpClientEvent | null> {
    this.checkState(DerpClientState.Ready, 'receive');
    for (;;) {
      const frame: DerpFrame | null = await this.nextFrame();
      if (frame === null) {
        return null;
      }
      if (frame.type === DerpFrameType.RecvPacket) {
        if (frame.payload.length < KEY_LEN_BYTES) {
          throw new DerpError(
            'FRAME',
            'RecvPacket payload shorter than srcKey: ' + String(frame.payload.length),
          ) as Error;
        }
        const srcKey: Uint8Array = frame.payload.slice(0, KEY_LEN_BYTES);
        const packet: Uint8Array = frame.payload.slice(KEY_LEN_BYTES);
        if (!this.peers.has(hexEncode(srcKey))) {
          continue; // 未按 key 订阅该来源 → 跳过
        }
        const ev: DerpClientEvent = {
          kind: DerpClientEventKind.RecvPacket,
          srcKey: srcKey,
          packet: packet,
          data: new Uint8Array(0),
          rttMs: -1,
        };
        return ev;
      }
      if (frame.type === DerpFrameType.Pong) {
        const pingKey: string = hexEncode(frame.payload);
        const sentAt: number | undefined = this.pendingPings.get(pingKey);
        let rtt: number = -1;
        if (sentAt !== undefined) {
          rtt = this.clock.monotonicMs() - sentAt;
          this.pendingPings.delete(pingKey);
        }
        const pongData: Uint8Array = frame.payload.slice();
        const ev: DerpClientEvent = {
          kind: DerpClientEventKind.Pong,
          srcKey: new Uint8Array(0),
          packet: new Uint8Array(0),
          data: pongData,
          rttMs: rtt,
        };
        return ev;
      }
      if (frame.type === DerpFrameType.PeerGone) {
        if (frame.payload.length < KEY_LEN_BYTES) {
          throw new DerpError(
            'FRAME',
            'PeerGone payload shorter than peer key: ' + String(frame.payload.length),
          ) as Error;
        }
        const goneKey: Uint8Array = frame.payload.slice(0, KEY_LEN_BYTES);
        const ev: DerpClientEvent = {
          kind: DerpClientEventKind.PeerGone,
          srcKey: goneKey,
          packet: new Uint8Array(0),
          data: new Uint8Array(0),
          rttMs: -1,
        };
        return ev;
      }
      if (frame.type === DerpFrameType.Ping) {
        await this.writeFrame(DerpFrameType.Pong, frame.payload);
        continue;
      }
      if (
        frame.type === DerpFrameType.KeepAlive ||
        frame.type === DerpFrameType.ServerInfo ||
        frame.type === DerpFrameType.PeerPresent ||
        frame.type === DerpFrameType.Health ||
        frame.type === DerpFrameType.Restarting
      ) {
        continue;
      }
      throw new DerpError('FRAME', 'unexpected derp frame type on client link: ' + String(frame.type)) as Error;
    }
  }

  /** 按 key 订阅 peer（32B 公钥，按内容去重、保序）。长度不符抛 DerpError('RANGE')。 */
  public subscribePeer(key: Uint8Array): void {
    if (key.length !== KEY_LEN_BYTES) {
      throw new DerpError('RANGE', 'peer key must be 32 bytes, got ' + String(key.length)) as Error;
    }
    const k: string = hexEncode(key);
    if (this.peers.has(k)) {
      return;
    }
    this.peers.set(k, key.slice());
    this.peerOrder.push(k);
  }

  /** 取消订阅；未订阅时为 no-op。 */
  public unsubscribePeer(key: Uint8Array): void {
    const k: string = hexEncode(key);
    if (!this.peers.delete(k)) {
      return;
    }
    const idx: number = this.peerOrder.indexOf(k);
    if (idx >= 0) {
      this.peerOrder.splice(idx, 1);
    }
  }

  public isPeerSubscribed(key: Uint8Array): boolean {
    return this.peers.has(hexEncode(key));
  }

  /** 已订阅 peer 公钥列表（保持订阅顺序；返回独立拷贝）。 */
  public subscribedPeerKeys(): Uint8Array[] {
    const out: Uint8Array[] = [];
    for (const k of this.peerOrder) {
      const v: Uint8Array | undefined = this.peers.get(k);
      if (v !== undefined) {
        out.push(v.slice());
      }
    }
    return out;
  }

  /** 关闭连接并进入 Closed；幂等。 */
  public close(): void {
    if (this.conn !== null) {
      this.conn.close();
      this.conn = null;
    }
    this.state = DerpClientState.Closed;
  }

  private checkState(expected: number, op: string): void {
    if (this.state !== expected) {
      // 生命周期错误：按契约 §8.1 不占用 DerpError 的 code 集合，抛普通 Error
      throw new Error(
        op + ' requires state ' + String(expected) + ' but client is in state ' + String(this.state),
      );
    }
  }

  /** 取下一完整帧：优先消费内部队列，否则从连接读 chunk 喂帧重组器。EOF 返回 null。 */
  private async nextFrame(): Promise<DerpFrame | null> {
    for (;;) {
      if (this.frameQueue.length > 0) {
        const f: DerpFrame | undefined = this.frameQueue.shift();
        if (f !== undefined) {
          return f;
        }
        continue;
      }
      const conn: DerpConnection | null = this.conn;
      if (conn === null) {
        throw new Error('derp connection is closed');
      }
      const chunk: Uint8Array | null = await conn.read();
      if (chunk === null) {
        return null;
      }
      const frames: DerpFrame[] = this.frameReader.push(chunk);
      for (const f of frames) {
        this.frameQueue.push(f);
      }
    }
  }

  private async expectFrame(type: number, name: string): Promise<DerpFrame> {
    const f: DerpFrame | null = await this.nextFrame();
    if (f === null) {
      throw new DerpError('FRAME', 'derp connection closed while waiting for ' + name) as Error;
    }
    if (f.type !== type) {
      throw new DerpError('FRAME', 'expected ' + name + ' frame but got type ' + String(f.type)) as Error;
    }
    return f;
  }

  private async writeFrame(type: number, payload: Uint8Array): Promise<void> {
    const conn: DerpConnection | null = this.conn;
    if (conn === null) {
      throw new Error('derp connection is closed');
    }
    const bytes: Uint8Array = derpFrameEncode(type, payload);
    await conn.write(bytes);
  }
}

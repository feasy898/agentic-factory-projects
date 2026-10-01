/**
 * Peer 索引表：本端视角的"会话索引 → 对端会话"登记簿。
 *
 * WireGuard 语义：每个会话有两端各自选择的 u32 索引（本端 localIndex /
 * 对端 peerIndex）。收包时分发器用报文 receiver index（= 本端给对端分配的
 * localIndex）查表定位会话；发包时 receiver index 填对端的 peerIndex。
 * 本表就是分发器数据面：installSession 把握手产出装订成收发会话条目，
 * entryByLocalIndex 供 UDP 分发查用。
 *
 * 新会话装订即替换同 localIndex 的旧条目（白皮书重钥语义：新会话顶替旧会话）；
 * removePeer 级联移除该对端全部会话。
 */

import { KEY_LEN_BYTES } from '@ohos-tailscale/common';
import { type WgHandshakeOutput } from './handshake.ts';
import { WgRecvSession, WgSendSession } from './transport.ts';

/** 索引表条目（A2：纯字段 interface；会话对象为新建实例）。 */
export interface WgSessionEntry {
  /** 对端标识（调用方命名空间，如 nodekey hex）。 */
  peerId: string;
  /** 本端为该会话选择的索引（发包时填 sender，收包时用 receiver 匹配）。 */
  localIndex: number;
  /** 对端为该会话选择的索引（发包时填 receiver index）。 */
  peerIndex: number;
  /** 本端 → 对端 发送会话。 */
  sendSession: WgSendSession;
  /** 对端 → 本端 接收会话（内含反重放窗口状态）。 */
  recvSession: WgRecvSession;
  /** 装订时刻（调用方注入，毫秒）。 */
  establishedMs: number;
}

/** peer 静态公钥登记条目（模块私有）。 */
interface WgPeerRecord {
  staticPublic: Uint8Array;
}

export class WgPeerTable {
  private peers: Map<string, WgPeerRecord> = new Map();
  private byPeerId: Map<string, WgSessionEntry> = new Map();
  private byLocalIndex: Map<number, WgSessionEntry> = new Map();

  /** 登记对端静态公钥（32B；深拷贝）。重复登记覆写；非法长度抛 Error。 */
  public registerPeer(peerId: string, staticPublic: Uint8Array): void {
    if (staticPublic.length !== KEY_LEN_BYTES) {
      throw new Error(
        'WgPeerTable.registerPeer: static public must be ' +
          String(KEY_LEN_BYTES) +
          ' bytes, got ' +
          String(staticPublic.length),
      );
    }
    const record: WgPeerRecord = { staticPublic: staticPublic.slice() };
    this.peers.set(peerId, record);
  }

  /** 是否已登记对端。 */
  public hasPeer(peerId: string): boolean {
    return this.peers.has(peerId);
  }

  /** 对端静态公钥拷贝；未登记返回 null。 */
  public staticPublicOf(peerId: string): Uint8Array | null {
    const record: WgPeerRecord | undefined = this.peers.get(peerId);
    if (record === undefined) {
      return null;
    }
    return record.staticPublic.slice();
  }

  /** 已登记对端数。 */
  public peerCount(): number {
    return this.peers.size;
  }

  /** 已登记对端 id 列表（Map 插入序，新数组）。 */
  public peerIds(): string[] {
    const ids: string[] = [];
    this.peers.forEach((record: WgPeerRecord, peerId: string): void => {
      ids.push(peerId);
    });
    return ids;
  }

  /**
   * 移除对端及其全部会话条目；返回是否确有该对端。
   */
  public removePeer(peerId: string): boolean {
    const existed: boolean = this.peers.delete(peerId);
    const entry: WgSessionEntry | undefined = this.byPeerId.get(peerId);
    if (entry !== undefined) {
      this.byPeerId.delete(peerId);
      const mapped: WgSessionEntry | undefined = this.byLocalIndex.get(entry.localIndex);
      if (mapped !== undefined && mapped.peerId === peerId) {
        this.byLocalIndex.delete(entry.localIndex);
      }
    }
    return existed;
  }

  /**
   * 用握手产出装订会话（新建收发会话实例并登记 localIndex 映射）。
   * 未登记的 peerId 抛 Error。重钥替换语义：该对端的旧会话条目整体让位
   * （旧 localIndex 路由一并移除）；同 localIndex 被其他对端占用时同样让位。
   * 返回新建条目。
   */
  public installSession(peerId: string, output: WgHandshakeOutput, establishedMs: number): WgSessionEntry {
    if (!this.peers.has(peerId)) {
      throw new Error('WgPeerTable.installSession: unknown peer ' + peerId);
    }
    const previousForPeer: WgSessionEntry | undefined = this.byPeerId.get(peerId);
    if (previousForPeer !== undefined) {
      const mapped: WgSessionEntry | undefined = this.byLocalIndex.get(previousForPeer.localIndex);
      if (mapped !== undefined && mapped.peerId === peerId) {
        this.byLocalIndex.delete(previousForPeer.localIndex);
      }
    }
    const previous: WgSessionEntry | undefined = this.byLocalIndex.get(output.localIndex);
    if (previous !== undefined && previous.peerId !== peerId) {
      this.byPeerId.delete(previous.peerId);
    }
    const localIndex: number = output.localIndex;
    const peerIndex: number = output.peerIndex;
    const entry: WgSessionEntry = {
      peerId: peerId,
      localIndex: localIndex,
      peerIndex: peerIndex,
      // 发送会话携带"对端分配的索引"（写入 receiver index 字段）；
      // 接收会话以本端 localIndex 校验入包 —— 两者经索引表互为镜像。
      sendSession: new WgSendSession(peerIndex, output.sendKey),
      recvSession: new WgRecvSession(localIndex, output.recvKey),
      establishedMs: establishedMs,
    };
    this.byPeerId.set(peerId, entry);
    this.byLocalIndex.set(output.localIndex, entry);
    return entry;
  }

  /** 按本端索引查会话（UDP 分发主路径）；无则 null。返回的是表内活跃条目（非拷贝）。 */
  public entryByLocalIndex(localIndex: number): WgSessionEntry | null {
    const entry: WgSessionEntry | undefined = this.byLocalIndex.get(localIndex);
    if (entry === undefined) {
      return null;
    }
    return entry;
  }

  /** 按对端 id 查当前会话；无则 null。返回表内活跃条目（非拷贝）。 */
  public entryByPeerId(peerId: string): WgSessionEntry | null {
    const entry: WgSessionEntry | undefined = this.byPeerId.get(peerId);
    if (entry === undefined) {
      return null;
    }
    return entry;
  }

  /** 移除单个会话条目（按本端索引）；返回是否确有。 */
  public removeSession(localIndex: number): boolean {
    const entry: WgSessionEntry | undefined = this.byLocalIndex.get(localIndex);
    if (entry === undefined) {
      return false;
    }
    this.byLocalIndex.delete(localIndex);
    const current: WgSessionEntry | undefined = this.byPeerId.get(entry.peerId);
    if (current !== undefined && current.localIndex === localIndex) {
      this.byPeerId.delete(entry.peerId);
    }
    return true;
  }

  /** 活跃会话条目数。 */
  public sessionCount(): number {
    return this.byLocalIndex.size;
  }
}

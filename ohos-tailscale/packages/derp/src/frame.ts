/**
 * DERP 帧层（架构契约 §8.1，AU2 对齐）：
 *
 *   帧 = type u8 || length u32(BE) || payload
 *
 * ✅ 上游核对（AU2，2026-09-29 实读 tailscale main derp/derp.go 与 derp_client.go）：
 * - 帧头第二字段为 **大端 uint32**（不含 5 字节头本身）——原本地契约的 uvarint 编码
 *   为 AU2 核对前的过渡形态，本次按上游改为 u32BE（架构 §10.3 v1.2 修订记录）；
 * - 帧类型码表与上游 derp.go FrameType 常量逐一对照（含方向与载荷布局注释）；
 * - Magic = "DERP🔑"（8B），出现在服务器 ServerKey 帧载荷开头；
 * - 单帧长度上限沿用 1MB（上游 readFrame maxSize 同量级，DoS 防护基线）；
 * - 未知帧类型在解码层透传（前向兼容），在编码层与客户端分发层拒绝；
 * - 声明长度超限抛 DerpError('RANGE')，结构损坏（截断/长度不足）抛 DerpError('FRAME')；
 * - 拷贝语义（R8）：derpFrameEncode 返回独立拷贝；derpFrameDecode 与
 *   DerpFrameReader.push 返回的 payload 均为独立拷贝（slice），不与输入共享视图。
 */

import { ByteWriter } from '@ohos-tailscale/common';

/** 单帧 payload 字节数上限（DoS 防护基线）。 */
export const DERP_MAX_FRAME_BYTES: number = 1048576;

/** 服务器 ServerKey 帧载荷开头的协议魔数（derp.go Magic："DERP🔑"，8B）。 */
export const DERP_MAGIC: Uint8Array = Uint8Array.from([0x44, 0x45, 0x52, 0x50, 0xf0, 0x9f, 0x94, 0x91]);

export interface DerpFrameTypeE {
  ServerKey: number; // 0x01 服务器→客户端：Magic(8B) || 服务器公钥(32B)
  ClientInfo: number; // 0x02 客户端→服务器：本端公钥(32B) || nonce(24B) || naclbox(json)
  ServerInfo: number; // 0x03 服务器→客户端：nonce(24B) || naclbox(json)（客户端可跳过）
  SendPacket: number; // 0x04 客户端→服务器：dstKey(32B) || 数据包
  RecvPacket: number; // 0x05 服务器→客户端：srcKey(32B) || 数据包（协议 v2）
  KeepAlive: number; // 0x06 双向：空载荷保活
  NotePreferred: number; // 0x07 客户端→服务器：单字节 0/1（home DERP 偏好上报）
  PeerGone: number; // 0x08 服务器→客户端：peer 公钥(32B) || 原因(1B)
  PeerPresent: number; // 0x09 服务器→客户端：mesh 成员通知（客户端可跳过）
  ForwardPacket: number; // 0x0a 服务器↔服务器：srcKey(32B) || dstKey(32B) || 数据包
  WatchConns: number; // 0x10 mesh 订阅（需 mesh 权限）
  ClosePeer: number; // 0x11 关闭指定 peer（需 mesh 权限）
  Ping: number; // 0x12 双向：8B 探测数据（对端回 Pong）
  Pong: number; // 0x13 双向：Ping 数据原样回显
  Health: number; // 0x14 服务器→客户端：健康状态文本（客户端可跳过）
  Restarting: number; // 0x15 服务器→客户端：即将重启提示（客户端可跳过）
}

export const DerpFrameType: DerpFrameTypeE = {
  ServerKey: 0x01,
  ClientInfo: 0x02,
  ServerInfo: 0x03,
  SendPacket: 0x04,
  RecvPacket: 0x05,
  KeepAlive: 0x06,
  NotePreferred: 0x07,
  PeerGone: 0x08,
  PeerPresent: 0x09,
  ForwardPacket: 0x0a,
  WatchConns: 0x10,
  ClosePeer: 0x11,
  Ping: 0x12,
  Pong: 0x13,
  Health: 0x14,
  Restarting: 0x15,
};

/** 帧类型运行时校验（R5 常量对象模式配套）；不在表内返回 null。 */
export function parseDerpFrameType(v: number): number | null {
  const values: number[] = [
    DerpFrameType.ServerKey,
    DerpFrameType.ClientInfo,
    DerpFrameType.ServerInfo,
    DerpFrameType.SendPacket,
    DerpFrameType.RecvPacket,
    DerpFrameType.KeepAlive,
    DerpFrameType.NotePreferred,
    DerpFrameType.PeerGone,
    DerpFrameType.PeerPresent,
    DerpFrameType.ForwardPacket,
    DerpFrameType.WatchConns,
    DerpFrameType.ClosePeer,
    DerpFrameType.Ping,
    DerpFrameType.Pong,
    DerpFrameType.Health,
    DerpFrameType.Restarting,
  ];
  for (const t of values) {
    if (t === v) {
      return v;
    }
  }
  return null;
}

/** derp 包错误（R7）：code 集合严格为 'FRAME'（结构损坏）、'RANGE'（数值越界）、'STATE'（状态机非法迁移/拨号失败，v1.1 裁定增补）。 */
export class DerpError extends Error {
  public code: string;

  constructor(code: string, message: string) {
    super(message);
    this.code = code;
  }
}

/** 单帧解码结果。 */
export interface DerpFrame {
  type: number;
  payload: Uint8Array;
}

/** 帧头长度：type u8 + length u32BE。 */
const FRAME_HEADER_LEN: number = 5;

/**
 * 编码单帧：type u8 || u32BE(payload.length) || payload。
 * type 不在码表内抛 DerpError('RANGE')；payload 超上限抛 DerpError('RANGE')。
 * 返回独立拷贝。
 */
export function derpFrameEncode(type: number, payload: Uint8Array): Uint8Array {
  if (parseDerpFrameType(type) === null) {
    throw new DerpError('RANGE', 'unknown derp frame type: ' + String(type));
  }
  if (payload.length > DERP_MAX_FRAME_BYTES) {
    throw new DerpError('RANGE', 'derp frame payload too large: ' + String(payload.length));
  }
  const w: ByteWriter = new ByteWriter(FRAME_HEADER_LEN + payload.length);
  w.writeU8(type);
  w.writeU32be(payload.length);
  w.writeBytes(payload);
  return w.toUint8Array();
}

/**
 * 解码单帧（输入必须是恰好一帧）：
 * - 截断（头部/payload 不全）、尾部多余字节 → DerpError('FRAME')；
 * - 声明长度 > DERP_MAX_FRAME_BYTES → DerpError('RANGE')；
 * - type 不在码表内仍解出（透传，前向兼容）。
 * payload 为独立拷贝。
 */
export function derpFrameDecode(src: Uint8Array): DerpFrame {
  if (src.length < FRAME_HEADER_LEN) {
    throw new DerpError('FRAME', 'derp frame input shorter than header: ' + String(src.length));
  }
  const type: number = src[0];
  const declared: number = ((src[1] << 24) | (src[2] << 16) | (src[3] << 8) | src[4]) >>> 0;
  if (declared > DERP_MAX_FRAME_BYTES) {
    throw new DerpError('RANGE', 'derp frame length exceeds limit: ' + String(declared));
  }
  const total: number = FRAME_HEADER_LEN + declared;
  if (src.length < total) {
    throw new DerpError(
      'FRAME',
      'derp frame payload truncated (declared ' + String(declared) +
        ', have ' + String(src.length - FRAME_HEADER_LEN) + ')',
    );
  }
  if (src.length > total) {
    throw new DerpError('FRAME', 'unexpected trailing bytes after derp frame');
  }
  const frame: DerpFrame = { type: type, payload: src.slice(FRAME_HEADER_LEN, total) };
  return frame;
}

/**
 * 跨 chunk 帧重组器：任意切分的字节流 → 完整帧序列。
 * push 返回"本轮新解出的完整帧"（0..n 个），半帧数据内部缓存；
 * 声明长度超限在 push 时立即抛错（不等 payload 到齐）。
 */
export class DerpFrameReader {
  private buf: Uint8Array = new Uint8Array(0);
  private pos: number = 0;

  /**
   * 输入新到达的字节 chunk，返回本轮解出的完整帧（payload 均为独立拷贝）。
   */
  public push(chunk: Uint8Array): DerpFrame[] {
    const pendingLen: number = this.buf.length - this.pos;
    const merged: Uint8Array = new Uint8Array(pendingLen + chunk.length);
    if (pendingLen > 0) {
      merged.set(this.buf.subarray(this.pos, this.buf.length), 0);
    }
    if (chunk.length > 0) {
      merged.set(chunk, pendingLen);
    }
    this.buf = merged;
    this.pos = 0;

    const out: DerpFrame[] = [];
    for (;;) {
      if (this.buf.length - this.pos < FRAME_HEADER_LEN) {
        break; // 头部未到齐
      }
      const declared: number =
        ((this.buf[this.pos + 1] << 24) | (this.buf[this.pos + 2] << 16) | (this.buf[this.pos + 3] << 8) | this.buf[this.pos + 4]) >>> 0;
      if (declared > DERP_MAX_FRAME_BYTES) {
        throw new DerpError('RANGE', 'derp frame length exceeds limit: ' + String(declared));
      }
      const payloadEnd: number = this.pos + FRAME_HEADER_LEN + declared;
      if (this.buf.length < payloadEnd) {
        break; // payload 未到齐
      }
      const frame: DerpFrame = {
        type: this.buf[this.pos],
        payload: this.buf.slice(this.pos + FRAME_HEADER_LEN, payloadEnd),
      };
      out.push(frame);
      this.pos = payloadEnd;
    }
    if (this.pos > 0) {
      this.buf = this.buf.slice(this.pos);
      this.pos = 0;
    }
    return out;
  }

  /** 当前缓存的半帧字节数。 */
  public pendingBytes(): number {
    return this.buf.length - this.pos;
  }
}

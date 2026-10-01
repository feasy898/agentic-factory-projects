/**
 * 通道帧编解码（架构契约 §6 frame.ts）：2B 大端长度前缀 + noise 消息。
 *
 * ✅ 上游核对注（architecture.md §10-U1，2026-09-28 实读 tailscale
 * control/controlbase/conn.go）：真实 controlbase 记录帧 = `type u8(=1 record) ||
 * length u16be || ciphertext`，length = 明文 + 16B tag；上游另有 maxMessageSize=4096
 * 的总帧上限与 msgType 字节，属控制面会话层（control 包）的组帧职责，本包按本地
 * 契约只做 2B BE 前缀 + 载荷（≤ 65535B，u16 值域内）——常量集中本文件，若 control
 * 包需要完整的 controlbase 记录头，只需在此加类型字节常量，不改函数形态。
 */

import { NoiseError } from './errors.ts';

/** 长度前缀字节数（u16be）。 */
const FRAME_HEADER_LEN: number = 2;
/** 单帧载荷上限（u16 表示域）。 */
const FRAME_MAX_BODY_LEN: number = 65535;

/** 单帧解码结果。payload 为独立拷贝（R8）。 */
export interface NoiseFrame {
  payload: Uint8Array;
}

/** 编码一帧：2B BE 长度前缀 + msg。msg 超过 65535B 抛 NoiseError('FRAME')。返回新数组。 */
export function noiseFrameEncode(msg: Uint8Array): Uint8Array {
  if (msg.length > FRAME_MAX_BODY_LEN) {
    throw new NoiseError('FRAME', 'noise frame: body too large: ' + String(msg.length) + ' > ' + String(FRAME_MAX_BODY_LEN)) as Error;
  }
  const out: Uint8Array = new Uint8Array(FRAME_HEADER_LEN + msg.length);
  out[0] = (msg.length >> 8) & 0xff;
  out[1] = msg.length & 0xff;
  out.set(msg, FRAME_HEADER_LEN);
  return out;
}

/**
 * 解码首帧：读 2B BE 长度前缀并取出对应载荷（独立拷贝）。
 * 头/体截断抛 NoiseError('FRAME')；载荷之后的尾随字节不属于本帧，忽略
 * （流式多帧重组请用 NoiseFrameReader）。
 */
export function noiseFrameDecode(src: Uint8Array): NoiseFrame {
  if (src.length < FRAME_HEADER_LEN) {
    throw new NoiseError('FRAME', 'noise frame: truncated header: ' + String(src.length)) as Error;
  }
  const len: number = ((src[0] << 8) | src[1]) & 0xffff;
  if (src.length < FRAME_HEADER_LEN + len) {
    throw new NoiseError('FRAME', 'noise frame: truncated body: have ' + String(src.length - FRAME_HEADER_LEN) + ', need ' + String(len)) as Error;
  }
  const frame: NoiseFrame = { payload: src.slice(FRAME_HEADER_LEN, FRAME_HEADER_LEN + len) };
  return frame;
}

/**
 * 跨 chunk 帧重组器：push 喂入新到字节，返回本轮解出的完整帧（0..n 个）；
 * 半帧字节缓存到下次。帧载荷为独立拷贝（R8）。
 */
export class NoiseFrameReader {
  private buf: Uint8Array = new Uint8Array(0);

  public push(chunk: Uint8Array): NoiseFrame[] {
    const merged: Uint8Array = new Uint8Array(this.buf.length + chunk.length);
    merged.set(this.buf, 0);
    merged.set(chunk, this.buf.length);
    this.buf = merged;

    const frames: NoiseFrame[] = [];
    let consumed: number = 0;
    while (this.buf.length - consumed >= FRAME_HEADER_LEN) {
      const len: number = ((this.buf[consumed] << 8) | this.buf[consumed + 1]) & 0xffff;
      if (this.buf.length - consumed < FRAME_HEADER_LEN + len) {
        break;
      }
      const frame: NoiseFrame = { payload: this.buf.slice(consumed + FRAME_HEADER_LEN, consumed + FRAME_HEADER_LEN + len) };
      frames.push(frame);
      consumed += FRAME_HEADER_LEN + len;
    }
    if (consumed > 0) {
      this.buf = this.buf.slice(consumed);
    }
    return frames;
  }

  /** 缓存中的半帧字节数（完整帧总是即刻返回，故缓存里只会有不完整帧）。 */
  public pendingBytes(): number {
    return this.buf.length;
  }
}

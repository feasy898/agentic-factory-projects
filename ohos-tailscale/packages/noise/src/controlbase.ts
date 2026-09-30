/**
 * ts2021/controlbase 帧封装层（架构契约 §6 controlbase.ts）——把本包 Noise IK 会话
 * 适配到真实 tailscale/Headscale 控制面的线格式。
 *
 * ✅ 上游核对（AU1，2026-09-29 实读 tailscale main：
 *    control/controlbase/{messages.go,handshake.go,conn.go}、control/controlhttp/{constants.go,client.go}）：
 * - 协议名 'Noise_IK_25519_ChaChaPoly_BLAKE2s'、prologue = "Tailscale Control Protocol v" + 版本号
 *   （握手前混入，随后混入响应方静态公钥 `<- s`）——与本包 SymmetricState/NoiseIkInitiator 逐项一致；
 * - initiation 帧 101B：2B BE 协议版本 + 1B 类型(0x01) + 2B BE 载荷长度(96) + 32B 临时公钥 +
 *   48B enc(静态公钥) + 16B tag（messages.go initiationMessage）；
 * - response 帧 51B：1B 类型(0x02) + 2B BE 长度(48) + 32B 临时公钥 + 16B tag；
 * - error 帧：1B 类型(0x03) + 2B BE 长度 + 未认证 UTF-8 文本（服务器握手拒绝）；
 * - record 帧：1B 类型(0x04) + 2B BE 密文长度 + 密文；帧总长上限 4096 → 明文上限 4077
 *   （conn.go maxMessageSize/maxPlaintextSize）；
 * - 传输 nonce 为 4B 零 || BE64 计数器（conn.go nonce.Increment），与 transport.ts 一致；
 * - 客户端 tx 用 Split 的 k1、rx 用 k2（conn.go 与 handshake.go 的 c1/c2 绑定）；
 * - 零长度 record 合法（conn.go Read 循环跳过）；Write(空) 不发送任何字节；
 * - 解密失败即会话报废（conn.go decryptLocked 将 cipher 置 nil）；
 * - HTTP 层：POST /ts2021，头 Upgrade: tailscale-control-protocol、Connection: upgrade、
 *   X-Tailscale-Handshake: base64(完整 101B initiation)（controlhttp 常量与 tryURLUpgrade），
 *   101 Switching Protocols 之后裸连接即 controlbase 字节流。
 *
 * 平台无关：网络经 ControlBaseDuplex 注入（send/receive/close），核心 src 不依赖任何 Node API。
 */

import { KEY_LEN_BYTES, ByteWriter, utf8Encode, type Rng } from '@ohos-tailscale/common';
import { NoiseError } from './errors.ts';
import { NoiseIkInitiator, type NoiseTransportPair } from './handshake.ts';
import { NoiseTransportCipher } from './transport.ts';

/**
 * 控制面协议版本（initiation 头 2B BE 字段 + prologue 后缀）。
 * ✅ 上游核对（2026-09-29）：现代 tailscale 客户端在此字段填的是 tailcfg
 * CurrentCapabilityVersion（当前 148），不是早期的 noise 协议版本 1——headscale
 * v0.29.4 的 ns.earlyNoise 直接把它当 CapabilityVersion 做最低门禁
 * （MinSupportedCapabilityVersion=113），发 1 会被拒（"unsupported client version"）。
 */
export const CONTROLBASE_PROTOCOL_VERSION: number = 148;

/** prologue 前缀（controlbase protocolVersionPrefix），实际 prologue = 前缀 + 十进制版本号。 */
export const CONTROLBASE_PROLOGUE_PREFIX: string = 'Tailscale Control Protocol v';

/** 帧总长上限（含 3B 头；conn.go maxMessageSize）。 */
export const CONTROLBASE_MAX_FRAME_BYTES: number = 4096;

/** 单帧明文上限 = 4096 − 3B 头 − 16B tag（conn.go maxPlaintextSize）。 */
export const CONTROLBASE_MAX_PLAINTEXT_BYTES: number = CONTROLBASE_MAX_FRAME_BYTES - 3 - 16;

const MSG_TYPE_INIT: number = 1;
const MSG_TYPE_RESPONSE: number = 2;
const MSG_TYPE_ERROR: number = 3;
const MSG_TYPE_RECORD: number = 4;
const HEADER_LEN: number = 3;
const INIT_HEADER_LEN: number = 5;
const TAG_LEN: number = 16;
const RESPONSE_PAYLOAD_LEN: number = KEY_LEN_BYTES + TAG_LEN; // 48B

/** 与真实控制面通信的全双工字节流（平台注入点；实现必须用 class implements）。 */
export interface ControlBaseDuplex {
  /** 发送原始字节（整体写入语义）。 */
  send(data: Uint8Array): Promise<void>;
  /** 阻塞读取下一段到达的字节（长度不定，至少 1B；连接结束则 reject）。 */
  receive(): Promise<Uint8Array>;
  /** 关闭底层连接（可重复调用）。 */
  close(): Promise<void>;
}

/** initiation 构建结果：101B 帧 + 未完成的握手状态机（HTTP 头内嵌场景分两步用）。 */
export interface ControlBaseInitiation {
  /** 完整 101B initiation 帧（含 5B 头；即 HTTP 头里 base64 的内容）。 */
  frame: Uint8Array;
  /** 内部握手状态机：收齐 51B response 帧后传给 completeControlbaseHandshake。 */
  initiator: NoiseIkInitiator;
  /** 本次握手的 prologue（含版本号）。 */
  prologue: Uint8Array;
}

/** 构建 initiation 帧（controlbase ClientDeferred 前半）。 */
export function controlbaseBuildInitiation(
  machinePrivate: Uint8Array,
  controlStatic: Uint8Array,
  rng: Rng,
  version: number = CONTROLBASE_PROTOCOL_VERSION,
): ControlBaseInitiation {
  if (machinePrivate.length !== KEY_LEN_BYTES) {
    throw new NoiseError('STATE', 'controlbase: machinePrivate must be 32B') as Error;
  }
  if (controlStatic.length !== KEY_LEN_BYTES) {
    throw new NoiseError('STATE', 'controlbase: controlStatic must be 32B') as Error;
  }
  if (version < 0 || version > 0xffff) {
    throw new NoiseError('STATE', 'controlbase: protocol version out of u16 range: ' + String(version)) as Error;
  }
  const prologue: Uint8Array = utf8Encode(CONTROLBASE_PROLOGUE_PREFIX + String(version));
  const initiator: NoiseIkInitiator = new NoiseIkInitiator(prologue, machinePrivate, controlStatic, rng);
  const payload: Uint8Array = initiator.writeMessageA(new Uint8Array(0)); // 96B
  const head: ByteWriter = new ByteWriter(INIT_HEADER_LEN);
  head.writeU16be(version);
  head.writeU8(MSG_TYPE_INIT);
  head.writeU16be(payload.length);
  const frame: Uint8Array = new Uint8Array(INIT_HEADER_LEN + payload.length);
  frame.set(head.toUint8Array(), 0);
  frame.set(payload, INIT_HEADER_LEN);
  const result: ControlBaseInitiation = { frame: frame, initiator: initiator, prologue: prologue };
  return result;
}

/** 3B 头读取结果。 */
interface FrameHead {
  type: number;
  length: number;
}

/** 从缓冲区 offset 处解析 3B 帧头。 */
function parseFrameHead(buf: Uint8Array, offset: number): FrameHead {
  const head: FrameHead = { type: buf[offset], length: (buf[offset + 1] << 8) | buf[offset + 2] };
  return head;
}

/**
 * 完成 handshake 后半：解析 51B response 帧（或 error 帧）并派生会话
 * （controlbase continueClientHandshake）。
 */
export function controlbaseCompleteHandshake(
  initiation: ControlBaseInitiation,
  responseFrame: Uint8Array,
): ControlBaseSession {
  if (responseFrame.length < HEADER_LEN) {
    throw new NoiseError('PROLOGUE', 'controlbase: response shorter than header: ' + String(responseFrame.length)) as Error;
  }
  const head: FrameHead = parseFrameHead(responseFrame, 0);
  if (head.type === MSG_TYPE_ERROR) {
    const text: Uint8Array = responseFrame.slice(HEADER_LEN);
    throw new NoiseError('STATE', 'controlbase: server refused handshake: ' + utf8DecodeSafe(text)) as Error;
  }
  if (head.type !== MSG_TYPE_RESPONSE) {
    throw new NoiseError('PROLOGUE', 'controlbase: unexpected response message type ' + String(head.type)) as Error;
  }
  if (head.length !== RESPONSE_PAYLOAD_LEN || responseFrame.length !== HEADER_LEN + RESPONSE_PAYLOAD_LEN) {
    throw new NoiseError(
      'PROLOGUE',
      'controlbase: wrong response frame: header length=' + String(head.length) +
        ' frame bytes=' + String(responseFrame.length) +
        ' (want header ' + String(RESPONSE_PAYLOAD_LEN) + ' + frame ' + String(HEADER_LEN + RESPONSE_PAYLOAD_LEN) + ')',
    ) as Error;
  }
  initiation.initiator.readMessageB(responseFrame.slice(HEADER_LEN));
  const pair: NoiseTransportPair = initiation.initiator.split();
  return new ControlBaseSession(pair.send, pair.recv);
}

/** 容错 UTF-8 解码（仅用于 error 帧文本；非法字节替换为 U+FFFD）。 */
function utf8DecodeSafe(b: Uint8Array): string {
  let out: string = '';
  let i: number = 0;
  while (i < b.length) {
    const c: number = b[i];
    if (c < 0x80) {
      out += String.fromCharCode(c);
      i += 1;
    } else if (c >= 0xc0 && c < 0xe0 && i + 1 < b.length) {
      out += String.fromCharCode(((c & 0x1f) << 6) | (b[i + 1] & 0x3f));
      i += 2;
    } else if (c >= 0xe0 && c < 0xf0 && i + 2 < b.length) {
      out += String.fromCharCode(((c & 0x0f) << 12) | ((b[i + 1] & 0x3f) << 6) | (b[i + 2] & 0x3f));
      i += 3;
    } else {
      out += '\uFFFD';
      i += 1;
    }
  }
  return out;
}

/**
 * controlbase 会话：record 帧读写（对齐 conn.go 的 Read/Write 语义）。
 * write() 对超长明文自动分帧；write(空) 不发送；read() 跳过零长度帧直到有明文；
 * 任一方向解密失败抛 NoiseError('DECRYPT')，此后会话不再可用（对齐 cipher 置 nil）。
 * 接收缓冲为动态拼接——真实 socket 的 TCP 分段可能一次到达 >4096B 的多帧合并块，
 * 不能假设 receive() 返回小分片（互操作实测踩中：MapResponse 增大后固定缓冲必溢出）。
 */
export class ControlBaseSession {
  private readonly sendCipher: NoiseTransportCipher;
  private readonly recvCipher: NoiseTransportCipher;
  private recvBuf: Uint8Array = new Uint8Array(0);
  private broken: boolean = false;
  private closed: boolean = false;

  /** @internal 由 controlbaseCompleteHandshake 构造。 */
  public constructor(sendCipher: NoiseTransportCipher, recvCipher: NoiseTransportCipher) {
    this.sendCipher = sendCipher;
    this.recvCipher = recvCipher;
  }

  /** 发送明文；>4077B 自动分帧；零长度不发送任何字节。失败抛 NoiseError('STATE')。 */
  public async write(duplex: ControlBaseDuplex, plaintext: Uint8Array): Promise<void> {
    this.assertUsable();
    let offset: number = 0;
    while (offset < plaintext.length) {
      const take: number = Math.min(CONTROLBASE_MAX_PLAINTEXT_BYTES, plaintext.length - offset);
      const chunk: Uint8Array = plaintext.slice(offset, offset + take);
      offset += take;
      const ciphertext: Uint8Array = this.sendCipher.encrypt(chunk);
      const frame: Uint8Array = new Uint8Array(HEADER_LEN + ciphertext.length);
      frame[0] = MSG_TYPE_RECORD;
      frame[1] = (ciphertext.length >> 8) & 0xff;
      frame[2] = ciphertext.length & 0xff;
      frame.set(ciphertext, HEADER_LEN);
      await duplex.send(frame);
    }
  }

  /**
   * 读取下一段明文（单条 record 的解密结果；跳过零长度帧）。
   * 连接由对端关闭时抛 NoiseError('STATE')；解密失败抛 NoiseError('DECRYPT') 并报废会话。
   */
  public async read(duplex: ControlBaseDuplex): Promise<Uint8Array> {
    this.assertUsable();
    for (;;) {
      if (this.recvBuf.length >= HEADER_LEN) {
        const head: FrameHead = parseFrameHead(this.recvBuf, 0);
        if (head.type !== MSG_TYPE_RECORD) {
          this.broken = true;
          throw new NoiseError('PROLOGUE', 'controlbase: unexpected record message type ' + String(head.type)) as Error;
        }
        if (head.length > CONTROLBASE_MAX_FRAME_BYTES - HEADER_LEN) {
          this.broken = true;
          throw new NoiseError('FRAME', 'controlbase: record frame too large: ' + String(head.length)) as Error;
        }
        if (this.recvBuf.length >= HEADER_LEN + head.length) {
          let plaintext: Uint8Array;
          try {
            plaintext = this.recvCipher.decrypt(this.recvBuf.slice(HEADER_LEN, HEADER_LEN + head.length));
          } catch (e) {
            this.broken = true;
            throw e as Error;
          }
          this.recvBuf = this.recvBuf.slice(HEADER_LEN + head.length);
          if (plaintext.length === 0) {
            continue; // 零长度帧：keepalive，读下一条
          }
          return plaintext;
        }
      }
      const chunk: Uint8Array = await duplex.receive();
      if (chunk.length === 0) {
        this.broken = true;
        throw new NoiseError('STATE', 'controlbase: connection closed by peer') as Error;
      }
      this.recvBuf = concatBuffers(this.recvBuf, chunk);
    }
  }

  /** 本端主动关闭（不发任何 BYE——协议本身没有；直接关底层连接）。 */
  public async close(duplex: ControlBaseDuplex): Promise<void> {
    if (this.closed) {
      return;
    }
    this.closed = true;
    this.broken = true;
    await duplex.close();
  }

  private assertUsable(): void {
    if (this.closed) {
      throw new NoiseError('STATE', 'controlbase: session closed') as Error;
    }
    if (this.broken) {
      throw new NoiseError('STATE', 'controlbase: session broken by earlier error') as Error;
    }
  }
}

function concatBuffers(a: Uint8Array, b: Uint8Array): Uint8Array {
  const out: Uint8Array = new Uint8Array(a.length + b.length);
  out.set(a, 0);
  out.set(b, a.length);
  return out;
}

/**
 * 一步式客户端握手（已有裸字节流时使用；HTTP 头内嵌场景请用 build/complete 两步式）。
 * 读取 response 时容忍服务器把 51B 分片送达。
 */
export async function controlbaseClientHandshake(
  duplex: ControlBaseDuplex,
  machinePrivate: Uint8Array,
  controlStatic: Uint8Array,
  rng: Rng,
  version: number = CONTROLBASE_PROTOCOL_VERSION,
): Promise<ControlBaseSession> {
  const init: ControlBaseInitiation = controlbaseBuildInitiation(machinePrivate, controlStatic, rng, version);
  await duplex.send(init.frame);
  let acc: Uint8Array = new Uint8Array(0);
  for (;;) {
    if (acc.length >= HEADER_LEN) {
      const head: FrameHead = parseFrameHead(acc, 0);
      if (head.type === MSG_TYPE_ERROR) {
        if (acc.length >= HEADER_LEN + head.length) {
          throw new NoiseError('STATE', 'controlbase: server refused handshake: ' + utf8DecodeSafe(acc.slice(HEADER_LEN, HEADER_LEN + head.length))) as Error;
        }
      } else if (acc.length >= HEADER_LEN + head.length) {
        return controlbaseCompleteHandshake(init, acc.slice(0, HEADER_LEN + head.length));
      }
    }
    const chunk: Uint8Array = await duplex.receive();
    if (chunk.length === 0) {
      throw new NoiseError('STATE', 'controlbase: connection closed during handshake') as Error;
    }
    const merged: Uint8Array = new Uint8Array(acc.length + chunk.length);
    merged.set(acc, 0);
    merged.set(chunk, acc.length);
    acc = merged;
  }
}

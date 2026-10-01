/**
 * 极简 HTTP/2（h2c）客户端 —— ts2021 Noise 连接上的控制面应用层。
 *
 * ✅ 上游核对（2026-09-29）：headscale v0.29.4 在 controlbase 升级后直接
 * http2.Server.ServeConn(noiseConn)（hscontrol/noise.go）——Noise 之上是纯 HTTP/2，
 * 无 HTTP/1.1 回退；握手完成后服务器会先发 EarlyNoise 载荷（5B magic + 4B BE 长度 +
 * JSON{NodeKeyChallenge}，见 hscontrol/noise.go earlyNoise）。
 *
 * 本模块只实现注册/地图所需的最小子集（仅限 Node 侧联调脚本使用）：
 * - 连接前奏 + SETTINGS；对服务器 SETTINGS 回 ACK；
 * - HPACK 用"字面量、不索引、不 Huffman"编码请求头（Go hpack 解码器标准支持）；
 * - 响应不解析 HEADERS（按帧长度跳过），只收 stream N 的 DATA 帧直到 END_STREAM；
 * - 忽略 WINDOW_UPDATE/PING/GOAWAY 之外的杂项帧（收到 GOAWAY 抛错）。
 */

import type { ControlBaseSession, ControlBaseDuplex } from '../packages/noise/src/controlbase.ts';

const H2_PREFACE: string = 'PRI * HTTP/2.0\r\n\r\nSM\r\n\r\n';

const FRAME_DATA: number = 0x0;
const FRAME_HEADERS: number = 0x1;
const FRAME_SETTINGS: number = 0x4;
const FRAME_PING: number = 0x6;
const FRAME_GOAWAY: number = 0x7;
const FLAG_END_STREAM: number = 0x1;
const FLAG_ACK: number = 0x1;
const FLAG_END_HEADERS: number = 0x4;

export class H2OverNoise {
  private nextStream: number = 1;
  private connected: boolean = false;
  /** 服务器在 HEADERS 前尚未消费的 DATA 尾巴（跨帧缓存）。 */
  private leftover: Uint8Array = new Uint8Array(0);
  private readonly session: ControlBaseSession;
  private readonly duplex: ControlBaseDuplex;

  public constructor(session: ControlBaseSession, duplex: ControlBaseDuplex) {
    this.session = session;
    this.duplex = duplex;
  }

  private async writeFrame(type: number, flags: number, streamId: number, payload: Uint8Array): Promise<void> {
    const head: Uint8Array = new Uint8Array(9);
    head[0] = (payload.length >> 16) & 0xff;
    head[1] = (payload.length >> 8) & 0xff;
    head[2] = payload.length & 0xff;
    head[3] = type;
    head[4] = flags;
    head[5] = (streamId >>> 24) & 0x7f;
    head[6] = (streamId >>> 16) & 0xff;
    head[7] = (streamId >>> 8) & 0xff;
    head[8] = streamId & 0xff;
    await this.session.write(this.duplex, concat(head, payload));
  }

  /** 连接前奏（每连接一次）：读掉 EarlyNoise 与服务器 SETTINGS，发 SETTINGS。 */
  public async connect(): Promise<void> {
    if (this.connected) {
      return;
    }
    // 1) EarlyNoise：5B magic + 4B BE 长度 + JSON（只跳过不消费内容）
    const earlyHead: Uint8Array = await this.readPlain(9);
    const earlyLen: number = (earlyHead[5] << 24) | (earlyHead[6] << 16) | (earlyHead[7] << 8) | earlyHead[8];
    await this.readPlain(earlyLen);
    // 2) 客户端前奏 + 空 SETTINGS
    const preface: Uint8Array = new Uint8Array(24 + 9);
    for (let i: number = 0; i < 24; i += 1) {
      preface[i] = H2_PREFACE.charCodeAt(i);
    }
    // SETTINGS 帧头：长度 0（24..26）、type=4（27）、flags=0（28）、stream 0（29..32）
    preface[27] = FRAME_SETTINGS;
    await this.session.write(this.duplex, preface);
    // 3) 读完服务器的 SETTINGS 并 ACK（跳过其它帧）
    for (;;) {
      const f: H2Frame = await this.readFrame();
      if (f.type === FRAME_SETTINGS && (f.flags & FLAG_ACK) === 0) {
        await this.writeFrame(FRAME_SETTINGS, FLAG_ACK, 0, new Uint8Array(0));
        break;
      }
    }
    this.connected = true;
  }

  /**
   * 发起一次 POST 请求并收完响应（END_STREAM）。
   * 返回响应 DATA 帧拼接的字节；HEADERS 不解析（状态码按 200 处理，错误表现为 body 非 JSON）。
   */
  public async post(authority: string, path: string, jsonBody: string): Promise<Uint8Array> {
    await this.connect();
    const streamId: number = this.nextStream;
    this.nextStream += 2;

    const headerBlock: Uint8Array = hpackLiteralHeaders([
      [':method', 'POST'],
      [':scheme', 'http'],
      [':authority', authority],
      [':path', path],
      ['content-type', 'application/json'],
      ['content-length', String(jsonBody.length)],
    ]);
    await this.writeFrame(FRAME_HEADERS, FLAG_END_HEADERS, streamId, headerBlock);
    const body: Uint8Array = new TextEncoder().encode(jsonBody);
    await this.writeFrame(FRAME_DATA, FLAG_END_STREAM, streamId, body);

    const parts: Uint8Array[] = [];
    let done: boolean = false;
    while (!done) {
      const f: H2Frame = await this.readFrame();
      if (f.type === FRAME_GOAWAY) {
        throw new Error('h2c: server sent GOAWAY: ' + ascii(f.payload));
      }
      if (f.type === FRAME_SETTINGS && (f.flags & FLAG_ACK) === 0) {
        await this.writeFrame(FRAME_SETTINGS, FLAG_ACK, 0, new Uint8Array(0));
        continue;
      }
      if (f.type === FRAME_DATA && f.streamId === streamId) {
        parts.push(f.payload);
        if ((f.flags & FLAG_END_STREAM) !== 0) {
          done = true;
        }
      }
      // HEADERS/PING/WINDOW_UPDATE 等：跳过（本用例不依赖响应头）
    }
    return concatAll(parts);
  }

  /**
   * 发起一次 POST 并只读响应流中的第一条消息（map 长轮询流专用：服务器持续推送
   * DATA 帧、永不置 END_STREAM）。
   *
   * ✅ 上游核对（2026-09-29 实测 headscale v0.29.4）：map 流的每条 MapResponse
   * 以 4B **小端**长度前缀开头（非换行分隔），前缀长度 = 紧随其后的 JSON 字节数。
   */
  public async postFirstLine(authority: string, path: string, jsonBody: string): Promise<string> {
    await this.connect();
    const streamId: number = this.nextStream;
    this.nextStream += 2;
    const headerBlock: Uint8Array = hpackLiteralHeaders([
      [':method', 'POST'],
      [':scheme', 'http'],
      [':authority', authority],
      [':path', path],
      ['content-type', 'application/json'],
      ['content-length', String(jsonBody.length)],
    ]);
    await this.writeFrame(FRAME_HEADERS, FLAG_END_HEADERS, streamId, headerBlock);
    const body: Uint8Array = new TextEncoder().encode(jsonBody);
    await this.writeFrame(FRAME_DATA, FLAG_END_STREAM, streamId, body);

    let acc: Uint8Array = new Uint8Array(0);
    for (;;) {
      const f: H2Frame = await this.readFrame();
      if (f.type === FRAME_GOAWAY) {
        throw new Error('h2c: server sent GOAWAY: ' + ascii(f.payload));
      }
      if (f.type === FRAME_SETTINGS && (f.flags & FLAG_ACK) === 0) {
        await this.writeFrame(FRAME_SETTINGS, FLAG_ACK, 0, new Uint8Array(0));
        continue;
      }
      if (f.type === FRAME_DATA && f.streamId === streamId) {
        acc = concat(acc, f.payload);
        if (acc.length >= 4) {
          const msgLen: number =
            (acc[0] | (acc[1] << 8) | (acc[2] << 16) | (acc[3] << 24)) >>> 0;
          if (acc.length >= 4 + msgLen) {
            return new TextDecoder().decode(acc.slice(4, 4 + msgLen));
          }
        }
      }
    }
  }

  private async readPlain(n: number): Promise<Uint8Array> {
    const out: Uint8Array = new Uint8Array(n);
    let total: number = 0;
    while (total < n) {
      const chunk: Uint8Array = await this.session.read(this.duplex);
      const take: number = Math.min(chunk.length, n - total);
      out.set(chunk.slice(0, take), total);
      if (chunk.length > take) {
        this.leftover = concat(this.leftover, chunk.slice(take));
      }
      total += take;
    }
    return out;
  }

  private async readFrame(): Promise<H2Frame> {
    let buf: Uint8Array = this.leftover;
    this.leftover = new Uint8Array(0);
    while (buf.length < 9) {
      buf = concat(buf, await this.session.read(this.duplex));
    }
    const len: number = (buf[0] << 16) | (buf[1] << 8) | buf[2];
    const type: number = buf[3];
    const flags: number = buf[4];
    const streamId: number = ((buf[5] << 24) | (buf[6] << 16) | (buf[7] << 8) | buf[8]) & 0x7fffffff;
    while (buf.length < 9 + len) {
      buf = concat(buf, await this.session.read(this.duplex));
    }
    const out: H2Frame = { type: type, flags: flags, streamId: streamId, payload: buf.slice(9, 9 + len) };
    this.leftover = buf.slice(9 + len);
    return out;
  }
}

interface H2Frame {
  type: number;
  flags: number;
  streamId: number;
  payload: Uint8Array;
}

/**
 * HPACK 编码：每条头用"字面量字段、不索引、新名字"（首字节 0x00），
 * 名/值用 7 位前缀长度 + 原文（Huffman 位 0）。Go 的 hpack 解码器标准支持。
 */
function hpackLiteralHeaders(pairs: Array<[string, string]>): Uint8Array {
  const parts: Uint8Array[] = [];
  for (const pair of pairs) {
    const name: Uint8Array = new TextEncoder().encode(pair[0]);
    const value: Uint8Array = new TextEncoder().encode(pair[1]);
    parts.push(new Uint8Array([0x00]));
    parts.push(hpackString(name));
    parts.push(hpackString(value));
  }
  return concatAll(parts);
}

function hpackString(b: Uint8Array): Uint8Array {
  const out: Uint8Array = new Uint8Array(1 + 4 + b.length);
  let off: number = 0;
  // 长度用 7 位前缀整数编码（<127 单字节；本项目 body 不会超，防御性支持多字节）
  let len: number = b.length;
  if (len < 0x7f) {
    out[off] = len;
    off += 1;
  } else {
    out[off] = 0x7f;
    off += 1;
    let rest: number = len - 0x7f;
    while (rest >= 0x80) {
      out[off] = (rest & 0x7f) | 0x80;
      off += 1;
      rest >>= 7;
    }
    out[off] = rest;
    off += 1;
  }
  out.set(b, off);
  return out.slice(0, off + b.length);
}

function concat(a: Uint8Array, b: Uint8Array): Uint8Array {
  const out: Uint8Array = new Uint8Array(a.length + b.length);
  out.set(a, 0);
  out.set(b, a.length);
  return out;
}

function concatAll(parts: Uint8Array[]): Uint8Array {
  let total: number = 0;
  for (const p of parts) {
    total += p.length;
  }
  const out: Uint8Array = new Uint8Array(total);
  let off: number = 0;
  for (const p of parts) {
    out.set(p, off);
    off += p.length;
  }
  return out;
}

function ascii(b: Uint8Array): string {
  let out: string = '';
  for (let i: number = 0; i < Math.min(b.length, 80); i += 1) {
    out += String.fromCharCode(b[i]);
  }
  return out;
}

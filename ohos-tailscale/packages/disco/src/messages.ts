/**
 * disco 消息编解码（sealed 内层报文）。
 *
 * 上游实读依据（2026-10-01，GPU 机 jsdelivr CDN 拉取 tailscale main 的
 * disco/disco.go，全文对照实现；文件头注原文引用线格式）：
 *
 *   Header:  magic [6]byte "TS💬" (54 53 f0 9f 92 ac)
 *            senderDiscoPub [32]byte
 *            nonce [24]byte
 *   密封内： messageType byte ‖ messageVersion byte(=0) ‖ message-payload
 *
 * 本文件实现 0x01 Ping / 0x02 Pong / 0x03 CallMeMaybe 三类（与 tailscale
 * 1.16 时代客户端的已知类型集一致）：
 * - Ping：TxID 12B ‖ NodeKey 32B（仅当非零）‖ 0 填充 padding 字节
 *   （Padding 用于路径 MTU 探测）；解析对超长报文刻意宽松——超出
 *   TxID+NodeKey 的尾部字节一律计入 padding（上游 parsePing 同语义）。
 * - Pong：TxID 12B ‖ Src 16B（IPv4 用 v4-mapped 形式）‖ Port u16be。
 * - CallMeMaybe：N × (IP 16B ‖ Port u16be)；解析宽松语义与上游一致：
 *   version≠0 / 长度非 18 倍数 / 空 → 返回空端点列表（不报错）。
 *
 * 类型 0x04–0x09（UDP relay 家族：BindUDPRelayEndpoint* / CallMeMaybeVia /
 * AllocateUDPRelayEndpoint*）上游已注册但绑定 net/udprelay 服务端语义，
 * 本轮不实现——解码层对它们与未知类型一样抛 DiscoError('TYPE')，与"旧客户端
 * 收到新类型即忽略"的上游行为一致；二期随 UDP relay 扩展。
 */

import { ByteReader, ByteWriter } from '@ohos-tailscale/common';
import { DiscoError } from './errors.ts';

/** sealed 内层报文头：type u8 + version u8（上游 MessageHeaderLen = 2）。 */
const MSG_HEADER_LEN: number = 2;

/** TxID 长度（12B；上游 Ping.TxID / Pong.TxID）。 */
export const DISCO_TXID_LEN_BYTES: number = 12;

/** 密钥/公钥长度（32B）。 */
export const DISCO_KEY_LEN_BYTES: number = 32;

/** 端点条目长度 = IP 16B + Port 2B（上游 epLength）。 */
export const DISCO_EP_LEN_BYTES: number = 18;

/** Pong 载荷长度 = TxID 12 + IP 16 + Port 2（上游 pongLen）。 */
const PONG_LEN: number = DISCO_TXID_LEN_BYTES + 16 + 2;

/** Ping 载荷最小长度 = TxID 12 + NodeKey 32（上游 PingLen）。 */
const PING_LEN: number = DISCO_TXID_LEN_BYTES + DISCO_KEY_LEN_BYTES;

/** 消息类型常量对象（R5 模式，禁 enum；0x04–0x09 上游已注册、本轮未实现）。 */
export interface DiscoMessageTypeE {
  Ping: number;
  Pong: number;
  CallMeMaybe: number;
}

export const DiscoMessageType: DiscoMessageTypeE = {
  Ping: 0x01,
  Pong: 0x02,
  CallMeMaybe: 0x03,
};

/** 当前实现接受的类型集合（0x01–0x03；其余一律 'TYPE'）。 */
function isSupportedType(t: number): boolean {
  return t === DiscoMessageType.Ping || t === DiscoMessageType.Pong || t === DiscoMessageType.CallMeMaybe;
}

/** disco Ping（字段均为独立拷贝；nodeKey 为 null 表示不带 NodeKey）。 */
export interface DiscoPing {
  txid: Uint8Array;
  nodeKey: Uint8Array | null;
  padding: number;
}

/** disco Pong：srcIp16 为线上原样 16B（IPv4 为 v4-mapped）。 */
export interface DiscoPong {
  txid: Uint8Array;
  srcIp16: Uint8Array;
  srcPort: number;
}

/** disco 端点条目（ip16 为线上原样 16B；IPv4 用 v4-mapped）。 */
export interface DiscoEndpoint {
  ip16: Uint8Array;
  port: number;
}

/** disco CallMeMaybe：MyNumber = 本端候选端点列表。 */
export interface DiscoCallMeMaybe {
  myNumber: DiscoEndpoint[];
}

/** 判定 32B 是否全零（上游 NodeKey.IsZero 语义：零键不编码进 Ping）。 */
function isZero32(b: Uint8Array): boolean {
  if (b.length !== DISCO_KEY_LEN_BYTES) {
    return false;
  }
  for (let i: number = 0; i < b.length; i += 1) {
    if (b[i] !== 0) {
      return false;
    }
  }
  return true;
}

/** 写报文头（type + version）。 */
function writeHeader(w: ByteWriter, type: number, version: number): void {
  w.writeU8(type);
  w.writeU8(version);
}

/** v0 版本字节（上游 const v0 = 0）。 */
const MSG_VERSION: number = 0;

/** 编码 Ping（上游 Ping.AppendMarshal）。 */
export function pingEncode(m: DiscoPing): Uint8Array {
  if (m.txid.length !== DISCO_TXID_LEN_BYTES) {
    throw new DiscoError(
      'RANGE',
      'ping encode: txid must be ' + String(DISCO_TXID_LEN_BYTES) + ' bytes, got ' + String(m.txid.length),
    ) as Error;
  }
  const hasKey: boolean = m.nodeKey !== null && !isZero32(m.nodeKey);
  const dataLen: number = DISCO_TXID_LEN_BYTES + (hasKey ? DISCO_KEY_LEN_BYTES : 0) + m.padding;
  const w: ByteWriter = new ByteWriter(MSG_HEADER_LEN + dataLen);
  writeHeader(w, DiscoMessageType.Ping, MSG_VERSION);
  w.writeBytes(m.txid);
  if (hasKey && m.nodeKey !== null) {
    w.writeBytes(m.nodeKey);
  }
  for (let i: number = 0; i < m.padding; i += 1) {
    w.writeU8(0);
  }
  return w.toUint8Array();
}

/** 解码 Ping（上游 parsePing：≥12B 必需；尾部超长字节一律计 padding；零键视作 padding）。 */
export function pingParse(p: Uint8Array): DiscoPing {
  if (p.length < MSG_HEADER_LEN + DISCO_TXID_LEN_BYTES) {
    throw new DiscoError('SHORT', 'ping parse: message too short, got ' + String(p.length)) as Error;
  }
  const r: ByteReader = new ByteReader(p);
  const type: number = r.readU8();
  const version: number = r.readU8();
  if (type !== DiscoMessageType.Ping) {
    throw new DiscoError('TYPE', 'ping parse: type must be 0x01, got 0x' + type.toString(16)) as Error;
  }
  const txid: Uint8Array = r.readBytes(DISCO_TXID_LEN_BYTES);
  let padding: number = p.length - MSG_HEADER_LEN - DISCO_TXID_LEN_BYTES;
  let nodeKey: Uint8Array | null = null;
  if (p.length - MSG_HEADER_LEN >= PING_LEN) {
    const nk: Uint8Array = r.readBytes(DISCO_KEY_LEN_BYTES);
    if (!isZero32(nk)) {
      nodeKey = nk;
      padding -= DISCO_KEY_LEN_BYTES;
    }
  }
  const m: DiscoPing = { txid: txid, nodeKey: nodeKey, padding: padding };
  void version;
  return m;
}

/** 编码 Pong（上游 Pong.AppendMarshal）。 */
export function pongEncode(m: DiscoPong): Uint8Array {
  if (m.txid.length !== DISCO_TXID_LEN_BYTES) {
    throw new DiscoError(
      'RANGE',
      'pong encode: txid must be ' + String(DISCO_TXID_LEN_BYTES) + ' bytes, got ' + String(m.txid.length),
    ) as Error;
  }
  if (m.srcIp16.length !== 16) {
    throw new DiscoError('RANGE', 'pong encode: src ip must be 16 bytes, got ' + String(m.srcIp16.length)) as Error;
  }
  const w: ByteWriter = new ByteWriter(MSG_HEADER_LEN + PONG_LEN);
  writeHeader(w, DiscoMessageType.Pong, MSG_VERSION);
  w.writeBytes(m.txid);
  w.writeBytes(m.srcIp16);
  w.writeU16be(m.srcPort);
  return w.toUint8Array();
}

/** 解码 Pong（上游 parsePong：载荷 <30B 抛 errShort）。 */
export function pongParse(p: Uint8Array): DiscoPong {
  if (p.length < MSG_HEADER_LEN + PONG_LEN) {
    throw new DiscoError('SHORT', 'pong parse: message too short, got ' + String(p.length)) as Error;
  }
  const r: ByteReader = new ByteReader(p);
  const type: number = r.readU8();
  if (type !== DiscoMessageType.Pong) {
    throw new DiscoError('TYPE', 'pong parse: type must be 0x02, got 0x' + type.toString(16)) as Error;
  }
  r.readU8();
  const txid: Uint8Array = r.readBytes(DISCO_TXID_LEN_BYTES);
  const ip16: Uint8Array = r.readBytes(16);
  const port: number = r.readU16be();
  const m: DiscoPong = { txid: txid, srcIp16: ip16, srcPort: port };
  return m;
}

/** 编码 CallMeMaybe（上游 CallMeMaybe.AppendMarshal：N × 18B）。 */
export function callMeMaybeEncode(m: DiscoCallMeMaybe): Uint8Array {
  const w: ByteWriter = new ByteWriter(MSG_HEADER_LEN + DISCO_EP_LEN_BYTES * m.myNumber.length);
  writeHeader(w, DiscoMessageType.CallMeMaybe, MSG_VERSION);
  for (let i: number = 0; i < m.myNumber.length; i += 1) {
    const ep: DiscoEndpoint = m.myNumber[i];
    if (ep.ip16.length !== 16) {
      throw new DiscoError('RANGE', 'cmm encode: endpoint ip must be 16 bytes') as Error;
    }
    w.writeBytes(ep.ip16);
    w.writeU16be(ep.port);
  }
  return w.toUint8Array();
}

/**
 * 解码 CallMeMaybe（上游 parseCallMeMaybe 的宽松语义原样保留）：
 * version≠0 / 空 / 长度非 18 倍数 → 返回空端点列表（不抛错）。
 */
export function callMeMaybeParse(p: Uint8Array): DiscoCallMeMaybe {
  const empty: DiscoEndpoint[] = [];
  const emptyMsg: DiscoCallMeMaybe = { myNumber: empty };
  if (p.length < MSG_HEADER_LEN) {
    return emptyMsg;
  }
  const r: ByteReader = new ByteReader(p);
  const type: number = r.readU8();
  const version: number = r.readU8();
  if (type !== DiscoMessageType.CallMeMaybe) {
    throw new DiscoError('TYPE', 'cmm parse: type must be 0x03, got 0x' + type.toString(16)) as Error;
  }
  const rest: number = p.length - MSG_HEADER_LEN;
  if (version !== 0 || rest === 0 || rest % DISCO_EP_LEN_BYTES !== 0) {
    return emptyMsg;
  }
  const eps: DiscoEndpoint[] = [];
  for (let i: number = 0; i < rest / DISCO_EP_LEN_BYTES; i += 1) {
    const ip16: Uint8Array = r.readBytes(16);
    const port: number = r.readU16be();
    const ep: DiscoEndpoint = { ip16: ip16, port: port };
    eps.push(ep);
  }
  const m: DiscoCallMeMaybe = { myNumber: eps };
  return m;
}

/**
 * 解码密封内层报文的类型判定载体（ArkTS 无联合类型，用可空字段载体）。
 * kind/version 总有值；对应类型的载荷挂在各自字段（其余为 null）。
 */
export interface DiscoDecodedMessage {
  kind: number;
  version: number;
  ping: DiscoPing | null;
  pong: DiscoPong | null;
  callMeMaybe: DiscoCallMeMaybe | null;
}

/**
 * 解码密封内层报文（上游 Parse 的类型分发）：
 * 已实现类型走各自解析；未实现/未知类型抛 DiscoError('TYPE')。
 */
export function discoMessageParse(p: Uint8Array): DiscoDecodedMessage {
  if (p.length < MSG_HEADER_LEN) {
    throw new DiscoError('SHORT', 'disco message parse: too short, got ' + String(p.length)) as Error;
  }
  const t: number = p[0];
  const ver: number = p[1];
  if (!isSupportedType(t)) {
    throw new DiscoError(
      'TYPE',
      'disco message parse: unsupported message type 0x' + t.toString(16) + ' (0x04-0x09 upstream UDP-relay family not implemented)',
    ) as Error;
  }
  if (t === DiscoMessageType.Ping) {
    const ping: DiscoPing = pingParse(p);
    const out: DiscoDecodedMessage = {
      kind: t,
      version: ver,
      ping: ping,
      pong: null,
      callMeMaybe: null,
    };
    return out;
  }
  if (t === DiscoMessageType.Pong) {
    const pong: DiscoPong = pongParse(p);
    const out: DiscoDecodedMessage = {
      kind: t,
      version: ver,
      ping: null,
      pong: pong,
      callMeMaybe: null,
    };
    return out;
  }
  const cmm: DiscoCallMeMaybe = callMeMaybeParse(p);
  const out: DiscoDecodedMessage = {
    kind: t,
    version: ver,
    ping: null,
    pong: null,
    callMeMaybe: cmm,
  };
  return out;
}

/** 判定 16B IP 是否为 v4-mapped（::ffff:0:0/96 前缀）。 */
export function ip16IsV4Mapped(ip16: Uint8Array): boolean {
  if (ip16.length !== 16) {
    return false;
  }
  for (let i: number = 0; i < 10; i += 1) {
    if (ip16[i] !== 0) {
      return false;
    }
  }
  return ip16[10] === 0xff && ip16[11] === 0xff;
}

/** 16B IP 去映射：v4-mapped 返回 4B 拷贝，否则返回 16B 拷贝。 */
export function unmapIp16(ip16: Uint8Array): Uint8Array {
  if (ip16IsV4Mapped(ip16)) {
    return ip16.slice(12, 16);
  }
  return ip16.slice();
}

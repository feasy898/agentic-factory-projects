/**
 * STUN 线格式（netcheck 引擎的编码面核心）。
 *
 * 上游实读依据（2026-10-01，GPU 机 jsdelivr CDN 拉取 tailscale main 的
 * net/stun/stun.go，逐函数对照实现）：
 * - Binding Request（Request）：头部 = type 0x0001 ‖ len u16be ‖ magic cookie
 *   21 12 a4 42 ‖ TxID 12B；属性 SOFTWARE(0x8022, "tailnode"，8B 无需填充) ‖
 *   FINGERPRINT(0x8028, CRC32-IEEE(前缀全部字节) ^ 0x5354554e，u32be)。
 * - ParseBindingRequest（服务端视角）：须 Is 且 type=request 且 SOFTWARE 精确等于
 *   "tailnode" 且最后一个属性为 FINGERPRINT 且校验通过（ErrWrongSoftware /
 *   ErrNoFingerprint / ErrWrongFingerprint 语义逐一保留）。
 * - Response：type 0x0101，属性 XOR-MAPPED-ADDRESS(0x0020)：[0,fam] ‖
 *   port^0x2112(u16be) ‖ 地址异或（前 4B 对 magic cookie，其后对 TxID）。
 * - ParseResponse：XOR-MAPPED-ADDRESS(含 0x8020 变体) 为准；缺失时回退
 *   MAPPED-ADDRESS(0x0001)；IPv4 返回去映射后的 4B 地址（netip.Unmap 语义）。
 *   不校验 FINGERPRINT（上游 ParseResponse 同样不校验）。
 * - Is：len ≥ 20 且首字节高两位为 0 且 b[4:8] == magic。
 *
 * 外部锚定：XOR-MAPPED-ADDRESS 解码用 RFC 5769 §2.2/§2.3 官方向量（IPv4
 * 192.0.2.1:32853 / IPv6 2001:db8:…:6677:32853）；CRC32-IEEE 用规范 KAT
 * ("1234569" → 0xCBF43926)；请求编码字节序用 python3 zlib.crc32（独立实现）
 * 计算的黄金样本（测试头注注明计算式）。
 *
 * 引擎边界（如实保留）：本文件只做线格式与事务配对；端点枚举、
 * MappingVariesByDestIP、端口映射协议（PCP/PMP/UPnP）、按接口绑定等
 * netcheck 引擎调度留二期（protocol-notes.md §8 #5）。
 */

import { utf8Encode } from '@ohos-tailscale/common';
import { StunError } from './errors.ts';

/** STUN 头长（RFC 5389 §6；上游 headerLen = 20）。 */
export const STUN_HEADER_LEN: number = 20;

/** TxID 长度（12B）。 */
export const STUN_TXID_LEN_BYTES: number = 12;

/** Magic Cookie（RFC 5389 §6）。 */
export const STUN_MAGIC_COOKIE: Uint8Array = new Uint8Array([0x21, 0x12, 0xa4, 0x42]);

/** SOFTWARE 值（上游 software = "tailnode"，8B 长使其无需属性填充）。 */
export const STUN_SOFTWARE: string = 'tailnode';

const ATTR_SOFTWARE: number = 0x8022;
const ATTR_FINGERPRINT: number = 0x8028;
const ATTR_MAPPED_ADDRESS: number = 0x0001;
const ATTR_XOR_MAPPED_ADDRESS: number = 0x0020;
const ATTR_XOR_MAPPED_ADDRESS_ALT: number = 0x8020;

const BINDING_REQUEST_TYPE: number = 0x0001;
const BINDING_SUCCESS_TYPE: number = 0x0101;

/** FINGERPRINT 的 CRC32 异或常量（上游 fingerPrint：crc32 ^ 0x5354554e = "STUN"）。 */
const FINGERPRINT_XOR: number = 0x5354554e;

/** CRC32-IEEE 查表（反射多项式 0xEDB88320）。 */
let crcTable: Int32Array | null = null;

function crcTableInit(): Int32Array {
  if (crcTable !== null) {
    return crcTable;
  }
  const table: Int32Array = new Int32Array(256);
  for (let i: number = 0; i < 256; i += 1) {
    let c: number = i;
    for (let k: number = 0; k < 8; k += 1) {
      if ((c & 1) !== 0) {
        c = (0xedb88320 ^ (c >>> 1)) >>> 0;
      } else {
        c = c >>> 1;
      }
    }
    table[i] = c;
  }
  crcTable = table;
  return table;
}

/** CRC32-IEEE（zlib/gzip 多项式；规范 KAT "123456789" → 0xCBF43926）。 */
export function crc32Ieee(data: Uint8Array): number {
  const table: Int32Array = crcTableInit();
  let crc: number = 0xffffffff;
  for (let i: number = 0; i < data.length; i += 1) {
    crc = (table[(crc ^ data[i]) & 0xff] ^ (crc >>> 8)) >>> 0;
  }
  return (crc ^ 0xffffffff) >>> 0;
}

/** 上游 fingerPrint：CRC32-IEEE 后异或 "STUN"。 */
function stunFingerprint(prefix: Uint8Array): number {
  return (crc32Ieee(prefix) ^ FINGERPRINT_XOR) >>> 0;
}

function writeU16be(b: Uint8Array, off: number, v: number): void {
  b[off] = (v >>> 8) & 0xff;
  b[off + 1] = v & 0xff;
}

function writeU32be(b: Uint8Array, off: number, v: number): void {
  b[off] = (v >>> 24) & 0xff;
  b[off + 1] = (v >>> 16) & 0xff;
  b[off + 2] = (v >>> 8) & 0xff;
  b[off + 3] = v & 0xff;
}

function readU16be(b: Uint8Array, off: number): number {
  return ((b[off] << 8) | b[off + 1]) & 0xffff;
}

function readU32be(b: Uint8Array, off: number): number {
  return (((b[off] << 24) | (b[off + 1] << 16) | (b[off + 2] << 8) | b[off + 3]) >>> 0);
}

function requireTxid(txid: Uint8Array): void {
  if (txid.length !== STUN_TXID_LEN_BYTES) {
    throw new StunError(
      'RANGE',
      'stun: txid must be ' + String(STUN_TXID_LEN_BYTES) + ' bytes, got ' + String(txid.length),
    ) as Error;
  }
}

/** 判定 b 是否 STUN 报文（上游 Is）。 */
export function stunIs(b: Uint8Array): boolean {
  if (b.length < STUN_HEADER_LEN) {
    return false;
  }
  if ((b[0] & 0b11000000) !== 0) {
    return false;
  }
  for (let i: number = 0; i < 4; i += 1) {
    if (b[4 + i] !== STUN_MAGIC_COOKIE[i]) {
      return false;
    }
  }
  return true;
}

/** 取报文中的 TxID（不校验类型；非 STUN 形态抛 'NOT_STUN'）。 */
export function stunTxid(b: Uint8Array): Uint8Array {
  if (!stunIs(b)) {
    throw new StunError('NOT_STUN', 'stun: not a stun packet') as Error;
  }
  return b.slice(8, 8 + STUN_TXID_LEN_BYTES);
}

/** 生成 Binding Request（上游 Request：SOFTWARE + FINGERPRINT，共 40B）。 */
export function stunRequest(txid: Uint8Array): Uint8Array {
  requireTxid(txid);
  const software: Uint8Array = utf8Encode(STUN_SOFTWARE);
  const msgLen: number = 4 + software.length + 8; // SOFTWARE attr + FINGERPRINT attr
  const out: Uint8Array = new Uint8Array(STUN_HEADER_LEN + msgLen);
  writeU16be(out, 0, BINDING_REQUEST_TYPE);
  writeU16be(out, 2, msgLen);
  out.set(STUN_MAGIC_COOKIE, 4);
  out.set(txid, 8);
  let off: number = STUN_HEADER_LEN;
  writeU16be(out, off, ATTR_SOFTWARE);
  writeU16be(out, off + 2, software.length);
  out.set(software, off + 4);
  off += 4 + software.length;
  const fp: number = stunFingerprint(out.slice(0, off));
  writeU16be(out, off, ATTR_FINGERPRINT);
  writeU16be(out, off + 2, 4);
  writeU32be(out, off + 4, fp);
  return out;
}

/** 属性遍历回调载体（ArkTS 无函数回调遍历的元组，逐 attr 交付）。 */
interface StunAttrView {
  type: number;
  value: Uint8Array;
}

/** 属性遍历（上游 foreachAttr：len 按 4B 对齐推进；不足 4B/越界 → MALFORMED）。 */
function* foreachAttr(attrs: Uint8Array): Generator<StunAttrView> {
  let off: number = 0;
  while (off < attrs.length) {
    if (attrs.length - off < 4) {
      throw new StunError('MALFORMED', 'stun: truncated attribute header') as Error;
    }
    const type: number = readU16be(attrs, off);
    const len: number = readU16be(attrs, off + 2);
    const padded: number = (len + 3) & ~3;
    off += 4;
    if (padded > attrs.length - off) {
      throw new StunError('MALFORMED', 'stun: attribute overruns message') as Error;
    }
    const view: StunAttrView = { type: type, value: attrs.slice(off, off + len) };
    yield view;
    off += padded;
  }
}

/** 解析 Binding Request（服务端视角；上游 ParseBindingRequest 校验链）。 */
export function stunParseBindingRequest(b: Uint8Array): Uint8Array {
  if (!stunIs(b)) {
    throw new StunError('NOT_STUN', 'stun: not a stun packet') as Error;
  }
  if (readU16be(b, 0) !== BINDING_REQUEST_TYPE) {
    throw new StunError('NOT_REQUEST', 'stun: not a binding request') as Error;
  }
  const txid: Uint8Array = b.slice(8, 8 + STUN_TXID_LEN_BYTES);
  const attrsLen: number = readU16be(b, 2);
  let attrs: Uint8Array = b.slice(STUN_HEADER_LEN);
  if (attrsLen > attrs.length) {
    throw new StunError('MALFORMED', 'stun: attribute length overruns message') as Error;
  }
  if (attrs.length > attrsLen) {
    attrs = attrs.slice(0, attrsLen);
  }
  let softwareOk: boolean = false;
  let lastAttr: number = -1;
  let gotFp: number | null = null;
  const walker: Generator<StunAttrView> = foreachAttr(attrs);
  let step: IteratorResult<StunAttrView> = walker.next();
  while (!step.done) {
    const attr: StunAttrView = step.value;
    lastAttr = attr.type;
    if (attr.type === ATTR_SOFTWARE) {
      const want: Uint8Array = utf8Encode(STUN_SOFTWARE);
      if (attr.value.length === want.length) {
        let eq: boolean = true;
        for (let i: number = 0; i < want.length; i += 1) {
          if (attr.value[i] !== want[i]) {
            eq = false;
            break;
          }
        }
        softwareOk = eq;
      }
    }
    if (attr.type === ATTR_FINGERPRINT && attr.value.length === 4) {
      gotFp = readU32be(attr.value, 0);
    }
    step = walker.next();
  }
  if (!softwareOk) {
    throw new StunError('WRONG_SOFTWARE', 'stun: request came from non-tailscale software') as Error;
  }
  if (lastAttr !== ATTR_FINGERPRINT || gotFp === null) {
    throw new StunError('NO_FINGERPRINT', 'stun: request did not end in fingerprint') as Error;
  }
  const wantFp: number = stunFingerprint(b.slice(0, b.length - 8));
  if (gotFp !== wantFp) {
    throw new StunError('WRONG_FINGERPRINT', 'stun: bogus fingerprint') as Error;
  }
  return txid;
}

/** 解析成功的 Binding Response 的地址视图（ip 为去映射后的 4B 或 16B 原始字节）。 */
export interface StunParsedResponse {
  txid: Uint8Array;
  ip: Uint8Array;
  port: number;
}

/** 地址族字节 → 地址字节长（0x01=IPv4 4B、0x02=IPv6 16B、其余 0）。 */
function familyAddrLen(fam: number): number {
  if (fam === 0x01) {
    return 4;
  }
  if (fam === 0x02) {
    return 16;
  }
  return 0;
}

/** XOR-MAPPED-ADDRESS 属性解码（上游 xorMappedAddress）。 */
function xorMapped(txid: Uint8Array, attr: Uint8Array): { ip: Uint8Array; port: number } {
  if (attr.length < 4) {
    throw new StunError('MALFORMED', 'stun: xor-mapped-address too short') as Error;
  }
  const port: number = (readU16be(attr, 2) ^ 0x2112) & 0xffff;
  const addrLen: number = familyAddrLen(attr[1]);
  if (addrLen === 0) {
    throw new StunError('MALFORMED', 'stun: unknown address family') as Error;
  }
  if (attr.length - 4 < addrLen) {
    throw new StunError('MALFORMED', 'stun: xor-mapped-address truncated') as Error;
  }
  const addr: Uint8Array = new Uint8Array(addrLen);
  for (let i: number = 0; i < addrLen; i += 1) {
    if (i < 4) {
      addr[i] = attr[4 + i] ^ STUN_MAGIC_COOKIE[i];
    } else {
      addr[i] = attr[4 + i] ^ txid[i - 4];
    }
  }
  const out = { ip: addr, port: port };
  return out;
}

/** MAPPED-ADDRESS 属性解码（上游 mappedAddress，回退用）。 */
function mappedAddress(attr: Uint8Array): { ip: Uint8Array; port: number } {
  if (attr.length < 4) {
    throw new StunError('MALFORMED', 'stun: mapped-address too short') as Error;
  }
  const port: number = readU16be(attr, 2);
  const addrLen: number = familyAddrLen(attr[1]);
  if (addrLen === 0) {
    throw new StunError('MALFORMED', 'stun: unknown address family') as Error;
  }
  if (attr.length - 4 < addrLen) {
    throw new StunError('MALFORMED', 'stun: mapped-address truncated') as Error;
  }
  const out = { ip: attr.slice(4, 4 + addrLen), port: port };
  return out;
}

/** v4-mapped IPv6（::ffff:0:0/96 前缀）→ 4B；否则原样 16B。 */
function unmapIp(ip: Uint8Array): Uint8Array {
  if (ip.length === 16) {
    let mapped: boolean = true;
    for (let i: number = 0; i < 10; i += 1) {
      if (ip[i] !== 0) {
        mapped = false;
        break;
      }
    }
    if (mapped && ip[10] === 0xff && ip[11] === 0xff) {
      return ip.slice(12, 16);
    }
  }
  return ip;
}

/** 生成 Binding Success Response（上游 Response；ip 4B=IPv4 / 16B=IPv6 原始字节）。 */
export function stunResponse(txid: Uint8Array, ip: Uint8Array, port: number): Uint8Array {
  requireTxid(txid);
  let fam: number = 0;
  if (ip.length === 4) {
    fam = 1;
  } else if (ip.length === 16) {
    fam = 2;
  } else {
    throw new StunError('RANGE', 'stun: ip must be 4 or 16 bytes, got ' + String(ip.length)) as Error;
  }
  const attrsLen: number = 8 + ip.length;
  const out: Uint8Array = new Uint8Array(STUN_HEADER_LEN + attrsLen);
  writeU16be(out, 0, BINDING_SUCCESS_TYPE);
  writeU16be(out, 2, attrsLen);
  out.set(STUN_MAGIC_COOKIE, 4);
  out.set(txid, 8);
  let off: number = STUN_HEADER_LEN;
  writeU16be(out, off, ATTR_XOR_MAPPED_ADDRESS);
  writeU16be(out, off + 2, 4 + ip.length);
  off += 4;
  out[off] = 0;
  out[off + 1] = fam;
  writeU16be(out, off + 2, (port ^ 0x2112) & 0xffff);
  off += 4;
  for (let i: number = 0; i < ip.length; i += 1) {
    if (i < 4) {
      out[off + i] = ip[i] ^ STUN_MAGIC_COOKIE[i];
    } else {
      out[off + i] = ip[i] ^ txid[i - 4];
    }
  }
  return out;
}

/** 解析 Binding Response（上游 ParseResponse：XOR-MAPPED 优先，MAPPED 回退）。 */
export function stunParseResponse(b: Uint8Array): StunParsedResponse {
  if (!stunIs(b)) {
    throw new StunError('NOT_STUN', 'stun: not a stun packet') as Error;
  }
  const txid: Uint8Array = b.slice(8, 8 + STUN_TXID_LEN_BYTES);
  if (readU16be(b, 0) !== BINDING_SUCCESS_TYPE) {
    throw new StunError('NOT_SUCCESS', 'stun: not a success response') as Error;
  }
  const attrsLen: number = readU16be(b, 2);
  let attrs: Uint8Array = b.slice(STUN_HEADER_LEN);
  if (attrsLen > attrs.length) {
    throw new StunError('MALFORMED', 'stun: attribute length overruns message') as Error;
  }
  if (attrs.length > attrsLen) {
    attrs = attrs.slice(0, attrsLen);
  }
  let addr: { ip: Uint8Array; port: number } | null = null;
  let fallback: { ip: Uint8Array; port: number } | null = null;
  const walker: Generator<StunAttrView> = foreachAttr(attrs);
  let step: IteratorResult<StunAttrView> = walker.next();
  while (!step.done) {
    const attr: StunAttrView = step.value;
    if (attr.type === ATTR_XOR_MAPPED_ADDRESS || attr.type === ATTR_XOR_MAPPED_ADDRESS_ALT) {
      addr = xorMapped(txid, attr.value);
    } else if (attr.type === ATTR_MAPPED_ADDRESS) {
      fallback = mappedAddress(attr.value);
    }
    step = walker.next();
  }
  const chosen = addr !== null ? addr : fallback;
  if (chosen === null) {
    throw new StunError('MALFORMED', 'stun: no usable mapped address attribute') as Error;
  }
  const out: StunParsedResponse = { txid: txid, ip: unmapIp(chosen.ip), port: chosen.port };
  return out;
}

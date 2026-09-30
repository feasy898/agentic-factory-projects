/**
 * 哈希与 KDF（架构契约 §4 hash.ts）：SHA-256、HMAC-SHA256、BLAKE2s-256
 * （无键/键控，供 WireGuard MAC1/MAC2 使用）、HMAC-BLAKE2s（Noise/WG HKDF 的
 * 底层原语，内部导出）、HKDF（RFC 5869 展开形态，即 Noise/WG 的 KDF²/KDF³）。
 *
 * - SHA-256：FIPS 180-4。初始向量 H 与轮常量 K 按 FIPS 定义（前 8/64 个素数的
 *   平方/立方根小数部分的前 32 位）用 BigInt 精确计算后以字面量固化，
 *   锚点（H[0]=0x6a09e667、K[0]=0x428a2f98、K[63]=0xc67178f2）已核对。
 * - BLAKE2s：RFC 7693。IV 与 SHA-256 的 H 相同；SIGMA 置换表为 RFC 规定常量；
 *   键控模式参数块 h[0] ^= 0x01010000 ^ (keyLen << 8) ^ 32，带键时先压缩一个
 *   64B 的补零密钥块（空消息时该块即末块）。
 *   键控 BLAKE2s 的测试向量来自独立参考实现（CPython hashlib.blake2s，libb2 同源）
 *   的运行时输出，非凭记忆抄写；无键 BLAKE2s 另与 node:crypto('blake2s256') 交叉验证。
 * - HMAC：RFC 2104，块长 64B。BLAKE2s 的 HMAC 是 Noise/WG 规范明确要求的构造
 *   （区别于 BLAKE2s 自带的 keyed 模式）；node:crypto 可用 createHmac('blake2s256')
 *   直接交叉验证（OpenSSL 支持），测试已覆盖。
 * - HKDF：extract = HMAC(salt=chainingKey, ikm)；expand 的 info 为空、计数器
 *   0x01..0x03，输出按 32B 切分 —— 与 WireGuard 白皮书/Noise 规范的 KDF²/KDF³
 *   逐步一致。返回 Uint8Array[]（R4：禁 tuple，用定长数组）。
 */

import { CryptoError } from './errors.ts';

// ---------------------------------------------------------------------------
// SHA-256（FIPS 180-4）
// ---------------------------------------------------------------------------

/** 初始哈希值（前 8 个素数平方根小数部分前 32 位）。BLAKE2s IV 与此相同（RFC 7693 §2.6）。 */
const SHA256_H: number[] = [
  0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19,
];

/** 轮常量 K（前 64 个素数立方根小数部分前 32 位）。 */
const SHA256_K: number[] = [
  0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
  0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
  0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
  0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
  0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
  0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
  0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
  0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
];

function readU32be(b: Uint8Array, off: number): number {
  return ((b[off] << 24) | (b[off + 1] << 16) | (b[off + 2] << 8) | b[off + 3]) >>> 0;
}

function writeU32le(b: Uint8Array, off: number, v: number): void {
  b[off] = v & 0xff;
  b[off + 1] = (v >>> 8) & 0xff;
  b[off + 2] = (v >>> 16) & 0xff;
  b[off + 3] = (v >>> 24) & 0xff;
}

function rotr32(v: number, n: number): number {
  return ((v >>> n) | (v << (32 - n))) >>> 0;
}

/** SHA-256 压缩函数：h 就地吸收一个 64B 块。 */
function sha256Compress(h: number[], block: Uint8Array): void {
  const w: number[] = new Array<number>(64);
  for (let i: number = 0; i < 16; i += 1) {
    w[i] = readU32be(block, i * 4);
  }
  for (let i: number = 16; i < 64; i += 1) {
    const s0: number = rotr32(w[i - 15], 7) ^ rotr32(w[i - 15], 18) ^ (w[i - 15] >>> 3);
    const s1: number = rotr32(w[i - 2], 17) ^ rotr32(w[i - 2], 19) ^ (w[i - 2] >>> 10);
    w[i] = (w[i - 16] + s0 + w[i - 7] + s1) >>> 0;
  }
  let a: number = h[0];
  let b: number = h[1];
  let c: number = h[2];
  let d: number = h[3];
  let e: number = h[4];
  let f: number = h[5];
  let g: number = h[6];
  let hh: number = h[7];
  for (let i: number = 0; i < 64; i += 1) {
    const bigS1: number = rotr32(e, 6) ^ rotr32(e, 11) ^ rotr32(e, 25);
    const ch: number = (e & f) ^ (~e & g);
    const t1: number = (hh + bigS1 + ch + SHA256_K[i] + w[i]) >>> 0;
    const bigS0: number = rotr32(a, 2) ^ rotr32(a, 13) ^ rotr32(a, 22);
    const maj: number = (a & b) ^ (a & c) ^ (b & c);
    const t2: number = (bigS0 + maj) >>> 0;
    hh = g;
    g = f;
    f = e;
    e = (d + t1) >>> 0;
    d = c;
    c = b;
    b = a;
    a = (t1 + t2) >>> 0;
  }
  h[0] = (h[0] + a) >>> 0;
  h[1] = (h[1] + b) >>> 0;
  h[2] = (h[2] + c) >>> 0;
  h[3] = (h[3] + d) >>> 0;
  h[4] = (h[4] + e) >>> 0;
  h[5] = (h[5] + f) >>> 0;
  h[6] = (h[6] + g) >>> 0;
  h[7] = (h[7] + hh) >>> 0;
}

/**
 * SHA-256 一次性摘要。任意长度输入（含空）；返回 32B 新数组。
 */
export function sha256(data: Uint8Array): Uint8Array {
  const h: number[] = SHA256_H.slice();
  const bitLen: number = data.length * 8;
  // 填充：0x80 + 零 + 64bit 大端位长；总长 = ceil((len+9)/64) * 64
  //（len+9 恰为 64 的倍数时不再多补一块，如 len=55 → 单块）
  const total: number = Math.ceil((data.length + 9) / 64) * 64;
  const buf: Uint8Array = new Uint8Array(total);
  buf.set(data, 0);
  buf[data.length] = 0x80;
  // 64bit 大端位长：高 32 位 = floor(bitLen / 2^32)（精度安全：bitLen < 2^53），
  // 低 32 位按位与/移位取字节。
  const hi32: number = Math.floor(bitLen / 4294967296);
  buf[total - 8] = (hi32 >>> 24) & 0xff;
  buf[total - 7] = (hi32 >>> 16) & 0xff;
  buf[total - 6] = (hi32 >>> 8) & 0xff;
  buf[total - 5] = hi32 & 0xff;
  buf[total - 4] = (bitLen >>> 24) & 0xff;
  buf[total - 3] = (bitLen >>> 16) & 0xff;
  buf[total - 2] = (bitLen >>> 8) & 0xff;
  buf[total - 1] = bitLen & 0xff;
  for (let off: number = 0; off < total; off += 64) {
    sha256Compress(h, buf.subarray(off, off + 64));
  }
  const out: Uint8Array = new Uint8Array(32);
  for (let i: number = 0; i < 8; i += 1) {
    out[i * 4] = (h[i] >>> 24) & 0xff;
    out[i * 4 + 1] = (h[i] >>> 16) & 0xff;
    out[i * 4 + 2] = (h[i] >>> 8) & 0xff;
    out[i * 4 + 3] = h[i] & 0xff;
  }
  return out;
}

// ---------------------------------------------------------------------------
// BLAKE2s（RFC 7693）
// ---------------------------------------------------------------------------

/** SIGMA 置换表（RFC 7693 §2.7，10 轮 × 16 项）。 */
const SIGMA: number[][] = [
  [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15],
  [14, 10, 4, 8, 9, 15, 13, 6, 1, 12, 0, 2, 11, 7, 5, 3],
  [11, 8, 12, 0, 5, 2, 15, 13, 10, 14, 3, 6, 7, 1, 9, 4],
  [7, 9, 3, 1, 13, 12, 11, 14, 2, 6, 5, 10, 4, 0, 15, 8],
  [9, 0, 5, 7, 2, 4, 10, 15, 14, 1, 11, 12, 6, 8, 3, 13],
  [2, 12, 6, 10, 0, 11, 8, 3, 4, 13, 7, 5, 15, 14, 1, 9],
  [12, 5, 1, 15, 14, 13, 4, 10, 0, 7, 6, 3, 9, 2, 8, 11],
  [13, 11, 7, 14, 12, 1, 3, 9, 5, 0, 15, 4, 8, 6, 2, 10],
  [6, 15, 14, 9, 11, 3, 0, 8, 12, 2, 13, 7, 1, 4, 10, 5],
  [10, 2, 8, 4, 7, 6, 1, 5, 15, 11, 9, 14, 3, 12, 13, 0],
];

function blake2sG(
  v: number[],
  a: number,
  b: number,
  c: number,
  d: number,
  x: number,
  y: number,
): void {
  v[a] = (v[a] + v[b] + x) >>> 0;
  v[d] = rotr32(v[d] ^ v[a], 16);
  v[c] = (v[c] + v[d]) >>> 0;
  v[b] = rotr32(v[b] ^ v[c], 12);
  v[a] = (v[a] + v[b] + y) >>> 0;
  v[d] = rotr32(v[d] ^ v[a], 8);
  v[c] = (v[c] + v[d]) >>> 0;
  v[b] = rotr32(v[b] ^ v[c], 7);
}

/** BLAKE2s 压缩函数（RFC 7693 §3.2）：h 就地吸收一个 64B 块。 */
function blake2sCompress(h: number[], block: Uint8Array, t: number, last: boolean): void {
  const m: number[] = new Array<number>(16);
  for (let i: number = 0; i < 16; i += 1) {
    m[i] =
      (block[i * 4] |
        (block[i * 4 + 1] << 8) |
        (block[i * 4 + 2] << 16) |
        (block[i * 4 + 3] << 24)) >>>
      0;
  }
  const v: number[] = new Array<number>(16);
  for (let i: number = 0; i < 8; i += 1) {
    v[i] = h[i];
    v[8 + i] = SHA256_H[i];
  }
  v[12] = v[12] ^ (t >>> 0);
  v[13] = v[13] ^ (Math.floor(t / 4294967296) >>> 0);
  // RFC 7693 §3.2：末块标志只翻转 v[14]（v[15] 不动 —— 早前误翻两个导致全错，
  // 已对照 RFC 原文与 node:crypto 修正）。
  if (last) {
    v[14] = (~v[14]) >>> 0;
  }
  for (let r: number = 0; r < 10; r += 1) {
    const s: number[] = SIGMA[r];
    blake2sG(v, 0, 4, 8, 12, m[s[0]], m[s[1]]);
    blake2sG(v, 1, 5, 9, 13, m[s[2]], m[s[3]]);
    blake2sG(v, 2, 6, 10, 14, m[s[4]], m[s[5]]);
    blake2sG(v, 3, 7, 11, 15, m[s[6]], m[s[7]]);
    blake2sG(v, 0, 5, 10, 15, m[s[8]], m[s[9]]);
    blake2sG(v, 1, 6, 11, 12, m[s[10]], m[s[11]]);
    blake2sG(v, 2, 7, 8, 13, m[s[12]], m[s[13]]);
    blake2sG(v, 3, 4, 9, 14, m[s[14]], m[s[15]]);
  }
  for (let i: number = 0; i < 8; i += 1) {
    h[i] = (h[i] ^ v[i] ^ v[i + 8]) >>> 0;
  }
}

/**
 * BLAKE2s-256 核心（RFC 7693）：key 为 null 时无键模式；
 * 带键时 key 长度必须 1..32B（0..32 之外抛 CryptoError('RANGE')）。
 * 返回 32B 新数组。内部导出供 blake2s256/blake2s256Keyed 复用。
 */
function blake2sCore(data: Uint8Array, key: Uint8Array | null): Uint8Array {
  const keyLen: number = key === null ? 0 : key.length;
  if (keyLen > 32) {
    throw new CryptoError('RANGE', 'blake2s: key must be at most 32 bytes, got ' + String(keyLen)) as Error;
  }
  const h: number[] = SHA256_H.slice();
  // 参数块：digest_length=32，key_length，fanout=1，depth=1 → 0x01010000 ^ (kk<<8) ^ nn
  h[0] = (h[0] ^ (0x01010000 ^ (keyLen << 8) ^ 32)) >>> 0;

  // 带键时先补零到 64B 作为首块（RFC 7693 §2.8）
  let prefixed: Uint8Array = data;
  if (key !== null && key.length > 0) {
    prefixed = new Uint8Array(64 + data.length);
    prefixed.set(key, 0);
    prefixed.set(data, 64);
  }
  const total: number = prefixed.length;
  if (total === 0) {
    // 空输入：压缩一个全零空块，t=0，末块标志
    blake2sCompress(h, new Uint8Array(64), 0, true);
  } else {
    const nBlocks: number = Math.ceil(total / 64);
    for (let i: number = 0; i < nBlocks; i += 1) {
      const start: number = i * 64;
      const end: number = Math.min(start + 64, total);
      const block: Uint8Array = new Uint8Array(64);
      for (let j: number = start; j < end; j += 1) {
        block[j - start] = prefixed[j];
      }
      blake2sCompress(h, block, end, i === nBlocks - 1);
    }
  }
  const out: Uint8Array = new Uint8Array(32);
  for (let i: number = 0; i < 8; i += 1) {
    writeU32le(out, i * 4, h[i]);
  }
  return out;
}

/** 无键 BLAKE2s-256。任意长度输入；返回 32B 新数组。 */
export function blake2s256(data: Uint8Array): Uint8Array {
  return blake2sCore(data, null);
}

/**
 * 键控 BLAKE2s-256（key 1..32B；WireGuard MAC1/MAC2 用 32B 键，取前 16B 即 MAC）。
 * 返回 32B 新数组。key 长度越界抛 CryptoError('RANGE')。
 */
export function blake2s256Keyed(key: Uint8Array, data: Uint8Array): Uint8Array {
  if (key.length < 1) {
    throw new CryptoError('RANGE', 'blake2s256Keyed: key must be 1..32 bytes, got 0') as Error;
  }
  return blake2sCore(data, key);
}

// ---------------------------------------------------------------------------
// HMAC（RFC 2104，块长 64B）
// ---------------------------------------------------------------------------

/**
 * HMAC 密钥预处理：> 64B 先用 HMAC 所属哈希 H 压缩（RFC 2104：H(K)）；
 * 零填充到 64B。hashId：1 = SHA-256，2 = BLAKE2s。返回 64B 新数组。
 */
function hmacPadKey(key: Uint8Array, hashId: number): Uint8Array {
  let k: Uint8Array = key;
  if (k.length > 64) {
    k = hashId === 1 ? sha256(k) : blake2sCore(k, null);
  }
  const padded: Uint8Array = new Uint8Array(64);
  for (let i: number = 0; i < k.length && i < 64; i += 1) {
    padded[i] = k[i];
  }
  return padded;
}

/** HMAC-SHA256（RFC 2104 §2）。key 任意长度；返回 32B 新数组。 */
export function hmacSha256(key: Uint8Array, data: Uint8Array): Uint8Array {
  const padded: Uint8Array = hmacPadKey(key, 1);
  const inner: Uint8Array = new Uint8Array(64 + data.length);
  const outer: Uint8Array = new Uint8Array(64 + 32);
  for (let i: number = 0; i < 64; i += 1) {
    inner[i] = padded[i] ^ 0x36;
    outer[i] = padded[i] ^ 0x5c;
  }
  inner.set(data, 64);
  outer.set(sha256(inner), 64);
  return sha256(outer);
}

/**
 * HMAC-BLAKE2s（RFC 2104 构造，H = BLAKE2s-256；Noise/WG HKDF 底层）。
 * 注意区别于键控 BLAKE2s：这是标准 HMAC 双层哈希，块长 64B。
 * key 任意长度；返回 32B 新数组。内部导出供 HKDF 与测试使用
 * （node:crypto 的 createHmac('blake2s256') 可直接交叉验证）。
 */
export function hmacBlake2s(key: Uint8Array, data: Uint8Array): Uint8Array {
  const padded: Uint8Array = hmacPadKey(key, 2);
  const inner: Uint8Array = new Uint8Array(64 + data.length);
  const outer: Uint8Array = new Uint8Array(64 + 32);
  for (let i: number = 0; i < 64; i += 1) {
    inner[i] = padded[i] ^ 0x36;
    outer[i] = padded[i] ^ 0x5c;
  }
  inner.set(data, 64);
  outer.set(blake2sCore(inner, null), 64);
  return blake2sCore(outer, null);
}

// ---------------------------------------------------------------------------
// HKDF（RFC 5869 展开形态；Noise/WireGuard KDF²/KDF³）
// ---------------------------------------------------------------------------

/** HKDF-Expand（info 固定为空，输出 length 字节，length ≤ 3*32）。H 由 hashId 选择。 */
function hkdfExpandN(hashId: number, prk: Uint8Array, length: number): Uint8Array {
  const nBlocks: number = Math.ceil(length / 32);
  const okm: Uint8Array = new Uint8Array(nBlocks * 32);
  let prev: Uint8Array = new Uint8Array(0);
  for (let i: number = 1; i <= nBlocks; i += 1) {
    const input: Uint8Array = new Uint8Array(prev.length + 1);
    input.set(prev, 0);
    input[input.length - 1] = i;
    if (hashId === 1) {
      prev = hmacSha256(prk, input);
    } else {
      prev = hmacBlake2s(prk, input);
    }
    okm.set(prev, (i - 1) * 32);
  }
  return okm;
}

/**
 * KDF(chainingKey, ikm, outputs)：extract = HMAC(chainingKey, ikm)，
 * expand 按 0x01..0x03 计数器展开，切分为 outputs 个 32B。
 * 返回 Uint8Array[]（长度 = outputs；R4 禁 tuple，用定长数组承载）。
 * chainingKey/ikm 任意长度（HMAC 语义允许；WG/Noise 实际用 32B）。
 */
function hkdfN(chainingKey: Uint8Array, ikm: Uint8Array, outputs: number, hashId: number): Uint8Array[] {
  const prk: Uint8Array =
    hashId === 1 ? hmacSha256(chainingKey, ikm) : hmacBlake2s(chainingKey, ikm);
  const okm: Uint8Array = hkdfExpandN(hashId, prk, outputs * 32);
  const out: Uint8Array[] = [];
  for (let i: number = 0; i < outputs; i += 1) {
    out.push(okm.slice(i * 32, i * 32 + 32));
  }
  return out;
}

/** KDF²（HMAC-BLAKE2s）：WG/Noise 双输出链键推进。返回定长 2 的 Uint8Array[]。 */
export function kdf2Blake2s(chainingKey: Uint8Array, ikm: Uint8Array): Uint8Array[] {
  return hkdfN(chainingKey, ikm, 2, 2);
}

/** KDF³（HMAC-BLAKE2s）：WG/Noise 三输出（临时传输密钥）。返回定长 3 的 Uint8Array[]。 */
export function kdf3Blake2s(chainingKey: Uint8Array, ikm: Uint8Array): Uint8Array[] {
  return hkdfN(chainingKey, ikm, 3, 2);
}

/** KDF²（HMAC-SHA256）：ts2021/Noise 协议族同形 KDF。返回定长 2 的 Uint8Array[]。 */
export function kdf2Sha256(chainingKey: Uint8Array, ikm: Uint8Array): Uint8Array[] {
  return hkdfN(chainingKey, ikm, 2, 1);
}

/** KDF³（HMAC-SHA256）。返回定长 3 的 Uint8Array[]。 */
export function kdf3Sha256(chainingKey: Uint8Array, ikm: Uint8Array): Uint8Array[] {
  return hkdfN(chainingKey, ikm, 3, 1);
}

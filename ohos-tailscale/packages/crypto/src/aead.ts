/**
 * ChaCha20-Poly1305 AEAD（RFC 8439）。
 *
 * - ChaCha20：块函数为 4x4 状态上的 20 轮（10 个双轮），计数器为 32 位（§2.4）。
 * - Poly1305：一次性认证器，r 被 clamp 到 0x0ffffffc0ffffffc0ffffffc0fffffff，
 *   素数 p = 2^130 - 5；BigInt 实现每块做一次模乘（§2.5）。
 * - AEAD 构造（§2.8）：polyKey = 块计数 0 的前 32 字节；加密从计数 1 起；
 *   MAC 输入 = AAD || pad16 || ciphertext || pad16 || le64(len(AAD)) || le64(len(CT))；
 *   密文布局 = ciphertext || tag(16B)（架构契约 §4）。
 *
 * 注：早先起草时记忆中的 RFC 8439 §2.5.2 Poly1305 向量与 RFC 原文核对一致，
 * 并在测试中与 node:crypto('chacha20-poly1305') 交叉验证；若与 node:crypto
 * 冲突，以 node:crypto 为准（测试注释另有说明）。
 */

import { AEAD_NONCE_LEN_BYTES, AEAD_TAG_LEN_BYTES, KEY_LEN_BYTES } from '@ohos-tailscale/common';
import { CryptoError } from './errors.ts';
import { constTimeEqual } from './util.ts';

/** RFC 8439 §2.3.2 常量字 "expand 32-byte k" 的 u32le 视图。 */
const CHACHA_CONST: number[] = [0x61707865, 0x3320646e, 0x79622d32, 0x6b206574];

/** Poly1305 素数 p = 2^130 - 5。 */
const POLY_P: bigint = (1n << 130n) - 5n;
/** Poly1305 r 的 clamp 掩码（§2.5）。 */
const POLY_R_MASK: bigint = 0x0ffffffc0ffffffc0ffffffc0fffffffn;

function readU32le(b: Uint8Array, off: number): number {
  return ((b[off] | (b[off + 1] << 8) | (b[off + 2] << 16) | (b[off + 3] << 24)) >>> 0);
}

function writeU32le(b: Uint8Array, off: number, v: number): void {
  b[off] = v & 0xff;
  b[off + 1] = (v >>> 8) & 0xff;
  b[off + 2] = (v >>> 16) & 0xff;
  b[off + 3] = (v >>> 24) & 0xff;
}

/** u64 长度字段按小端写入（P6：u64 一律 BigInt）。 */
function writeU64le(b: Uint8Array, off: number, v: bigint): void {
  let x: bigint = v;
  for (let i: number = 0; i < 8; i += 1) {
    b[off + i] = Number(x & 0xffn);
    x >>= 8n;
  }
}

function rotl32(v: number, n: number): number {
  return ((v << n) | (v >>> (32 - n))) >>> 0;
}

/** RFC 8439 §2.1.1 quarter round，原地修改 s。 */
function quarterRound(s: number[], a: number, b: number, c: number, d: number): void {
  s[a] = (s[a] + s[b]) >>> 0;
  s[d] = rotl32(s[d] ^ s[a], 16);
  s[c] = (s[c] + s[d]) >>> 0;
  s[b] = rotl32(s[b] ^ s[c], 12);
  s[a] = (s[a] + s[b]) >>> 0;
  s[d] = rotl32(s[d] ^ s[a], 8);
  s[c] = (s[c] + s[d]) >>> 0;
  s[b] = rotl32(s[b] ^ s[c], 7);
}

/**
 * ChaCha20 块函数（RFC 8439 §2.3）：key 32B、counter u32、nonce 12B → 64B keystream。
 * 返回新数组。内部导出供测试直接对照 RFC §2.3.2 与 node:crypto('chacha20')。
 */
export function chacha20Block(key: Uint8Array, counter: number, nonce: Uint8Array): Uint8Array {
  const st: number[] = new Array<number>(16);
  for (let i: number = 0; i < 4; i += 1) {
    st[i] = CHACHA_CONST[i];
  }
  for (let i: number = 0; i < 8; i += 1) {
    st[4 + i] = readU32le(key, i * 4);
  }
  st[12] = counter >>> 0;
  st[13] = readU32le(nonce, 0);
  st[14] = readU32le(nonce, 4);
  st[15] = readU32le(nonce, 8);

  const work: number[] = st.slice();
  for (let round: number = 0; round < 10; round += 1) {
    // 列轮
    quarterRound(work, 0, 4, 8, 12);
    quarterRound(work, 1, 5, 9, 13);
    quarterRound(work, 2, 6, 10, 14);
    quarterRound(work, 3, 7, 11, 15);
    // 对角轮
    quarterRound(work, 0, 5, 10, 15);
    quarterRound(work, 1, 6, 11, 12);
    quarterRound(work, 2, 7, 8, 13);
    quarterRound(work, 3, 4, 9, 14);
  }

  const out: Uint8Array = new Uint8Array(64);
  for (let i: number = 0; i < 16; i += 1) {
    writeU32le(out, i * 4, (work[i] + st[i]) >>> 0);
  }
  return out;
}

/**
 * ChaCha20 流加密/解密（XOR）：从 initialCounter 起，按 64B 块推进计数器（u32 回绕）。
 * 返回与 data 等长的新数组（独立拷贝）。
 */
export function chacha20Xor(
  key: Uint8Array,
  initialCounter: number,
  nonce: Uint8Array,
  data: Uint8Array,
): Uint8Array {
  const out: Uint8Array = new Uint8Array(data.length);
  let counter: number = initialCounter >>> 0;
  for (let off: number = 0; off < data.length; off += 64) {
    const ks: Uint8Array = chacha20Block(key, counter, nonce);
    const n: number = Math.min(64, data.length - off);
    for (let i: number = 0; i < n; i += 1) {
      out[off + i] = data[off + i] ^ ks[i];
    }
    counter = (counter + 1) >>> 0;
  }
  return out;
}

/** 小端字节 → BigInt（最多 17 字节）。 */
function decodeLe(b: Uint8Array): bigint {
  let r: bigint = 0n;
  for (let i: number = b.length - 1; i >= 0; i -= 1) {
    r = (r << 8n) | BigInt(b[i]);
  }
  return r;
}

/**
 * Poly1305 MAC（RFC 8439 §2.5）：一次性密钥 32B（r = key[0..16] 经 clamp，s = key[16..32]）。
 * 每个块（含不足 16B 的尾块）后跟 0x01 字节进入多项式累加；结果 = (acc + s) mod 2^128。
 * 返回 16 字节新数组。内部导出供测试对照 RFC §2.5.2。
 */
export function poly1305Mac(key: Uint8Array, msg: Uint8Array): Uint8Array {
  if (key.length !== 32) {
    throw new CryptoError(
      'RANGE',
      'poly1305: key must be 32 bytes, got ' + String(key.length),
    ) as Error;
  }
  // r = clamp(le(key[0..16]))；s = le(key[16..32])
  const r: bigint = decodeLe(key.subarray(0, 16)) & POLY_R_MASK;
  const s: bigint = decodeLe(key.subarray(16, 32));
  let acc: bigint = 0n;
  let off: number = 0;
  while (off < msg.length) {
    const n: number = Math.min(16, msg.length - off);
    // 块缓冲 17 字节：数据后紧跟 0x01 字节（部分块先零填充到 n 位再置 1，
    // 即 0x01 位于下标 n —— RFC 8439 §2.5.1；早前误固定在 16 导致尾块错）。
    const block: Uint8Array = new Uint8Array(17);
    for (let i: number = 0; i < n; i += 1) {
      block[i] = msg[off + i];
    }
    block[n] = 1;
    acc = ((acc + decodeLe(block)) * r) % POLY_P;
    off += n;
  }
  const tagVal: bigint = (acc + s) & ((1n << 128n) - 1n);
  const tag: Uint8Array = new Uint8Array(16);
  let x: bigint = tagVal;
  for (let i: number = 0; i < 16; i += 1) {
    tag[i] = Number(x & 0xffn);
    x >>= 8n;
  }
  return tag;
}

/** pad16：不足 16 倍数补零的字节数。 */
function padLen(n: number): number {
  return n % 16 === 0 ? 0 : 16 - (n % 16);
}

/** AEAD MAC 输入（RFC 8439 §2.8）。 */
function aeadMacData(aad: Uint8Array, ciphertext: Uint8Array): Uint8Array {
  const total: number =
    aad.length + padLen(aad.length) + ciphertext.length + padLen(ciphertext.length) + 16;
  const out: Uint8Array = new Uint8Array(total);
  let off: number = 0;
  out.set(aad, off);
  off += aad.length + padLen(aad.length);
  out.set(ciphertext, off);
  off += ciphertext.length + padLen(ciphertext.length);
  writeU64le(out, off, BigInt(aad.length));
  writeU64le(out, off + 8, BigInt(ciphertext.length));
  return out;
}

function assertAeadKeyNonce(key: Uint8Array, nonce: Uint8Array): void {
  if (key.length !== KEY_LEN_BYTES) {
    throw new CryptoError(
      'RANGE',
      'aead: key must be ' + String(KEY_LEN_BYTES) + ' bytes, got ' + String(key.length),
    ) as Error;
  }
  if (nonce.length !== AEAD_NONCE_LEN_BYTES) {
    throw new CryptoError(
      'RANGE',
      'aead: nonce must be ' + String(AEAD_NONCE_LEN_BYTES) + ' bytes, got ' + String(nonce.length),
    ) as Error;
  }
}

/**
 * AEAD 封装：返回 ciphertext || tag(16B) 的新数组（独立拷贝；不修改任何入参）。
 * key 32B、nonce 12B，不符抛 CryptoError('RANGE')；
 * aad 传零长度数组表示无 AAD；plaintext 允许零长度（keepalive）。
 */
export function aeadSeal(
  key: Uint8Array,
  nonce: Uint8Array,
  plaintext: Uint8Array,
  aad: Uint8Array,
): Uint8Array {
  assertAeadKeyNonce(key, nonce);
  const block0: Uint8Array = chacha20Block(key, 0, nonce);
  const polyKey: Uint8Array = block0.slice(0, 32);
  const ciphertext: Uint8Array = chacha20Xor(key, 1, nonce, plaintext);
  const tag: Uint8Array = poly1305Mac(polyKey, aeadMacData(aad, ciphertext));
  const out: Uint8Array = new Uint8Array(ciphertext.length + AEAD_TAG_LEN_BYTES);
  out.set(ciphertext, 0);
  out.set(tag, ciphertext.length);
  return out;
}

/**
 * AEAD 解封：ciphertextWithTag = ciphertext || tag(16B)。
 * Poly1305 认证失败抛 CryptoError('AUTH')；tag 缺失（长度 < 16）抛 CryptoError('RANGE')。
 * 返回与明文等长的新数组（独立拷贝；不修改入参）。
 */
export function aeadOpen(
  key: Uint8Array,
  nonce: Uint8Array,
  ciphertextWithTag: Uint8Array,
  aad: Uint8Array,
): Uint8Array {
  assertAeadKeyNonce(key, nonce);
  if (ciphertextWithTag.length < AEAD_TAG_LEN_BYTES) {
    throw new CryptoError(
      'RANGE',
      'aead: ciphertextWithTag must be at least ' +
        String(AEAD_TAG_LEN_BYTES) +
        ' bytes, got ' +
        String(ciphertextWithTag.length),
    ) as Error;
  }
  const ctLen: number = ciphertextWithTag.length - AEAD_TAG_LEN_BYTES;
  const ciphertext: Uint8Array = ciphertextWithTag.slice(0, ctLen);
  const tag: Uint8Array = ciphertextWithTag.slice(ctLen);
  const block0: Uint8Array = chacha20Block(key, 0, nonce);
  const polyKey: Uint8Array = block0.slice(0, 32);
  const expected: Uint8Array = poly1305Mac(polyKey, aeadMacData(aad, ciphertext));
  if (!constTimeEqual(expected, tag)) {
    throw new CryptoError('AUTH', 'aead: Poly1305 authentication failed') as Error;
  }
  return chacha20Xor(key, 1, nonce, ciphertext);
}

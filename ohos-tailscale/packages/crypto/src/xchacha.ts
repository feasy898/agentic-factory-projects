/**
 * XChaCha20-Poly1305（draft-irtf-cfrg-xchacha-03）与 HChaCha20 子密钥派生。
 *
 * 上游实读依据（2026-10-01，GPU 机 jsdelivr CDN 拉取，存档于本轮 worklog）：
 * - draft-irtf-cfrg-xchacha-03（datatracker.ietf.org 原文）：HChaCha20 = ChaCha20
 *   状态（常量 4 字 + key 8 字 + nonce16 4 字，置于 s[12..15]）跑满 20 轮、
 *   **不做末态加法**，输出 = s[0..3] ‖ s[12..15] 的 u32le 字节（§2.2.1）；
 *   AEAD 构造：subkey = HChaCha20(key, nonce[0:16])，随后按 RFC 8439 以
 *   nonce12 = 0x00*8 ‖ nonce[16:24] 走标准 ChaCha20-Poly1305（§2.3 / 附录 A.1）。
 * - wireguard-go device/cookie.go：Cookie Reply 的 32B 加密 cookie 用
 *   chacha20poly1305.NewX（即本构造），AAD = 收到报文的 MAC1 字段。
 *
 * 锚定：HChaCha20 示例向量与 AEAD_XCHACHA20_POLY1305 全 KAT 来自该草案原文
 * （§2.2.1 / 附录 A.1），测试写死十六进制；内层 ChaCha20-Poly1305 复用
 * aead.ts（RFC 8439 向量 + node:crypto 交叉验证锚定，见 aead.test.ts）。
 *
 * 密文布局与 aead.ts 一致 = ciphertext ‖ tag(16B)。
 */

import { AEAD_NONCE_LEN_BYTES, AEAD_TAG_LEN_BYTES, KEY_LEN_BYTES } from '@ohos-tailscale/common';
import { aeadOpen, aeadSeal } from './aead.ts';
import { CryptoError } from './errors.ts';

/** RFC 8439 §2.3.2 常量字 "expand 32-byte k" 的 u32le 视图（与 aead.ts 同源）。 */
const CHACHA_CONST: number[] = [0x61707865, 0x3320646e, 0x79622d32, 0x6b206574];

/** XChaCha20 nonce 长度（24B = HChaCha20 的 16B + RFC 8439 段的 8B）。 */
export const XNONCE_LEN_BYTES: number = 24;

function readU32le(b: Uint8Array, off: number): number {
  return ((b[off] | (b[off + 1] << 8) | (b[off + 2] << 16) | (b[off + 3] << 24)) >>> 0);
}

function writeU32le(b: Uint8Array, off: number, v: number): void {
  b[off] = v & 0xff;
  b[off + 1] = (v >>> 8) & 0xff;
  b[off + 2] = (v >>> 16) & 0xff;
  b[off + 3] = (v >>> 24) & 0xff;
}

function rotl32(v: number, n: number): number {
  return ((v << n) | (v >>> (32 - n))) >>> 0;
}

/** RFC 8439 §2.1.1 quarter round（与 aead.ts 同实现，本文件私有副本）。 */
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

function assertLen(b: Uint8Array, want: number, what: string): void {
  if (b.length !== want) {
    throw new CryptoError(
      'RANGE',
      'xchacha: ' + what + ' must be ' + String(want) + ' bytes, got ' + String(b.length),
    ) as Error;
  }
}

/**
 * HChaCha20（draft-irtf-cfrg-xchacha-03 §2.2.1）：key 32B、nonce 16B → 子密钥 32B。
 * 状态 = 常量 4 字 ‖ key 8 字 ‖ nonce16 4 字；20 轮后**不做末态加法**，
 * 输出 = s[0..3] ‖ s[12..15] 逐字 u32le。返回 32B 新数组。
 */
export function hchacha20(key: Uint8Array, nonce16: Uint8Array): Uint8Array {
  assertLen(key, KEY_LEN_BYTES, 'key');
  assertLen(nonce16, 16, 'nonce16');
  const st: number[] = new Array<number>(16);
  for (let i: number = 0; i < 4; i += 1) {
    st[i] = CHACHA_CONST[i];
  }
  for (let i: number = 0; i < 8; i += 1) {
    st[4 + i] = readU32le(key, i * 4);
  }
  for (let i: number = 0; i < 4; i += 1) {
    st[12 + i] = readU32le(nonce16, i * 4);
  }

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

  // 无末态加法：仅取首行（s[0..3]）与末行（s[12..15]）。
  const out: Uint8Array = new Uint8Array(32);
  for (let i: number = 0; i < 4; i += 1) {
    writeU32le(out, i * 4, work[i] >>> 0);
    writeU32le(out, 16 + i * 4, work[12 + i] >>> 0);
  }
  return out;
}

/** 由 24B nonce 派生内层 RFC 8439 的 12B nonce：0x00*4 ‖ nonce[16:24]（草案 §2.3 的 32-bit fixed-common part）。 */
function innerNonce(nonce24: Uint8Array): Uint8Array {
  const nonce12: Uint8Array = new Uint8Array(AEAD_NONCE_LEN_BYTES);
  nonce12.set(nonce24.slice(16, 24), 4);
  return nonce12;
}

/**
 * XChaCha20-Poly1305 封装（draft-irtf-cfrg-xchacha-03 §2.3）：
 * subkey = HChaCha20(key, nonce[0:16])，随后按 RFC 8439 AEAD（nonce12 =
 * 0x00*8 ‖ nonce[16:24]）封装。返回 ciphertext ‖ tag(16B) 新数组（独立拷贝）。
 * key 32B、nonce 24B，不符抛 CryptoError('RANGE')；plaintext 允许零长度。
 */
export function xchacha20poly1305Seal(
  key: Uint8Array,
  nonce: Uint8Array,
  plaintext: Uint8Array,
  aad: Uint8Array,
): Uint8Array {
  assertLen(key, KEY_LEN_BYTES, 'key');
  assertLen(nonce, XNONCE_LEN_BYTES, 'nonce');
  const subkey: Uint8Array = hchacha20(key, nonce.slice(0, 16));
  return aeadSeal(subkey, innerNonce(nonce), plaintext, aad);
}

/**
 * XChaCha20-Poly1305 解封：sealed = ciphertext ‖ tag(16B)。
 * 认证失败抛 CryptoError('AUTH')（与 aeadOpen 语义一致）。
 * 返回与明文等长的新数组（独立拷贝；不修改入参）。
 */
export function xchacha20poly1305Open(
  key: Uint8Array,
  nonce: Uint8Array,
  sealed: Uint8Array,
  aad: Uint8Array,
): Uint8Array {
  assertLen(key, KEY_LEN_BYTES, 'key');
  assertLen(nonce, XNONCE_LEN_BYTES, 'nonce');
  if (sealed.length < AEAD_TAG_LEN_BYTES) {
    throw new CryptoError(
      'RANGE',
      'xchacha: sealed must be at least ' +
        String(AEAD_TAG_LEN_BYTES) +
        ' bytes, got ' +
        String(sealed.length),
    ) as Error;
  }
  const subkey: Uint8Array = hchacha20(key, nonce.slice(0, 16));
  return aeadOpen(subkey, innerNonce(nonce), sealed, aad);
}

/**
 * 测试专用：Noise IK 握手（ts2021/controlbase 口味）的**独立参考实现** —— 直接用
 * node:crypto 原语（createHash('blake2s256')、createHmac('blake2s256')、X25519 JWK DH、
 * chacha20-poly1305）从协议序列逐步展开，与 src/ 实现（走 @ohos-tailscale/crypto 原语）
 * 无共享代码，用于交叉验证握手字节向量。已用公开 cacophony 已知答案向量
 * （Noise_IK_25519_ChaChaPoly_BLAKE2s）整链验证：本文件展开顺序可逐字节复现该向量的
 * msg A/msg B/握手哈希（见 external-vector.test.ts 的向量锚定测试）。
 *
 * 本文件为 *.test.ts（评审裁定：node:crypto 只允许出现在 *.test.ts —— architecture.md
 * §4.1 口径与 §3.3 门禁的 test 通配 override），因此把原 test 辅助文件
 * reference.ts 并入 *.test.ts 命名范围；本文件不注册用例（避免被其他测试文件
 * import 时重复注册），参考栈自身的对照自检见 handshake.test.ts 的「参考栈自检」组。
 */

import {
  createCipheriv,
  createDecipheriv,
  createHash,
  createHmac,
  createPrivateKey,
  createPublicKey,
  diffieHellman,
  webcrypto,
  type KeyObject,
} from 'node:crypto';
import { base64UrlEncode, utf8Encode } from '@ohos-tailscale/common';
import { NOISE_PROTOCOL_NAME } from '../src/handshake.ts';

/** 握手层 EncryptAndHash 的固定 nonce（n=0 → 12B 全零；每令牌一次性密钥，controlbase singleUseCHP 同型）。 */
export const ZERO_NONCE: Uint8Array = new Uint8Array(12);

/** 参考实现所需的全套固定密钥（原始 32B 标量/公钥；临时私钥允许未 clamp，node 侧 X25519 自行 clamp）。 */
export interface RefKeys {
  iStaticPriv: Uint8Array;
  iStaticPub: Uint8Array;
  rStaticPriv: Uint8Array;
  rStaticPub: Uint8Array;
  iEphPriv: Uint8Array;
  iEphPub: Uint8Array;
  rEphPriv: Uint8Array;
  rEphPub: Uint8Array;
}

/** 参考握手输出：两条线上消息 + split 出的两个方向传输键。 */
export interface RefHandshakeResult {
  msgA: Uint8Array;
  msgB: Uint8Array;
  /** k1：initiator → responder 方向发送键。 */
  iToSend: Uint8Array;
  /** k2：responder → initiator 方向发送键。 */
  iToRecv: Uint8Array;
}

export function concat2(a: Uint8Array, b: Uint8Array): Uint8Array {
  const out: Uint8Array = new Uint8Array(a.length + b.length);
  out.set(a, 0);
  out.set(b, a.length);
  return out;
}

export function concat3(a: Uint8Array, b: Uint8Array, c: Uint8Array): Uint8Array {
  return concat2(concat2(a, b), c);
}

/** u16 大端前缀（帧头）。 */
export function u16beBytes(len: number): Uint8Array {
  const out: Uint8Array = new Uint8Array(2);
  out[0] = (len >> 8) & 0xff;
  out[1] = len & 0xff;
  return out;
}

/** node blake2s256 摘要（导出仅供 handshake.test.ts 的「参考栈自检」组对照）。 */
export function blake2s(data: Uint8Array): Uint8Array {
  return new Uint8Array(createHash('blake2s256').update(data).digest());
}

function hmacBlk(key: Uint8Array, data: Uint8Array): Uint8Array {
  return new Uint8Array(createHmac('blake2s256', key).update(data).digest());
}

/**
 * HKDF-HMAC-BLAKE2s 双输出（controlbase MixDH 形：ck = out1，令牌密钥 = out2；
 * RFC 5869 链式展开，与 x/crypto/hkdf 流的前两块一致）。
 */
export function kdf2(ck: Uint8Array, ikm: Uint8Array): Uint8Array[] {
  const prk: Uint8Array = hmacBlk(ck, ikm);
  const t1: Uint8Array = hmacBlk(prk, Uint8Array.of(1));
  const t2: Uint8Array = hmacBlk(prk, concat2(t1, Uint8Array.of(2)));
  const out: Uint8Array[] = [t1, t2];
  return out;
}

/** JWK 用 base64url（去 '=' 填充）。 */
function b64url(raw: Uint8Array): string {
  const padded: string = base64UrlEncode(raw);
  let end: number = padded.length;
  while (end > 0 && padded.charAt(end - 1) === '=') {
    end -= 1;
  }
  return padded.slice(0, end);
}

function jwkPrivate(priv: Uint8Array, pub: Uint8Array): KeyObject {
  const jwk: webcrypto.JsonWebKey = { kty: 'OKP', crv: 'X25519', x: b64url(pub), d: b64url(priv) };
  return createPrivateKey({ key: jwk, format: 'jwk' });
}

function jwkPublic(pub: Uint8Array): KeyObject {
  const jwk: webcrypto.JsonWebKey = { kty: 'OKP', crv: 'X25519', x: b64url(pub) };
  return createPublicKey({ key: jwk, format: 'jwk' });
}

/** X25519 DH（node 原生；标量按 RFC 7748 内部 clamp）。 */
export function dh(priv: Uint8Array, pub: Uint8Array, ownPub: Uint8Array): Uint8Array {
  return new Uint8Array(diffieHellman({ privateKey: jwkPrivate(priv, ownPub), publicKey: jwkPublic(pub) }));
}

/** node ChaCha20-Poly1305 封装，返回 ciphertext || tag(16B)。 */
export function aeadSealRef(key: Uint8Array, nonce: Uint8Array, plaintext: Uint8Array, aad: Uint8Array): Uint8Array {
  const cipher = createCipheriv('chacha20-poly1305', key, nonce, { authTagLength: 16 });
  cipher.setAAD(aad);
  const ct: Uint8Array = new Uint8Array(cipher.update(plaintext));
  const tail: Uint8Array = new Uint8Array(cipher.final());
  const tag: Uint8Array = new Uint8Array(cipher.getAuthTag());
  return concat3(ct, tail, tag);
}

/** node ChaCha20-Poly1305 解封（测试内往返用）。 */
export function aeadOpenRef(key: Uint8Array, nonce: Uint8Array, sealed: Uint8Array, aad: Uint8Array): Uint8Array {
  const tag: Uint8Array = sealed.slice(sealed.length - 16);
  const ct: Uint8Array = sealed.slice(0, sealed.length - 16);
  const decipher = createDecipheriv('chacha20-poly1305', key, nonce, { authTagLength: 16 });
  decipher.setAAD(aad);
  decipher.setAuthTag(tag);
  const pt1: Uint8Array = new Uint8Array(decipher.update(ct));
  const pt2: Uint8Array = new Uint8Array(decipher.final());
  return concat2(pt1, pt2);
}

/**
 * 完整 IK 参考握手（controlbase 口味）：预消息 `<- s`（prologue 后 MixHash 响应方
 * 静态公钥）→ 逐令牌展开 `-> e, es, s, ss` / `<- e, ee, se`；每个 DH 令牌
 * (ck, k) = HKDF2(ck, DH)（无 temp_h 混入 h），加密块 ad = 当前 h、全零 nonce、
 * 成功后 h = MixHash(密文)。返回两条线上消息与 split 键。
 */
export function referenceHandshake(
  keys: RefKeys,
  prologue: Uint8Array,
  payloadA: Uint8Array,
  payloadB: Uint8Array,
): RefHandshakeResult {
  const name: Uint8Array = utf8Encode(NOISE_PROTOCOL_NAME);
  let h: Uint8Array;
  if (name.length <= 32) {
    h = new Uint8Array(32);
    h.set(name, 0);
  } else {
    h = blake2s(name);
  }
  let ck: Uint8Array = h.slice();
  h = blake2s(concat2(h, prologue));
  h = blake2s(concat2(h, keys.rStaticPub)); // 预消息 <- s（prologue 之后）

  // ---- msg A：-> e, es, s, ss ----
  h = blake2s(concat2(h, keys.iEphPub)); // e
  const kdfEs: Uint8Array[] = kdf2(ck, dh(keys.iEphPriv, keys.rStaticPub, keys.iEphPub)); // es
  ck = kdfEs[0];
  const encStatic: Uint8Array = aeadSealRef(kdfEs[1], ZERO_NONCE, keys.iStaticPub, h); // s
  h = blake2s(concat2(h, encStatic));
  const kdfSs: Uint8Array[] = kdf2(ck, dh(keys.iStaticPriv, keys.rStaticPub, keys.iStaticPub)); // ss
  ck = kdfSs[0];
  const encPayloadA: Uint8Array = aeadSealRef(kdfSs[1], ZERO_NONCE, payloadA, h);
  h = blake2s(concat2(h, encPayloadA));
  const msgA: Uint8Array = concat3(keys.iEphPub, encStatic, encPayloadA);

  // ---- msg B：<- e, ee, se ----
  h = blake2s(concat2(h, keys.rEphPub)); // e
  const kdfEe: Uint8Array[] = kdf2(ck, dh(keys.rEphPriv, keys.iEphPub, keys.rEphPub)); // ee
  ck = kdfEe[0];
  const kdfSe: Uint8Array[] = kdf2(ck, dh(keys.rEphPriv, keys.iStaticPub, keys.rEphPub)); // se
  ck = kdfSe[0];
  const encPayloadB: Uint8Array = aeadSealRef(kdfSe[1], ZERO_NONCE, payloadB, h);
  h = blake2s(concat2(h, encPayloadB));
  const msgB: Uint8Array = concat2(keys.rEphPub, encPayloadB);

  // ---- Split：HKDF(ck, 空, 2) ----
  const split: Uint8Array[] = kdf2(ck, new Uint8Array(0));
  const result: RefHandshakeResult = { msgA: msgA, msgB: msgB, iToSend: split[0], iToRecv: split[1] };
  return result;
}

/**
 * 契约 §6 传输 nonce：4B 零 || BE64(counter)。
 * 已实读核实：真实 tailscale controlbase conn.go 的 nonce.Increment() 为
 * BE64 计数器（与现行 Noise 规范 §12.3 的 LE64 不同，controlbase 刻意为之）。
 */
export function refNonce(counter: bigint): Uint8Array {
  const n: Uint8Array = new Uint8Array(12);
  let x: bigint = counter;
  for (let i: number = 11; i >= 4; i -= 1) {
    n[i] = Number(x & 0xffn);
    x >>= 8n;
  }
  return n;
}

/** 参考传输加密：counter 编码的 nonce + 空 AAD。 */
export function refTransportSeal(key: Uint8Array, counter: bigint, plaintext: Uint8Array): Uint8Array {
  return aeadSealRef(key, refNonce(counter), plaintext, new Uint8Array(0));
}

/**
 * disco 密封包装层（UDP 包级）：magic ‖ 发送端 disco 公钥 ‖ nonce ‖ secretbox。
 *
 * 上游实读依据（2026-10-01 实拉，与本文件逐项对应）：
 * - tailscale disco/disco.go 文件头注：wrapper = magic[6] "TS💬" ‖
 *   senderDiscoPub[32] ‖ nonce[24]，其后为 nacl box（即 nacl/secretbox，
 *   XSalsa20-Poly1305，MAC 输入密文，tag 前置）。
 * - types/key/disco.go：DiscoPrivate.Shared(p) = box.Precompute(peerPub, myPriv)
 *   （curve25519 + HSalsa20 折叠，零输入）；DiscoShared.Seal = 随机 24B nonce 的
 *   box.SealAfterPrecomputation（输出 = tag ‖ 密文，nonce 不重复内嵌——wrapper
 *   头已带 nonce）。DiscoPrivate 生成时即 clamp（本仓 crypto 的 X25519 在
 *   scalarMult 内 clamp，语义一致）。
 * - LooksLikeDiscoWrapper / Source：长度 ≥ 6+32+24 且 magic 匹配；Source 取
 *   wrapper[6:38]。
 *
 * 密封原语复用 crypto 包（naclboxSharedKey / salsa20Poly1305Seal/Open），该层已与
 * tweetnacl 逐字节互验（crypto/test/naclbox.test.ts）；本包测试再做一次
 * tweetnacl 端到端互开互验（wrapper.test.ts）。
 *
 * P4：nonce 由调用方注入（Rng 生成），本模块不自取随机。
 */

import { KEY_LEN_BYTES, utf8Encode } from '@ohos-tailscale/common';
import {
  naclboxSharedKey,
  salsa20Poly1305Open,
  salsa20Poly1305Seal,
  x25519PublicKeyFromPrivate,
} from '@ohos-tailscale/crypto';
import { DiscoError } from './errors.ts';

/** 所有 disco 消息的 6B 头 "TS💬"（上游 disco.Magic，0x54 53 f0 9f 92 ac）。 */
export const DISCO_MAGIC: Uint8Array = utf8Encode('TS\u{1F4AC}');

/** disco nonce 长度（上游 NonceLen = 24）。 */
export const DISCO_NONCE_LEN_BYTES: number = 24;

/** wrapper 头长 = magic 6 + senderPub 32 + nonce 24。 */
const WRAPPER_HEADER_LEN: number = DISCO_MAGIC.length + KEY_LEN_BYTES + DISCO_NONCE_LEN_BYTES;

/** disco 共享密钥：box.Precompute 语义（HSalsa20(X25519(myPriv, peerPub), 0)）。 */
export function discoSharedKey(myPrivate: Uint8Array, peerPublic: Uint8Array): Uint8Array {
  if (myPrivate.length !== KEY_LEN_BYTES) {
    throw new DiscoError(
      'RANGE',
      'disco shared key: private must be 32 bytes, got ' + String(myPrivate.length),
    ) as Error;
  }
  if (peerPublic.length !== KEY_LEN_BYTES) {
    throw new DiscoError(
      'RANGE',
      'disco shared key: peer public must be 32 bytes, got ' + String(peerPublic.length),
    ) as Error;
  }
  return naclboxSharedKey(myPrivate, peerPublic);
}

/** 判定 p 是否形似 disco wrapper（上游 LooksLikeDiscoWrapper）。 */
export function looksLikeDisco(p: Uint8Array): boolean {
  if (p.length < WRAPPER_HEADER_LEN) {
    return false;
  }
  for (let i: number = 0; i < DISCO_MAGIC.length; i += 1) {
    if (p[i] !== DISCO_MAGIC[i]) {
      return false;
    }
  }
  return true;
}

/** 取 wrapper 的发送端 disco 公钥（上游 Source）；非 wrapper 返回 null。返回拷贝。 */
export function discoSource(p: Uint8Array): Uint8Array | null {
  if (!looksLikeDisco(p)) {
    return null;
  }
  return p.slice(DISCO_MAGIC.length, DISCO_MAGIC.length + KEY_LEN_BYTES);
}

/** 密封结果载体（ArkTS 无元组，用 interface）。 */
export interface DiscoSealed {
  /** 完整 UDP 载荷：magic ‖ 本端公钥 ‖ nonce ‖ tag‖密文。 */
  wrapper: Uint8Array;
}

/**
 * 密封一条内层报文（先 pingEncode 等编码，再本函数包装）。
 * nonce24 由调用方生成注入（P4）。返回 DiscoSealed。
 * 键长不符抛 DiscoError('RANGE')；inner 允许任意长度（≥2B 由消息层自检）。
 */
export function discoSeal(
  inner: Uint8Array,
  myPrivate: Uint8Array,
  peerPublic: Uint8Array,
  nonce24: Uint8Array,
): DiscoSealed {
  if (nonce24.length !== DISCO_NONCE_LEN_BYTES) {
    throw new DiscoError(
      'RANGE',
      'disco seal: nonce must be ' + String(DISCO_NONCE_LEN_BYTES) + ' bytes, got ' + String(nonce24.length),
    ) as Error;
  }
  const shared: Uint8Array = discoSharedKey(myPrivate, peerPublic);
  const myPublic: Uint8Array = x25519PublicKeyFromPrivate(myPrivate);
  const boxOut: Uint8Array = salsa20Poly1305Seal(shared, nonce24, inner);
  const wrapper: Uint8Array = new Uint8Array(WRAPPER_HEADER_LEN + boxOut.length);
  wrapper.set(DISCO_MAGIC, 0);
  wrapper.set(myPublic, DISCO_MAGIC.length);
  wrapper.set(nonce24, DISCO_MAGIC.length + KEY_LEN_BYTES);
  wrapper.set(boxOut, WRAPPER_HEADER_LEN);
  const out: DiscoSealed = { wrapper: wrapper };
  return out;
}

/** 解封结果载体。 */
export interface DiscoUnsealed {
  /** 发送端 disco 公钥（独立拷贝）。 */
  senderPublic: Uint8Array;
  /** 解密后的内层报文（type+ver+payload，独立拷贝）。 */
  message: Uint8Array;
}

/**
 * 解封一条 disco wrapper：按 wrapper 内的发送端公钥派生共享密钥并解密。
 * 非 wrapper 形态 / 认证失败（键不符或密文被改）→ null（上游 Open 返回 !ok）。
 */
export function discoOpen(wrapper: Uint8Array, myPrivate: Uint8Array): DiscoUnsealed | null {
  if (!looksLikeDisco(wrapper)) {
    return null;
  }
  if (myPrivate.length !== KEY_LEN_BYTES) {
    throw new DiscoError(
      'RANGE',
      'disco open: private must be 32 bytes, got ' + String(myPrivate.length),
    ) as Error;
  }
  const senderPublic: Uint8Array = wrapper.slice(DISCO_MAGIC.length, DISCO_MAGIC.length + KEY_LEN_BYTES);
  const nonce: Uint8Array = wrapper.slice(
    DISCO_MAGIC.length + KEY_LEN_BYTES,
    DISCO_MAGIC.length + KEY_LEN_BYTES + DISCO_NONCE_LEN_BYTES,
  );
  const sealed: Uint8Array = wrapper.slice(WRAPPER_HEADER_LEN);
  const shared: Uint8Array = discoSharedKey(myPrivate, senderPublic);
  const opened: Uint8Array | null = salsa20Poly1305Open(shared, nonce, sealed);
  if (opened === null) {
    return null;
  }
  const out: DiscoUnsealed = { senderPublic: senderPublic, message: opened };
  return out;
}

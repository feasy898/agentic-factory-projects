/**
 * XChaCha20-Poly1305 / HChaCha20 测试。
 *
 * 锚定来源（2026-10-01 实拉原文）：
 * - draft-irtf-cfrg-xchacha-03（datatracker.ietf.org/doc/html/draft-irtf-cfrg-xchacha-03.txt）：
 *   §2.2.1 HChaCha20 示例向量、附录 A.1 AEAD_XCHACHA20_POLY1305 全 KAT
 *   （"Ladies and Gentlemen…" 明文 + AAD + Key80..9f + IV 40..57）。
 * - 结构性等价断言：xchachaSeal(key,nonce,…) 必须逐字节等于
 *   aeadSeal(hchacha20(key,nonce[0:16]), 00*8‖nonce[16:24], …)（内层复用已锚定的
 *   RFC 8439 实现；node:crypto 交叉验证在 aead.test.ts，不在本文件重复）。
 */

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { hexDecode, hexEncode } from '@ohos-tailscale/common';
import { aeadSeal, aeadOpen } from '../src/aead.ts';
import {
  hchacha20,
  xchacha20poly1305Open,
  xchacha20poly1305Seal,
} from '../src/xchacha.ts';
import { CryptoError } from '../src/errors.ts';

/** draft-irtf-cfrg-xchacha-03 §2.2.1：key = 00 01 … 1f，nonce16 = 00000009 0000004a 00000000 31415927。 */
const H_KEY: Uint8Array = hexDecode(
  '000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f',
);
const H_NONCE: Uint8Array = hexDecode('000000090000004a0000000031415927');
/** 草案原文 "Resultant HChaCha20 subkey"。 */
const H_SUBKEY: string = '82413b4227b27bfed30e42508a877d73a0f9e4d58a74a853c12ec41326d3ecdc';

test('HChaCha20：draft-irtf-cfrg-xchacha-03 §2.2.1 示例向量', () => {
  const subkey: Uint8Array = hchacha20(H_KEY, H_NONCE);
  assert.equal(subkey.length, 32);
  assert.equal(hexEncode(subkey), H_SUBKEY);
});

/** 附录 A.1 的 Key（80..9f）与 IV（40 41..4f 50 51..57）。 */
const AE_KEY: Uint8Array = hexDecode(
  '808182838485868788898a8b8c8d8e8f909192939495969798999a9b9c9d9e9f',
);
const AE_NONCE: Uint8Array = hexDecode('404142434445464748494a4b4c4d4e4f5051525354555657');
const AE_AAD: Uint8Array = hexDecode('50515253c0c1c2c3c4c5c6c7');
const AE_PLAINTEXT: Uint8Array = hexDecode(
  '4c616469657320616e642047656e746c656d656e206f662074686520636c6173' +
    '73206f66202739393a204966204920636f756c64206f6666657220796f75206f' +
    '6e6c79206f6e652074697020666f7220746865206675747572652c2073756e73' +
    '637265656e20776f756c642062652069742e',
);
/** 附录 A.1 Ciphertext（114B）+ Tag（16B，c0875924…cf49）。 */
const AE_SEALED: string =
  'bd6d179d3e83d43b9576579493c0e939572a1700252bfaccbed2902c21396cbb' +
  '731c7f1b0b4aa6440bf3a82f4eda7e39ae64c6708c54c216cb96b72e1213b452' +
  '2f8c9ba40db5d945b11b69b982c1bb9e3f3fac2bc369488f76b2383565d3fff9' +
  '21f9664c97637da9768812f615c68b13b52e' +
  'c0875924c1c7987947deafd8780acf49';

test('XChaCha20-Poly1305：附录 A.1 全 KAT（seal）', () => {
  const sealed: Uint8Array = xchacha20poly1305Seal(AE_KEY, AE_NONCE, AE_PLAINTEXT, AE_AAD);
  assert.equal(sealed.length, AE_PLAINTEXT.length + 16);
  assert.equal(hexEncode(sealed), AE_SEALED);
});

test('XChaCha20-Poly1305：附录 A.1 全 KAT（open 回明文）', () => {
  const sealed: Uint8Array = hexDecode(AE_SEALED);
  const pt: Uint8Array = xchacha20poly1305Open(AE_KEY, AE_NONCE, sealed, AE_AAD);
  assert.deepEqual(Array.from(pt), Array.from(AE_PLAINTEXT));
});

test('XChaCha20-Poly1305：与内层 RFC 8439 构造逐字节等价（结构性锚）', () => {
  const pt: Uint8Array = new Uint8Array(37);
  for (let i: number = 0; i < 37; i += 1) {
    pt[i] = (i * 7 + 3) & 0xff;
  }
  const aad: Uint8Array = hexDecode('aabbcc');
  const direct: Uint8Array = xchacha20poly1305Seal(AE_KEY, AE_NONCE, pt, aad);
  // 等价构造：subkey = hchacha20(key, nonce[0:16])，nonce12 = 00*4 ‖ nonce[16:24]
  const subkey: Uint8Array = hchacha20(AE_KEY, AE_NONCE.slice(0, 16));
  const nonce12: Uint8Array = new Uint8Array(12);
  nonce12.set(AE_NONCE.slice(16, 24), 4);
  const composed: Uint8Array = aeadSeal(subkey, nonce12, pt, aad);
  assert.equal(hexEncode(direct), hexEncode(composed));
  const opened: Uint8Array = aeadOpen(subkey, nonce12, direct, aad);
  assert.deepEqual(Array.from(opened), Array.from(pt));
});

test('XChaCha20-Poly1305：AAD 不符抛 CryptoError(AUTH)；入参不被修改', () => {
  const sealed: Uint8Array = xchacha20poly1305Seal(AE_KEY, AE_NONCE, AE_PLAINTEXT, AE_AAD);
  const badAad: Uint8Array = AE_AAD.slice();
  badAad[0] ^= 0x01;
  const keyCopy: Uint8Array = AE_KEY.slice();
  const nonceCopy: Uint8Array = AE_NONCE.slice();
  assert.throws(
    (): void => {
      xchacha20poly1305Open(keyCopy, nonceCopy, sealed, badAad);
    },
    (e: unknown): boolean => e instanceof CryptoError && e.code === 'AUTH',
  );
  assert.deepEqual(Array.from(keyCopy), Array.from(AE_KEY));
  assert.deepEqual(Array.from(nonceCopy), Array.from(AE_NONCE));
});

test('XChaCha20-Poly1305：零长明文 + 长度校验（RANGE）', () => {
  const empty: Uint8Array = new Uint8Array(0);
  const sealed: Uint8Array = xchacha20poly1305Seal(AE_KEY, AE_NONCE, empty, AE_AAD);
  assert.equal(sealed.length, 16);
  const opened: Uint8Array = xchacha20poly1305Open(AE_KEY, AE_NONCE, sealed, AE_AAD);
  assert.equal(opened.length, 0);
  assert.throws(
    (): void => {
      xchacha20poly1305Seal(AE_KEY, AE_NONCE.slice(0, 12), empty, AE_AAD);
    },
    (e: unknown): boolean => e instanceof CryptoError && e.code === 'RANGE',
  );
});

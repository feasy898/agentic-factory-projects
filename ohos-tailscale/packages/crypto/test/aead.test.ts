/**
 * ChaCha20-Poly1305 AEAD 测试（RFC 8439）：
 * - §2.8.2 完整 AEAD 向量（密文||tag 布局）；
 * - §2.3.2 块函数向量 + 与 node:crypto('chacha20') 跨计数器/跨块 keystream 交叉；
 * - §2.5.2 Poly1305 向量；
 * - aeadSeal/aeadOpen 与 node:crypto('chacha20-poly1305') 多长度交叉；
 * - 篡改任意 1 bit → CryptoError('AUTH')；长度违规 → CryptoError('RANGE')。
 *
 * 向量来源：RFC 8439 原文（rfc-editor.org）。凡 node:crypto 可对照之处均实时对照；
 * 若记忆向量与 node:crypto 冲突，以 node:crypto 为准（本次落盘向量已核对一致）。
 */

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createCipheriv, createDecipheriv } from 'node:crypto';
import { hexDecode, hexEncode, utf8Encode } from '@ohos-tailscale/common';
import { aeadOpen, aeadSeal, chacha20Block, chacha20Xor, poly1305Mac } from '../src/aead.ts';
import { CryptoError } from '../src/errors.ts';

// RFC 8439 §2.8.2
const RFC_KEY: string = '808182838485868788898a8b8c8d8e8f909192939495969798999a9b9c9d9e9f';
const RFC_NONCE: string = '070000004041424344454647';
const RFC_AAD: string = '50515253c0c1c2c3c4c5c6c7';
const RFC_AAD_LEN: number = 12;
const RFC_CT: string =
  'd31a8d34648e60db7b86afbc53ef7ec2a4aded51296e08fea9e2b5a736ee62d6' +
  '3dbea45e8ca9671282fafb69da92728b1a71de0a9e060b2905d6a5b67ecd3b36' +
  '92ddbd7f2d778b8c9803aee328091b58fab324e4fad675945585808b4831d7bc' +
  '3ff4def08e4b7a9de576d26586cec64b6116';
const RFC_TAG: string = '1ae10b594f09e26a7e902ecbd0600691';

// RFC 8439 §2.3.2 块函数向量
const BLOCK_KEY: string = '000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f';
const BLOCK_NONCE: string = '000000090000004a00000000';
const BLOCK_COUNTER: number = 1;
const BLOCK_OUT: string =
  '10f1e7e4d13b5915500fdd1fa32071c4' +
  'c7d1f4c733c068030422aa9ac3d46c4e' +
  'd2826446079faa0914c2d705d98b02a2' +
  'b5129cd1de164eb9cbd083e8a2503c4e';

// RFC 8439 §2.5.2 Poly1305 向量
const POLY_KEY: string = '85d6be7857556d337f4452fe42d506a80103808afb0db2fd4abff6af4149f51b';
const POLY_MSG: string = 'Cryptographic Forum Research Group';
const POLY_TAG: string = 'a8061dc1305136c6c22b8baf0c0127a9';

/** 确定性字节序列（长度任意）。 */
const seqBytes = (n: number, seed: number): Uint8Array => {
  const out: Uint8Array = new Uint8Array(n);
  for (let i: number = 0; i < n; i += 1) {
    out[i] = (seed + i * 31) % 256;
  }
  return out;
};

const concatBytes = (a: Uint8Array, b: Uint8Array): Uint8Array => {
  const out: Uint8Array = new Uint8Array(a.length + b.length);
  out.set(a, 0);
  out.set(b, a.length);
  return out;
};

/** 翻转第 index 字节的第 bit 位，返回拷贝。 */
const flipBit = (src: Uint8Array, index: number, bit: number): Uint8Array => {
  const out: Uint8Array = src.slice();
  out[index] = out[index] ^ (1 << bit);
  return out;
};

/** node:crypto 封装：返回 ciphertext || tag。 */
const nodeSeal = (key: Uint8Array, nonce: Uint8Array, pt: Uint8Array, aad: Uint8Array): Uint8Array => {
  const cipher = createCipheriv('chacha20-poly1305', key, nonce, { authTagLength: 16 });
  cipher.setAAD(aad);
  const ct: Uint8Array = new Uint8Array(cipher.update(pt));
  const tail: Uint8Array = new Uint8Array(cipher.final());
  const tag: Uint8Array = new Uint8Array(cipher.getAuthTag());
  return concatBytes(concatBytes(ct, tail), tag);
};

/** node:crypto 解封：失败抛错。 */
const nodeOpen = (key: Uint8Array, nonce: Uint8Array, ctWithTag: Uint8Array, aad: Uint8Array): Uint8Array => {
  const tag: Uint8Array = ctWithTag.slice(ctWithTag.length - 16);
  const ct: Uint8Array = ctWithTag.slice(0, ctWithTag.length - 16);
  const decipher = createDecipheriv('chacha20-poly1305', key, nonce, { authTagLength: 16 });
  decipher.setAAD(aad);
  decipher.setAuthTag(tag);
  const pt1: Uint8Array = new Uint8Array(decipher.update(ct));
  const pt2: Uint8Array = new Uint8Array(decipher.final());
  return concatBytes(pt1, pt2);
};

/** 断言 fn 抛出指定 code 的 CryptoError。 */
const assertCryptoError = (fn: () => void, code: string): void => {
  let thrown: boolean = false;
  let gotCode: string = '';
  try {
    fn();
  } catch (e) {
    thrown = true;
    const err: CryptoError = e as CryptoError;
    gotCode = err.code;
  }
  assert.equal(thrown, true, 'expected CryptoError not thrown');
  assert.equal(gotCode, code, 'unexpected CryptoError code');
};

test('RFC 8439 §2.8.2 AEAD 完整向量（密文||tag）+ node:crypto 对照', () => {
  const key: Uint8Array = hexDecode(RFC_KEY);
  const nonce: Uint8Array = hexDecode(RFC_NONCE);
  const aad: Uint8Array = hexDecode(RFC_AAD);
  const pt: Uint8Array = utf8Encode(
    "Ladies and Gentlemen of the class of '99: If I could offer you only one tip for the future, sunscreen would be it.",
  );
  const sealed: Uint8Array = aeadSeal(key, nonce, pt, aad);
  assert.equal(sealed.length, pt.length + 16);
  assert.equal(hexEncode(sealed.slice(0, pt.length)), RFC_CT, 'ciphertext mismatch');
  assert.equal(hexEncode(sealed.slice(pt.length)), RFC_TAG, 'tag mismatch');
  // node:crypto 对照
  assert.deepEqual(sealed, nodeSeal(key, nonce, pt, aad), 'mismatch vs node:crypto seal');
  // node 封 → 我解
  assert.deepEqual(aeadOpen(key, nonce, nodeSeal(key, nonce, pt, aad), aad), pt);
  // 我封 → node 解
  assert.deepEqual(nodeOpen(key, nonce, sealed, aad), pt);
  // 自封自解
  assert.deepEqual(aeadOpen(key, nonce, sealed, aad), pt);
});

test('RFC 8439 §2.3.2 块函数向量', () => {
  const ks: Uint8Array = chacha20Block(hexDecode(BLOCK_KEY), BLOCK_COUNTER, hexDecode(BLOCK_NONCE));
  assert.equal(ks.length, 64);
  assert.equal(hexEncode(ks), BLOCK_OUT, 'chacha20 block mismatch');
});

test('chacha20 keystream 与 node:crypto("chacha20") 跨计数器/跨块交叉', () => {
  const key: Uint8Array = hexDecode(BLOCK_KEY);
  const nonce: Uint8Array = hexDecode(BLOCK_NONCE);
  const zeros: Uint8Array = new Uint8Array(200); // 跨 4 个 64B 块
  // RFC 8439 §2.8：单消息块数不得超过 2^32，计数器越界行为未定义 ——
  // 实测 OpenSSL 越界后既非 u32 回绕也非进位 nonce，属其私有行为，
  // 故常规计数器全量对照；临界计数器只对照回绕前的首块（规范区域内一致）。
  const counters: number[] = [0, 1, 2, 42, 4294967295];
  for (const counter of counters) {
    // node plain chacha20：16B IV = u32le(counter) || 12B nonce
    const iv: Uint8Array = new Uint8Array(16);
    let c: number = counter;
    for (let i: number = 0; i < 4; i += 1) {
      iv[i] = c & 0xff;
      c = Math.floor(c / 256);
    }
    iv.set(nonce, 4);
    const cipher = createCipheriv('chacha20', key, iv);
    const nodeKs: Uint8Array = new Uint8Array(cipher.update(zeros));
    const mineKs: Uint8Array = chacha20Xor(key, counter, nonce, zeros); // 0 XOR ks = ks
    if (counter <= 4294967295 - 4) {
      assert.deepEqual(mineKs, nodeKs, 'keystream mismatch at counter ' + String(counter));
    } else {
      assert.deepEqual(mineKs.slice(0, 64), nodeKs.slice(0, 64), 'first-block mismatch at counter ' + String(counter));
    }
  }
});

test('RFC 8439 §2.5.2 Poly1305 向量', () => {
  const tag: Uint8Array = poly1305Mac(hexDecode(POLY_KEY), utf8Encode(POLY_MSG));
  assert.equal(hexEncode(tag), POLY_TAG, 'poly1305 tag mismatch');
  assert.equal(poly1305Mac(hexDecode(POLY_KEY), new Uint8Array(0)).length, 16);
});

test('aeadSeal 与 node:crypto 多长度×多AAD交叉 + 往返', () => {
  const key: Uint8Array = seqBytes(32, 1);
  const nonce: Uint8Array = seqBytes(12, 2);
  const ptLens: number[] = [0, 1, 15, 16, 17, 63, 64, 65, 127, 128, 129, 255, 1000];
  const aadLens: number[] = [0, 1, 13, 16, 20];
  for (const ptLen of ptLens) {
    for (const aadLen of aadLens) {
      const pt: Uint8Array = seqBytes(ptLen, ptLen * 3 + 1);
      const aad: Uint8Array = seqBytes(aadLen, aadLen * 5 + 2);
      const sealed: Uint8Array = aeadSeal(key, nonce, pt, aad);
      assert.equal(sealed.length, ptLen + 16);
      assert.deepEqual(sealed, nodeSeal(key, nonce, pt, aad), 'seal mismatch pt=' + String(ptLen) + ' aad=' + String(aadLen));
      assert.deepEqual(aeadOpen(key, nonce, sealed, aad), pt, 'self roundtrip');
      assert.deepEqual(aeadOpen(key, nonce, nodeSeal(key, nonce, pt, aad), aad), pt, 'open node seal');
      assert.deepEqual(nodeOpen(key, nonce, sealed, aad), pt, 'node opens my seal');
    }
  }
});

test('篡改密文/tag/AAD 任意 1 bit → CryptoError(AUTH)', () => {
  const key: Uint8Array = seqBytes(32, 3);
  const nonce: Uint8Array = seqBytes(12, 4);
  const pt: Uint8Array = seqBytes(77, 5);
  const aad: Uint8Array = seqBytes(12, 6);
  const sealed: Uint8Array = aeadSeal(key, nonce, pt, aad);
  const cases: Uint8Array[] = [
    flipBit(sealed, 0, 0),
    flipBit(sealed, 40, 3),
    flipBit(sealed, pt.length - 1, 7),
    flipBit(sealed, pt.length, 0), // tag 第一字节
    flipBit(sealed, sealed.length - 1, 1), // tag 最后一字节
  ];
  for (const bad of cases) {
    assertCryptoError(() => aeadOpen(key, nonce, bad, aad), 'AUTH');
  }
  // AAD 篡改
  assertCryptoError(() => aeadOpen(key, nonce, sealed, flipBit(aad, 0, 0)), 'AUTH');
  // AAD 长度改变
  assertCryptoError(() => aeadOpen(key, nonce, sealed, aad.slice(0, 11)), 'AUTH');
  // 错误密钥（长度正确、内容错误）→ AUTH
  assertCryptoError(() => aeadOpen(seqBytes(32, 7), nonce, sealed, aad), 'AUTH');
  // 空 AAD 与非空 AAD 混用 → AUTH
  assertCryptoError(() => aeadOpen(key, nonce, sealed, new Uint8Array(0)), 'AUTH');
});

test('长度违规 → CryptoError(RANGE)；输出为独立拷贝（R8）', () => {
  const key: Uint8Array = seqBytes(32, 8);
  const nonce: Uint8Array = seqBytes(12, 9);
  const pt: Uint8Array = seqBytes(33, 10);
  assertCryptoError(() => aeadSeal(seqBytes(31, 11), nonce, pt, new Uint8Array(0)), 'RANGE');
  assertCryptoError(() => aeadSeal(key, seqBytes(11, 12), pt, new Uint8Array(0)), 'RANGE');
  assertCryptoError(() => aeadOpen(key, nonce, seqBytes(15, 13), new Uint8Array(0)), 'RANGE');
  // 解封输出不与密文输入共享内存
  const sealed: Uint8Array = aeadSeal(key, nonce, pt, new Uint8Array(0));
  const opened: Uint8Array = aeadOpen(key, nonce, sealed, new Uint8Array(0));
  sealed[0] = (sealed[0] ^ 0xff) & 0xff;
  assert.deepEqual(opened, pt, 'opened plaintext must not alias ciphertext input');
  // 密封输出不与明文输入共享内存
  const ptMut: Uint8Array = pt.slice();
  const sealed2: Uint8Array = aeadSeal(key, nonce, ptMut, new Uint8Array(0));
  ptMut[0] = (ptMut[0] ^ 0xff) & 0xff;
  assert.deepEqual(aeadOpen(key, nonce, sealed2, new Uint8Array(0)), pt, 'sealed output must not alias plaintext input');
});

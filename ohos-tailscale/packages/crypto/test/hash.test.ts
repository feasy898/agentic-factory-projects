/**
 * hash.ts 测试：SHA-256 / HMAC-SHA256 / BLAKE2s-256（无键与键控）/ HMAC-BLAKE2s / HKDF。
 *
 * - SHA-256：FIPS 180-4 式已知向量（空串、"abc"、双块 "abcdbcde…"）+ node:crypto 全长度交叉。
 * - HMAC-SHA256：RFC 4231 TC1/TC2 + node:crypto createHmac 交叉（含长键/空键）。
 * - BLAKE2s256（无键）："69217a30…"（空）与 "508c5e8c…"（"abc"）知名摘要 + node:crypto
 *   createHash('blake2s256') 全长度交叉 + 独立参考（CPython hashlib.blake2s）向量。
 * - 键控 BLAKE2s（node:crypto 无对应 API）：KAT 全部取自独立参考实现 CPython
 *   hashlib.blake2s(key=…) 的运行时输出（与本机 Python 3.12 实测一致），非凭记忆抄写。
 *   其中 key=00..1f、空输入 → 48a8997d… 即官方 blake2-kat 首向量
 *   （注意其 key 是 00 01 … 1f 递增序列；曾误记为全零键，已按参考实现修正）。
 * - HMAC-BLAKE2s：node:crypto createHmac('blake2s256') 原生可用（OpenSSL 提供），
 *   直接交叉验证；若记忆/构造与 node:crypto 冲突，以 node:crypto 为准。
 * - HKDF（kdf2/kdf3）：RFC 5869 TC3（空 salt、空 info）经公开 API 锚定；
 *   其余用 node:crypto 原语在测试内独立展开 HKDF 对照（架构契约 §4.1 的"二次实现"）。
 */

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createHash, createHmac } from 'node:crypto';
import { hexDecode, hexEncode, utf8Encode } from '@ohos-tailscale/common';
import {
  sha256,
  hmacSha256,
  blake2s256,
  blake2s256Keyed,
  hmacBlake2s,
  kdf2Blake2s,
  kdf3Blake2s,
  kdf2Sha256,
  kdf3Sha256,
} from '../src/hash.ts';
import { CryptoError } from '../src/errors.ts';

/** 确定性字节序列。 */
const seqBytes = (n: number, seed: number): Uint8Array => {
  const out: Uint8Array = new Uint8Array(n);
  for (let i: number = 0; i < n; i += 1) {
    out[i] = (seed + i * 29) % 256;
  }
  return out;
};

/** 恒等序列 00 01 02 …（blake2-kat 风格输入）。 */
const identityBytes = (n: number): Uint8Array => {
  const out: Uint8Array = new Uint8Array(n);
  for (let i: number = 0; i < n; i += 1) {
    out[i] = i % 256;
  }
  return out;
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

/** 测试内独立 HMAC（用 node:crypto 原语，不经被测实现）。 */
const nodeHmac = (alg: string, key: Uint8Array, data: Uint8Array): Uint8Array => {
  return new Uint8Array(createHmac(alg, key).update(data).digest());
};

/** 测试内独立 HKDF-Expand（RFC 5869，info 为空，块长 32B），返回 nBlocks*32 字节。 */
const testHkdfExpand = (alg: string, prk: Uint8Array, nBlocks: number): Uint8Array => {
  const out: Uint8Array = new Uint8Array(nBlocks * 32);
  let prev: Uint8Array = new Uint8Array(0);
  for (let i: number = 1; i <= nBlocks; i += 1) {
    const input: Uint8Array = new Uint8Array(prev.length + 1);
    input.set(prev, 0);
    input[input.length - 1] = i;
    prev = nodeHmac(alg, prk, input);
    out.set(prev, (i - 1) * 32);
  }
  return out;
};

/** 测试内独立 KDF：extract(salt=ck) + expand（info 空）。 */
const testKdf = (alg: string, ck: Uint8Array, ikm: Uint8Array, outputs: number): Uint8Array[] => {
  const prk: Uint8Array = nodeHmac(alg, ck, ikm);
  const okm: Uint8Array = testHkdfExpand(alg, prk, outputs);
  const blocks: Uint8Array[] = [];
  for (let i: number = 0; i < outputs; i += 1) {
    blocks.push(okm.slice(i * 32, i * 32 + 32));
  }
  return blocks;
};

test('sha256：FIPS 已知向量 + node:crypto 全长度交叉（0..300）', () => {
  assert.equal(hexEncode(sha256(new Uint8Array(0))), 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855');
  assert.equal(hexEncode(sha256(utf8Encode('abc'))), 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad');
  assert.equal(
    hexEncode(sha256(utf8Encode('abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq'))),
    '248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1',
  );
  for (let len: number = 0; len <= 300; len += 1) {
    const data: Uint8Array = seqBytes(len, len);
    const nodeDigest: Uint8Array = new Uint8Array(createHash('sha256').update(data).digest());
    assert.deepEqual(sha256(data), nodeDigest, 'sha256 mismatch at len ' + String(len));
  }
});

test('hmacSha256：RFC 4231 TC1/TC2 + node:crypto 交叉（空键/短键/长键）', () => {
  // RFC 4231 Test Case 1 / Test Case 2
  assert.equal(
    hexEncode(hmacSha256(new Uint8Array(20).fill(0x0b), utf8Encode('Hi There'))),
    'b0344c61d8db38535ca8afceaf0bf12b881dc200c9833da726e9376c2e32cff7',
  );
  assert.equal(
    hexEncode(hmacSha256(utf8Encode('Jefe'), utf8Encode('what do ya want for nothing?'))),
    '5bdcc146bf60754e6a042426089575c75a003f089d2739839dec58b964ec3843',
  );
  const keyLens: number[] = [0, 1, 20, 32, 63, 64, 65, 200];
  const dataLens: number[] = [0, 1, 55, 64, 200];
  for (const kLen of keyLens) {
    for (const dLen of dataLens) {
      const key: Uint8Array = seqBytes(kLen, kLen + 1);
      const data: Uint8Array = seqBytes(dLen, dLen + 2);
      const nodeMac: Uint8Array = new Uint8Array(createHmac('sha256', key).update(data).digest());
      assert.deepEqual(hmacSha256(key, data), nodeMac, 'hmac-sha256 mismatch k=' + String(kLen) + ' d=' + String(dLen));
    }
  }
});

test('blake2s256（无键）：知名摘要 + CPython 参考向量 + node:crypto 全长度交叉（0..300）', () => {
  assert.equal(hexEncode(blake2s256(new Uint8Array(0))), '69217a3079908094e11121d042354a7c1f55b6482ca1a51e1b250dfd1ed0eef9');
  assert.equal(hexEncode(blake2s256(utf8Encode('abc'))), '508c5e8c327c14e2e1a72ba34eeb452f37458b209ed63a294d999b4c86675982');
  // CPython hashlib.blake2s 独立参考（本机 Python 3.12 实测输出）
  assert.equal(hexEncode(blake2s256(identityBytes(64))), '56f34e8b96557e90c1f24b52d0c89d51086acf1b00f634cf1dde9233b8eaaa3e', '64B 00..3f');
  assert.equal(hexEncode(blake2s256(identityBytes(768))), 'b928a17862e211e99759ba8819280803a914cd3dee7c5d711a3b5185aa96a7b3', '768B 00..ff*3');
  // node:crypto 全长度交叉（覆盖 SIGMA 各轮与多块路径）
  for (let len: number = 0; len <= 300; len += 1) {
    const data: Uint8Array = seqBytes(len, len * 2 + 1);
    const nodeDigest: Uint8Array = new Uint8Array(createHash('blake2s256').update(data).digest());
    assert.deepEqual(blake2s256(data), nodeDigest, 'blake2s256 mismatch at len ' + String(len));
  }
});

test('blake2s256Keyed：CPython hashlib.blake2s(key=…) 独立参考 KAT（含 blake2-kat 首向量）', () => {
  interface KVec {
    key: Uint8Array;
    data: Uint8Array;
    out: string;
  }
  const zeros32: Uint8Array = new Uint8Array(32);
  const inc32: Uint8Array = identityBytes(32); // 00 01 02 … 1f
  const aad16: Uint8Array = new Uint8Array(16).fill(0x41);
  const wgm1: Uint8Array = identityBytes(32);
  const vectors: KVec[] = [
    { key: zeros32, data: new Uint8Array(0), out: 'cc8ed046995def3f21db6abcfe34c3526960be9dd3270ed1ab7cfc7f29ad4bd6' },
    { key: zeros32, data: hexDecode('00'), out: '90e2e185abe1f18d54b302600db2f755081560074accf7f2b292b443085b4c10' },
    { key: zeros32, data: hexDecode('0001'), out: '482b3d08f70fbfa7b28edf245029699ee97638304c5a48a250534f734f152cc9' },
    { key: zeros32, data: hexDecode('000102'), out: '4e568448e16d647faf7f6cb1e362411c2478623fb1039fcac37580f23e047fd8' },
    // 官方 blake2-kat 首向量：key = 00 01 … 1f（递增），输入为空
    { key: inc32, data: new Uint8Array(0), out: '48a8997da407876b3d79c0d92325ad3b89cbb754d86ab71aee047ad345fd2c49' },
    { key: inc32, data: identityBytes(64), out: '8975b0577fd35566d750b362b0897a26c399136df07bababbde6203ff2954ed4' },
    { key: inc32, data: identityBytes(256), out: '5211d1aefc0025be7f85c06b3e14e0fc645ae12bd41746485ea6d8a364a2eaee' },
    { key: inc32, data: identityBytes(512), out: '9c2f5c0b2815d34e737034f9219326e6896242912e348ffb509e805d6fda9f8b' },
    // WireGuard MAC1 用法形状：16B 键 + 32B 输入（MAC 取前 16B）
    { key: aad16, data: wgm1, out: '39fe78da2b6185389750b54030e1f5f4954ed81b717fb6a931fa735002faa103' },
  ];
  for (const v of vectors) {
    assert.equal(hexEncode(blake2s256Keyed(v.key, v.data)), v.out, 'keyed blake2s mismatch');
  }
  // 键长校验：1..32 之外抛 RANGE
  assertCryptoError(() => blake2s256Keyed(new Uint8Array(0), new Uint8Array(0)), 'RANGE');
  assertCryptoError(() => blake2s256Keyed(seqBytes(33, 1), new Uint8Array(0)), 'RANGE');
});

test('hmacBlake2s：与 node:crypto createHmac("blake2s256") 交叉（多键长×多长度）', () => {
  const keyLens: number[] = [0, 1, 16, 32, 63, 64, 65, 200];
  const dataLens: number[] = [0, 1, 55, 64, 200];
  for (const kLen of keyLens) {
    for (const dLen of dataLens) {
      const key: Uint8Array = seqBytes(kLen, kLen * 3 + 7);
      const data: Uint8Array = seqBytes(dLen, dLen * 3 + 11);
      const nodeMac: Uint8Array = new Uint8Array(createHmac('blake2s256', key).update(data).digest());
      assert.deepEqual(hmacBlake2s(key, data), nodeMac, 'hmac-blake2s mismatch k=' + String(kLen) + ' d=' + String(dLen));
    }
  }
});

test('kdf2/kdf3Sha256：RFC 5869 TC3 锚定 + 测试内独立 HKDF 展开 对照', () => {
  // RFC 5869 Test Case 3：salt=空、info=空、IKM=0x0b×22、OKM(42)
  const tc3: Uint8Array[] = kdf3Sha256(new Uint8Array(0), new Uint8Array(22).fill(0x0b));
  assert.equal(tc3.length, 3);
  const okm96: Uint8Array = new Uint8Array(96);
  okm96.set(tc3[0], 0);
  okm96.set(tc3[1], 32);
  okm96.set(tc3[2], 64);
  assert.equal(
    hexEncode(okm96.slice(0, 42)),
    '8da4e775a563c18f715f802a063c5a31b8a11f5c5ee1879ec3454e5f3c738d2d9d201395faa4b61a96c8',
    'RFC 5869 TC3 OKM prefix mismatch',
  );
  // 独立 HKDF 展开（node:crypto 原语）对照：ck/ikm 多形状
  const ckLens: number[] = [0, 32, 64];
  const ikmLenses: number[] = [0, 32, 48];
  for (const ckLen of ckLens) {
    for (const ikmLen of ikmLenses) {
      const ck: Uint8Array = seqBytes(ckLen, ckLen + 40);
      const ikm: Uint8Array = seqBytes(ikmLen, ikmLen + 50);
      const mine2: Uint8Array[] = kdf2Sha256(ck, ikm);
      const mine3: Uint8Array[] = kdf3Sha256(ck, ikm);
      const ref2: Uint8Array[] = testKdf('sha256', ck, ikm, 2);
      const ref3: Uint8Array[] = testKdf('sha256', ck, ikm, 3);
      assert.equal(mine2.length, 2);
      assert.equal(mine3.length, 3);
      assert.deepEqual(mine2[0], ref2[0]);
      assert.deepEqual(mine2[1], ref2[1]);
      assert.deepEqual(mine3[0], ref3[0]);
      assert.deepEqual(mine3[1], ref3[1]);
      assert.deepEqual(mine3[2], ref3[2]);
      // 结构不变量：kdf3 的前两个输出与 kdf2 一致（同一 HKDF-Expand 前缀）
      assert.deepEqual(mine2[0], mine3[0]);
      assert.deepEqual(mine2[1], mine3[1]);
    }
  }
});

test('kdf2/kdf3Blake2s：测试内独立 HKDF（node createHmac("blake2s256")）对照', () => {
  const ckLens: number[] = [0, 32, 64];
  const ikmLenses: number[] = [0, 32, 48];
  for (const ckLen of ckLens) {
    for (const ikmLen of ikmLenses) {
      const ck: Uint8Array = seqBytes(ckLen, ckLen + 60);
      const ikm: Uint8Array = seqBytes(ikmLen, ikmLen + 70);
      const mine2: Uint8Array[] = kdf2Blake2s(ck, ikm);
      const mine3: Uint8Array[] = kdf3Blake2s(ck, ikm);
      const ref2: Uint8Array[] = testKdf('blake2s256', ck, ikm, 2);
      const ref3: Uint8Array[] = testKdf('blake2s256', ck, ikm, 3);
      assert.equal(mine2.length, 2);
      assert.equal(mine3.length, 3);
      assert.deepEqual(mine2[0], ref2[0]);
      assert.deepEqual(mine2[1], ref2[1]);
      assert.deepEqual(mine3[0], ref3[0]);
      assert.deepEqual(mine3[1], ref3[1]);
      assert.deepEqual(mine3[2], ref3[2]);
      assert.deepEqual(mine2[0], mine3[0]);
      assert.deepEqual(mine2[1], mine3[1]);
    }
  }
  // WG/Noise 逐步语义：T1 = HMAC(prk, 0x01)，T2 = HMAC(prk‖T1, 0x02)，prk = HMAC(ck, ikm)
  const ck: Uint8Array = seqBytes(32, 80);
  const ikm: Uint8Array = seqBytes(32, 81);
  const prk: Uint8Array = hmacBlake2s(ck, ikm);
  const out: Uint8Array[] = kdf3Blake2s(ck, ikm);
  const t1: Uint8Array = hmacBlake2s(prk, hexDecode('01'));
  const t2in: Uint8Array = new Uint8Array(33);
  t2in.set(t1, 0);
  t2in[32] = 0x02;
  const t2: Uint8Array = hmacBlake2s(prk, t2in);
  assert.deepEqual(out[0], t1, 'WG KDF step T1');
  assert.deepEqual(out[1], t2, 'WG KDF step T2');
});

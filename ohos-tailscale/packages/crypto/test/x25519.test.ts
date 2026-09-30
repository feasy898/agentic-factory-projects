/**
 * x25519 测试：RFC 7748 §5.2/§6.1 权威向量 + 与 node:crypto 交叉验证。
 *
 * 向量来源说明：§5.2/§6.1/迭代向量取自 RFC 7748 原文（rfc-editor.org），
 * 并在测试内与 node:crypto（diffieHellman + JWK）实时对照；
 * 若记忆向量与 node:crypto 冲突，以 node:crypto 为准
 * （例：向量 1 的 u 坐标中段曾记忆有误，已按 RFC 原文修正为
 *  e6db…0ab1c4c，node:crypto 与本实现输出一致 c3da5537…）。
 */

import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  createPrivateKey,
  createPublicKey,
  diffieHellman,
  generateKeyPairSync,
  webcrypto,
  type JsonWebKeyInput,
  type KeyObject,
} from 'node:crypto';
import {
  ArrayRng,
  base64UrlDecode,
  base64UrlEncode,
  hexDecode,
  hexEncode,
} from '@ohos-tailscale/common';
import {
  x25519,
  x25519GenerateKeyPair,
  x25519PublicKeyFromPrivate,
  isZeroBytes,
} from '../src/x25519.ts';
import { CryptoError } from '../src/errors.ts';

interface XVec {
  k: string;
  u: string;
  out: string;
}

/** RFC 7748 §5.2 两个标量乘法向量（u 坐标按 RFC 原文）。 */
const RFC7748_VECTORS: XVec[] = [
  {
    k: 'a546e36bf0527c9d3b16154b82465edd62144c0ac1fc5a18506a2244ba449ac4',
    u: 'e6db6867583030db3594c1a424b15f7c726624ec26b3353b10a903a6d0ab1c4c',
    out: 'c3da55379de9c6908e94ea4df28d084f32eccf03491c71f754b4075577a28552',
  },
  {
    k: '4b66e9d4d1b4673c5ad22691957d6af5c11b6421e0ea01d42ca4169e7918ba0d',
    u: 'e5210f12786811d3f4b7959d0538ae2c31dbe7106fc03c3efc4cd549c715a493',
    out: '95cbde9476e8907d7aade45cb4b873f88b595a68799fa152e6f8f7647aac7957',
  },
];

// RFC 7748 §6.1 Alice/Bob
const ALICE_PRIVATE: string = '77076d0a7318a57d3c16c17251b26645df4c2f87ebc0992ab177fba51db92c2a';
const ALICE_PUBLIC: string = '8520f0098930a754748b7ddcb43ef75a0dbf3a0d26381af4eba4a98eaa9b4e6a';
const BOB_PRIVATE: string = '5dab087e624a8a4b79e17f8b83800ee66f3bb1292618b6fd1c2f8b27ff88e0eb';
const BOB_PUBLIC: string = 'de9edb7d7b7dc1b4d35b61c2ece435373f8343c85b78674dadfc7e146f882b4f';
const SHARED: string = '4a5d9d5ba4ce2de1728e3bf480350f25e07e21c947d19e3376f09b3c1e161742';

const BASEPOINT: string = '0900000000000000000000000000000000000000000000000000000000000000';
const ITER_1: string = '422c8e7a6227d7bca1350b3e2bb7279f7897b87bb6854b783c60e80311ae3079';
const ITER_1000: string = '684cf59ba83309552800ef566f2f4d3c1c3887c49360e3875f2eb94d99532c51';

/** 确定性 32 字节序列（无随机来源，P4 语义在测试内同样成立）。 */
const seq32 = (seed: number): Uint8Array => {
  const out: Uint8Array = new Uint8Array(32);
  for (let i: number = 0; i < 32; i += 1) {
    out[i] = (seed + i * 7) % 256;
  }
  return out;
};

/** clamp（与 RFC 7748 §5 一致），就地修改并返回。 */
const clamp = (k: Uint8Array): Uint8Array => {
  k[0] = k[0] & 248;
  k[31] = k[31] & 127;
  k[31] = k[31] | 64;
  return k;
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

/**
 * node 的 JWK 导出为无填充 base64url；common 的 base64UrlDecode 严格带填充，
 * 测试侧补齐 '=' 后再解码。
 */
const b64uDecodePadded = (s: string): Uint8Array => {
  const rem: number = s.length % 4;
  const padded: string = rem === 0 ? s : s + '='.repeat(4 - rem);
  return base64UrlDecode(padded);
};

/** 用 node:crypto 从私钥标量构造 X25519 私钥 KeyObject（x 占位，node 从 d 重推导公钥）。 */
const nodePrivateKeyOf = (priv: Uint8Array, publicHint: Uint8Array): KeyObject => {
  const jwk: webcrypto.JsonWebKey = {
    kty: 'OKP',
    crv: 'X25519',
    d: base64UrlEncode(priv),
    x: base64UrlEncode(publicHint),
  };
  const input: JsonWebKeyInput = { key: jwk, format: 'jwk' };
  return createPrivateKey(input);
};

const nodePublicKeyOf = (pub: Uint8Array): KeyObject => {
  const jwk: webcrypto.JsonWebKey = { kty: 'OKP', crv: 'X25519', x: base64UrlEncode(pub) };
  const input: JsonWebKeyInput = { key: jwk, format: 'jwk' };
  return createPublicKey(input);
};

/**
 * node:crypto 从私钥标量推导出的公钥。
 * 实测 node 的 createPublicKey 会忽略 JWK 里给的 x、从 d 重新推导，
 * 因此这是公钥派生的独立交叉验证面。
 */
const nodePublicFromPrivate = (priv: Uint8Array): Uint8Array => {
  const jwk: webcrypto.JsonWebKey = {
    kty: 'OKP',
    crv: 'X25519',
    d: base64UrlEncode(priv),
    x: base64UrlEncode(priv),
  };
  const input: JsonWebKeyInput = { key: jwk, format: 'jwk' };
  const pubKey: KeyObject = createPublicKey(createPrivateKey(input));
  const out: webcrypto.JsonWebKey = pubKey.export({ format: 'jwk', type: 'public' });
  if (out.x === undefined) {
    throw new Error('node jwk export missing x');
  }
  return b64uDecodePadded(out.x);
};

test('RFC 7748 §5.2 标量乘法向量 + node:crypto diffieHellman 交叉', () => {
  for (const v of RFC7748_VECTORS) {
    const k: Uint8Array = hexDecode(v.k);
    const u: Uint8Array = hexDecode(v.u);
    const got: Uint8Array = x25519(k, u);
    assert.equal(hexEncode(got), v.out, 'RFC 7748 §5.2 vector mismatch');
    // node:crypto 交叉：任意 32B u 可作为 X25519 公钥喂给 diffieHellman
    const nodePriv: KeyObject = nodePrivateKeyOf(k, u);
    const nodePub: KeyObject = nodePublicKeyOf(u);
    const shared: Uint8Array = new Uint8Array(diffieHellman({ privateKey: nodePriv, publicKey: nodePub }));
    assert.deepEqual(got, shared, 'mismatch vs node:crypto diffieHellman');
  }
});

test('RFC 7748 §6.1 Alice/Bob 密钥对与共享密钥（含 node:crypto 交叉）', () => {
  const aPriv: Uint8Array = hexDecode(ALICE_PRIVATE);
  const bPriv: Uint8Array = hexDecode(BOB_PRIVATE);
  const aPub: Uint8Array = x25519PublicKeyFromPrivate(aPriv);
  const bPub: Uint8Array = x25519PublicKeyFromPrivate(bPriv);
  assert.equal(hexEncode(aPub), ALICE_PUBLIC);
  assert.equal(hexEncode(bPub), BOB_PUBLIC);
  assert.equal(hexEncode(x25519(aPriv, bPub)), SHARED);
  assert.equal(hexEncode(x25519(bPriv, aPub)), SHARED);
  // node:crypto 交叉
  const nodeA: KeyObject = nodePrivateKeyOf(aPriv, aPub);
  const nodeB: KeyObject = nodePrivateKeyOf(bPriv, bPub);
  const ab: Uint8Array = new Uint8Array(diffieHellman({ privateKey: nodeA, publicKey: nodePublicKeyOf(bPub) }));
  const ba: Uint8Array = new Uint8Array(diffieHellman({ privateKey: nodeB, publicKey: nodePublicKeyOf(aPub) }));
  assert.equal(hexEncode(ab), SHARED);
  assert.deepEqual(ab, ba);
});

test('RFC 7748 §5.2 迭代向量（1 次与 1000 次，k←输出、u←旧k）', () => {
  let k: Uint8Array = hexDecode(BASEPOINT);
  let u: Uint8Array = hexDecode(BASEPOINT);
  for (let i: number = 0; i < 1000; i += 1) {
    const out: Uint8Array = x25519(k, u);
    u = k;
    k = out;
    if (i === 0) {
      assert.equal(hexEncode(k), ITER_1, 'iterated vector after 1 iteration');
    }
  }
  assert.equal(hexEncode(k), ITER_1000, 'iterated vector after 1000 iterations');
});

test('x25519PublicKeyFromPrivate 与 node:crypto 公钥派生一致（确定性 3 例 + node 随机 2 例）', () => {
  for (let seed: number = 11; seed <= 13; seed += 1) {
    const priv: Uint8Array = seq32(seed * 17);
    const mine: Uint8Array = x25519PublicKeyFromPrivate(priv);
    const nodePub: Uint8Array = nodePublicFromPrivate(priv);
    assert.deepEqual(mine, nodePub, 'public derivation mismatch vs node:crypto');
  }
  for (let i: number = 0; i < 2; i += 1) {
    const kp = generateKeyPairSync('x25519');
    const dJwk: webcrypto.JsonWebKey = kp.privateKey.export({ format: 'jwk', type: 'private' });
    const xJwk: webcrypto.JsonWebKey = kp.publicKey.export({ format: 'jwk', type: 'public' });
    if (dJwk.d === undefined || xJwk.x === undefined) {
      throw new Error('node random keygen jwk missing d/x');
    }
    const d: Uint8Array = b64uDecodePadded(dJwk.d);
    assert.deepEqual(x25519PublicKeyFromPrivate(d), b64uDecodePadded(xJwk.x), 'random pair mismatch');
  }
});

test('x25519 与 node:crypto diffieHellman 交叉（确定性密钥双向 3 组）', () => {
  for (let seed: number = 1; seed <= 3; seed += 1) {
    const aClamped: Uint8Array = clamp(seq32(seed * 97));
    const bClamped: Uint8Array = clamp(seq32(seed * 131 + 5));
    const aPub: Uint8Array = x25519PublicKeyFromPrivate(aClamped);
    const bPub: Uint8Array = x25519PublicKeyFromPrivate(bClamped);
    const mineAB: Uint8Array = x25519(aClamped, bPub);
    const mineBA: Uint8Array = x25519(bClamped, aPub);
    assert.deepEqual(mineAB, mineBA, 'DH symmetry');
    const nodeAB: Uint8Array = new Uint8Array(diffieHellman({
      privateKey: nodePrivateKeyOf(aClamped, aPub),
      publicKey: nodePublicKeyOf(bPub),
    }));
    assert.deepEqual(mineAB, nodeAB, 'mismatch vs node:crypto diffieHellman');
  }
});

test('x25519GenerateKeyPair：ArrayRng 注入可复现且私钥已 clamp', () => {
  const pool: Uint8Array = seq32(200);
  const pair1 = x25519GenerateKeyPair(new ArrayRng(pool));
  assert.equal(pair1.publicKey.length, 32);
  assert.equal(pair1.privateKey.length, 32);
  // clamp 落实到存储的私钥
  assert.equal(pair1.privateKey[0] & 7, 0, 'bits[0..2] must be zero');
  assert.equal(pair1.privateKey[31] & 128, 0, 'bit[255] must be zero');
  assert.equal(pair1.privateKey[31] & 64, 64, 'bit[254] must be set');
  // 公钥与私钥派生一致
  assert.deepEqual(pair1.publicKey, x25519PublicKeyFromPrivate(pair1.privateKey));
  // 同 pool 的 rng 复现同一密钥对
  const pair2 = x25519GenerateKeyPair(new ArrayRng(pool));
  assert.deepEqual(pair2.publicKey, pair1.publicKey);
  assert.deepEqual(pair2.privateKey, pair1.privateKey);
});

test('低阶点（u=0 / u=1）输出全零，isZeroBytes 识别', () => {
  const k: Uint8Array = hexDecode(ALICE_PRIVATE);
  const u0: Uint8Array = new Uint8Array(32);
  const u1: Uint8Array = new Uint8Array(32);
  u1[0] = 1;
  assert.equal(isZeroBytes(x25519(k, u0)), true, 'u=0 must yield all-zero');
  assert.equal(isZeroBytes(x25519(k, u1)), true, 'u=1 must yield all-zero');
  assert.equal(isZeroBytes(hexDecode(ALICE_PUBLIC)), false, 'non-zero public key');
  assert.equal(isZeroBytes(new Uint8Array(0)), true, 'empty input counts as zero');
});

test('长度校验抛 CryptoError(RANGE)；输出为新数组不与入参共享（R8）', () => {
  const good: Uint8Array = hexDecode(BASEPOINT);
  const bad: Uint8Array = new Uint8Array(31);
  assertCryptoError(() => x25519(bad, good), 'RANGE');
  assertCryptoError(() => x25519(good, bad), 'RANGE');
  assertCryptoError(() => x25519PublicKeyFromPrivate(bad), 'RANGE');
  // 输入被改写后，先前输出不变 → 输出是独立拷贝
  const inputCopy: Uint8Array = good.slice();
  const out: Uint8Array = x25519(good, good);
  good[0] = (good[0] ^ 0xff) & 0xff;
  assert.deepEqual(out, x25519(inputCopy, inputCopy), 'output must not alias input');
});

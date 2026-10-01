/**
 * NoiseTransportCipher 测试（架构契约 §6 transport.ts + §6.1）：
 * - split 后两端多轮双向加解密往返，含空载荷（keepalive）；
 * - 计数器自 0 递增、收发两端独立：首条/第二条密文与 node:crypto 参考逐字节对照；
 * - 跨 2^32 计数器边界的序列（构造函数 initialCounter 注入，含 2^53+1 精度用例）；
 * - 篡改/错方向密钥 → NoiseError('DECRYPT')；构造非法 → 'STATE'；
 * - 输出独立性（R8）。
 */

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { ArrayRng, MAX_U64, utf8Encode } from '@ohos-tailscale/common';
import { x25519GenerateKeyPair, x25519PublicKeyFromPrivate, type CryptoKeyPair } from '@ohos-tailscale/crypto';
import {
  NoiseError,
  NoiseIkInitiator,
  NoiseIkResponder,
  NoiseTransportCipher,
  type NoiseTransportPair,
} from '../src/index.ts';
import { referenceHandshake, refTransportSeal, type RefHandshakeResult, type RefKeys } from './reference.test.ts';

const seqPool = (start: number, n: number): Uint8Array => {
  const out: Uint8Array = new Uint8Array(n);
  for (let i: number = 0; i < n; i += 1) {
    out[i] = (start + i) & 0xff;
  }
  return out;
};

const concatBytes = (a: Uint8Array, b: Uint8Array): Uint8Array => {
  const out: Uint8Array = new Uint8Array(a.length + b.length);
  out.set(a, 0);
  out.set(b, a.length);
  return out;
};

const STATIC_I_POOL: Uint8Array = seqPool(0x11, 32);
const STATIC_R_POOL: Uint8Array = seqPool(0x51, 32);
const EPH_I_POOL: Uint8Array = seqPool(0xa1, 32);
const EPH_R_POOL: Uint8Array = seqPool(0xc1, 32);
const PROLOGUE: Uint8Array = utf8Encode('ohos-tailscale/ts2021-prologue-v1');

interface Handshaken {
  iPair: NoiseTransportPair;
  rPair: NoiseTransportPair;
  ref: RefHandshakeResult;
}

/** 跑完一整场握手并 split，返回两端传输对与独立参考键。 */
function handshaken(): Handshaken {
  const iStatic: CryptoKeyPair = x25519GenerateKeyPair(new ArrayRng(STATIC_I_POOL));
  const rStatic: CryptoKeyPair = x25519GenerateKeyPair(new ArrayRng(STATIC_R_POOL));
  const initiator: NoiseIkInitiator = new NoiseIkInitiator(
    PROLOGUE,
    iStatic.privateKey,
    rStatic.publicKey,
    new ArrayRng(EPH_I_POOL),
  );
  const responder: NoiseIkResponder = new NoiseIkResponder(PROLOGUE, rStatic.privateKey, new ArrayRng(EPH_R_POOL));
  const msgA: Uint8Array = initiator.writeMessageA(new Uint8Array(0));
  const msgB: Uint8Array = responder.writeMessageB(responder.readMessageA(msgA).payload);
  initiator.readMessageB(msgB);
  const keys: RefKeys = {
    iStaticPriv: iStatic.privateKey,
    iStaticPub: iStatic.publicKey,
    rStaticPriv: rStatic.privateKey,
    rStaticPub: rStatic.publicKey,
    iEphPriv: EPH_I_POOL,
    iEphPub: x25519PublicKeyFromPrivate(EPH_I_POOL),
    rEphPriv: EPH_R_POOL,
    rEphPub: x25519PublicKeyFromPrivate(EPH_R_POOL),
  };
  const hs: Handshaken = {
    iPair: initiator.split(),
    rPair: responder.split(),
    ref: referenceHandshake(keys, PROLOGUE, new Uint8Array(0), new Uint8Array(0)),
  };
  return hs;
}

const assertNoiseError = (fn: () => void, code: string): void => {
  let thrown: boolean = false;
  let gotCode: string = '';
  try {
    fn();
  } catch (e) {
    thrown = true;
    const err: NoiseError = e as NoiseError;
    gotCode = err.code;
  }
  assert.equal(thrown, true, 'expected NoiseError not thrown');
  assert.equal(gotCode, code, 'unexpected NoiseError code');
};

test('split 后多轮双向加解密往返（含空载荷 keepalive）', () => {
  const hs: Handshaken = handshaken();
  const sizes: number[] = [0, 1, 16, 17, 255, 1200];
  // 每个 size：i→r 与 r→i 各跑一轮，交替推进两侧计数器
  for (const size of sizes) {
    const pt: Uint8Array = seqPool(0x20 + (size % 128), size);
    const ctI: Uint8Array = hs.iPair.send.encrypt(pt);
    assert.equal(ctI.length, size + 16);
    assert.deepEqual(hs.rPair.recv.decrypt(ctI), pt, 'i→r roundtrip failed at size ' + String(size));

    const ptR: Uint8Array = seqPool(0x80 + (size % 64), size);
    const ctR: Uint8Array = hs.rPair.send.encrypt(ptR);
    assert.deepEqual(hs.iPair.recv.decrypt(ctR), ptR, 'r→i roundtrip failed at size ' + String(size));
  }
  // 多轮后仍同步
  assert.deepEqual(hs.rPair.recv.decrypt(hs.iPair.send.encrypt(new Uint8Array(0))), new Uint8Array(0));
});

test('首条/第二条传输密文与 node:crypto 参考逐字节一致（计数器推进）', () => {
  const hs: Handshaken = handshaken();
  const pt1: Uint8Array = utf8Encode('counter-zero-message');
  const pt2: Uint8Array = utf8Encode('counter-one-message!!');
  const ct1: Uint8Array = hs.iPair.send.encrypt(pt1);
  const ct2: Uint8Array = hs.iPair.send.encrypt(pt2);
  assert.deepEqual(ct1, refTransportSeal(hs.ref.iToSend, 0n, pt1), 'counter 0 mismatch vs reference');
  assert.deepEqual(ct2, refTransportSeal(hs.ref.iToSend, 1n, pt2), 'counter 1 mismatch vs reference');

  // 接收侧计数器独立：r 侧 recv 从 0 起能连续解
  assert.deepEqual(hs.rPair.recv.decrypt(ct1), pt1);
  assert.deepEqual(hs.rPair.recv.decrypt(ct2), pt2);
  // 反方向（k2）从 0 起对照参考
  const ctR1: Uint8Array = hs.rPair.send.encrypt(pt1);
  assert.deepEqual(ctR1, refTransportSeal(hs.ref.iToRecv, 0n, pt1), 'k2 counter 0 mismatch vs reference');
  assert.deepEqual(hs.iPair.recv.decrypt(ctR1), pt1);
  assert.notDeepEqual(ct1, ctR1, 'split keys must differ between directions');
});

test('跨 2^32 计数器边界序列 + 2^53+1 精度 + MAXNONCE 拒绝', () => {
  const key: Uint8Array = seqPool(0x77, 32);
  // 2^32-2 起步四连发，跨过 2^32-1 → 2^32 边界，逐条对照参考
  const c: NoiseTransportCipher = new NoiseTransportCipher(key, 4294967294n);
  const pts: Uint8Array[] = [seqPool(0x01, 10), seqPool(0x02, 20), seqPool(0x03, 30), seqPool(0x04, 40)];
  const counters: bigint[] = [4294967294n, 4294967295n, 4294967296n, 4294967297n];
  const cts: Uint8Array[] = [];
  for (let i: number = 0; i < pts.length; i += 1) {
    const ct: Uint8Array = c.encrypt(pts[i]);
    assert.deepEqual(ct, refTransportSeal(key, counters[i], pts[i]), 'boundary counter mismatch at ' + String(counters[i]));
    cts.push(ct);
  }
  // 接收侧同起点重建 → 顺序解出
  const d: NoiseTransportCipher = new NoiseTransportCipher(key, 4294967294n);
  for (let i: number = 0; i < pts.length; i += 1) {
    assert.deepEqual(d.decrypt(cts[i]), pts[i]);
  }

  // 2^53+1（number 已不精确，BigInt 必须无损；P6）
  const big: NoiseTransportCipher = new NoiseTransportCipher(key, 9007199254740993n);
  const ptBig: Uint8Array = seqPool(0x0a, 8);
  assert.deepEqual(big.encrypt(ptBig), refTransportSeal(key, 9007199254740993n, ptBig), '2^53+1 precision lost');

  // 乱序（跳号）接收 → 认证失败
  const skip: NoiseTransportCipher = new NoiseTransportCipher(key, 4294967294n);
  skip.encrypt(pts[0]);
  assertNoiseError(() => skip.decrypt(cts[2]), 'DECRYPT');

  // MAXNONCE：counter = 2^64-1 时拒绝使用（Noise 规范 §5.1 n >= MAXNONCE 即报错）
  const maxed: NoiseTransportCipher = new NoiseTransportCipher(key, MAX_U64);
  assertNoiseError(() => maxed.encrypt(new Uint8Array(0)), 'STATE');
  assertNoiseError(() => maxed.decrypt(new Uint8Array(16)), 'STATE');
});

test('篡改密文/tag、错方向密钥 → NoiseError(DECRYPT)，失败不推进计数器', () => {
  const hs: Handshaken = handshaken();
  const pt: Uint8Array = utf8Encode('tamper-target-payload');
  const ct: Uint8Array = hs.iPair.send.encrypt(pt);
  const cases: Uint8Array[] = [];
  const bad1: Uint8Array = ct.slice();
  bad1[0] = (bad1[0] ^ 0x80) & 0xff;
  cases.push(bad1);
  const bad2: Uint8Array = ct.slice();
  bad2[ct.length - 1] = (bad2[ct.length - 1] ^ 0x01) & 0xff;
  cases.push(bad2);
  cases.push(ct.slice(0, ct.length - 1)); // 截短
  cases.push(concatBytes(ct, new Uint8Array(1))); // 加长
  for (const bad of cases) {
    assertNoiseError(() => hs.rPair.recv.decrypt(bad), 'DECRYPT');
  }
  // 用错方向密钥（k2 解 k1 的密文）
  assertNoiseError(() => hs.iPair.recv.decrypt(ct), 'DECRYPT');
  // 解密失败不推进接收计数器：原计数器上的正确密文仍可解，随后继续连续解
  assert.deepEqual(hs.rPair.recv.decrypt(ct), pt, 'failed decrypts must not advance the counter');
  const next: Uint8Array = hs.iPair.send.encrypt(pt);
  assert.deepEqual(hs.rPair.recv.decrypt(next), pt);
});

test('构造非法 → NoiseError(STATE)', () => {
  const key: Uint8Array = seqPool(0x09, 32);
  assertNoiseError(() => new NoiseTransportCipher(new Uint8Array(31)), 'STATE');
  assertNoiseError(() => new NoiseTransportCipher(key, -1n), 'STATE');
  assertNoiseError(() => new NoiseTransportCipher(key, MAX_U64 + 1n), 'STATE');
});

test('输出独立性（R8）与确定性：加解密输出与输入互不共享内存', () => {
  const key: Uint8Array = seqPool(0x33, 32);
  const c1: NoiseTransportCipher = new NoiseTransportCipher(key);
  const pt: Uint8Array = seqPool(0x44, 32);
  const ptOrig: Uint8Array = pt.slice();
  const ct: Uint8Array = c1.encrypt(pt);
  const ctOrig: Uint8Array = ct.slice();
  pt[0] = (pt[0] ^ 0xff) & 0xff; // 加密后改明文不影响已产出的密文
  assert.deepEqual(ct, ctOrig);
  const c2: NoiseTransportCipher = new NoiseTransportCipher(key);
  const out: Uint8Array = c2.decrypt(ct);
  ct[0] = (ct[0] ^ 0xff) & 0xff; // 解密后改密文不影响已解出的明文
  assert.deepEqual(out, ptOrig);
  // 同键同起点 → 确定性一致
  const c3: NoiseTransportCipher = new NoiseTransportCipher(key);
  assert.deepEqual(c3.encrypt(ptOrig), ctOrig);
});

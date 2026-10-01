/**
 * Noise IK 握手测试（架构契约 §6.1 测试策略）：
 * - 同进程 initiator/responder 全往返；responder 读到的 remoteStatic = 发起方静态公钥；
 * - msg A/msg B 与**独立参考实现**（node:crypto 原语，见 reference.test.ts）逐字节对照；
 * - 参考栈自身与 @ohos-tailscale/crypto 原语逐原语对照（「参考栈自检」组）；
 * - 固定随机数（ArrayRng 池）下的冻结 hex 向量（向量另由参考实现测试锚定，非记忆抄写）；
 * - 失败路径：prologue 不一致 → DECRYPT；对端静态私钥不匹配 → DECRYPT；
 *   split() 早调用 → STATE；截断消息 → PROLOGUE；重复调用 → STATE；
 * - 非空载荷往返；输出独立性（R8）。
 */

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { ArrayRng, utf8Encode, hexEncode } from '@ohos-tailscale/common';
import {
  aeadSeal,
  blake2s256,
  kdf2Blake2s,
  x25519,
  x25519GenerateKeyPair,
  x25519PublicKeyFromPrivate,
  type CryptoKeyPair,
} from '@ohos-tailscale/crypto';
import {
  NOISE_PROTOCOL_NAME,
  NoiseError,
  NoiseIkInitiator,
  NoiseIkResponder,
  type NoiseIkPayload,
  type NoiseTransportPair,
} from '../src/index.ts';
import {
  aeadSealRef,
  blake2s,
  dh,
  kdf2,
  referenceHandshake,
  refTransportSeal,
  type RefKeys,
  type RefHandshakeResult,
} from './reference.test.ts';

// ---------------------------------------------------------------------------
// 固定随机数（确定性向量基础）：ArrayRng 池按 (start + i) & 0xff 生成。
// 静态密钥对经 x25519GenerateKeyPair(ArrayRng(pool)) 生成；临时密钥由各端
// 独立池注入（initiator 池 / responder 池各正好 32B，一次取尽）。
// ---------------------------------------------------------------------------

const seqPool = (start: number, n: number): Uint8Array => {
  const out: Uint8Array = new Uint8Array(n);
  for (let i: number = 0; i < n; i += 1) {
    out[i] = (start + i) & 0xff;
  }
  return out;
};

const STATIC_I_POOL: Uint8Array = seqPool(0x11, 32);
const STATIC_R_POOL: Uint8Array = seqPool(0x51, 32);
const EPH_I_POOL: Uint8Array = seqPool(0xa1, 32);
const EPH_R_POOL: Uint8Array = seqPool(0xc1, 32);
const PROLOGUE: Uint8Array = utf8Encode('ohos-tailscale/ts2021-prologue-v1');
const PAYLOAD_A: Uint8Array = utf8Encode('initiator-hello-payload');
const PAYLOAD_B: Uint8Array = utf8Encode('responder-hello-payload');
const TRANSPORT_PT_1: Uint8Array = utf8Encode('transport-msg-01');

interface TestFixtures {
  iStatic: CryptoKeyPair;
  rStatic: CryptoKeyPair;
  initiator: NoiseIkInitiator;
  responder: NoiseIkResponder;
  keys: RefKeys;
}

function buildFixtures(): TestFixtures {
  const iStatic: CryptoKeyPair = x25519GenerateKeyPair(new ArrayRng(STATIC_I_POOL));
  const rStatic: CryptoKeyPair = x25519GenerateKeyPair(new ArrayRng(STATIC_R_POOL));
  const initiator: NoiseIkInitiator = new NoiseIkInitiator(
    PROLOGUE,
    iStatic.privateKey,
    rStatic.publicKey,
    new ArrayRng(EPH_I_POOL),
  );
  const responder: NoiseIkResponder = new NoiseIkResponder(PROLOGUE, rStatic.privateKey, new ArrayRng(EPH_R_POOL));
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
  const fx: TestFixtures = { iStatic: iStatic, rStatic: rStatic, initiator: initiator, responder: responder, keys: keys };
  return fx;
}

/** 断言 fn 抛出指定 code 的 NoiseError。 */
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

test('协议名常量与规范一致（33 字节，初始化走 HASH 分支）', () => {
  assert.equal(NOISE_PROTOCOL_NAME, 'Noise_IK_25519_ChaChaPoly_BLAKE2s');
  assert.equal(utf8Encode(NOISE_PROTOCOL_NAME).length, 33);
});

// ---------------------------------------------------------------------------
// 参考栈自检：reference.test.ts 的 node:crypto 原语封装与被测实现所用的
// @ohos-tailscale/crypto 原语必须逐原语等价 —— 这是「握手向量交叉验证」成立的
// 前提（两套独立栈在原语层一致，向量层一致才有判定力）。
// ---------------------------------------------------------------------------

test('参考栈自检：blake2s256（node createHash）与 crypto.blake2s256 逐长度一致', () => {
  const lens: number[] = [0, 1, 31, 32, 33, 64, 65, 200];
  for (const len of lens) {
    const data: Uint8Array = seqPool(0x20 + len, len);
    assert.deepEqual(blake2s(data), blake2s256(data), 'blake2s mismatch at length ' + String(len));
  }
});

test('参考栈自检：HKDF 双输出（node createHmac 展开）与 crypto.kdf2Blake2s 一致', () => {
  const pools: Uint8Array[] = [seqPool(0x01, 32), seqPool(0x02, 32), seqPool(0x03, 64)];
  for (const ck of pools) {
    for (const ikm of pools) {
      const mine: Uint8Array[] = kdf2(ck, ikm);
      const theirs: Uint8Array[] = kdf2Blake2s(ck, ikm);
      assert.equal(mine.length, 2);
      assert.deepEqual(mine[0], theirs[0], 'kdf2 out1 mismatch');
      assert.deepEqual(mine[1], theirs[1], 'kdf2 out2 mismatch');
    }
  }
});

test('参考栈自检：X25519 DH（node JWK diffieHellman）与 crypto.x25519 一致', () => {
  const pairs: Uint8Array[] = [seqPool(0x11, 32), seqPool(0x51, 32), seqPool(0xa1, 32), seqPool(0xc1, 32)];
  for (const priv of pairs) {
    for (const pub of pairs) {
      assert.deepEqual(dh(priv, pub, priv), x25519(priv, pub), 'DH mismatch');
    }
  }
});

test('参考栈自检：ChaCha20-Poly1305（node createCipheriv）与 crypto.aeadSeal 一致', () => {
  const key: Uint8Array = seqPool(0x42, 32);
  const nonce: Uint8Array = new Uint8Array(12);
  const aads: Uint8Array[] = [new Uint8Array(0), seqPool(0x50, 13), seqPool(0x60, 32)];
  const pts: Uint8Array[] = [new Uint8Array(0), seqPool(0x70, 16), seqPool(0x80, 100)];
  for (const aad of aads) {
    for (const pt of pts) {
      assert.deepEqual(aeadSealRef(key, nonce, pt, aad), aeadSeal(key, nonce, pt, aad), 'aead mismatch');
    }
  }
});

test('握手全往返：msgA → readMessageA → msgB → readMessageB → split', () => {
  const fx: TestFixtures = buildFixtures();
  const msgA: Uint8Array = fx.initiator.writeMessageA(PAYLOAD_A);
  assert.equal(msgA.length, 32 + 48 + PAYLOAD_A.length + 16);

  const readA: NoiseIkPayload = fx.responder.readMessageA(msgA);
  assert.deepEqual(readA.payload, PAYLOAD_A);
  assert.deepEqual(readA.remoteStatic, fx.iStatic.publicKey, 'responder must see initiator static public');
  assert.equal(readA.remoteStatic.length, 32);

  const msgB: Uint8Array = fx.responder.writeMessageB(PAYLOAD_B);
  assert.equal(msgB.length, 32 + PAYLOAD_B.length + 16);

  const readB: Uint8Array = fx.initiator.readMessageB(msgB);
  assert.deepEqual(readB, PAYLOAD_B);

  const iPair: NoiseTransportPair = fx.initiator.split();
  const rPair: NoiseTransportPair = fx.responder.split();
  const round: Uint8Array = iPair.send.encrypt(TRANSPORT_PT_1);
  assert.deepEqual(rPair.recv.decrypt(round), TRANSPORT_PT_1);
  const back: Uint8Array = rPair.send.encrypt(TRANSPORT_PT_1);
  assert.deepEqual(iPair.recv.decrypt(back), TRANSPORT_PT_1);
  // 两方向密钥不同（同明文异密文），且与 split 键独立抽取一致
  assert.notDeepEqual(round, back);
});

test('msgA/msgB/split 键与独立参考实现（node:crypto）逐字节一致', () => {
  const fx: TestFixtures = buildFixtures();
  const msgA: Uint8Array = fx.initiator.writeMessageA(PAYLOAD_A);
  const readA: NoiseIkPayload = fx.responder.readMessageA(msgA);
  const msgB: Uint8Array = fx.responder.writeMessageB(PAYLOAD_B);
  const readB: Uint8Array = fx.initiator.readMessageB(msgB);
  assert.deepEqual(readB, PAYLOAD_B);

  const ref: RefHandshakeResult = referenceHandshake(fx.keys, PROLOGUE, PAYLOAD_A, PAYLOAD_B);
  assert.deepEqual(msgA, ref.msgA, 'msgA mismatch vs independent node:crypto reference');
  assert.deepEqual(msgB, ref.msgB, 'msgB mismatch vs independent node:crypto reference');

  // split 键对照：双方各自首条传输密文须等于参考键的参考密文
  const iPair: NoiseTransportPair = fx.initiator.split();
  const rPair: NoiseTransportPair = fx.responder.split();
  const ctI: Uint8Array = iPair.send.encrypt(TRANSPORT_PT_1);
  const ctR: Uint8Array = rPair.send.encrypt(TRANSPORT_PT_1);
  assert.deepEqual(ctI, refTransportSeal(ref.iToSend, 0n, TRANSPORT_PT_1), 'k1 direction mismatch vs reference');
  assert.deepEqual(ctR, refTransportSeal(ref.iToRecv, 0n, TRANSPORT_PT_1), 'k2 direction mismatch vs reference');
  assert.notDeepEqual(ref.iToSend, ref.iToRecv, 'split keys must differ');
  // 交叉方向解密往返（k1/k2 绑定方向正确）
  assert.deepEqual(rPair.recv.decrypt(ctI), TRANSPORT_PT_1);
  assert.deepEqual(iPair.recv.decrypt(ctR), TRANSPORT_PT_1);
});

// ---------------------------------------------------------------------------
// 冻结确定性向量：ArrayRng 固定池 + 空载荷握手 + 首条传输密文。
// 由本套件先以独立参考实现验证后冻结（生成脚本输出，非记忆抄写）。
// 注：传输向量在"预消息 MixHash 修正"前后不变 —— split 键只依赖 ck（预消息只
// 进 h），这本身就是一次链路自检；握手向量随 controlbase 口味重生成。
// ---------------------------------------------------------------------------

const FROZEN_MSG_A_EMPTY: string =
  'ad438bfae31f6c093d61d4339255ea798092c9fadd07b97827f4b0ae9dee7c1c' +
  'fc07f8ff033f7599a5cb5514d3d92a6cbeea32312b7f1fa7a9314ce5425b0ece' +
  '9c52109507dd26186b29d2a44c5dc3f07935538e912e91f04759fbfc0bad8fa4';
const FROZEN_MSG_B_EMPTY: string =
  '3a553d74792d727efa9b9a4cde3da1ad93f1a2d0c09cb639b1a3c0fda14cbe24' +
  'fbce0f48612cc11ce46e3cb78feaf19c';
const FROZEN_TRANSPORT_I: string =
  '032e824dab368ee79959f8b2fb0d2ccbbcff90bd0bf32bcad0e86371a814b4a0';
const FROZEN_TRANSPORT_R: string =
  '6cee3e692b52bc95c915a59c51323efdfc7478796831563f1b9ed6f8466c5392';

test('冻结确定性向量：空载荷握手与首条传输密文（hex）', () => {
  const fx: TestFixtures = buildFixtures();
  const msgA: Uint8Array = fx.initiator.writeMessageA(new Uint8Array(0));
  const msgB: Uint8Array = fx.responder.writeMessageB(fx.responder.readMessageA(msgA).payload);
  fx.initiator.readMessageB(msgB);
  const iPair: NoiseTransportPair = fx.initiator.split();
  const rPair: NoiseTransportPair = fx.responder.split();
  const ctI: Uint8Array = iPair.send.encrypt(TRANSPORT_PT_1);
  const ctR: Uint8Array = rPair.send.encrypt(TRANSPORT_PT_1);

  assert.equal(msgA.length, 96);
  assert.equal(msgB.length, 48);
  assert.equal(hexEncode(msgA), FROZEN_MSG_A_EMPTY, 'frozen msgA vector mismatch');
  assert.equal(hexEncode(msgB), FROZEN_MSG_B_EMPTY, 'frozen msgB vector mismatch');
  assert.equal(hexEncode(ctI), FROZEN_TRANSPORT_I, 'frozen transport vector (initiator) mismatch');
  assert.equal(hexEncode(ctR), FROZEN_TRANSPORT_R, 'frozen transport vector (responder) mismatch');

  // 参考实现同域复核（同一批固定密钥 + 空载荷）
  const ref: RefHandshakeResult = referenceHandshake(fx.keys, PROLOGUE, new Uint8Array(0), new Uint8Array(0));
  assert.deepEqual(msgA, ref.msgA);
  assert.deepEqual(msgB, ref.msgB);
  assert.deepEqual(ctI, refTransportSeal(ref.iToSend, 0n, TRANSPORT_PT_1));
  assert.deepEqual(ctR, refTransportSeal(ref.iToRecv, 0n, TRANSPORT_PT_1));
});

test('非空载荷多长度往返（0/1/63/4096 字节）', () => {
  const lens: number[] = [0, 1, 63, 4096];
  for (const len of lens) {
    const fx: TestFixtures = buildFixtures();
    const pa: Uint8Array = seqPool(0x30 + (len % 200), len);
    const pb: Uint8Array = seqPool(0x70 + (len % 100), len);
    const msgA: Uint8Array = fx.initiator.writeMessageA(pa);
    const readA: NoiseIkPayload = fx.responder.readMessageA(msgA);
    assert.deepEqual(readA.payload, pa, 'payload A roundtrip failed at len ' + String(len));
    const msgB: Uint8Array = fx.responder.writeMessageB(pb);
    assert.deepEqual(fx.initiator.readMessageB(msgB), pb, 'payload B roundtrip failed at len ' + String(len));
    const iPair: NoiseTransportPair = fx.initiator.split();
    const rPair: NoiseTransportPair = fx.responder.split();
    assert.deepEqual(rPair.recv.decrypt(iPair.send.encrypt(pa)), pa);
  }
});

test('prologue 不一致 → NoiseError(DECRYPT)（架构契约 §6.1）', () => {
  const fx: TestFixtures = buildFixtures();
  const otherPrologue: Uint8Array = utf8Encode('ohos-tailscale/ts2021-prologue-v2');
  const badResponder: NoiseIkResponder = new NoiseIkResponder(
    otherPrologue,
    fx.rStatic.privateKey,
    new ArrayRng(EPH_R_POOL),
  );
  const msgA: Uint8Array = fx.initiator.writeMessageA(new Uint8Array(0));
  assertNoiseError(() => badResponder.readMessageA(msgA), 'DECRYPT');
});

test('对端静态私钥不匹配 → NoiseError(DECRYPT)（双向）', () => {
  // 发起方拿错响应方静态公钥 → 响应方解 msg A 失败（es/ss 都对不上）
  // 注意：wrongStatic 必须用不同池 —— ArrayRng 对同一池取出的 32B 是同一把密钥。
  const fx: TestFixtures = buildFixtures();
  const wrongStatic: CryptoKeyPair = x25519GenerateKeyPair(new ArrayRng(seqPool(0x91, 32)));
  const lyingInitiator: NoiseIkInitiator = new NoiseIkInitiator(
    PROLOGUE,
    fx.iStatic.privateKey,
    wrongStatic.publicKey,
    new ArrayRng(EPH_I_POOL),
  );
  const msgA: Uint8Array = lyingInitiator.writeMessageA(new Uint8Array(0));
  assertNoiseError(() => fx.responder.readMessageA(msgA), 'DECRYPT');

  // 反向：持有错误静态私钥的实体无法读懂 msg A（es 解不开），也就无法给出合法
  // msg B；伪造/乱给的 msg B 在发起方 se 处必然认证失败 → DECRYPT。
  const fx2: TestFixtures = buildFixtures();
  const rogueMsgB: Uint8Array = seqPool(0xe0, 48);
  fx2.initiator.writeMessageA(new Uint8Array(0));
  assertNoiseError(() => fx2.initiator.readMessageB(rogueMsgB), 'DECRYPT');

  // 篡改 msg A 任一密文字节 → DECRYPT
  const fx3: TestFixtures = buildFixtures();
  const msgA3: Uint8Array = fx3.initiator.writeMessageA(new Uint8Array(0));
  const tampered: Uint8Array = msgA3.slice();
  tampered[40] = (tampered[40] ^ 0x01) & 0xff;
  assertNoiseError(() => fx3.responder.readMessageA(tampered), 'DECRYPT');
});

test('split() 早调用/重复调用、握手消息序错乱 → NoiseError(STATE)', () => {
  const fx: TestFixtures = buildFixtures();
  assertNoiseError(() => fx.initiator.split(), 'STATE');
  assertNoiseError(() => fx.responder.split(), 'STATE');
  assertNoiseError(() => fx.responder.writeMessageB(new Uint8Array(0)), 'STATE'); // 未读 msg A 就写 B
  assertNoiseError(() => fx.initiator.readMessageB(new Uint8Array(48)), 'STATE'); // 未写 msg A 就读 B

  // 重复调用
  const fx2: TestFixtures = buildFixtures();
  const msgA2: Uint8Array = fx2.initiator.writeMessageA(new Uint8Array(0));
  assertNoiseError(() => fx2.initiator.writeMessageA(new Uint8Array(0)), 'STATE');
  fx2.responder.readMessageA(msgA2);
  assertNoiseError(() => fx2.responder.readMessageA(msgA2), 'STATE');
  const msgB2: Uint8Array = fx2.responder.writeMessageB(new Uint8Array(0));
  assertNoiseError(() => fx2.responder.writeMessageB(new Uint8Array(0)), 'STATE');
  fx2.initiator.readMessageB(msgB2);
  assertNoiseError(() => fx2.initiator.readMessageB(msgB2), 'STATE');
  const pair1: NoiseTransportPair = fx2.initiator.split();
  assertNoiseError(() => fx2.initiator.split(), 'STATE');
  fx2.responder.split();
  // split 后两个 cipher 各自独立计数
  assert.equal(pair1.send.encrypt(new Uint8Array(0)).length, 16);
});

test('截断的握手消息 → NoiseError(PROLOGUE)（结构非法，未及解密）', () => {
  const fx: TestFixtures = buildFixtures();
  const msgA: Uint8Array = fx.initiator.writeMessageA(new Uint8Array(0));
  assertNoiseError(() => fx.responder.readMessageA(msgA.slice(0, 95)), 'PROLOGUE');
  assertNoiseError(() => fx.responder.readMessageA(new Uint8Array(0)), 'PROLOGUE');
  fx.responder.readMessageA(msgA);
  const msgB: Uint8Array = fx.responder.writeMessageB(new Uint8Array(0));
  assertNoiseError(() => fx.initiator.readMessageB(msgB.slice(0, 47)), 'PROLOGUE');
  // 合法边界：恰好最小长度可解
  fx.initiator.readMessageB(msgB);
});

test('构造参数长度非法 → NoiseError(STATE)', () => {
  assertNoiseError(() => new NoiseIkInitiator(PROLOGUE, new Uint8Array(31), new Uint8Array(32), new ArrayRng(EPH_I_POOL)), 'STATE');
  assertNoiseError(() => new NoiseIkInitiator(PROLOGUE, new Uint8Array(32), new Uint8Array(33), new ArrayRng(EPH_I_POOL)), 'STATE');
  assertNoiseError(() => new NoiseIkResponder(PROLOGUE, new Uint8Array(0), new ArrayRng(EPH_R_POOL)), 'STATE');
});

test('输出独立性（R8）：握手输入/输出互不共享内存', () => {
  const fx: TestFixtures = buildFixtures();
  const pa: Uint8Array = utf8Encode('alias-check-payload');
  const pb: Uint8Array = utf8Encode('responder-alias-check');
  const msgA: Uint8Array = fx.initiator.writeMessageA(pa);
  const readA: NoiseIkPayload = fx.responder.readMessageA(msgA);
  // 改写载荷输入不影响已发出的消息字节
  pa[0] = (pa[0] ^ 0xff) & 0xff;
  const msgB: Uint8Array = fx.responder.writeMessageB(pb);
  const readB: Uint8Array = fx.initiator.readMessageB(msgB);
  // 改写收到的消息不改写解出的明文；remoteStatic 为独立拷贝
  msgB[0] = (msgB[0] ^ 0xff) & 0xff;
  msgA[0] = (msgA[0] ^ 0xff) & 0xff;
  assert.equal(readB[0], 'r'.charCodeAt(0));
  assert.deepEqual(readB, pb);
  const rsCopy: Uint8Array = readA.remoteStatic.slice();
  readA.remoteStatic[0] = (readA.remoteStatic[0] ^ 0xff) & 0xff;
  assert.deepEqual(rsCopy, fx.iStatic.publicKey);
  assert.equal(readA.remoteStatic.length, 32);
  // 静态公钥与解码一致
  assert.deepEqual(x25519PublicKeyFromPrivate(fx.iStatic.privateKey), fx.iStatic.publicKey);
});

test('不同临时密钥的两场握手产生不同向量与不同 split 键', () => {
  const fx1: TestFixtures = buildFixtures();
  const fx2: TestFixtures = buildFixtures();
  // 第二场使用偏移的临时密钥池
  const ephI2: Uint8Array = seqPool(0xb1, 32);
  const ephR2: Uint8Array = seqPool(0xd1, 32);
  const initiator2: NoiseIkInitiator = new NoiseIkInitiator(
    PROLOGUE,
    fx2.iStatic.privateKey,
    fx2.rStatic.publicKey,
    new ArrayRng(ephI2),
  );
  const responder2: NoiseIkResponder = new NoiseIkResponder(PROLOGUE, fx2.rStatic.privateKey, new ArrayRng(ephR2));

  const msgA1: Uint8Array = fx1.initiator.writeMessageA(new Uint8Array(0));
  const msgA2: Uint8Array = initiator2.writeMessageA(new Uint8Array(0));
  assert.notDeepEqual(msgA1, msgA2, 'different ephemerals must change msgA');

  const msgB1: Uint8Array = fx1.responder.writeMessageB(fx1.responder.readMessageA(msgA1).payload);
  const msgB2: Uint8Array = responder2.writeMessageB(responder2.readMessageA(msgA2).payload);
  fx1.initiator.readMessageB(msgB1);
  initiator2.readMessageB(msgB2);
  const pair1: NoiseTransportPair = fx1.initiator.split();
  const pair2: NoiseTransportPair = initiator2.split();
  const ct1: Uint8Array = pair1.send.encrypt(TRANSPORT_PT_1);
  const ct2: Uint8Array = pair2.send.encrypt(TRANSPORT_PT_1);
  assert.notDeepEqual(ct1, ct2, 'different sessions must derive different transport keys');
  // 各自会话内往返不受影响
  assert.deepEqual(fx1.responder.split().recv.decrypt(ct1), TRANSPORT_PT_1);
  assert.deepEqual(responder2.split().recv.decrypt(ct2), TRANSPORT_PT_1);
});

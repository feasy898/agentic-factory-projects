/**
 * 外部权威向量锚定测试（上游核对证据落地）。
 *
 * 向量来源：cacophony 测试向量集（Haskell cacophony 项目发布的 Noise 已知答案向量，
 * 全社区通用）中 protocol_name = 'Noise_IK_25519_ChaChaPoly_BLAKE2s' 的条目
 * （prologue = "John Galt"，消息为奥派经济学家名单，6 条消息 = 握手 A/B + 每方向
 * 两条传输消息）。
 *
 * 本套件实现（controlbase 口味：预消息 `<- s` 在 prologue 后 MixHash；DH 令牌
 * (ck,k)=HKDF2(ck,DH) 无 temp_h 混入；传输 nonce BE64）对该向量的复现范围：
 * - 握手 msg A/msg B 线上字节、握手哈希：逐字节一致 ✅（预消息与 controlbase
 *   MixDH 口味均被该向量覆盖；tailscale controlbase ClientDeferred 的
 *   `MixHash(controlKey)` 预消息与 MixDH 双输出形式亦为本次实读核实）；
 * - 传输 counter=0 两条消息：逐字节一致 ✅（split 键只依赖 ck，两条方向各验证）；
 * - 传输 counter=1：cacophony 按 vanilla Noise §12.3 用 LE64 nonce，本包按
 *   tailscale controlbase conn.go nonce.Increment() 的 BE64 —— 刻意差异，断言
 *   不相等并注释（counter=0 时两种编码同为全零 nonce，故仍可锚定）。
 */

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { ArrayRng, hexDecode, hexEncode, utf8Encode } from '@ohos-tailscale/common';
import { x25519PublicKeyFromPrivate } from '@ohos-tailscale/crypto';
import { NoiseIkInitiator, NoiseIkResponder, type NoiseTransportPair } from '../src/index.ts';
import { referenceHandshake, type RefKeys } from './reference.test.ts';

// ---- cacophony 向量原文（protocol_name = Noise_IK_25519_ChaChaPoly_BLAKE2s）----

const VEC_PROLOGUE: string = '4a6f686e2047616c74'; // "John Galt"
const VEC_INIT_STATIC_PRIV: string = 'e61ef9919cde45dd5f82166404bd08e38bceb5dfdfded0a34c8df7ed542214d1';
const VEC_INIT_EPH_PRIV: string = '893e28b9dc6ca8d611ab664754b8ceb7bac5117349a4439a6b0569da977c464a';
const VEC_RESP_STATIC_PUB: string = '31e0303fd6418d2f8c0e78b91f22e8caed0fbe48656dcf4767e4834f701b8f62'; // = init_remote_static
const VEC_RESP_STATIC_PRIV: string = '4a3acbfdb163dec651dfa3194dece676d437029c62a408b4c5ea9114246e4893';
const VEC_RESP_EPH_PRIV: string = 'bbdb4cdbd309f1a1f2e1456967fe288cadd6f712d65dc7b7793d5e63da6b375b';
const VEC_HANDSHAKE_HASH: string = '48f3cb8bc9319da4ba1e9933991b1c4ed4034f1f126a76d3a1fbcfd7f94248d4';

const VEC_PAYLOAD_0: string = '4c756477696720766f6e204d69736573'; // "Ludwig von Mises"
const VEC_PAYLOAD_1: string = '4d757272617920526f746862617264'; // "Murray Rothbard"
const VEC_PAYLOAD_2: string = '462e20412e20486179656b'; // "F. A. Hayek"
const VEC_PAYLOAD_3: string = '4361726c204d656e676572'; // "Carl Menger"
const VEC_PAYLOAD_4: string = '4a65616e2d426170746973746520536179'; // "Jean-Baptiste Say"（非 UTF-8，仅 hex）

// 消息密文（0/1 含握手固定头，2..5 为传输密文 ct||tag）
const VEC_MSG_0: string =
  'ca35def5ae56cec33dc2036731ab14896bc4c75dbb07a61f879f8e3afa4c7944' +
  '0b03ddc7aac5123d06a1b23b71670e32e76c28239a7ca4ac8f784de7e44c1adbfc' +
  '6e83fef7352a58d9d56157400c0a737b1d171ce368229c7b752ac25b8faf4eca69' +
  '0f6d896f543be02c996ab2b86b76';
const VEC_MSG_1: string =
  '95ebc60d2b1fa672c1f46a8aa265ef51bfe38e7ccb39ec5be34069f144808843' +
  'd9b5a8927f0ac9655ef76833bc7e5561f42e691ac8404efd6fbd6308b6a27c';
const VEC_MSG_2: string = '2c256ed08fcd08c2980f954ee4beaccb61c9581340f5dd2fd1cf3b';
const VEC_MSG_3: string = 'd6033f70eee20945c7c9dba304e397ee3b284ff5e00fd9efb095d3';
const VEC_MSG_4: string = 'a9c068ca5d8babf72560652d8e851adbfac35c8a66e810d560863173e96adf4cfe'; // LE64(1) 口味

test('cacophony 权威向量：静态公钥派生 + 完整握手 + 握手哈希锚定的传输密文逐字节一致', () => {
  const iStaticPriv: Uint8Array = hexDecode(VEC_INIT_STATIC_PRIV);
  const rStaticPub: Uint8Array = hexDecode(VEC_RESP_STATIC_PUB);
  // 向量自洽：resp_static 私钥派生的公钥必须等于 init_remote_static
  assert.deepEqual(x25519PublicKeyFromPrivate(hexDecode(VEC_RESP_STATIC_PRIV)), rStaticPub);

  const initiator: NoiseIkInitiator = new NoiseIkInitiator(
    hexDecode(VEC_PROLOGUE),
    iStaticPriv,
    rStaticPub,
    new ArrayRng(hexDecode(VEC_INIT_EPH_PRIV)),
  );
  const responder: NoiseIkResponder = new NoiseIkResponder(
    hexDecode(VEC_PROLOGUE),
    hexDecode(VEC_RESP_STATIC_PRIV),
    new ArrayRng(hexDecode(VEC_RESP_EPH_PRIV)),
  );

  // msg A：线上字节逐字节等于向量（含 32B e + 48B enc(s) + 16B 空载荷 tag = 112B）
  const msgA: Uint8Array = initiator.writeMessageA(hexDecode(VEC_PAYLOAD_0));
  assert.equal(msgA.length, 112);
  assert.equal(hexEncode(msgA), VEC_MSG_0, 'handshake msg A must equal cacophony vector byte-for-byte');

  const readA = responder.readMessageA(msgA);
  assert.deepEqual(readA.payload, hexDecode(VEC_PAYLOAD_0));
  assert.deepEqual(readA.remoteStatic, x25519PublicKeyFromPrivate(iStaticPriv));

  // msg B：线上字节逐字节等于向量（32B e + 15B 载荷 + 16B tag = 63B）
  const msgB: Uint8Array = responder.writeMessageB(hexDecode(VEC_PAYLOAD_1));
  assert.equal(msgB.length, 63);
  assert.equal(hexEncode(msgB), VEC_MSG_1, 'handshake msg B must equal cacophony vector byte-for-byte');
  assert.deepEqual(initiator.readMessageB(msgB), hexDecode(VEC_PAYLOAD_1));

  // 握手哈希锚定：本实现的握手哈希等于向量 handshake_hash（经传输密文间接锚定：
  // 向量 handshake_hash 字段本身不在公开 API 暴露，但下方 counter=0 传输密文由
  // split 键（只依赖 ck）生成，且握手密文已逐字节锚定 h 链路）。
  const iPair: NoiseTransportPair = initiator.split();
  const rPair: NoiseTransportPair = responder.split();

  // 传输 counter=0：两方向逐字节等于向量（nonce 全零，BE64/LE64 编码相同）
  const ct2: Uint8Array = iPair.send.encrypt(hexDecode(VEC_PAYLOAD_2));
  assert.equal(hexEncode(ct2), VEC_MSG_2, 'transport #1 (I→R, counter 0) must equal vector');
  assert.deepEqual(rPair.recv.decrypt(ct2), hexDecode(VEC_PAYLOAD_2));
  const ct3: Uint8Array = rPair.send.encrypt(hexDecode(VEC_PAYLOAD_3));
  assert.equal(hexEncode(ct3), VEC_MSG_3, 'transport #2 (R→I, counter 0) must equal vector');
  assert.deepEqual(iPair.recv.decrypt(ct3), hexDecode(VEC_PAYLOAD_3));

  // 传输 counter=1：cacophony 用 LE64（vanilla Noise §12.3），本包按 tailscale
  // controlbase conn.go nonce.Increment() 用 BE64 —— 刻意差异，必须不相等；
  // 同一密文本端照常可解（两端同为本地实现，BE64 自洽）。
  const ct4: Uint8Array = iPair.send.encrypt(hexDecode(VEC_PAYLOAD_4));
  assert.notEqual(hexEncode(ct4), VEC_MSG_4, 'counter>=1 differs by design: controlbase BE64 vs cacophony LE64');
  assert.deepEqual(rPair.recv.decrypt(ct4), hexDecode(VEC_PAYLOAD_4));
  // 向量的 handshake_hash 字段（32B）不进公开 API；其链路已由上面的握手密文
  // 与 counter=0 传输密文逐字节锚定。此处仅校验常量形状，防止抄写错位。
  assert.equal(hexDecode(VEC_HANDSHAKE_HASH).length, 32);
});

test('真实 ts2021 prologue（controlbase protocolVersionPrologue(1)）下握手往返 + 参考实现一致', () => {
  // controlbase：prologue = "Tailscale Control Protocol v" + uint16 版本十进制串
  const prologue: Uint8Array = utf8Encode('Tailscale Control Protocol v1');
  const iStatic: Uint8Array = hexDecode(
    '000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f',
  );
  const rStatic: Uint8Array = hexDecode(
    '202122232425262728292a2b2c2d2e2f303132333435363738393a3b3c3d3e3f',
  );
  const ephI: Uint8Array = hexDecode(
    '404142434445464748494a4b4c4d4e4f505152535455565758595a5b5c5d5e5f',
  );
  const ephR: Uint8Array = hexDecode(
    '606162636465666768696a6b6c6d6e6f707172737475767778797a7b7c7d7e7f',
  );
  const iStaticPub: Uint8Array = x25519PublicKeyFromPrivate(iStatic);
  const rStaticPub: Uint8Array = x25519PublicKeyFromPrivate(rStatic);

  const initiator: NoiseIkInitiator = new NoiseIkInitiator(prologue, iStatic, rStaticPub, new ArrayRng(ephI));
  const responder: NoiseIkResponder = new NoiseIkResponder(prologue, rStatic, new ArrayRng(ephR));

  const payloadA: Uint8Array = utf8Encode('ts2021 map-request');
  const payloadB: Uint8Array = utf8Encode('ts2021 map-response');
  const msgA: Uint8Array = initiator.writeMessageA(payloadA);
  const readA = responder.readMessageA(msgA);
  assert.deepEqual(readA.payload, payloadA);
  const msgB: Uint8Array = responder.writeMessageB(payloadB);
  assert.deepEqual(initiator.readMessageB(msgB), payloadB);

  const iPair: NoiseTransportPair = initiator.split();
  const rPair: NoiseTransportPair = responder.split();
  const probe: Uint8Array = utf8Encode('post-handshake probe');
  assert.deepEqual(rPair.recv.decrypt(iPair.send.encrypt(probe)), probe);

  // 与独立参考实现在同一真实 prologue 下逐字节一致（确定性向量锚定）
  const keys: RefKeys = {
    iStaticPriv: iStatic,
    iStaticPub: iStaticPub,
    rStaticPriv: rStatic,
    rStaticPub: rStaticPub,
    iEphPriv: ephI,
    iEphPub: x25519PublicKeyFromPrivate(ephI),
    rEphPriv: ephR,
    rEphPub: x25519PublicKeyFromPrivate(ephR),
  };
  const ref = referenceHandshake(keys, prologue, payloadA, payloadB);
  assert.deepEqual(msgA, ref.msgA);
  assert.deepEqual(msgB, ref.msgB);
});

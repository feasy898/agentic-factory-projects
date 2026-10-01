/**
 * disco 密封包装层测试。
 *
 * 交叉验证策略（与 crypto/naclbox.test.ts 同法）：与独立参考实现 tweetnacl
 * （devDependency，仅测试可用）互开互验——
 * - 共享密钥：discoSharedKey(A_PRIV,B_PUB) 必须 == nacl.box.before(B_PUB, A_PRIV)
 *   （box.Precompute 同构造）且两侧对称；
 * - 我方 seal → tweetnacl secretbox.open（nonce 取 wrapper 头）；
 * - tweetnacl secretbox seal → 我方 discoOpen。
 * wrapper 布局锚定：magic 6B "TS💬" ‖ senderPub 32B ‖ nonce 24B ‖ tag‖密文。
 */

import { test } from 'node:test';
import assert from 'node:assert/strict';
import nacl from 'tweetnacl';
import { hexDecode, hexEncode } from '@ohos-tailscale/common';
import { x25519PublicKeyFromPrivate } from '@ohos-tailscale/crypto';
import {
  DISCO_MAGIC,
  type DiscoSealed,
  type DiscoUnsealed,
  discoOpen,
  discoSeal,
  discoSharedKey,
  discoSource,
  looksLikeDisco,
  pingEncode,
  pingParse,
} from '../src/index.ts';

const A_PRIV: Uint8Array = new Uint8Array(32).fill(0x11);
const B_PRIV: Uint8Array = new Uint8Array(32).fill(0x22);
const A_PUB: Uint8Array = x25519PublicKeyFromPrivate(A_PRIV);
const B_PUB: Uint8Array = x25519PublicKeyFromPrivate(B_PRIV);
const NONCE: Uint8Array = hexDecode(
  '000102030405060708090a0b0c0d0e0f1011121314151617',
);
const INNER: Uint8Array = pingEncode({
  txid: hexDecode('0f0e0d0c0b0a090807060504'),
  nodeKey: null,
  padding: 0,
});

test('wrapper 头锚定：magic = "TS💬" 6B（54 53 f0 9f 92 ac）', () => {
  assert.equal(DISCO_MAGIC.length, 6);
  assert.equal(hexEncode(DISCO_MAGIC), '5453f09f92ac');
});

test('共享密钥：与 tweetnacl box.before 逐字节一致且两侧对称', () => {
  const ours: Uint8Array = discoSharedKey(A_PRIV, B_PUB);
  const theirs: Uint8Array = nacl.box.before(B_PUB, A_PRIV);
  assert.equal(hexEncode(ours), hexEncode(theirs));
  const reverse: Uint8Array = discoSharedKey(B_PRIV, A_PUB);
  assert.equal(hexEncode(reverse), hexEncode(ours));
});

test('我方 discoSeal → tweetnacl 按头内 nonce 解密（字节级互验）', () => {
  const sealed: DiscoSealed = discoSeal(INNER, A_PRIV, B_PUB, NONCE);
  const w: Uint8Array = sealed.wrapper;
  // 布局：6 magic ‖ 32 senderPub ‖ 24 nonce ‖ tag‖ct
  assert.equal(w.length, 6 + 32 + 24 + INNER.length + 16);
  assert.equal(hexEncode(w.slice(0, 6)), '5453f09f92ac');
  assert.equal(hexEncode(w.slice(6, 38)), hexEncode(A_PUB));
  assert.equal(hexEncode(w.slice(38, 62)), hexEncode(NONCE));
  // tweetnacl 用共享密钥 + 头内 nonce 打开 sealed 段
  const shared: Uint8Array = nacl.box.before(B_PUB, A_PRIV);
  const opened: Uint8Array | null = nacl.secretbox.open(w.slice(62), NONCE, shared);
  assert.ok(opened !== null, 'tweetnacl must open our sealed disco wrapper');
  assert.deepEqual(Array.from(opened), Array.from(INNER));
});

test('tweetnacl secretbox 密封 → 我方 discoOpen（反向互验）', () => {
  const shared: Uint8Array = nacl.box.before(A_PUB, B_PRIV);
  const boxed: Uint8Array = nacl.secretbox(INNER, NONCE, shared);
  const wrapper: Uint8Array = new Uint8Array(6 + 32 + 24 + boxed.length);
  wrapper.set(DISCO_MAGIC, 0);
  wrapper.set(B_PUB, 6);
  wrapper.set(NONCE, 38);
  wrapper.set(boxed, 62);
  const unsealed: DiscoUnsealed | null = discoOpen(wrapper, A_PRIV);
  assert.ok(unsealed !== null, 'we must open a tweetnacl-sealed wrapper');
  assert.equal(hexEncode(unsealed.senderPublic), hexEncode(B_PUB));
  assert.deepEqual(Array.from(unsealed.message), Array.from(INNER));
  // 解出的内层报文可继续走消息层解析
  const ping: ReturnType<typeof pingParse> = pingParse(unsealed.message);
  assert.equal(hexEncode(ping.txid), '0f0e0d0c0b0a090807060504');
});

test('discoOpen：错误接收方/篡改/非 wrapper → null', () => {
  const sealed: DiscoSealed = discoSeal(INNER, A_PRIV, B_PUB, NONCE);
  const w: Uint8Array = sealed.wrapper;

  // 第三方（无私钥 B）打不开
  const cPriv: Uint8Array = new Uint8Array(32).fill(0x33);
  assert.ok(discoOpen(w, cPriv) === null);
  // 篡改密文一个字节 → 认证失败
  const tampered: Uint8Array = w.slice();
  tampered[tampered.length - 1] ^= 0x01;
  assert.ok(discoOpen(tampered, B_PRIV) === null);
  // 非 wrapper：magic 错 / 过短
  const badMagic: Uint8Array = w.slice();
  badMagic[0] = 0x54;
  badMagic[1] = 0x54;
  assert.ok(discoOpen(badMagic, B_PRIV) === null);
  assert.ok(!looksLikeDisco(new Uint8Array(61)));
  assert.ok(discoSource(new Uint8Array(10)) === null);
  // discoSource 取头内公钥
  assert.equal(hexEncode(discoSource(w) as Uint8Array), hexEncode(A_PUB));
});

test('ping 全链路：encode → seal → open → parse（A→B 往返）', () => {
  const ping = {
    txid: hexDecode('aabbccddeeff001122334455'),
    nodeKey: A_PUB,
    padding: 8,
  };
  const sealed: DiscoSealed = discoSeal(pingEncode(ping), A_PRIV, B_PUB, NONCE);
  const unsealed: DiscoUnsealed | null = discoOpen(sealed.wrapper, B_PRIV);
  assert.ok(unsealed !== null);
  const back: ReturnType<typeof pingParse> = pingParse(unsealed.message);
  assert.equal(hexEncode(back.txid), 'aabbccddeeff001122334455');
  assert.ok(back.nodeKey !== null);
  assert.equal(hexEncode(back.nodeKey), hexEncode(A_PUB));
  assert.equal(back.padding, 8);
});

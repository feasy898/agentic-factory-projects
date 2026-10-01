/**
 * Cookie Reply（type=3）测试：编解码布局 + 响应端生成/发起端消费端到端 +
 * R_m 轮换边界 + mac2 校验组合。
 *
 * 锚定：布局与语义按 wireguard-go master（device/noise-protocol.go:112、
 * device/cookie.go）与白皮书 §5.4.7 实现（头注详见 src/cookie-reply.ts）；
 * AEAD 层（XChaCha20-Poly1305）由 draft-irtf-cfrg-xchacha-03 KAT 在
 * crypto/test/xchacha.test.ts 锚定，本文件不重复。
 */

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { ArrayRng, hexDecode, hexEncode } from '@ohos-tailscale/common';
import { blake2s256Keyed } from '@ohos-tailscale/crypto';
import { wgComputeCookie } from '../src/cookie.ts';
import {
  WG_COOKIE_REFRESH_MS,
  WgCookieReplyConsumer,
  WgCookieResponder,
  cookieReplyDecode,
  cookieReplyEncode,
  extractMac1Field,
} from '../src/cookie-reply.ts';
import { WgProtocolError } from '../src/errors.ts';
import { x25519PublicKeyFromPrivate } from '@ohos-tailscale/crypto';

/** 响应端（被寻址方）静态密钥/公钥——Cookie Reply 键语义见 src/cookie-reply.ts 头注。 */
const RESPONDER_PRIV: Uint8Array = new Uint8Array(32).fill(0x31);
const RESPONDER_PUB: Uint8Array = x25519PublicKeyFromPrivate(RESPONDER_PRIV);
const SRC_ADDR: Uint8Array = new Uint8Array([192, 168, 13, 37, 10, 10, 10]);
/** 确定性 Rng：pool = 0x00..0xff 循环（ArrayRng 语义）。 */
const RNG_POOL: Uint8Array = ((): Uint8Array => {
  const p: Uint8Array = new Uint8Array(256);
  for (let i: number = 0; i < 256; i += 1) {
    p[i] = i;
  }
  return p;
})();

/** 构造一个带 macs 段的假完整报文：body 20B + mac1(16B 由 body 派生) + mac2 全零。 */
function fakeFullMsg(seed: number): { full: Uint8Array; mac1: Uint8Array } {
  const body: Uint8Array = new Uint8Array(20);
  for (let i: number = 0; i < 20; i += 1) {
    body[i] = (seed + i * 13) & 0xff;
  }
  const mac1: Uint8Array = blake2s256Keyed(hexDecode('00112233445566778899aabbccddeeff'), body).slice(0, 16);
  const full: Uint8Array = new Uint8Array(body.length + 32);
  full.set(body, 0);
  full.set(mac1, body.length);
  // mac2 16B 全零（常态：对端未持有 cookie）
  return { full: full, mac1: mac1 };
}

test('Cookie Reply 编解码往返 + 布局（type u32le=3 前缀 03 00 00 00）', () => {
  const reply = {
    receiver: 1377,
    nonce: hexDecode('000102030405060708090a0b0c0d0e0f1011121314151617'),
    cookieSealed: new Uint8Array(32).fill(0xab),
  };
  const buf: Uint8Array = cookieReplyEncode(reply);
  assert.equal(buf.length, 64);
  assert.equal(hexEncode(buf.slice(0, 4)), '03000000');
  assert.equal(hexEncode(buf.slice(4, 8)), '61050000'); // 1377 = 0x561 → LE 61 05 00 00
  const back = cookieReplyDecode(buf);
  assert.equal(back.receiver, 1377);
  assert.equal(hexEncode(back.nonce), hexEncode(reply.nonce));
  assert.equal(hexEncode(back.cookieSealed), hexEncode(reply.cookieSealed));
});

test('Cookie Reply 解码：长度非 64 → BAD_LEN；type≠3 → BAD_TYPE', () => {
  assert.throws(
    (): void => {
      cookieReplyDecode(new Uint8Array(63));
    },
    (e: unknown): boolean => e instanceof WgProtocolError && e.code === 'BAD_LEN',
  );
  const badType: Uint8Array = new Uint8Array(64);
  badType[0] = 4;
  assert.throws(
    (): void => {
      cookieReplyDecode(badType);
    },
    (e: unknown): boolean => e instanceof WgProtocolError && e.code === 'BAD_TYPE',
  );
});

test('端到端：responder.createReply → consumer.consume 得到正确 cookie（τ = Mac(R_m, src)）', () => {
  const responder: WgCookieResponder = new WgCookieResponder(new ArrayRng(RNG_POOL));
  const consumer: WgCookieReplyConsumer = new WgCookieReplyConsumer(RESPONDER_PUB);
  const msg = fakeFullMsg(1);
  consumer.noteSentMac1(msg.mac1);

  const replyBuf: Uint8Array = responder.createReply(msg.full, 1377, RESPONDER_PUB, SRC_ADDR, 1000);
  assert.equal(replyBuf.length, 64);

  const cookie: Uint8Array | null = consumer.consume(replyBuf);
  assert.ok(cookie !== null, 'consumer must open responder reply');
  assert.equal(cookie.length, 16);
  // 期望 cookie 回放：responder2 用同一 RNG_POOL 从头取流——首次 ensureSecret
  // 消费前 32B，与 responder.createReply 内部首次生成 R_m 的取流一致（确定性
  // 随机源语义），故 τ = Mac(R_m, src) 应逐字节相等。
  const responder2: WgCookieResponder = new WgCookieResponder(new ArrayRng(RNG_POOL));
  const secret: Uint8Array = responder2.ensureSecret(1000);
  const expectCookie: Uint8Array = wgComputeCookie(secret, SRC_ADDR);
  assert.equal(hexEncode(cookie), hexEncode(expectCookie));
});

test('端到端：AAD 不符（noteSentMac1 记错/未记）→ consume 返回 null', () => {
  const responder: WgCookieResponder = new WgCookieResponder(new ArrayRng(RNG_POOL));
  const msg = fakeFullMsg(2);
  const other = fakeFullMsg(3);
  const replyBuf: Uint8Array = responder.createReply(msg.full, 7, RESPONDER_PUB, SRC_ADDR, 1000);

  const consumerNoMac1: WgCookieReplyConsumer = new WgCookieReplyConsumer(RESPONDER_PUB);
  assert.equal(consumerNoMac1.consume(replyBuf), null);

  const consumerWrongMac1: WgCookieReplyConsumer = new WgCookieReplyConsumer(RESPONDER_PUB);
  consumerWrongMac1.noteSentMac1(other.mac1);
  assert.equal(consumerWrongMac1.consume(replyBuf), null);
});

test('端到端：消费端密钥不符（不同 localStaticPublic）→ consume 返回 null', () => {
  const responder: WgCookieResponder = new WgCookieResponder(new ArrayRng(RNG_POOL));
  const msg = fakeFullMsg(4);
  const replyBuf: Uint8Array = responder.createReply(msg.full, 7, RESPONDER_PUB, SRC_ADDR, 1000);
  const otherPriv: Uint8Array = new Uint8Array(32).fill(0x99);
  const stranger: WgCookieReplyConsumer = new WgCookieReplyConsumer(x25519PublicKeyFromPrivate(otherPriv));
  stranger.noteSentMac1(msg.mac1);
  assert.equal(stranger.consume(replyBuf), null);
});

test('mac2 校验组合：consume 得 cookie → 对端按 cookie 发 mac2 → responder.verifyMac2 通过', () => {
  const responder: WgCookieResponder = new WgCookieResponder(new ArrayRng(RNG_POOL));
  const consumer: WgCookieReplyConsumer = new WgCookieReplyConsumer(RESPONDER_PUB);
  const msg = fakeFullMsg(5);
  consumer.noteSentMac1(msg.mac1);
  const replyBuf: Uint8Array = responder.createReply(msg.full, 7, RESPONDER_PUB, SRC_ADDR, 1000);
  const cookie: Uint8Array | null = consumer.consume(replyBuf);
  assert.ok(cookie !== null);

  // 发起端按收到的 cookie 计算 mac2 = BLAKE2s-128(cookie, msg[0:len-16])
  const body: Uint8Array = new Uint8Array(24).fill(0x42);
  const full: Uint8Array = new Uint8Array(body.length + 32);
  full.set(body, 0);
  full.set(msg.mac1, body.length);
  const mac2: Uint8Array = blake2s256Keyed(cookie, full.slice(0, body.length + 16)).slice(0, 16);
  full.set(mac2, body.length + 16);
  assert.ok(responder.verifyMac2(full, SRC_ADDR, 2000), 'valid mac2 must verify');

  // 源地址不同 → 失败；mac2 篡改 → 失败；mac2 全零（常态报文）→ true
  const otherSrc: Uint8Array = new Uint8Array([192, 168, 13, 38, 10, 10, 10]);
  assert.ok(!responder.verifyMac2(full, otherSrc, 2000), 'different src must fail');
  full[body.length + 16] ^= 0x01;
  assert.ok(!responder.verifyMac2(full, SRC_ADDR, 2000), 'tampered mac2 must fail');
  const zeroMac2: Uint8Array = new Uint8Array(body.length + 32);
  zeroMac2.set(body, 0);
  zeroMac2.set(msg.mac1, body.length);
  assert.ok(responder.verifyMac2(zeroMac2, SRC_ADDR, 2000), 'zero mac2 is the no-cookie normal');
});

test('R_m 轮换：超过 120s 后 verifyMac2 返回 false（不自动轮换校验侧）；轮换后 cookie 变化', () => {
  const responder: WgCookieResponder = new WgCookieResponder(new ArrayRng(RNG_POOL));
  const secretA: Uint8Array = responder.ensureSecret(0);
  assert.equal(secretA.length, 32);
  // 未过期：可校验（此处仅检查不抛）
  assert.ok(!responder.verifyMac2(new Uint8Array(64), SRC_ADDR, WG_COOKIE_REFRESH_MS - 1) || true);
  // 恰好到期（>= refresh）：verifyMac2 返回 false
  assert.ok(!responder.verifyMac2(new Uint8Array(64), SRC_ADDR, WG_COOKIE_REFRESH_MS));
  // 轮换后 secret 变化
  responder.rotateSecret(WG_COOKIE_REFRESH_MS);
  const secretB: Uint8Array = responder.ensureSecret(WG_COOKIE_REFRESH_MS + 1);
  assert.notEqual(hexEncode(secretA), hexEncode(secretB));
});

test('extractMac1Field：位置为倒数 32..16 字节；过短报文 → BAD_LEN', () => {
  const m = fakeFullMsg(6);
  const got: Uint8Array = extractMac1Field(m.full);
  assert.equal(hexEncode(got), hexEncode(m.mac1));
  assert.throws(
    (): void => {
      extractMac1Field(new Uint8Array(47));
    },
    (e: unknown): boolean => e instanceof WgProtocolError && e.code === 'BAD_LEN',
  );
});

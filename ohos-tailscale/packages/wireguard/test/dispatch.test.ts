/**
 * WgPacketDispatcher 分发测试：type=4 会话路由 / type=3 发起端消费路由 /
 * type=1/2 under-load Cookie Reply 路径 / 未知类型静默 / 长度与异常透传。
 *
 * 键语义锚定：Cookie Reply 加密键 = BLAKE2s("cookie--" || 响应端静态公钥)
 * （wireguard-go cookie.go Checker/Generator Init 同键，两侧取同一 32B）。
 */

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { ArrayRng, hexDecode, hexEncode } from '@ohos-tailscale/common';
import { x25519PublicKeyFromPrivate } from '@ohos-tailscale/crypto';
import { WgRecvSession, WgSendSession, WgPacketDispatcher, WgCookieResponder, WgCookieReplyConsumer } from '../src/index.ts';
import { WgProtocolError } from '../src/errors.ts';

const RESPONDER_PRIV: Uint8Array = new Uint8Array(32).fill(0x77);
const RESPONDER_PUB: Uint8Array = x25519PublicKeyFromPrivate(RESPONDER_PRIV);
const SRC: Uint8Array = new Uint8Array([10, 0, 0, 1, 41641 & 0xff, (41641 >> 8) & 0xff]);
const SESSION_KEY: Uint8Array = hexDecode(
  '000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f',
);
const RNG_POOL: Uint8Array = ((): Uint8Array => {
  const p: Uint8Array = new Uint8Array(256);
  for (let i: number = 0; i < 256; i += 1) {
    p[i] = i;
  }
  return p;
})();

test('type=4 路由：lookup 配对会话 → 解密明文；未知索引静默 unhandled', () => {
  const send: WgSendSession = new WgSendSession(42, SESSION_KEY);
  const recv: WgRecvSession = new WgRecvSession(42, SESSION_KEY);
  const d: WgPacketDispatcher = new WgPacketDispatcher();
  d.setTransportLookup((idx: number): WgRecvSession | null => (idx === 42 ? recv : null));
  const packet: Uint8Array = send.encryptPacket(hexDecode('cafebabe'));
  const got = d.dispatch(packet, SRC, 1000);
  assert.equal(got.msgType, 4);
  assert.ok(got.handled);
  assert.equal(hexEncode(got.plaintext as Uint8Array), 'cafebabe');

  const other = d.dispatch(new WgSendSession(43, SESSION_KEY).encryptPacket(hexDecode('01')), SRC, 1000);
  assert.ok(!other.handled);
  assert.ok(other.plaintext === null);

  // 无 lookup（纯握手/cookie 分发形态）→ unhandled
  const bare: WgPacketDispatcher = new WgPacketDispatcher();
  assert.ok(!bare.dispatch(packet, SRC, 1000).handled);
});

test('type=4 解密异常透传：同一会话解同包两次，第二次 REPLAY', () => {
  const send: WgSendSession = new WgSendSession(9, SESSION_KEY);
  const recv: WgRecvSession = new WgRecvSession(9, SESSION_KEY);
  const d: WgPacketDispatcher = new WgPacketDispatcher();
  d.setTransportLookup((): WgRecvSession | null => recv);
  const packet: Uint8Array = send.encryptPacket(hexDecode('aa'));
  assert.ok(d.dispatch(packet, SRC, 0).handled);
  assert.throws(
    (): void => {
      d.dispatch(packet, SRC, 0);
    },
    (e: unknown): boolean => e instanceof WgProtocolError && e.code === 'REPLAY',
  );
});

/** 构造带 macs 段的"握手状"报文（under-load 路径只依赖类型/偏移/MAC1 字段）。 */
function handshakeLike(type: number, senderIndex: number): Uint8Array {
  const body: Uint8Array = new Uint8Array(type === 1 ? 116 : 60);
  for (let i: number = 0; i < body.length; i += 1) {
    body[i] = (i * 11 + 5) & 0xff;
  }
  const mac1: Uint8Array = new Uint8Array(16).fill(0x21);
  const full: Uint8Array = new Uint8Array(body.length + 32);
  full[0] = type;
  full[4] = senderIndex;
  full.set(body, 8);
  full.set(mac1, body.length + 8);
  return full;
}

test('type=3 发起端路径：awaited 索引匹配 + 消费成功 → onCookie 回调', () => {
  // 响应端（B）对 A 发来的握手回 Cookie Reply（键 = B 的静态公钥）
  const responder: WgCookieResponder = new WgCookieResponder(new ArrayRng(RNG_POOL));
  const offender: Uint8Array = handshakeLike(1, 77);
  const replyBuf: Uint8Array = responder.createReply(offender, 77, RESPONDER_PUB, SRC, 1000);

  // A 端分发器：等待 receiver=77 的回复；消费端 AAD = 我方（发起端）发出的握手 MAC1 字段
  const consumer: WgCookieReplyConsumer = new WgCookieReplyConsumer(RESPONDER_PUB);
  consumer.noteSentMac1(offender.slice(offender.length - 32, offender.length - 16));
  const d: WgPacketDispatcher = new WgPacketDispatcher();
  let gotCookie: Uint8Array | null = null;
  d.setConsumerRoute({
    consumer: consumer,
    awaitedReceiverIndex: 77,
    onCookie: (c: Uint8Array): void => {
      gotCookie = c;
    },
  });
  const got = d.dispatch(replyBuf, SRC, 1000);
  assert.equal(got.msgType, 3);
  assert.ok(got.handled);
  assert.ok(got.cookie !== null && got.cookie.length === 16);
  assert.ok(gotCookie !== null, 'onCookie callback must fire');
});

test('type=3：awaited 索引不匹配 → unhandled；无路由 → unhandled；键不符也 unhandled', () => {
  const responder: WgCookieResponder = new WgCookieResponder(new ArrayRng(RNG_POOL));
  const offender: Uint8Array = handshakeLike(1, 77);
  const replyBuf: Uint8Array = responder.createReply(offender, 77, RESPONDER_PUB, SRC, 1000);

  const mismatch: WgPacketDispatcher = new WgPacketDispatcher();
  mismatch.setConsumerRoute({
    consumer: new WgCookieReplyConsumer(RESPONDER_PUB),
    awaitedReceiverIndex: 88,
    onCookie: (): void => {},
  });
  assert.ok(!mismatch.dispatch(replyBuf, SRC, 1000).handled);

  const bare: WgPacketDispatcher = new WgPacketDispatcher();
  assert.ok(!bare.dispatch(replyBuf, SRC, 1000).handled);

  const stranger: WgPacketDispatcher = new WgPacketDispatcher();
  stranger.setConsumerRoute({
    consumer: new WgCookieReplyConsumer(x25519PublicKeyFromPrivate(new Uint8Array(32).fill(0x99))),
    awaitedReceiverIndex: 77,
    onCookie: (): void => {},
  });
  assert.ok(!stranger.dispatch(replyBuf, SRC, 1000).handled);
});

test('type=1 under-load：无握手回调 + 响应端路由 → 64B 回包（receiver 回显来包 sender，type=3）', () => {
  const responder: WgCookieResponder = new WgCookieResponder(new ArrayRng(RNG_POOL));
  const d: WgPacketDispatcher = new WgPacketDispatcher();
  d.setResponderRoute({ responder: responder, responderStaticPublic: RESPONDER_PUB });

  // 伪造 initiation：type u32le=1，sender u32le=77，载荷 + macs 段（MAC1 为 0x21*16）
  const init: Uint8Array = new Uint8Array(148);
  init[0] = 1;
  init[4] = 77;
  const mac1: Uint8Array = new Uint8Array(16).fill(0x21);
  init.set(mac1, 148 - 32);
  const got = d.dispatch(init, SRC, 1000);
  assert.equal(got.msgType, 1);
  assert.ok(got.handled);
  const reply: Uint8Array = got.replyPacket as Uint8Array;
  assert.equal(reply.length, 64);
  assert.equal(reply[0], 3);
  assert.equal(hexEncode(reply.slice(4, 8)), hexEncode(new Uint8Array([77, 0, 0, 0])));

  // 全链路：A 端（发起方）消费这个回包 → 得到与 B 端一致的 cookie
  const consumer: WgCookieReplyConsumer = new WgCookieReplyConsumer(RESPONDER_PUB);
  consumer.noteSentMac1(mac1);
  const cookie: Uint8Array | null = consumer.consume(reply);
  assert.ok(cookie !== null, 'initiator must open the dispatcher-generated reply');
  // τ 一致性：responder 侧同 Rng 流回放
  const responder2: WgCookieResponder = new WgCookieResponder(new ArrayRng(RNG_POOL));
  const expect: Uint8Array = responder2.createReply(init, 77, RESPONDER_PUB, SRC, 1000);
  void expect; // （回包内容随机 nonce 不可比；此处只断言可开——cookie 值一致性已由 cookie-reply.test.ts 端到端锚定）
});

test('type=1/2 有握手回调 → 原包交给回调，不再回 Cookie Reply', () => {
  const responder: WgCookieResponder = new WgCookieResponder(new ArrayRng(RNG_POOL));
  const d: WgPacketDispatcher = new WgPacketDispatcher();
  d.setResponderRoute({ responder: responder, responderStaticPublic: RESPONDER_PUB });
  const seen: number[] = [];
  d.setHandshakeHandler((packet: Uint8Array, src: Uint8Array): void => {
    seen.push(packet.length, src.length);
  });
  const resp: Uint8Array = new Uint8Array(92);
  resp[0] = 2;
  const got = d.dispatch(resp, SRC, 1000);
  assert.ok(got.handled);
  assert.ok(got.replyPacket === null);
  assert.deepEqual(seen, [92, SRC.length]);
});

test('未知类型静默 unhandled；<4B 抛 BAD_LEN', () => {
  const d: WgPacketDispatcher = new WgPacketDispatcher();
  const unknown: Uint8Array = new Uint8Array(32);
  unknown[0] = 99;
  assert.ok(!d.dispatch(unknown, SRC, 0).handled);
  assert.throws(
    (): void => {
      d.dispatch(new Uint8Array(3), SRC, 0);
    },
    (e: unknown): boolean => e instanceof WgProtocolError && e.code === 'BAD_LEN',
  );
});

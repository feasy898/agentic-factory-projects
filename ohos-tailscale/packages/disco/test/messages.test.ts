/**
 * disco 消息编解码测试（tailscale disco/disco.go 上游对齐验证）。
 *
 * 锚定：布局断言按上游 marshal 代码逐字段写死（Ping=2+12+32(+padding)、
 * Pong=2+30、CallMeMaybe=2+18N；端口一律 u16be；IP 一律 16B，IPv4 用
 * v4-mapped）；宽松解析语义（超长 Ping 计 padding、畸形 CMM 返回空表）
 * 与上游 parsePing/parseCallMeMaybe 一致。
 */

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { hexDecode, hexEncode } from '@ohos-tailscale/common';
import {
  DiscoError,
  DiscoMessageType,
  callMeMaybeEncode,
  callMeMaybeParse,
  discoMessageParse,
  ip16IsV4Mapped,
  pingEncode,
  pingParse,
  pongEncode,
  pongParse,
  unmapIp16,
} from '../src/index.ts';

const TXID: Uint8Array = hexDecode('000102030405060708090a0b');
const NODE_KEY: Uint8Array = hexDecode(
  '1122334455667788112233445566778811223344556677881122334455667788',
);
const IP4_MAPPED: Uint8Array = hexDecode('00000000000000000000ffffc0a8017c'); // ::ffff:198.51.100.21
const IP6: Uint8Array = hexDecode('20010db8000000000000000000000001');

test('Ping 编码：带 NodeKey + padding 的完整布局', () => {
  const ping = {
    txid: TXID,
    nodeKey: NODE_KEY,
    padding: 5,
  };
  const buf: Uint8Array = pingEncode(ping);
  assert.equal(buf.length, 2 + 12 + 32 + 5);
  assert.equal(buf[0], 0x01);
  assert.equal(buf[1], 0x00);
  assert.equal(hexEncode(buf.slice(2, 14)), hexEncode(TXID));
  assert.equal(hexEncode(buf.slice(14, 46)), hexEncode(NODE_KEY));
  // padding 尾部全零
  for (let i: number = 46; i < buf.length; i += 1) {
    assert.equal(buf[i], 0);
  }
});

test('Ping 编码：null 或全零 NodeKey 都不编码（上游 IsZero 语义）', () => {
  const withNull = { txid: TXID, nodeKey: null, padding: 0 };
  const withZero = { txid: TXID, nodeKey: new Uint8Array(32), padding: 0 };
  const a: Uint8Array = pingEncode(withNull);
  const b: Uint8Array = pingEncode(withZero);
  assert.equal(a.length, 14);
  assert.equal(hexEncode(a), hexEncode(b));
});

test('Ping 解析往返；超长尾部计入 padding（上游宽松语义）；<14B 抛 SHORT', () => {
  const ping = { txid: TXID, nodeKey: NODE_KEY, padding: 3 };
  const back: ReturnType<typeof pingParse> = pingParse(pingEncode(ping));
  assert.equal(hexEncode(back.txid), hexEncode(TXID));
  assert.ok(back.nodeKey !== null);
  assert.equal(hexEncode(back.nodeKey), hexEncode(NODE_KEY));
  assert.equal(back.padding, 3);

  // 上游客户端未来扩展：多出的尾字节全部算 padding
  const long = { txid: TXID, nodeKey: NODE_KEY, padding: 40 };
  const parsedLong: ReturnType<typeof pingParse> = pingParse(pingEncode(long));
  assert.equal(parsedLong.padding, 40);

  // 无键报文解析：nodeKey = null，padding = 0
  const noKey: ReturnType<typeof pingParse> = pingParse(pingEncode({ txid: TXID, nodeKey: null, padding: 0 }));
  assert.ok(noKey.nodeKey === null);
  assert.equal(noKey.padding, 0);

  assert.throws(
    (): void => {
      pingParse(new Uint8Array(13));
    },
    (e: unknown): boolean => e instanceof DiscoError && e.code === 'SHORT',
  );
});

test('Pong 编解码往返 + v4-mapped 布局（端口 u16be）', () => {
  const pong = { txid: TXID, srcIp16: IP4_MAPPED, srcPort: 41641 };
  const buf: Uint8Array = pongEncode(pong);
  assert.equal(buf.length, 2 + 30);
  assert.equal(buf[0], 0x02);
  // 端口 41641 = 0xA2A9 → be 字节 a2 a9（位于 2+12+16 = 30 偏移）
  assert.equal(hexEncode(buf.slice(30, 32)), 'a2a9');
  const back: ReturnType<typeof pongParse> = pongParse(buf);
  assert.equal(hexEncode(back.txid), hexEncode(TXID));
  assert.equal(hexEncode(back.srcIp16), hexEncode(IP4_MAPPED));
  assert.equal(back.srcPort, 41641);
  assert.ok(ip16IsV4Mapped(back.srcIp16));
  assert.equal(hexEncode(unmapIp16(back.srcIp16)), 'c0a8017c');

  const pong6 = { txid: TXID, srcIp16: IP6, srcPort: 1 };
  const back6: ReturnType<typeof pongParse> = pongParse(pongEncode(pong6));
  assert.ok(!ip16IsV4Mapped(back6.srcIp16));
  assert.equal(unmapIp16(back6.srcIp16).length, 16);

  assert.throws(
    (): void => {
      pongParse(new Uint8Array(2 + 29));
    },
    (e: unknown): boolean => e instanceof DiscoError && e.code === 'SHORT',
  );
});

test('CallMeMaybe 编解码往返（多端点）', () => {
  const cmm = {
    myNumber: [
      { ip16: IP4_MAPPED, port: 41641 },
      { ip16: IP6, port: 12345 },
    ],
  };
  const buf: Uint8Array = callMeMaybeEncode(cmm);
  assert.equal(buf.length, 2 + 18 * 2);
  assert.equal(buf[0], 0x03);
  const back: ReturnType<typeof callMeMaybeParse> = callMeMaybeParse(buf);
  assert.equal(back.myNumber.length, 2);
  assert.equal(hexEncode(back.myNumber[0].ip16), hexEncode(IP4_MAPPED));
  assert.equal(back.myNumber[0].port, 41641);
  assert.equal(hexEncode(back.myNumber[1].ip16), hexEncode(IP6));
  assert.equal(back.myNumber[1].port, 12345);
});

test('CallMeMaybe 宽松语义：畸形/空/版本非 0 → 空端点列表（不抛错）', () => {
  // 长度非 18 倍数
  const malformed: Uint8Array = new Uint8Array(2 + 18 + 5);
  malformed[0] = 0x03;
  assert.equal(callMeMaybeParse(malformed).myNumber.length, 0);
  // 空载荷
  const empty: Uint8Array = new Uint8Array(2);
  empty[0] = 0x03;
  assert.equal(callMeMaybeParse(empty).myNumber.length, 0);
  // version ≠ 0
  const badVer: Uint8Array = new Uint8Array(2 + 18);
  badVer[0] = 0x03;
  badVer[1] = 1;
  assert.equal(callMeMaybeParse(badVer).myNumber.length, 0);
});

test('discoMessageParse：类型分发 + 未实现/未知类型抛 TYPE', () => {
  const decPong: ReturnType<typeof discoMessageParse> = discoMessageParse(
    pongEncode({ txid: TXID, srcIp16: IP6, srcPort: 443 }),
  );
  assert.equal(decPong.kind, DiscoMessageType.Pong);
  assert.equal(decPong.version, 0);
  assert.ok(decPong.pong !== null);
  assert.ok(decPong.ping === null);
  assert.ok(decPong.callMeMaybe === null);

  // 上游已注册但本轮未实现的 UDP relay 家族（0x04）→ 与未知类型同途
  const relay: Uint8Array = new Uint8Array(2 + 8);
  relay[0] = 0x04;
  assert.throws(
    (): void => {
      discoMessageParse(relay);
    },
    (e: unknown): boolean => e instanceof DiscoError && e.code === 'TYPE',
  );
  const unknown: Uint8Array = new Uint8Array(4);
  unknown[0] = 0x7f;
  assert.throws(
    (): void => {
      discoMessageParse(unknown);
    },
    (e: unknown): boolean => e instanceof DiscoError && e.code === 'TYPE',
  );
});

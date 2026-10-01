/**
 * Cookie 机制骨架测试：
 * - LABEL 字节（"mac1----"/"cookie--"）与 mac1 键派生向量；
 * - mac1/mac2 计算与独立 keyed-BLAKE2s 表达式一致（截断 16B）；
 * - wgComputeCookie 结构（ip 长度/port/秒 拒绝域）；
 * - WgCookieCache 存取/拷贝语义/过期清理；
 * - wgVerifyMac2Field 三分支；握手集成（provideCookie → mac2 字节/响应端校验）。
 */

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { ArrayRng, FixedClock, hexDecode, hexEncode, utf8Encode } from '@ohos-tailscale/common';
import { blake2s256, blake2s256Keyed, x25519GenerateKeyPair } from '@ohos-tailscale/crypto';
import {
  WgCookieCache,
  WgHandshakeInitiator,
  WgHandshakeResponder,
  wgComputeCookie,
  wgComputeMac1,
  wgComputeMac2,
  wgCookieKey,
  wgMac2KeyFromCookie,
  wgMac1Key,
  wgVerifyMac2Field,
} from '../src/index.ts';
import { WgProtocolError } from '../src/errors.ts';

/** 确定性字节序列（测试夹具）。 */
const seqBytes = (n: number, seed: number): Uint8Array => {
  const out: Uint8Array = new Uint8Array(n);
  for (let i: number = 0; i < n; i += 1) {
    out[i] = (seed + i * 31) % 256;
  }
  return out;
};


const assertWgError = (fn: () => void, code: string): void => {
  let thrown: boolean = false;
  let gotCode: string = '';
  try {
    fn();
  } catch (e) {
    thrown = true;
    const err: WgProtocolError = e as WgProtocolError;
    gotCode = err.code;
  }
  assert.equal(thrown, true, 'expected WgProtocolError not thrown');
  assert.equal(gotCode, code, 'unexpected WgProtocolError code');
};

// 与 handshake.test.ts 相同的确定性静态密钥
const staticA = x25519GenerateKeyPair(new ArrayRng(seqBytes(32, 11)));
const staticB = x25519GenerateKeyPair(new ArrayRng(seqBytes(32, 22)));

test('LABEL 常量字节 = "mac1----" / "cookie--"（白皮书 5.4.7）', () => {
  assert.equal(hexEncode(utf8Encode('mac1----')), '6d6163312d2d2d2d');
  assert.equal(hexEncode(utf8Encode('cookie--')), '636f6f6b69652d2d');
});

test('wgMac1Key/wgCookieKey 键派生（确定性向量 + 独立表达式对照）', () => {
  // 由本实现确定性输出锁定的回归向量（ArrayRng seq(11)/seq(22) 静态密钥）
  assert.equal(hexEncode(staticB.publicKey), 'fa6fb15897363cb12ffd3987a6a8501a47b9053fc320474b4dc6241ebda2925f');
  const mac1Key: Uint8Array = wgMac1Key(staticB.publicKey);
  assert.equal(hexEncode(mac1Key), '1f96ed6d72e279de71a908ad8294f609896d6e870c497ced4f702682c557226b');
  // 独立表达式：HASH(LABEL_MAC1 || spub)
  const label1: Uint8Array = utf8Encode('mac1----');
  const manual1: Uint8Array = new Uint8Array(8 + 32);
  manual1.set(label1, 0);
  manual1.set(staticB.publicKey, 8);
  assert.deepEqual(mac1Key, blake2s256(manual1), 'mac1 key vs manual hash');
  // cookie 键同理
  const label2: Uint8Array = utf8Encode('cookie--');
  const manual2: Uint8Array = new Uint8Array(8 + 32);
  manual2.set(label2, 0);
  manual2.set(staticA.publicKey, 8);
  assert.deepEqual(wgCookieKey(staticA.publicKey), blake2s256(manual2));
  // 不同对端公钥 → 不同键
  assert.notDeepEqual(wgMac1Key(staticA.publicKey), wgMac1Key(staticB.publicKey));
});

test('wgComputeMac1/wgComputeMac2 = keyed-BLAKE2s 截断 16B', () => {
  const msg: Uint8Array = seqBytes(116, 7);
  const mac1Key: Uint8Array = wgMac1Key(staticB.publicKey);
  const mac1: Uint8Array = wgComputeMac1(mac1Key, msg);
  assert.equal(mac1.length, 16);
  assert.deepEqual(mac1, blake2s256Keyed(mac1Key, msg).slice(0, 16));
  const cookie: Uint8Array = hexDecode('00112233445566778899aabbccddeeff');
  const mac2Key: Uint8Array = wgMac2KeyFromCookie(cookie);
  const msg2: Uint8Array = seqBytes(132, 9);
  const mac2: Uint8Array = wgComputeMac2(mac2Key, msg2);
  assert.equal(mac2.length, 16);
  assert.deepEqual(mac2, blake2s256Keyed(mac2Key, msg2).slice(0, 16));
  // 输入任何一字节变化 → mac 变化
  const msgBad: Uint8Array = msg.slice();
  msgBad[50] = (msgBad[50] ^ 0x01) & 0xff;
  assert.notDeepEqual(wgComputeMac1(mac1Key, msgBad), mac1);
});

test('wgMac2KeyFromCookie：mac2 键 = cookie 本身（白皮书 5.4.4 Mac(L_m,msg)）', () => {
  const cookie: Uint8Array = hexDecode('00112233445566778899aabbccddeeff');
  const key: Uint8Array = wgMac2KeyFromCookie(cookie);
  assert.deepEqual(key, cookie, 'mac2 key must be the cookie itself');
  // 返回独立拷贝：改返回值不影响调用方的 cookie
  const before: number = cookie[0];
  (key as Uint8Array)[0] = (before ^ 0xff) & 0xff;
  assert.equal(cookie[0], before, 'returned key must be an independent copy');
  assert.throws(() => wgMac2KeyFromCookie(seqBytes(15, 1)));
  assert.throws(() => wgMac2KeyFromCookie(seqBytes(17, 1)));
});

test('wgComputeCookie = Mac(R_m, 源地址)（白皮书 5.4.7 / wireguard-go cookie.go:98）', () => {
  const secret: Uint8Array = seqBytes(32, 21); // R_m：2 分钟轮换的随机秘密（调用方注入）
  const srcV4: Uint8Array = hexDecode('c0a80101' + 'a2c9'); // IPv4 + BE16 端口（编组二期随传输层核对）
  const c1: Uint8Array = wgComputeCookie(secret, srcV4);
  assert.equal(c1.length, 16);
  // 独立表达式对照 + 确定性
  assert.deepEqual(c1, blake2s256Keyed(secret, srcV4).slice(0, 16));
  assert.deepEqual(wgComputeCookie(secret, srcV4), c1);
  // 任一输入变化 → cookie 变化
  assert.notDeepEqual(wgComputeCookie(seqBytes(32, 22), srcV4), c1);
  assert.notDeepEqual(wgComputeCookie(secret, hexDecode('c0a80102' + 'a2c9')), c1);
  assert.notDeepEqual(wgComputeCookie(secret, hexDecode('c0a80101' + 'a2ca')), c1);
  // 拒绝域：secret 须 32B；源地址 1..32B
  assert.throws(() => wgComputeCookie(seqBytes(31, 1), srcV4));
  assert.throws(() => wgComputeCookie(seqBytes(33, 1), srcV4));
  assert.throws(() => wgComputeCookie(secret, new Uint8Array(0)));
  assert.throws(() => wgComputeCookie(secret, seqBytes(33, 2)));
  assert.equal(wgComputeCookie(secret, hexDecode('7f00' + '00' + '01')).length, 16);
});

test('WgCookieCache 存取/拷贝/过期清理', () => {
  const cache: WgCookieCache = new WgCookieCache();
  const key1: Uint8Array = wgMac1Key(staticB.publicKey);
  const key2: Uint8Array = wgMac1Key(staticA.publicKey);
  assert.equal(cache.size(), 0);
  assert.equal(cache.cookieFor(key1), null);
  const c1: Uint8Array = hexDecode('000102030405060708090a0b0c0d0e0f');
  cache.update(key1, c1, 1000);
  cache.update(key2, hexDecode('feedfacefeedfacefeedfacefeedface'), 2500);
  assert.equal(cache.size(), 2);
  const got: Uint8Array | null = cache.cookieFor(key1);
  assert.notEqual(got, null);
  assert.deepEqual(got, c1);
  // 返回独立拷贝：改返回值/改源不影响缓存
  (got as Uint8Array)[0] = 0xff;
  c1[0] = 0xff;
  assert.deepEqual(cache.cookieFor(key1), hexDecode('000102030405060708090a0b0c0d0e0f'));
  // 同键更新覆盖
  cache.update(key1, hexDecode('ffffffffffffffffffffffffffffffff'), 3000);
  assert.deepEqual(cache.cookieFor(key1), hexDecode('ffffffffffffffffffffffffffffffff'));
  assert.equal(cache.size(), 2);
  // 过期清理：仅清 updatedMs < now - maxAge（阈值 2000：key1 首次 1000 已被覆盖为 3000？）
  // —— 覆盖后 key1.updatedMs=3000 保留，key2.updatedMs=2500 保留：
  assert.equal(cache.dropStale(3000, 1000), 0);
  assert.equal(cache.size(), 2);
  // 新增一条旧条目（updatedMs=500）后清理，只清它
  const key3: Uint8Array = wgCookieKey(staticA.publicKey);
  cache.update(key3, hexDecode('12121212121212121212121212121212'), 500);
  assert.equal(cache.dropStale(3000, 1000), 1);
  assert.equal(cache.size(), 2);
  assert.notEqual(cache.cookieFor(key1), null);
  assert.notEqual(cache.cookieFor(key2), null);
  assert.equal(cache.cookieFor(key3), null);
  // 长度违规
  assert.throws(() => cache.update(seqBytes(31, 1), c1, 0));
  assert.throws(() => cache.update(key1, seqBytes(15, 1), 0));
});

test('wgVerifyMac2Field：全零放行 / 有 cookie 比对 / 无 cookie 拒绝', () => {
  const zeros: Uint8Array = new Uint8Array(16);
  const cookie: Uint8Array = hexDecode('aabbccddeeff00112233445566778899');
  const expect: Uint8Array = wgComputeMac2(wgMac2KeyFromCookie(cookie), seqBytes(132, 5));
  wgVerifyMac2Field(zeros, null); // 全零恒放行
  wgVerifyMac2Field(zeros, expect);
  wgVerifyMac2Field(expect, expect); // 一致放行
  assertWgError(() => wgVerifyMac2Field(expect, null), 'MAC'); // 非零无 cookie
  const bad: Uint8Array = expect.slice();
  bad[0] = (bad[0] ^ 0x01) & 0xff;
  assertWgError(() => wgVerifyMac2Field(bad, expect), 'MAC'); // 不一致
});

test('握手集成：provideCookie → initiation mac2 按公式；响应端可验', () => {
  const clock: FixedClock = new FixedClock(1717000000123);
  const cookie: Uint8Array = hexDecode('11223344556677889900aabbccddeeff');
  const noCookieInit: WgHandshakeInitiator = new WgHandshakeInitiator(
    staticA.privateKey,
    staticB.publicKey,
    new ArrayRng(seqBytes(36, 101)),
    clock,
  );
  const initPlain: Uint8Array = noCookieInit.createInitiation();
  assert.deepEqual(initPlain.slice(132), new Uint8Array(16), 'mac2 must be all-zero without cookie');

  const withCookieInit: WgHandshakeInitiator = new WgHandshakeInitiator(
    staticA.privateKey,
    staticB.publicKey,
    new ArrayRng(seqBytes(36, 101)),
    clock,
  );
  withCookieInit.provideCookie(cookie);
  const initCookie: Uint8Array = withCookieInit.createInitiation();
  // 除 mac2 段外与无 cookie 版本逐字节一致（同 rng/时钟）
  assert.deepEqual(initCookie.slice(0, 132), initPlain.slice(0, 132));
  const expectMac2: Uint8Array = wgComputeMac2(wgMac2KeyFromCookie(cookie), initCookie.subarray(0, 132));
  assert.deepEqual(initCookie.slice(132), expectMac2, 'mac2 field must match formula');

  // 响应端登记"已发 cookie"后可通过校验
  const responder: WgHandshakeResponder = new WgHandshakeResponder(
    staticB.privateKey,
    new ArrayRng(seqBytes(36, 202)),
    clock,
  );
  assertWgError(() => responder.consumeInitiation(initCookie), 'MAC');
  responder.provideCookieSent(cookie);
  const info = responder.consumeInitiation(initCookie);
  assert.equal(info.senderIndex, 2726519877);
  // mac2 覆盖不含 macs 段：改动 mac2 之外任一字节应仍被 mac1 拦截（顺序：mac1 先）
  const tampered: Uint8Array = initCookie.slice();
  tampered[40] = (tampered[40] ^ 0x01) & 0xff;
  const responder2: WgHandshakeResponder = new WgHandshakeResponder(
    staticB.privateKey,
    new ArrayRng(seqBytes(36, 202)),
    clock,
  );
  responder2.provideCookieSent(cookie);
  assertWgError(() => responder2.consumeInitiation(tampered), 'MAC');
});

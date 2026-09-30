/**
 * STUN 线格式测试。
 *
 * 外部锚定（全部 2026-10-01 实拉原文）：
 * - XOR-MAPPED-ADDRESS 解码：RFC 5769 §2.2 / §2.3 官方向量（IPv4
 *   192.0.2.1:32853、IPv6 2001:db8:1234:5678:11:2233:4455:6677:32853，
 *   rfc-editor.org/rfc/rfc5769.txt）。
 * - CRC32-IEEE：规范 KAT "123456789" → 0xCBF43926。
 * - Binding Request 编码黄金样本：40B 全 hex 写死；指纹字段 = python3
 *   zlib.crc32（独立 IEEE 实现）按上游 net/stun/stun.go Request() 布局计算
 *   （prefix crc32 = d9fff8de，^ "STUN" = 8aabad90）。
 * - 服务端视角 ParseBindingRequest 的软件/指纹校验链与错误码对齐上游错误集。
 */

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { ArrayRng, FixedClock, hexDecode, hexEncode } from '@ohos-tailscale/common';
import {
  StunError,
  StunTransaction,
  crc32Ieee,
  stunIs,
  stunParseBindingRequest,
  stunParseResponse,
  stunRequest,
  stunResponse,
} from '../src/index.ts';

const TXID: Uint8Array = hexDecode('000102030405060708090a0b');

/** RFC 5769 §2.2：Sample IPv4 Response（完整 60+4B）。 */
const RFC5769_V4: Uint8Array = hexDecode(
  '0101003c2112a442b7e7a701bc34d686fa87dfae' +
    '8022000b7465737420766563746f7220' +
    '002000080001a147e112a643' +
    '000800142b91f599fd9e90c38c7489f92af9ba53f06be7d7' +
    '80280004c07d4c96',
);

/** RFC 5769 §2.3：Sample IPv6 Response。 */
const RFC5769_V6: Uint8Array = hexDecode(
  '010100482112a442b7e7a701bc34d686fa87dfae' +
    '8022000b7465737420766563746f7220' +
    '002000140002a1470113a9faa5d3f179bc25f4b5bed2b9d9' +
    '00080014a382954e4be67bf11784c97c8292c275bfe3ed41' +
    '80280004c8fb0b4c',
);

test('CRC32-IEEE 规范 KAT："123456789" → 0xCBF43926', () => {
  const data: Uint8Array = new TextEncoder().encode('123456789');
  assert.equal(crc32Ieee(data), 0xcbf43926);
});

test('Binding Request 编码：40B 黄金样本（指纹经 python3 zlib.crc32 独立计算）', () => {
  const req: Uint8Array = stunRequest(TXID);
  assert.equal(req.length, 40);
  assert.equal(
    hexEncode(req),
    '000100142112a442000102030405060708090a0b' + '802200087461696c6e6f6465' + '802800048aabad90',
  );
  assert.ok(stunIs(req));
});

test('服务端视角：ParseBindingRequest 接受合法请求并回 TxID', () => {
  const txid: Uint8Array = stunParseBindingRequest(stunRequest(TXID));
  assert.equal(hexEncode(txid), hexEncode(TXID));
});

test('服务端视角：非 STUN / 非 request / 软件/指纹校验链逐环拒绝', () => {
  assert.throws(
    (): void => {
      stunParseBindingRequest(new Uint8Array(20));
    },
    (e: unknown): boolean => e instanceof StunError && e.code === 'NOT_STUN',
  );
  // type 改成 0x0101（首字节 0x01，次字节原已 0x01）→ NOT_REQUEST
  const notReq: Uint8Array = stunRequest(TXID);
  notReq[0] = 0x01;
  assert.throws(
    (): void => {
      stunParseBindingRequest(notReq);
    },
    (e: unknown): boolean => e instanceof StunError && e.code === 'NOT_REQUEST',
  );
  // SOFTWARE 值改写 → WRONG_SOFTWARE
  const badSw: Uint8Array = stunRequest(TXID);
  badSw[24] = 0x54; // 't' → 'T'（SOFTWARE 值首字节）
  assert.throws(
    (): void => {
      stunParseBindingRequest(badSw);
    },
    (e: unknown): boolean => e instanceof StunError && e.code === 'WRONG_SOFTWARE',
  );
  // 末属性非 FINGERPRINT（截掉指纹属性并改长度）→ NO_FINGERPRINT
  const noFp: Uint8Array = stunRequest(TXID).slice(0, 32);
  noFp[2] = 0;
  noFp[3] = 12;
  assert.throws(
    (): void => {
      stunParseBindingRequest(noFp);
    },
    (e: unknown): boolean => e instanceof StunError && e.code === 'NO_FINGERPRINT',
  );
  // 指纹位翻转 → WRONG_FINGERPRINT
  const badFp: Uint8Array = stunRequest(TXID);
  badFp[39] ^= 0x01;
  assert.throws(
    (): void => {
      stunParseBindingRequest(badFp);
    },
    (e: unknown): boolean => e instanceof StunError && e.code === 'WRONG_FINGERPRINT',
  );
});

test('RFC 5769 §2.2 IPv4 向量：XOR-MAPPED 解出 192.0.2.1:32853（去映射 4B）', () => {
  const r: ReturnType<typeof stunParseResponse> = stunParseResponse(RFC5769_V4);
  assert.equal(hexEncode(r.txid), 'b7e7a701bc34d686fa87dfae');
  assert.equal(r.ip.length, 4);
  assert.equal(hexEncode(r.ip), 'c0000201');
  assert.equal(r.port, 32853);
});

test('RFC 5769 §2.3 IPv6 向量：解出 2001:db8:1234:5678:11:2233:4455:6677:32853', () => {
  const r: ReturnType<typeof stunParseResponse> = stunParseResponse(RFC5769_V6);
  assert.equal(r.ip.length, 16);
  assert.equal(hexEncode(r.ip), '20010db8123456780011223344556677');
  assert.equal(r.port, 32853);
});

test('Response 编解码往返（v4/v6）+ MAPPED-ADDRESS 回退 + 非 0101 拒绝', () => {
  // 我方 Response → 解析回原地址（与 RFC 向量同路径）
  const r4: ReturnType<typeof stunParseResponse> = stunParseResponse(
    stunResponse(TXID, hexDecode('c0a8017c'), 41641),
  );
  assert.equal(hexEncode(r4.ip), 'c0a8017c');
  assert.equal(r4.port, 41641);
  const r6: ReturnType<typeof stunParseResponse> = stunParseResponse(
    stunResponse(TXID, hexDecode('20010db8000000000000000000000001'), 65535),
  );
  assert.equal(hexEncode(r6.ip), '20010db8000000000000000000000001');
  assert.equal(r6.port, 65535);

  // 仅 MAPPED-ADDRESS（0x0001，非异或）时回退可用（RFC 5389 §15.1 值布局）
  const mapped: Uint8Array = new Uint8Array(20 + 12);
  mapped[0] = 0x01; // type = 0x0101
  mapped[1] = 0x01;
  mapped[3] = 0x0c; // attrsLen = 12
  mapped.set([0x21, 0x12, 0xa4, 0x42], 4);
  mapped.set(TXID, 8);
  // 属性：type 0001 ‖ len 0008 ‖ 值 = [0, fam=01, port a2a9(41641), ip c0a8017c]
  mapped.set([0x00, 0x01, 0x00, 0x08, 0x00, 0x01, 0xa2, 0xa9, 0xc0, 0xa8, 0x01, 0x7c], 20);
  const rf: ReturnType<typeof stunParseResponse> = stunParseResponse(mapped);
  assert.equal(hexEncode(rf.ip), 'c0a8017c');
  assert.equal(rf.port, 41641);

  // type 非 0101 → NOT_SUCCESS
  const badType: Uint8Array = RFC5769_V4.slice();
  badType[0] = 0x01;
  badType[1] = 0x11;
  assert.throws(
    (): void => {
      stunParseResponse(badType);
    },
    (e: unknown): boolean => e instanceof StunError && e.code === 'NOT_SUCCESS',
  );
});

test('StunTransaction：TxID 注入生成、配对过滤、RTT 单调差', () => {
  const rng: ArrayRng = new ArrayRng(hexDecode('0a0b0c0d0e0f101112131415161718'));
  const clock: FixedClock = new FixedClock(0);
  const tx: StunTransaction = new StunTransaction(rng, clock);
  assert.equal(tx.txid.length, 12);
  assert.equal(hexEncode(tx.txid), '0a0b0c0d0e0f101112131415');
  const req: Uint8Array = tx.requestBytes();
  assert.equal(hexEncode(req.slice(8, 20)), hexEncode(tx.txid));

  // 别人的响应（TxID 不同）→ null；自己的响应 → 配对
  assert.equal(tx.matchResponse(RFC5769_V4), null);
  clock.advanceMs(37);
  const mine: Uint8Array = stunResponse(tx.txid, hexDecode('c0a8017c'), 41641);
  const got: ReturnType<StunTransaction['matchResponse']> = tx.matchResponse(mine);
  assert.ok(got !== null);
  assert.equal(got.port, 41641);
  assert.equal(tx.rttMs(), 37);

  // 非 STUN 字节流 → null
  assert.equal(tx.matchResponse(new Uint8Array(64)), null);
});

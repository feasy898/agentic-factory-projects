/**
 * TAI64N 时间戳测试：
 * - 已知向量：Unix 纪元 0 与 1717000000.123s（2^62 标签 + 大端秒/纳秒）；
 * - 编码/解码往返；字节序即数值序（大端，逐字节比较判新旧）；
 * - 负数/非有限输入拒绝；长度校验。
 */

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { hexDecode, hexEncode } from '@ohos-tailscale/common';
import { tai64nDecode, tai64nFromWallMs } from '../src/tai64n.ts';

const assertThrows = (fn: () => void, msgPart: string): void => {
  let thrown: boolean = false;
  try {
    fn();
  } catch (e) {
    thrown = true;
    const err: Error = e as Error;
    assert.ok(err.message.includes(msgPart), 'message should contain: ' + msgPart);
  }
  assert.equal(thrown, true, 'expected throw containing: ' + msgPart);
};

test('TAI64N 已知向量：Unix 0 → 2^62 标签零秒零纳秒', () => {
  const t: Uint8Array = tai64nFromWallMs(0);
  assert.equal(t.length, 12);
  assert.equal(hexEncode(t), '400000000000000000000000');
  const d = tai64nDecode(t);
  assert.equal(d.seconds, 4611686018427387904n);
  assert.equal(d.nanos, 0);
});

test('TAI64N 已知向量：1717000000.123s（白皮书布局：8B BE 秒 + 4B BE 纳秒）', () => {
  const t: Uint8Array = tai64nFromWallMs(1717000000123);
  assert.equal(hexEncode(t), '40000000665757400754d4c0');
  const d = tai64nDecode(t);
  assert.equal(d.seconds, 0x4000000000000000n + 1717000000n);
  assert.equal(d.nanos, 123000000);
});

test('TAI64N 编码/解码往返（多毫秒值）', () => {
  const samples: number[] = [1, 999, 1000, 1001, 1999, 123456789, 1717000000123, 4102444800000];
  for (const ms of samples) {
    const d = tai64nDecode(tai64nFromWallMs(ms));
    const backMs: number = Number(d.seconds - 4611686018427387904n) * 1000 + d.nanos / 1000000;
    assert.equal(backMs, ms, 'roundtrip mismatch at ' + String(ms));
  }
});

test('TAI64N 字节序即数值序：时间前进则编码逐字节变大（白皮书重放比较前提）', () => {
  let prev: Uint8Array = tai64nFromWallMs(0);
  for (let ms = 1; ms <= 5000; ms += 37) {
    const cur: Uint8Array = tai64nFromWallMs(ms);
    let cmp: number = -1;
    for (let i = 0; i < 12; i += 1) {
      if (cur[i] !== prev[i]) {
        cmp = cur[i] > prev[i] ? 1 : 0;
        break;
      }
    }
    assert.equal(cmp, 1, 'tai64n not increasing at ms=' + String(ms));
    prev = cur;
  }
});

test('TAI64N 非法输入拒绝', () => {
  assertThrows(() => tai64nFromWallMs(-1), 'non-negative');
  assertThrows(() => tai64nFromWallMs(Number.NaN), 'non-negative');
  assertThrows(() => tai64nFromWallMs(Number.POSITIVE_INFINITY), 'non-negative');
  assertThrows(() => tai64nDecode(new Uint8Array(11)), '12 bytes');
  assertThrows(() => tai64nDecode(hexDecode('40000000000000000000000000')), '12 bytes');
});

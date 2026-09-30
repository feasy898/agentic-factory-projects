/**
 * util.ts 测试：constTimeEqual / wipe（架构契约 §4.1 测试策略）。
 */

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { constTimeEqual, wipe } from '../src/util.ts';

test('constTimeEqual：相等/不等/长度不等（后者返回 false 不抛错）', () => {
  const a: Uint8Array = Uint8Array.from([1, 2, 3, 4]);
  const b: Uint8Array = Uint8Array.from([1, 2, 3, 4]);
  const c: Uint8Array = Uint8Array.from([1, 2, 3, 5]);
  const d: Uint8Array = Uint8Array.from([1, 2, 3]);
  assert.equal(constTimeEqual(a, b), true);
  assert.equal(constTimeEqual(a, c), false);
  assert.equal(constTimeEqual(a, d), false);
  assert.equal(constTimeEqual(d, a), false);
  assert.equal(constTimeEqual(new Uint8Array(0), new Uint8Array(0)), true);
  assert.equal(constTimeEqual(new Uint8Array(0), Uint8Array.from([0])), false);
  // 全零与全零相等；单比特差异识别
  assert.equal(constTimeEqual(new Uint8Array(32), new Uint8Array(32)), true);
  const oneBit: Uint8Array = new Uint8Array(32);
  oneBit[31] = 0x80;
  assert.equal(constTimeEqual(new Uint8Array(32), oneBit), false);
});

test('wipe：全零覆写；空数组 no-op；原缓冲就地清零', () => {
  const buf: Uint8Array = Uint8Array.from([0xde, 0xad, 0xbe, 0xef]);
  wipe(buf);
  assert.deepEqual(buf, new Uint8Array(4));
  const empty: Uint8Array = new Uint8Array(0);
  wipe(empty);
  assert.equal(empty.length, 0);
  const view: Uint8Array = new Uint8Array(8);
  view.set([1, 2, 3, 4, 5, 6, 7, 8], 0);
  const sub: Uint8Array = view.subarray(2, 6);
  wipe(sub);
  assert.deepEqual(view, Uint8Array.from([1, 2, 0, 0, 0, 0, 7, 8]));
});

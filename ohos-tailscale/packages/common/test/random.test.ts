import { test } from 'node:test';
import assert from 'node:assert/strict';
import { ArrayRng } from '../src/random.ts';
import type { Rng } from '../src/random.ts';

test('ArrayRng 按序填充', () => {
  const rng: ArrayRng = new ArrayRng(Uint8Array.from([0xaa, 0xbb, 0xcc]));
  const out: Uint8Array = new Uint8Array(5);
  rng.randomBytes(out);
  assert.deepEqual(Array.from(out), [0xaa, 0xbb, 0xcc, 0xaa, 0xbb]);
});

test('ArrayRng 循环取用且游标跨调用保持', () => {
  const rng: ArrayRng = new ArrayRng(Uint8Array.from([0x01, 0x02, 0x03]));
  const a: Uint8Array = new Uint8Array(2);
  rng.randomBytes(a);
  assert.deepEqual(Array.from(a), [0x01, 0x02]);
  const b: Uint8Array = new Uint8Array(2);
  rng.randomBytes(b);
  assert.deepEqual(Array.from(b), [0x03, 0x01]);
});

test('ArrayRng 构造时拷贝 pool（外部修改不影响）', () => {
  const pool: Uint8Array = Uint8Array.from([0x42]);
  const rng: ArrayRng = new ArrayRng(pool);
  pool[0] = 0x00;
  const out: Uint8Array = new Uint8Array(1);
  rng.randomBytes(out);
  assert.equal(out[0], 0x42);
});

test('ArrayRng 零长度填充为 no-op，空 pool 抛错', () => {
  const rng: ArrayRng = new ArrayRng(Uint8Array.from([0x09]));
  const empty: Uint8Array = new Uint8Array(0);
  rng.randomBytes(empty);
  const bad: ArrayRng = new ArrayRng(new Uint8Array(0));
  assert.throws(() => bad.randomBytes(new Uint8Array(3)), /empty pool/);
});

test('ArrayRng 满足 Rng 接口（多态使用）', () => {
  const rng: Rng = new ArrayRng(Uint8Array.from([0x7f]));
  const out: Uint8Array = new Uint8Array(3);
  rng.randomBytes(out);
  assert.deepEqual(Array.from(out), [0x7f, 0x7f, 0x7f]);
});

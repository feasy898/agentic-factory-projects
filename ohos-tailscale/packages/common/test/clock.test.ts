import { test } from 'node:test';
import assert from 'node:assert/strict';
import { FixedClock } from '../src/clock.ts';
import type { Clock } from '../src/clock.ts';

test('FixedClock 初始值与两轴独立起点', () => {
  const c: FixedClock = new FixedClock(1000);
  assert.equal(c.wallMs(), 1000);
  assert.equal(c.monotonicMs(), 0);
  const c2: FixedClock = new FixedClock();
  assert.equal(c2.wallMs(), 0);
});

test('FixedClock advanceMs 双轴同步前进', () => {
  const c: FixedClock = new FixedClock(100);
  c.advanceMs(50);
  assert.equal(c.wallMs(), 150);
  assert.equal(c.monotonicMs(), 50);
  c.advanceMs(1);
  assert.equal(c.wallMs(), 151);
  assert.equal(c.monotonicMs(), 51);
});

test('FixedClock advanceMs 拒绝负值（保持单调契约）', () => {
  const c: FixedClock = new FixedClock(10);
  assert.throws(() => c.advanceMs(-1), /negative/);
  assert.equal(c.monotonicMs(), 0);
});

test('FixedClock setWallMs 只平移挂钟轴', () => {
  const c: FixedClock = new FixedClock(100);
  c.advanceMs(10);
  c.setWallMs(99999);
  assert.equal(c.wallMs(), 99999);
  assert.equal(c.monotonicMs(), 10);
});

test('FixedClock 满足 Clock 接口（多态使用）', () => {
  const clock: Clock = new FixedClock(7);
  assert.equal(clock.wallMs(), 7);
  assert.equal(clock.monotonicMs(), 0);
});

/**
 * 帧编解码测试（架构契约 §6 frame.ts + §6.1）：
 * - 单帧/多帧编解码往返；空载荷帧；65535B 上界可用、65536B 抛 NoiseError('FRAME')；
 * - 大端前缀字节序；截断（无头/半头/缺体）抛 NoiseError('FRAME')；
 * - NoiseFrameReader：1 字节一片分片喂入与多帧粘包一片喂入，重组结果与整帧等价；
 *   pendingBytes 跟踪半帧缓存；尾随半帧保留到下次 push；
 * - 输出独立性（R8）：编码/解码输出与输入不共享内存。
 */

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { NoiseError, NoiseFrameReader, noiseFrameDecode, noiseFrameEncode, type NoiseFrame } from '../src/index.ts';

const seqPool = (start: number, n: number): Uint8Array => {
  const out: Uint8Array = new Uint8Array(n);
  for (let i: number = 0; i < n; i += 1) {
    out[i] = (start + i) & 0xff;
  }
  return out;
};

const assertFrameError = (fn: () => void): void => {
  let thrown: boolean = false;
  let gotCode: string = '';
  try {
    fn();
  } catch (e) {
    thrown = true;
    const err: NoiseError = e as NoiseError;
    gotCode = err.code;
  }
  assert.equal(thrown, true, 'expected NoiseError(FRAME) not thrown');
  assert.equal(gotCode, 'FRAME', 'unexpected NoiseError code');
};

/** 把若干帧编为一个字节流（粘包）。 */
const concatFrames = (frames: Uint8Array[]): Uint8Array => {
  let total: number = 0;
  for (const f of frames) {
    total += f.length;
  }
  const out: Uint8Array = new Uint8Array(total);
  let off: number = 0;
  for (const f of frames) {
    out.set(f, off);
    off += f.length;
  }
  return out;
};

test('单帧编码：大端 2B 长度前缀 + 原样载荷', () => {
  const body: Uint8Array = seqPool(0x20, 300);
  const frame: Uint8Array = noiseFrameEncode(body);
  assert.equal(frame.length, 302);
  assert.equal(frame[0], 0x01, 'length hi byte must be big-endian');
  assert.equal(frame[1], 0x2c, '300 = 0x012c');
  assert.deepEqual(frame.slice(2), body);

  const empty: Uint8Array = noiseFrameEncode(new Uint8Array(0));
  assert.equal(empty.length, 2);
  assert.deepEqual(empty, new Uint8Array([0x00, 0x00]));

  const decoded: NoiseFrame = noiseFrameDecode(frame);
  assert.deepEqual(decoded.payload, body);
  const decodedEmpty: NoiseFrame = noiseFrameDecode(empty);
  assert.equal(decodedEmpty.payload.length, 0);
});

test('上界：65535B 可编解码，65536B 抛 NoiseError(FRAME)', () => {
  const max: Uint8Array = seqPool(0x00, 65535);
  const frame: Uint8Array = noiseFrameEncode(max);
  assert.equal(frame.length, 65537);
  assert.equal(frame[0], 0xff);
  assert.equal(frame[1], 0xff);
  const decoded: NoiseFrame = noiseFrameDecode(frame);
  assert.equal(decoded.payload.length, 65535);
  assert.deepEqual(decoded.payload, max);

  assertFrameError(() => noiseFrameEncode(seqPool(0x00, 65536)));
});

test('解码错误：空输入/半头/缺体 → NoiseError(FRAME)', () => {
  assertFrameError(() => noiseFrameDecode(new Uint8Array(0)));
  assertFrameError(() => noiseFrameDecode(new Uint8Array([0x00])));
  // 声称 300B 只给 10B
  assertFrameError(() => noiseFrameDecode(new Uint8Array([0x01, 0x2c, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10])));
  // 声称 1B 但体缺失
  assertFrameError(() => noiseFrameDecode(new Uint8Array([0x00, 0x01])));
});

test('解码载荷为独立拷贝（R8）：不与输入共享内存', () => {
  const body: Uint8Array = seqPool(0x40, 5);
  const frame: Uint8Array = noiseFrameEncode(body);
  const decoded: NoiseFrame = noiseFrameDecode(frame);
  decoded.payload[0] = (decoded.payload[0] ^ 0xff) & 0xff;
  assert.equal(body[0], 0x40, 'decoded payload must not alias encoder input');
  assert.equal(frame[2], 0x40, 'decoded payload must not alias frame bytes');

  const out: Uint8Array = noiseFrameEncode(body);
  body[0] = (body[0] ^ 0xff) & 0xff;
  assert.equal(out[2], 0x40, 'encode output must not alias input');
});

test('NoiseFrameReader：1 字节一片分片喂入与整帧等价', () => {
  const bodies: Uint8Array[] = [seqPool(0x01, 5), new Uint8Array(0), seqPool(0x02, 40)];
  const stream: Uint8Array = concatFrames([
    noiseFrameEncode(bodies[0]),
    noiseFrameEncode(bodies[1]),
    noiseFrameEncode(bodies[2]),
  ]);
  const reader: NoiseFrameReader = new NoiseFrameReader();
  const out: NoiseFrame[] = [];
  let fed: number = 0;
  let consumed: number = 0;
  for (let i: number = 0; i < stream.length; i += 1) {
    fed += 1;
    const got: NoiseFrame[] = reader.push(stream.slice(i, i + 1));
    for (const f of got) {
      out.push(f);
      consumed += 2 + f.payload.length;
    }
    // 不变式：缓存字节数 = 已喂入 - 已成帧消费（半帧必须被缓存）
    assert.equal(reader.pendingBytes(), fed - consumed, 'pending bytes must equal buffered partial frame at byte ' + String(i));
  }
  assert.equal(out.length, 3);
  assert.deepEqual(out[0].payload, bodies[0]);
  assert.equal(out[1].payload.length, 0);
  assert.deepEqual(out[2].payload, bodies[2]);
  assert.equal(reader.pendingBytes(), 0);
});

test('NoiseFrameReader：多帧粘包一片喂入、半帧跨 push 保留', () => {
  const bodies: Uint8Array[] = [seqPool(0x0a, 20), seqPool(0x0b, 8), seqPool(0x0c, 33)];
  const f1: Uint8Array = noiseFrameEncode(bodies[0]);
  const f2: Uint8Array = noiseFrameEncode(bodies[1]);
  const f3: Uint8Array = noiseFrameEncode(bodies[2]);

  const reader: NoiseFrameReader = new NoiseFrameReader();
  // 一片含 f1 完整 + f2 前一半
  const cut: number = f1.length + 3;
  let got: NoiseFrame[] = reader.push(concatFrames([f1, f2]).slice(0, cut));
  assert.equal(got.length, 1);
  assert.deepEqual(got[0].payload, bodies[0]);
  assert.equal(reader.pendingBytes(), cut - f1.length);

  // 剩余：f2 后半 + f3 完整
  got = reader.push(concatFrames([f2, f3]).slice(cut - f1.length));
  assert.equal(got.length, 2);
  assert.deepEqual(got[0].payload, bodies[1]);
  assert.deepEqual(got[1].payload, bodies[2]);
  assert.equal(reader.pendingBytes(), 0);

  // 无完整帧时返回空数组
  got = reader.push(new Uint8Array([0x00]));
  assert.equal(got.length, 0);
  assert.equal(reader.pendingBytes(), 1);
  // 补上 00 00 → 恰好补成一个空载荷帧（缓存 [00|00 00] → 帧长 0x0000），余 [04 9f] 半头
  got = reader.push(new Uint8Array([0x00, 0x04, 0x9f]));
  assert.equal(got.length, 1);
  assert.equal(got[0].payload.length, 0);
  assert.equal(reader.pendingBytes(), 2);
  // 新帧声明 0x049f=1183B 但只有 2B → 半帧缓存
  got = reader.push(new Uint8Array([0xaa, 0xbb]));
  assert.equal(got.length, 0);
  assert.equal(reader.pendingBytes(), 4);
});

test('NoiseFrameReader：帧载荷为独立拷贝（R8）', () => {
  const body: Uint8Array = seqPool(0x50, 4);
  const stream: Uint8Array = noiseFrameEncode(body);
  const reader: NoiseFrameReader = new NoiseFrameReader();
  const got: NoiseFrame[] = reader.push(stream);
  assert.equal(got.length, 1);
  got[0].payload[0] = (got[0].payload[0] ^ 0xff) & 0xff;
  assert.equal(body[0], 0x50);
  // 缓存区被消费后内部不留引用（继续 push 正常）
  const second: NoiseFrame[] = reader.push(noiseFrameEncode(new Uint8Array([0x77])));
  assert.equal(second.length, 1);
  assert.deepEqual(second[0].payload, new Uint8Array([0x77]));
});

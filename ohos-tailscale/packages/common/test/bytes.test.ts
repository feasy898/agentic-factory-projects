import { test } from 'node:test';
import assert from 'node:assert/strict';
import { ByteReader, ByteWriter } from '../src/bytes.ts';
import { MAX_U64 } from '../src/constants.ts';

test('reader u8/u16/u32/u64 big-endian 已知向量', () => {
  const r: ByteReader = new ByteReader(Uint8Array.from([0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08]));
  assert.equal(r.readU8(), 0x01);
  assert.equal(r.readU16be(), 0x0203);
  assert.equal(r.readU32be(), 0x04050607);
  assert.equal(r.readU8(), 0x08);
  assert.ok(r.atEnd());
});

test('reader u16/u32 little-endian 已知向量', () => {
  const r: ByteReader = new ByteReader(Uint8Array.from([0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08]));
  assert.equal(r.readU16le(), 0x0201);
  assert.equal(r.readU32le(), 0x06050403);
  assert.equal(r.readU16le(), 0x0807);
  assert.ok(r.atEnd());
});

test('reader u64 往返（BE/LE，含 > 2^53 值）', () => {
  const vals: bigint[] = [0n, 1n, 0x123456789abcdefn, 9007199254740993n, MAX_U64];
  for (const v of vals) {
    const w: ByteWriter = new ByteWriter();
    w.writeU64be(v);
    assert.equal(new ByteReader(w.toUint8Array()).readU64be(), v);
    const w2: ByteWriter = new ByteWriter();
    w2.writeU64le(v);
    assert.equal(new ByteReader(w2.toUint8Array()).readU64le(), v);
  }
});

test('writer BE/LE 布局已知向量', () => {
  const w: ByteWriter = new ByteWriter();
  w.writeU16be(0x0102);
  w.writeU16le(0x0102);
  w.writeU32be(0x01020304);
  w.writeU32le(0x01020304);
  assert.deepEqual(
    Array.from(w.toUint8Array()),
    [0x01, 0x02, 0x02, 0x01, 0x01, 0x02, 0x03, 0x04, 0x04, 0x03, 0x02, 0x01],
  );
});

/** uvarint 已知向量载体（R4：全仓禁 tuple，用纯字段 interface）。 */
interface UvarintCase {
  bytes: Uint8Array;
  value: bigint;
}

test('reader uvarint LEB128 已知向量', () => {
  const cases: UvarintCase[] = [
    { bytes: Uint8Array.from([0x00]), value: 0n },
    { bytes: Uint8Array.from([0x01]), value: 1n },
    { bytes: Uint8Array.from([0x7f]), value: 127n },
    { bytes: Uint8Array.from([0x80, 0x01]), value: 128n },
    { bytes: Uint8Array.from([0xff, 0x01]), value: 255n },
    { bytes: Uint8Array.from([0x80, 0x02]), value: 256n },
    { bytes: Uint8Array.from([0xff, 0xff, 0xff, 0xff, 0x0f]), value: 0xffffffffn },
    { bytes: Uint8Array.from([0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0x01]), value: MAX_U64 },
  ];
  for (const c of cases) {
    assert.equal(new ByteReader(c.bytes).readUvarint(), c.value);
    const w: ByteWriter = new ByteWriter();
    w.writeUvarint(c.value);
    assert.deepEqual(w.toUint8Array(), c.bytes);
  }
});

test('reader uvarint 溢出与截断抛错', () => {
  // 第 10 字节 > 0x01 → 溢出
  const overflow: Uint8Array = Uint8Array.from(
    [0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0x02],
  );
  assert.throws(() => new ByteReader(overflow).readUvarint(), /overflows 64 bits/);
  // 10 字节全 continuation（第 10 字节 0xff > 0x01）→ 同样走溢出分支
  const tooLong: Uint8Array = Uint8Array.from(
    [0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0x01],
  );
  assert.throws(() => new ByteReader(tooLong).readUvarint(), /overflows 64 bits/);
  // 截断
  assert.throws(() => new ByteReader(Uint8Array.from([0x80])).readUvarint(), /out of range/);
});

test('reader 越界抛错且不前移', () => {
  const r: ByteReader = new ByteReader(Uint8Array.from([0x01, 0x02]));
  assert.throws(() => r.readU32be(), /out of range/);
  assert.equal(r.offset, 0);
  r.skip(2);
  assert.ok(r.atEnd());
  assert.throws(() => r.readU8(), /out of range/);
});

test('readBytes 返回独立拷贝', () => {
  const src: Uint8Array = Uint8Array.from([0x0a, 0x0b, 0x0c]);
  const r: ByteReader = new ByteReader(src);
  const got: Uint8Array = r.readBytes(3);
  got[0] = 0xff;
  assert.equal(src[0], 0x0a);
});

test('writer 自动扩容与 reset', () => {
  const w: ByteWriter = new ByteWriter(4);
  for (let i: number = 0; i < 100; i += 1) {
    w.writeU8(i & 0xff);
  }
  assert.equal(w.length, 100);
  const arr: Uint8Array = w.toUint8Array();
  assert.equal(arr.length, 100);
  assert.equal(arr[99], 99);
  w.reset();
  assert.equal(w.length, 0);
});

test('writer 数值域校验抛错', () => {
  const w: ByteWriter = new ByteWriter();
  assert.throws(() => w.writeU8(256), /u8 out of range/);
  assert.throws(() => w.writeU16be(0x10000), /u16 out of range/);
  assert.throws(() => w.writeU16le(-1), /u16 out of range/);
  assert.throws(() => w.writeU32be(-1), /u32 out of range/);
  assert.throws(() => w.writeU64be(18446744073709551616n), /u64 out of range/);
  assert.throws(() => w.writeUvarint(-1n), /u64 out of range/);
});

test('skip/takeRemaining/offset 语义', () => {
  const r: ByteReader = new ByteReader(Uint8Array.from([1, 2, 3, 4, 5]));
  r.skip(2);
  assert.equal(r.offset, 2);
  assert.equal(r.remaining, 3);
  const rest: Uint8Array = r.takeRemaining();
  assert.deepEqual(Array.from(rest), [3, 4, 5]);
  assert.ok(r.atEnd());
});

test('大负载 writeBytes + 往返一致性（1000 组随机长度）', () => {
  const w: ByteWriter = new ByteWriter(1);
  const parts: Uint8Array[] = [];
  let seed: number = 12345;
  const rand: () => number = (): number => {
    seed = (seed * 1103515245 + 12345) & 0x7fffffff;
    return seed;
  };
  for (let i: number = 0; i < 1000; i += 1) {
    const n: number = rand() % 257;
    const part: Uint8Array = new Uint8Array(n);
    for (let k: number = 0; k < n; k += 1) {
      part[k] = (n + k) & 0xff;
    }
    parts.push(part);
    w.writeUvarint(BigInt(n));
    w.writeBytes(part);
  }
  const r: ByteReader = new ByteReader(w.toUint8Array());
  for (const part of parts) {
    const n: bigint = r.readUvarint();
    assert.equal(n, BigInt(part.length));
    assert.deepEqual(Array.from(r.readBytes(Number(n))), Array.from(part));
  }
  assert.ok(r.atEnd());
});

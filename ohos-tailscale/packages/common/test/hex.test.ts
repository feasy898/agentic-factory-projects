import { test } from 'node:test';
import assert from 'node:assert/strict';
import { hexEncode, hexDecode } from '../src/hex.ts';

test('hexEncode 已知向量（小写输出）', () => {
  assert.equal(hexEncode(new Uint8Array(0)), '');
  assert.equal(hexEncode(Uint8Array.from([0xde, 0xad, 0xbe, 0xef])), 'deadbeef');
  assert.equal(hexEncode(Uint8Array.from([0x00, 0x0f, 0xf0, 0xff])), '000ff0ff');
  const all: Uint8Array = new Uint8Array(256);
  for (let i: number = 0; i < 256; i += 1) {
    all[i] = i;
  }
  let expect: string = '';
  for (let i: number = 0; i < 256; i += 1) {
    const h: string = i.toString(16);
    expect += h.length === 1 ? '0' + h : h;
  }
  assert.equal(hexEncode(all), expect);
});

test('hexDecode 接受大小写混合', () => {
  assert.deepEqual(hexDecode('DEADBEEF'), Uint8Array.from([0xde, 0xad, 0xbe, 0xef]));
  assert.deepEqual(hexDecode('DeAdBeEf'), Uint8Array.from([0xde, 0xad, 0xbe, 0xef]));
  assert.deepEqual(hexDecode(''), new Uint8Array(0));
});

test('hexEncode/hexDecode 全 256 字节往返', () => {
  const all: Uint8Array = new Uint8Array(256);
  for (let i: number = 0; i < 256; i += 1) {
    all[i] = i;
  }
  assert.deepEqual(hexDecode(hexEncode(all)), all);
});

test('hexDecode 非法输入抛错', () => {
  assert.throws(() => hexDecode('abc'), /odd-length/);
  assert.throws(() => hexDecode('zz'), /invalid hex character/);
  assert.throws(() => hexDecode('0g'), /invalid hex character/);
});

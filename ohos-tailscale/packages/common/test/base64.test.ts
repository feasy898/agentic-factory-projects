import { test } from 'node:test';
import assert from 'node:assert/strict';
import { base64Encode, base64Decode, base64UrlEncode, base64UrlDecode } from '../src/base64.ts';

/** RFC 4648 已知向量载体（R4：全仓禁 tuple，用纯字段 interface）。 */
interface B64Case {
  raw: string;
  encoded: string;
}

test('RFC 4648 标准 base64 已知向量', () => {
  const cases: B64Case[] = [
    { raw: '', encoded: '' },
    { raw: 'f', encoded: 'Zg==' },
    { raw: 'fo', encoded: 'Zm8=' },
    { raw: 'foo', encoded: 'Zm9v' },
    { raw: 'foob', encoded: 'Zm9vYg==' },
    { raw: 'fooba', encoded: 'Zm9vYmE=' },
    { raw: 'foobar', encoded: 'Zm9vYmFy' },
  ];
  for (const c of cases) {
    const bytes: Uint8Array = Uint8Array.from(c.raw, (ch: string) => ch.charCodeAt(0));
    assert.equal(base64Encode(bytes), c.encoded, 'encode ' + JSON.stringify(c.raw));
    assert.equal(
      Array.from(base64Decode(c.encoded))
        .map((b: number) => String.fromCharCode(b))
        .join(''),
      c.raw,
      'decode ' + c.encoded,
    );
  }
});

test('标准与 URL-safe 字母表差异', () => {
  // 0xfb 0xff → std '+/'，url '-_'
  const bytes: Uint8Array = Uint8Array.from([0xfb, 0xff, 0xbf]);
  const std: string = base64Encode(bytes);
  const url: string = base64UrlEncode(bytes);
  assert.equal(std, '+/+/');
  assert.equal(url, '-_-_');
  assert.notEqual(std, url);
  assert.deepEqual(base64UrlDecode(url), bytes);
  assert.deepEqual(base64Decode(std), bytes);
});

test('base64 全 256 字节 + 长度 0..64 往返（std 与 url）', () => {
  for (let len: number = 0; len <= 64; len += 1) {
    const src: Uint8Array = new Uint8Array(len);
    for (let i: number = 0; i < len; i += 1) {
      src[i] = (i * 37 + len) & 0xff;
    }
    assert.deepEqual(base64Decode(base64Encode(src)), src, 'std len=' + String(len));
    assert.deepEqual(base64UrlDecode(base64UrlEncode(src)), src, 'url len=' + String(len));
  }
  const all: Uint8Array = new Uint8Array(256);
  for (let i: number = 0; i < 256; i += 1) {
    all[i] = i;
  }
  assert.deepEqual(base64Decode(base64Encode(all)), all);
});

test('base64Decode 严格模式抛错集', () => {
  assert.throws(() => base64Decode('Z'), /multiple of 4/);        // 长度不对
  assert.throws(() => base64Decode('Zg='), /multiple of 4/);      // 填充后长度不对
  assert.throws(() => base64Decode('===='), /padding/);           // 填充过多
  assert.throws(() => base64Decode('Zg=z'), /invalid character/); // '=' 在中间
  assert.throws(() => base64Decode('Zg!*'), /invalid character/); // 非法字符
  assert.throws(() => base64UrlDecode('Zg+/'), /invalid character/); // url 字母表不接受 +/
});

test('base64 canonical（尾部非零位）拒绝', () => {
  // 'Zh=='：'h' = 33 = 0b100001，低 4 位 0001 ≠ 0 → 非法
  assert.throws(() => base64Decode('Zh=='), /non-canonical/);
  // 'Zg8='：'8' = 60 = 0b111100，低 2 位 00 → 合法
  assert.deepEqual(
    Array.from(base64Decode('Zg8=')),
    [0x66, 0x0f],
  );
});

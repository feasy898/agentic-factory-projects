import { test } from 'node:test';
import assert from 'node:assert/strict';
import { utf8Encode, utf8Decode } from '../src/utf8.ts';
import { hexEncode, hexDecode } from '../src/hex.ts';

test('UTF-8 各长度编码已知向量', () => {
  assert.equal(hexEncode(utf8Encode('')), '');
  assert.equal(hexEncode(utf8Encode('a')), '61');
  assert.equal(hexEncode(utf8Encode('é')), 'c3a9');        // U+00E9 → 2 字节
  assert.equal(hexEncode(utf8Encode('中')), 'e4b8ad');      // U+4E2D → 3 字节
  assert.equal(hexEncode(utf8Encode('€')), 'e282ac');      // U+20AC → 3 字节
  assert.equal(hexEncode(utf8Encode('😀')), 'f09f9880');   // U+1F600 → 4 字节（代理对）
});

test('UTF-8 混合文本往返', () => {
  const samples: string[] = [
    '',
    'hello, world',
    '中文测试：知识共享',
    'mixed 中文 with emoji 😀🚀 and éüñ',
    '\u0000\u0001控制字符\t\n',
    '「日本語テキスト」',
  ];
  for (const s of samples) {
    assert.equal(utf8Decode(utf8Encode(s)), s);
  }
});

test('UTF-8 宽范围码点往返（采样到 U+10FFFF）', () => {
  for (let cp: number = 0x20; cp <= 0x10ffff; cp += 4093) {
    if (cp >= 0xd800 && cp <= 0xdfff) {
      continue; // 代理区不能独立成字符串字面量路径
    }
    const s: string = String.fromCodePoint(cp);
    const back: string = utf8Decode(utf8Encode(s));
    assert.equal(back, s, 'U+' + cp.toString(16));
  }
});

test('utf8Encode 拒绝孤立代理项', () => {
  const loneHigh: string = String.fromCharCode(0xd83d);
  assert.throws(() => utf8Encode(loneHigh), /lone|unpaired/);
  const loneLow: string = String.fromCharCode(0xde00);
  assert.throws(() => utf8Encode(loneLow), /lone low surrogate/);
  const reversed: string = String.fromCharCode(0xdc00, 0xd800); // 低位在前
  assert.throws(() => utf8Encode(reversed), /lone low surrogate/);
});

test('utf8Decode 拒绝非法序列', () => {
  assert.throws(() => utf8Decode(hexDecode('c0af')), /invalid leading byte/);      // overlong 2B（C0/C1 禁）
  assert.throws(() => utf8Decode(hexDecode('e08080')), /invalid continuation/);    // overlong 3B
  assert.throws(() => utf8Decode(hexDecode('f08f8080')), /invalid continuation/);  // overlong 4B
  assert.throws(() => utf8Decode(hexDecode('eda080')), /invalid continuation/);    // 代理项 U+D800
  assert.throws(() => utf8Decode(hexDecode('f4908080')), /invalid continuation/);  // > U+10FFFF
  assert.throws(() => utf8Decode(hexDecode('f5808080')), /invalid leading byte/);  // F5+ 禁
  assert.throws(() => utf8Decode(hexDecode('e4b8')), /truncated/);                 // 截断
  assert.throws(() => utf8Decode(hexDecode('80')), /invalid leading byte/);        // 裸后续字节
  assert.throws(() => utf8Decode(hexDecode('c3')), /truncated/);                   // 截断 2B
});

test('utf8Decode 边界值合法性', () => {
  assert.equal(utf8Decode(hexDecode('7f')), '\u007f');
  assert.equal(utf8Decode(hexDecode('c280')), '\u0080');     // 最小 2B
  assert.equal(utf8Decode(hexDecode('dfbf')), '\u07ff');     // 最大 2B
  assert.equal(utf8Decode(hexDecode('e0a080')), '\u0800');   // 最小 3B
  assert.equal(utf8Decode(hexDecode('ed9fbf')), '\ud7ff');   // 代理区前
  assert.equal(utf8Decode(hexDecode('ee8080')), '\ue000');   // 代理区后
  assert.equal(utf8Decode(hexDecode('f48fbfbf')), String.fromCodePoint(0x10ffff)); // U+10FFFF
});

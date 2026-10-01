/**
 * hex 编解码（P5：禁 Buffer，全部手写纯 TS，无平台依赖）。
 */

const HEX_DIGITS: string = '0123456789abcdef';

/** 编码为小写 hex。 */
export function hexEncode(src: Uint8Array): string {
  let out: string = '';
  for (let i: number = 0; i < src.length; i += 1) {
    const b: number = src[i];
    out += HEX_DIGITS.charAt(b >> 4);
    out += HEX_DIGITS.charAt(b & 0x0f);
  }
  return out;
}

/** 解码 hex；接受大小写混合；奇数长度或非法字符抛 Error。 */
export function hexDecode(s: string): Uint8Array {
  if (s.length % 2 !== 0) {
    throw new Error('hexDecode: odd-length hex string (length ' + String(s.length) + ')');
  }
  const out: Uint8Array = new Uint8Array(s.length / 2);
  for (let i: number = 0; i < out.length; i += 1) {
    const hi: number = hexValue(s.charCodeAt(i * 2), i * 2);
    const lo: number = hexValue(s.charCodeAt(i * 2 + 1), i * 2 + 1);
    out[i] = hi * 16 + lo;
  }
  return out;
}

function hexValue(code: number, index: number): number {
  if (code >= 0x30 && code <= 0x39) {
    return code - 0x30;
  }
  if (code >= 0x61 && code <= 0x66) {
    return code - 0x61 + 10;
  }
  if (code >= 0x41 && code <= 0x46) {
    return code - 0x41 + 10;
  }
  throw new Error(
    'hexDecode: invalid hex character at index ' + String(index) + ' (code ' + String(code) + ')',
  );
}

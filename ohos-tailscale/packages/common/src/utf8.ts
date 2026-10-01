/**
 * UTF-8 编解码（纯 TS 手写，零平台依赖）。
 *
 * 依据 constraints §6-U3：TextEncoder/TextDecoder 在 ArkTS 运行时的可用性未验证，
 * 因此不使用任何平台 API，手写实现，可原样迁移。
 *
 * 策略：双侧严格。
 * - encode：遇到孤立代理项（lone surrogate，JS 字符串可承载但 UTF-8 无编码）抛 Error；
 * - decode：拒绝截断序列、超长（overlong）编码、代理项区（U+D800..DFFF）、
 *   超出 U+10FFFF 的码点，任一出现抛 Error。
 */

export function utf8Encode(s: string): Uint8Array {
  const out: number[] = [];
  let i: number = 0;
  while (i < s.length) {
    const c: number = s.charCodeAt(i);
    if (c >= 0xd800 && c <= 0xdbff) {
      if (i + 1 >= s.length) {
        throw new Error('utf8Encode: lone high surrogate at index ' + String(i));
      }
      const d: number = s.charCodeAt(i + 1);
      if (d < 0xdc00 || d > 0xdfff) {
        throw new Error('utf8Encode: unpaired high surrogate at index ' + String(i));
      }
      const cp: number = 0x10000 + ((c - 0xd800) << 10) + (d - 0xdc00);
      push4(out, cp);
      i += 2;
    } else if (c >= 0xdc00 && c <= 0xdfff) {
      throw new Error('utf8Encode: lone low surrogate at index ' + String(i));
    } else if (c <= 0x7f) {
      out.push(c);
      i += 1;
    } else if (c <= 0x7ff) {
      out.push(0xc0 | (c >> 6), 0x80 | (c & 0x3f));
      i += 1;
    } else {
      out.push(0xe0 | (c >> 12), 0x80 | ((c >> 6) & 0x3f), 0x80 | (c & 0x3f));
      i += 1;
    }
  }
  return Uint8Array.from(out);
}

function push4(out: number[], cp: number): void {
  out.push(
    0xf0 | (cp >> 18),
    0x80 | ((cp >> 12) & 0x3f),
    0x80 | ((cp >> 6) & 0x3f),
    0x80 | (cp & 0x3f),
  );
}

export function utf8Decode(bytes: Uint8Array): string {
  let out: string = '';
  let i: number = 0;
  while (i < bytes.length) {
    const b0: number = bytes[i];
    if (b0 < 0x80) {
      out += String.fromCharCode(b0);
      i += 1;
      continue;
    }
    let len: number;
    let cp: number;
    // 第二个字节的严格上下界：默认 80..BF；E0 拒绝 overlong、ED 拒绝代理项、F0 拒绝 overlong、F4 限 ≤ U+10FFFF
    let min2: number = 0x80;
    let max2: number = 0xbf;
    if (b0 >= 0xc2 && b0 <= 0xdf) {
      len = 2;
      cp = b0 & 0x1f;
    } else if (b0 >= 0xe0 && b0 <= 0xef) {
      len = 3;
      cp = b0 & 0x0f;
      if (b0 === 0xe0) {
        min2 = 0xa0;
      } else if (b0 === 0xed) {
        max2 = 0x9f;
      }
    } else if (b0 >= 0xf0 && b0 <= 0xf4) {
      len = 4;
      cp = b0 & 0x07;
      if (b0 === 0xf0) {
        min2 = 0x90;
      } else if (b0 === 0xf4) {
        max2 = 0x8f;
      }
    } else {
      throw new Error('utf8Decode: invalid leading byte 0x' + b0.toString(16) + ' at index ' + String(i));
    }
    if (i + len > bytes.length) {
      throw new Error('utf8Decode: truncated sequence at index ' + String(i));
    }
    if (bytes[i + 1] < min2 || bytes[i + 1] > max2) {
      throw new Error('utf8Decode: invalid continuation byte at index ' + String(i + 1));
    }
    for (let k: number = 1; k < len; k += 1) {
      const b: number = bytes[i + k];
      if (b < 0x80 || b > 0xbf) {
        throw new Error('utf8Decode: invalid continuation byte at index ' + String(i + k));
      }
      cp = (cp << 6) | (b & 0x3f);
    }
    if (cp >= 0xd800 && cp <= 0xdfff) {
      throw new Error('utf8Decode: surrogate code point at index ' + String(i));
    }
    if (cp > 0x10ffff) {
      throw new Error('utf8Decode: code point out of range at index ' + String(i));
    }
    if (cp <= 0xffff) {
      out += String.fromCharCode(cp);
    } else {
      const v: number = cp - 0x10000;
      out += String.fromCharCode(0xd800 + (v >> 10), 0xdc00 + (v & 0x3ff));
    }
    i += len;
  }
  return out;
}

/**
 * base64 编解码（RFC 4648；P5/U4：不使用 Buffer/btoa/atob，手写纯 TS）。
 *
 * 提供 std（'+'、'/'）与 url（'-'、'_'）两套，均带 '=' 填充。
 * 解码为严格模式：长度必须是 4 的倍数、'=' 只能出现在末尾（1~2 个）、
 * 非填充字符的剩余位必须为 0（canonical），否则抛 Error。
 */

const STD_ALPHABET: string = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';
const URL_ALPHABET: string = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_';

/** 标准 base64（带 '=' 填充）。 */
export function base64Encode(src: Uint8Array): string {
  return encodeWith(src, STD_ALPHABET);
}

/** 标准 base64 解码（严格、canonical）。 */
export function base64Decode(s: string): Uint8Array {
  return decodeWith(s, STD_ALPHABET);
}

/** URL-safe base64（'-'、'_'，带 '=' 填充）。 */
export function base64UrlEncode(src: Uint8Array): string {
  return encodeWith(src, URL_ALPHABET);
}

/** URL-safe base64 解码（严格、canonical）。 */
export function base64UrlDecode(s: string): Uint8Array {
  return decodeWith(s, URL_ALPHABET);
}

function encodeWith(src: Uint8Array, alphabet: string): string {
  let out: string = '';
  let i: number = 0;
  for (; i + 3 <= src.length; i += 3) {
    const n: number = (src[i] << 16) | (src[i + 1] << 8) | src[i + 2];
    out += alphabet.charAt((n >> 18) & 0x3f);
    out += alphabet.charAt((n >> 12) & 0x3f);
    out += alphabet.charAt((n >> 6) & 0x3f);
    out += alphabet.charAt(n & 0x3f);
  }
  const rest: number = src.length - i;
  if (rest === 1) {
    const n: number = src[i] << 16;
    out += alphabet.charAt((n >> 18) & 0x3f);
    out += alphabet.charAt((n >> 12) & 0x3f);
    out += '==';
  } else if (rest === 2) {
    const n: number = (src[i] << 16) | (src[i + 1] << 8);
    out += alphabet.charAt((n >> 18) & 0x3f);
    out += alphabet.charAt((n >> 12) & 0x3f);
    out += alphabet.charAt((n >> 6) & 0x3f);
    out += '=';
  }
  return out;
}

function decodeWith(s: string, alphabet: string): Uint8Array {
  if (s.length % 4 !== 0) {
    throw new Error('base64Decode: length ' + String(s.length) + ' is not a multiple of 4');
  }
  let pad: number = 0;
  for (let i: number = s.length - 1; i >= 0 && s.charAt(i) === '='; i -= 1) {
    pad += 1;
  }
  if (pad > 2) {
    throw new Error('base64Decode: too much padding');
  }
  const dataLen: number = s.length - pad;
  const outLen: number = Math.floor((s.length * 3) / 4) - pad;
  const out: Uint8Array = new Uint8Array(outLen);
  let acc: number = 0;
  let bits: number = 0;
  let o: number = 0;
  for (let i: number = 0; i < s.length; i += 1) {
    const ch: string = s.charAt(i);
    if (i >= dataLen) {
      break;
    }
    const code: number = ch.charCodeAt(0);
    if (code > 0x7f) {
      throw new Error('base64Decode: non-ASCII character at index ' + String(i));
    }
    const v: number = alphabet.indexOf(ch);
    if (v < 0) {
      throw new Error('base64Decode: invalid character ' + JSON.stringify(ch) + ' at index ' + String(i));
    }
    acc = (acc << 6) | v;
    bits += 6;
    if (bits >= 8) {
      bits -= 8;
      out[o] = (acc >> bits) & 0xff;
      o += 1;
    }
  }
  if (o !== outLen) {
    throw new Error('base64Decode: decoded ' + String(o) + ' bytes, expected ' + String(outLen));
  }
  // canonical 校验：最后一个数据字符的低（pad*2）位必须为 0
  if (dataLen > 0 && pad > 0) {
    const lastCh: string = s.charAt(dataLen - 1);
    const v: number = alphabet.indexOf(lastCh);
    if (v < 0 || (v & ((1 << (pad * 2)) - 1)) !== 0) {
      throw new Error('base64Decode: non-canonical trailing bits');
    }
  }
  return out;
}

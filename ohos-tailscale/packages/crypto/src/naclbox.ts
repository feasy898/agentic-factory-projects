/**
 * NaCl box（AU2/DERP 对齐所需）：X25519 + XSalsa20-Poly1305（golang.org/x/crypto/nacl/box
 * 语义）。tailscale DERP 的 FrameClientInfo 用 NodePrivate.SealTo = box.Seal(nonce,
 * cleartext, nonce, peerPub, selfPriv)——输出 nonce(24B) ‖ sealed(密文+16B tag)。
 *
 * 组成（全手写，P5 禁 Buffer/依赖）：
 * - 共享密钥 = X25519(本端私钥, 对端公钥)（复用 x25519.ts）；
 * - XSalsa20：HSalsa20(shared, nonce[0..16]) 派生 32B 子密钥，再以 Salsa20
 *   (子密钥, nonce[16..24], 计数器 0) 生成密钥流；密钥流前 32B 兼作 Poly1305 密钥；
 * - Poly1305：复用 aead.ts 的 poly1305Mac（与 RFC 8439 向量已锚定）；
 * - 正确性由 test/naclbox.test.ts 与 tweetnacl（devDependency，仅测试）交叉验证。
 */

import { x25519 } from './x25519.ts';
import { poly1305Mac } from './aead.ts';

const SIGMA: Uint32Array = new Uint32Array([0x61707865, 0x3320646e, 0x79622d32, 0x6b206574]);

/**
 * box_beforenm（NaCl 标准）：sharedKey = HSalsa20(X25519(本端私钥, 对端公钥), 全零输入)。
 * ⚠ 标准 crypto_box 的密钥折叠就是对 DH 输出再过一次 HSalsa20（Go nacl/box.Precompute、
 * tweetnacl box_beforenm 同型），与"裸 X25519"不同——本次与 tweetnacl 互操作实测锚定。
 */
export function naclboxSharedKey(privateKey: Uint8Array, peerPublicKey: Uint8Array): Uint8Array {
  const raw: Uint8Array = x25519(privateKey, peerPublicKey);
  return subkeyBytes(hsalsa20(raw, new Uint8Array(16)));
}

/**
 * 消息加密密钥流：从 counter=0 块的第 32 字节起（前 32B 归 Poly1305），随后接
 * counter=1,2,… 各块——nacl secretbox 的经典构造（把 32B 零填充异或出 poly 密钥区，
 * 消息流紧随其后），不是 ChaCha20-Poly1305 的"MAC 用块 0、密文从块 1 起"。
 */
function secretboxStream(subkey: Uint32Array, nonce8: Uint8Array, length: number): Uint8Array {
  const block0: Uint8Array = salsa20Block(subkey, nonce8, 0);
  const out: Uint8Array = new Uint8Array(length);
  let done: number = 0;
  const fromBlock0: number = Math.min(32, length);
  for (let i: number = 0; i < fromBlock0; i += 1) {
    out[i] = block0[32 + i];
  }
  done = fromBlock0;
  let counter: number = 1;
  while (done < length) {
    const block: Uint8Array = salsa20Block(subkey, nonce8, counter);
    const take: number = Math.min(64, length - done);
    for (let i: number = 0; i < take; i += 1) {
      out[done + i] = block[i];
    }
    done += take;
    counter += 1;
  }
  return out;
}

/** XSalsa20-Poly1305 封装（Go secretbox 布局）：返回 16B tag ‖ 密文（新数组）。MAC 输入是密文。 */
export function salsa20Poly1305Seal(sharedKey: Uint8Array, nonce24: Uint8Array, plaintext: Uint8Array): Uint8Array {
  if (sharedKey.length !== 32) {
    throw new Error('naclbox: shared key must be 32B');
  }
  if (nonce24.length !== 24) {
    throw new Error('naclbox: nonce must be 24B');
  }
  const subkey: Uint32Array = hsalsa20(sharedKey, nonce24);
  const nonce8: Uint8Array = nonce24.subarray(16, 24);
  const block0Key: Uint8Array = salsa20Block(subkey, nonce8, 0).slice(0, 32); // 密钥流前 32B 兼作 Poly1305 密钥
  const stream: Uint8Array = secretboxStream(subkey, nonce8, plaintext.length);
  const out: Uint8Array = new Uint8Array(plaintext.length + 16);
  for (let i: number = 0; i < plaintext.length; i += 1) {
    out[16 + i] = plaintext[i] ^ stream[i];
  }
  const tag: Uint8Array = poly1305Mac(block0Key, out.slice(16));
  out.set(tag, 0);
  return out;
}

/** XSalsa20-Poly1305 解封（Go secretbox 布局：tag ‖ 密文）：认证失败返回 null。 */
export function salsa20Poly1305Open(sharedKey: Uint8Array, nonce24: Uint8Array, sealed: Uint8Array): Uint8Array | null {
  if (sealed.length < 16) {
    return null;
  }
  const subkey: Uint32Array = hsalsa20(sharedKey, nonce24);
  const nonce8: Uint8Array = nonce24.subarray(16, 24);
  const block0Key: Uint8Array = salsa20Block(subkey, nonce8, 0).slice(0, 32);
  const expectedTag: Uint8Array = poly1305Mac(block0Key, sealed.slice(16));
  for (let i: number = 0; i < 16; i += 1) {
    const a: number = expectedTag[i];
    const b: number = sealed[i];
    if (a !== b) {
      return null;
    }
  }
  const stream: Uint8Array = secretboxStream(subkey, nonce8, sealed.length - 16);
  const out: Uint8Array = new Uint8Array(sealed.length - 16);
  for (let i: number = 0; i < out.length; i += 1) {
    out[i] = sealed[16 + i] ^ stream[i];
  }
  return out;
}

/**
 * box.Seal 语义封装：输出 nonce(24B) ‖ 16B tag ‖ 密文（Go 布局；DERP FrameClientInfo
 * 的 naclbox 段即此形态去 nonce）。nonce 由调用方注入（随机性由调用方的 Rng 提供，
 * 核心 src 不自带随机源）。
 */
export function naclboxSeal(
  privateKey: Uint8Array,
  peerPublicKey: Uint8Array,
  nonce24: Uint8Array,
  plaintext: Uint8Array,
): Uint8Array {
  const shared: Uint8Array = naclboxSharedKey(privateKey, peerPublicKey);
  const sealed: Uint8Array = salsa20Poly1305Seal(shared, nonce24, plaintext);
  const out: Uint8Array = new Uint8Array(24 + sealed.length);
  out.set(nonce24, 0);
  out.set(sealed, 24);
  return out;
}

/** box.Open 语义封装：输入 nonce(24B) ‖ 16B tag ‖ 密文；认证失败返回 null。 */
export function naclboxOpen(
  privateKey: Uint8Array,
  peerPublicKey: Uint8Array,
  sealedWithNonce: Uint8Array,
): Uint8Array | null {
  if (sealedWithNonce.length < 24 + 16) {
    return null;
  }
  const shared: Uint8Array = naclboxSharedKey(privateKey, peerPublicKey);
  return salsa20Poly1305Open(shared, sealedWithNonce.slice(0, 24), sealedWithNonce.slice(24));
}

/** HSalsa20（Bernstein）：20 轮、不回加初始态；输出 x0,x5,x10,x15,x6,x7,x8,x9 共 32B。 */
function hsalsa20(key32: Uint8Array, input16: Uint8Array): Uint32Array {
  const state: Uint32Array = salsa20CoreInit(key32, input16, 0);
  const x: Uint32Array = state.slice();
  salsa20Rounds(x);
  const out: Uint32Array = new Uint32Array(8);
  out[0] = x[0];
  out[1] = x[5];
  out[2] = x[10];
  out[3] = x[15];
  out[4] = x[6];
  out[5] = x[7];
  out[6] = x[8];
  out[7] = x[9];
  return out;
}

/** Salsa20 单块（64B）：20 轮后回加初始态，输出字序 0..15。 */
function salsa20Block(subkeyWords: Uint32Array, nonce8: Uint8Array, counter: number): Uint8Array {
  const keyWords: Uint32Array = wordsFromBytes(subkeyBytes(subkeyWords));
  const state: Uint32Array = new Uint32Array(16);
  state[0] = SIGMA[0];
  state[1] = keyWords[0];
  state[2] = keyWords[1];
  state[3] = keyWords[2];
  state[4] = keyWords[3];
  state[5] = SIGMA[1];
  state[6] = u32FromBytesLE(nonce8.subarray(0, 4));
  state[7] = u32FromBytesLE(nonce8.subarray(4, 8));
  state[8] = counter >>> 0;
  state[9] = 0;
  state[10] = SIGMA[2];
  state[11] = keyWords[4];
  state[12] = keyWords[5];
  state[13] = keyWords[6];
  state[14] = keyWords[7];
  state[15] = SIGMA[3];
  const x: Uint32Array = state.slice();
  salsa20Rounds(x);
  const out: Uint8Array = new Uint8Array(64);
  for (let w: number = 0; w < 16; w += 1) {
    u32ToBytesLE((x[w] + state[w]) >>> 0, out, w * 4);
  }
  return out;
}

/** Salsa20 初始态（含 128B 计数器布局的 HSalsa20 输入分支：counter 位恒 0）。 */
function salsa20CoreInit(key32: Uint8Array, input16: Uint8Array, counter: number): Uint32Array {
  const k: Uint32Array = new Uint32Array(8);
  for (let i: number = 0; i < 8; i += 1) {
    k[i] = u32FromBytesLE(key32.subarray(i * 4, i * 4 + 4));
  }
  const state: Uint32Array = new Uint32Array(16);
  state[0] = SIGMA[0];
  state[1] = k[0];
  state[2] = k[1];
  state[3] = k[2];
  state[4] = k[3];
  state[5] = SIGMA[1];
  state[6] = u32FromBytesLE(input16.subarray(0, 4));
  state[7] = u32FromBytesLE(input16.subarray(4, 8));
  state[8] = u32FromBytesLE(input16.subarray(8, 12));
  state[9] = u32FromBytesLE(input16.subarray(12, 16));
  state[10] = SIGMA[2];
  state[11] = k[4];
  state[12] = k[5];
  state[13] = k[6];
  state[14] = k[7];
  state[15] = SIGMA[3];
  if (counter !== 0) {
    state[8] = counter >>> 0;
    state[9] = 0;
  }
  return state;
}

function salsa20Rounds(x: Uint32Array): void {
  for (let round: number = 0; round < 10; round += 1) {
    // 列轮（quarterround on columns）
    qround(x, 0, 4, 8, 12);
    qround(x, 5, 9, 13, 1);
    qround(x, 10, 14, 2, 6);
    qround(x, 15, 3, 7, 11);
    // 行轮（quarterround on rows）
    qround(x, 0, 1, 2, 3);
    qround(x, 5, 6, 7, 4);
    qround(x, 10, 11, 8, 9);
    qround(x, 15, 12, 13, 14);
  }
}

function qround(x: Uint32Array, a: number, b: number, c: number, d: number): void {
  x[b] = (x[b] ^ rotl32(x[a] + x[d], 7)) >>> 0;
  x[c] = (x[c] ^ rotl32(x[b] + x[a], 9)) >>> 0;
  x[d] = (x[d] ^ rotl32(x[c] + x[b], 13)) >>> 0;
  x[a] = (x[a] ^ rotl32(x[d] + x[c], 18)) >>> 0;
}

function rotl32(v: number, n: number): number {
  const u: number = v >>> 0;
  return ((u << n) | (u >>> (32 - n))) >>> 0;
}

function u32FromBytesLE(b: Uint8Array): number {
  return ((b[0] | (b[1] << 8) | (b[2] << 16) | (b[3] << 24)) >>> 0);
}

function u32ToBytesLE(v: number, out: Uint8Array, off: number): void {
  const u: number = v >>> 0;
  out[off] = u & 0xff;
  out[off + 1] = (u >>> 8) & 0xff;
  out[off + 2] = (u >>> 16) & 0xff;
  out[off + 3] = (u >>> 24) & 0xff;
}

function subkeyBytes(words: Uint32Array): Uint8Array {
  const out: Uint8Array = new Uint8Array(32);
  for (let i: number = 0; i < 8; i += 1) {
    u32ToBytesLE(words[i], out, i * 4);
  }
  return out;
}

function wordsFromBytes(b: Uint8Array): Uint32Array {
  const out: Uint32Array = new Uint32Array(8);
  for (let i: number = 0; i < 8; i += 1) {
    out[i] = u32FromBytesLE(b.subarray(i * 4, i * 4 + 4));
  }
  return out;
}

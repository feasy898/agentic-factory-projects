/**
 * naclbox（NaCl box / XSalsa20-Poly1305）测试。
 *
 * 交叉验证策略：与独立参考实现 tweetnacl（devDependency，仅测试可用）互开互验。
 * 布局核对结论（2026-09-29 实测锚定）：标准 NaCl box = beforenm(HSalsa20(X25519,0))
 * + secretbox（内部再 HSalsa20(nonce[0:16])）；输出 Go 布局 = nonce ‖ 16B tag ‖ 密文
 * （MAC 输入是密文）。tweetnacl 与本实现现已逐字节同布局，直接互比。
 */

import { test } from 'node:test';
import assert from 'node:assert/strict';
import nacl from 'tweetnacl';
import {
  naclboxOpen,
  naclboxSeal,
  salsa20Poly1305Open,
  salsa20Poly1305Seal,
} from '../src/naclbox.ts';
import { x25519PublicKeyFromPrivate } from '../src/x25519.ts';

const A_PRIV: Uint8Array = new Uint8Array(32).fill(0x11);
const B_PRIV: Uint8Array = new Uint8Array(32).fill(0x22);
const A_PUB: Uint8Array = x25519PublicKeyFromPrivate(A_PRIV);
const B_PUB: Uint8Array = x25519PublicKeyFromPrivate(B_PRIV);
const NONCE: Uint8Array = Uint8Array.from(
  [0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x0a, 0x0b, 0x0c, 0x0d, 0x0e, 0x0f, 0x10, 0x11, 0x12, 0x13, 0x14, 0x15, 0x16, 0x17],
);
const MESSAGE: Uint8Array = new TextEncoder().encode('DERP FrameClientInfo payload {"Version":2,"MeshKey":""}');

test('我方 seal → tweetnacl open（字节级一致）', () => {
  const sealed: Uint8Array = naclboxSeal(A_PRIV, B_PUB, NONCE, MESSAGE);
  assert.equal(sealed.length, 24 + MESSAGE.length + 16);
  const opened: Uint8Array | null = nacl.box.open(sealed.slice(24), NONCE, A_PUB, B_PRIV);
  assert.ok(opened !== null, 'tweetnacl must open our box');
  assert.deepEqual(Array.from(opened), Array.from(MESSAGE));
});

test('tweetnacl seal → 我方 open（字节级一致）', () => {
  const sealedNoNonce: Uint8Array | null = nacl.box(MESSAGE, NONCE, A_PUB, B_PRIV);
  assert.ok(sealedNoNonce !== null);
  const withNonce: Uint8Array = new Uint8Array(24 + sealedNoNonce.length);
  withNonce.set(NONCE, 0);
  withNonce.set(sealedNoNonce, 24);
  const opened: Uint8Array | null = naclboxOpen(A_PRIV, B_PUB, withNonce);
  assert.ok(opened !== null);
  assert.deepEqual(Array.from(opened), Array.from(MESSAGE));
});

test('往返与篡改拒绝', () => {
  const sealed: Uint8Array = naclboxSeal(A_PRIV, B_PUB, NONCE, MESSAGE);
  const opened: Uint8Array | null = naclboxOpen(B_PRIV, A_PUB, sealed);
  assert.ok(opened !== null);
  assert.deepEqual(Array.from(opened), Array.from(MESSAGE));
  const tampered: Uint8Array = sealed.slice();
  tampered[30] = (tampered[30] + 1) & 0xff;
  assert.equal(naclboxOpen(B_PRIV, A_PUB, tampered), null);
  assert.equal(nacl.box.open(tampered.slice(24), NONCE, A_PUB, B_PRIV), null);
});

test('长消息（跨 Salsa20 块，>64B）与空消息', () => {
  const long: Uint8Array = new Uint8Array(300);
  for (let i: number = 0; i < 300; i += 1) {
    long[i] = i & 0xff;
  }
  const sealed: Uint8Array = naclboxSeal(A_PRIV, B_PUB, NONCE, long);
  const opened: Uint8Array | null = nacl.box.open(sealed.slice(24), NONCE, A_PUB, B_PRIV);
  assert.ok(opened !== null);
  assert.equal(opened.length, 300);
  const empty: Uint8Array = new Uint8Array(0);
  const sealedEmpty: Uint8Array = naclboxSeal(A_PRIV, B_PUB, NONCE, empty);
  assert.equal(sealedEmpty.length, 40);
  assert.ok(nacl.box.open(sealedEmpty.slice(24), NONCE, A_PUB, B_PRIV) !== null);
});

test('salsa20Poly1305 裸接口与 nacl.secretbox 逐字节一致', () => {
  const shared: Uint8Array = nacl.box.before(B_PUB, A_PRIV);
  const sealedMine: Uint8Array = salsa20Poly1305Seal(shared, NONCE, MESSAGE);
  const sealedRef: Uint8Array = nacl.secretbox(MESSAGE, NONCE, shared);
  assert.equal(Buffer.from(sealedMine).toString('hex'), Buffer.from(sealedRef).toString('hex'));
  const opened: Uint8Array | null = salsa20Poly1305Open(shared, NONCE, sealedRef);
  assert.ok(opened !== null);
  assert.deepEqual(Array.from(opened), Array.from(MESSAGE));
});

/**
 * Transport Data 测试：
 * - 加解密往返（含 keepalive 零载荷、跨块长度）；
 * - 报文结构：type=4 u32le / receiver index / counter u64le（小端）；
 * - **node:crypto（OpenSSL）独立锚定**：encryptPacket 输出（counter 0/1/2）
 *   与 node:crypto 以 wireguard-go nonce 规则（4B 零 || LE64(counter)）封装的
 *   结果逐字节一致 —— 防两端自洽的 nonce 端序偏差（评审 finding 1 类）；
 * - 高计数器（2^31、2^53+1）经测试内手造报文覆盖接收路径（WgSendSession
 *   契约签名不含计数器注入，发送侧高计数器覆盖见文件尾说明）；
 * - 反重放窗口：重复包 REPLAY、窗口内乱序可收、窗口外过旧 REPLAY；
 * - 失败路径：篡改 → DECRYPT、类型/长度/索引错误；
 * - 输出独立拷贝语义。
 *
 * 契约说明：architecture.md §5 冻结 WgSendSession 构造签名为
 * (localIndex, sendKey)，无计数器注入点 —— 发送侧无法经公开 API 到达
 * 2^31/2^53+1 计数器（§5.2 要求该覆盖）。本文件以手造报文覆盖接收侧
 * 高计数器语义（nonce 端序/窗口 BigInt 移位），发送侧高计数器的覆盖缺口
 * 作为 §5.2 与冻结签名的冲突上报修订（见模块结果）。
 */

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createCipheriv } from 'node:crypto';
import { ByteWriter, hexEncode } from '@ohos-tailscale/common';
import { aeadSeal } from '@ohos-tailscale/crypto';
import { WgRecvSession, WgSendSession } from '../src/index.ts';
import { WgProtocolError } from '../src/errors.ts';

/** 确定性字节序列（测试夹具）。 */
const seqBytes = (n: number, seed: number): Uint8Array => {
  const out: Uint8Array = new Uint8Array(n);
  for (let i: number = 0; i < n; i += 1) {
    out[i] = (seed + i * 31) % 256;
  }
  return out;
};

const KEY_A2B: Uint8Array = seqBytes(32, 1); // A → B 方向密钥
const IDX_A: number = 0x11223344; // A 的本地索引（B 收包时的 receiver index）
const IDX_B: number = 0x55667788; // B 的本地索引（A 发包时的 receiver index）
const EMPTY: Uint8Array = new Uint8Array(0);

const assertWgError = (fn: () => void, code: string): void => {
  let thrown: boolean = false;
  let gotCode: string = '';
  try {
    fn();
  } catch (e) {
    thrown = true;
    const err: WgProtocolError = e as WgProtocolError;
    gotCode = err.code;
  }
  assert.equal(thrown, true, 'expected WgProtocolError not thrown');
  assert.equal(gotCode, code, 'unexpected WgProtocolError code');
};

/** 传输 nonce（wireguard-go send.go:465 规则：4B 零 || LE64(counter)）。 */
const leNonce = (counter: bigint): Uint8Array => {
  const nonce: Uint8Array = new Uint8Array(12);
  let x: bigint = counter;
  for (let i: number = 4; i <= 11; i += 1) {
    nonce[i] = Number(x & 0xffn);
    x >>= 8n;
  }
  return nonce;
};

/** 测试内手造传输报文（覆盖发送会话无法注入的高计数器/任意 counter）。 */
const craftPacket = (
  key: Uint8Array,
  receiverIndex: number,
  counter: bigint,
  plaintext: Uint8Array,
): Uint8Array => {
  const sealed: Uint8Array = aeadSeal(key, leNonce(counter), plaintext, EMPTY);
  const w: ByteWriter = new ByteWriter(16);
  w.writeU32le(4);
  w.writeU32le(receiverIndex);
  w.writeU64le(counter);
  w.writeBytes(sealed);
  return w.toUint8Array();
};

/** node:crypto 封装（独立实现）：ciphertext || tag。 */
const nodeSeal = (key: Uint8Array, nonce: Uint8Array, pt: Uint8Array): Uint8Array => {
  const cipher = createCipheriv('chacha20-poly1305', key, nonce, { authTagLength: 16 });
  cipher.setAAD(EMPTY);
  const ct: Uint8Array = new Uint8Array(cipher.update(pt));
  const tail: Uint8Array = new Uint8Array(cipher.final());
  const tag: Uint8Array = new Uint8Array(cipher.getAuthTag());
  const out: Uint8Array = new Uint8Array(ct.length + tail.length + tag.length);
  out.set(ct, 0);
  out.set(tail, ct.length);
  out.set(tag, ct.length + tail.length);
  return out;
};

test('构造入参校验：键长/索引范围', () => {
  assert.throws(() => new WgSendSession(IDX_A, seqBytes(31, 2)));
  assert.throws(() => new WgRecvSession(IDX_B, seqBytes(33, 2)));
  assert.throws(() => new WgSendSession(-1, KEY_A2B));
  assert.throws(() => new WgSendSession(4294967296, KEY_A2B));
});

test('往返：多长度明文（含 keepalive 零载荷与跨块大包）', () => {
  const send: WgSendSession = new WgSendSession(IDX_A, KEY_A2B);
  const recv: WgRecvSession = new WgRecvSession(IDX_A, KEY_A2B);
  const lens: number[] = [0, 1, 15, 16, 17, 63, 64, 65, 255, 1000, 1500];
  for (const len of lens) {
    const pt: Uint8Array = seqBytes(len, len + 1);
    const pkt: Uint8Array = send.encryptPacket(pt);
    assert.equal(pkt.length, 16 + len + 16, 'packet length at pt=' + String(len));
    assert.deepEqual(recv.decryptPacket(pkt), pt, 'roundtrip at pt=' + String(len));
  }
});

test('keepalive：零载荷 → 32B 报文，解密返回零长度数组', () => {
  const send: WgSendSession = new WgSendSession(IDX_A, KEY_A2B);
  const recv: WgRecvSession = new WgRecvSession(IDX_A, KEY_A2B);
  const pkt: Uint8Array = send.encryptPacket(EMPTY);
  assert.equal(pkt.length, 32);
  const pt: Uint8Array = recv.decryptPacket(pkt);
  assert.equal(pt.length, 0);
});

test('报文结构：type u32le=4 / receiver index / counter u64le 小端（counter 0..2）', () => {
  const send: WgSendSession = new WgSendSession(IDX_A, KEY_A2B);
  const counters: string[] = ['0000000000000000', '0100000000000000', '0200000000000000'];
  for (let i = 0; i < counters.length; i += 1) {
    const pkt: Uint8Array = send.encryptPacket(new Uint8Array(4));
    assert.equal(pkt[0], 4);
    assert.deepEqual(pkt.slice(1, 4), new Uint8Array(3), 'reserved must be zero');
    const dv: DataView = new DataView(pkt.buffer, pkt.byteOffset);
    assert.equal(dv.getUint32(4, true), IDX_A);
    assert.equal(hexEncode(pkt.slice(8, 16)), counters[i], 'counter le64 at ' + String(i));
  }
});

test('**node:crypto 锚定**：encryptPacket == OpenSSL chacha20-poly1305（LE64 nonce，counter≥1）', () => {
  const send: WgSendSession = new WgSendSession(IDX_A, KEY_A2B);
  // 逐包与 node:crypto 对照：nonce 若为大端即在此失败（counter=0 双方同为全零，
  // counter=1/2 才区分端序 —— 评审 finding 1 的回归锚）
  for (const ptLen of [0, 5, 64]) {
    const probe: WgSendSession = new WgSendSession(IDX_A, KEY_A2B);
    for (const counter of [0n, 1n, 2n]) {
      const pt: Uint8Array = seqBytes(ptLen, ptLen * 7 + Number(counter) + 1);
      const pkt: Uint8Array = probe.encryptPacket(pt);
      const expect: Uint8Array = nodeSeal(KEY_A2B, leNonce(counter), pt);
      assert.deepEqual(pkt.slice(16), expect, 'AEAD output mismatch at counter=' + counter.toString());
      assert.equal(hexEncode(pkt.slice(8, 16)), hexEncode(leNonce(counter).slice(4)), 'counter bytes LE');
    }
  }
  // node 封 → 我方接收会话解（counter=1）
  const recv: WgRecvSession = new WgRecvSession(IDX_A, KEY_A2B);
  const pt: Uint8Array = seqBytes(20, 9);
  const nodePkt: Uint8Array = craftFromNode(pt, 1n);
  assert.deepEqual(recv.decryptPacket(nodePkt), pt);
});

/** node:crypto 封装 → 手工组头（counter=1 路径的独立实现互验）。 */
const craftFromNode = (pt: Uint8Array, counter: bigint): Uint8Array => {
  const sealed: Uint8Array = nodeSeal(KEY_A2B, leNonce(counter), pt);
  const w: ByteWriter = new ByteWriter(16);
  w.writeU32le(4);
  w.writeU32le(IDX_A);
  w.writeU64le(counter);
  w.writeBytes(sealed);
  return w.toUint8Array();
};

test('高计数器接收路径：2^31 与 2^53+1（手造报文，nonce LE + BigInt 窗口）', () => {
  const recv: WgRecvSession = new WgRecvSession(IDX_A, KEY_A2B);
  // 2^31（0x80000000）
  const p31: Uint8Array = craftPacket(KEY_A2B, IDX_A, 2147483648n, seqBytes(10, 3));
  assert.equal(hexEncode(p31.slice(8, 16)), '0000008000000000');
  assert.deepEqual(recv.decryptPacket(p31), seqBytes(10, 3));
  // 2^53+1（0x0020000000000001，Number 精度之外）
  const p53: Uint8Array = craftPacket(KEY_A2B, IDX_A, 9007199254740993n, seqBytes(10, 4));
  assert.equal(hexEncode(p53.slice(8, 16)), '0100000000002000');
  assert.deepEqual(recv.decryptPacket(p53), seqBytes(10, 4));
  // 2^53+2 继续可解
  const p54: Uint8Array = craftPacket(KEY_A2B, IDX_A, 9007199254740994n, seqBytes(10, 5));
  assert.deepEqual(recv.decryptPacket(p54), seqBytes(10, 5));
});

test('反重放：同包重发 → REPLAY；窗口内乱序可收；重复再收 → REPLAY', () => {
  const recv: WgRecvSession = new WgRecvSession(IDX_A, KEY_A2B);
  const p0: Uint8Array = craftPacket(KEY_A2B, IDX_A, 0n, seqBytes(8, 6));
  const p1: Uint8Array = craftPacket(KEY_A2B, IDX_A, 1n, seqBytes(8, 7));
  const p5: Uint8Array = craftPacket(KEY_A2B, IDX_A, 5n, seqBytes(8, 8));
  const p3: Uint8Array = craftPacket(KEY_A2B, IDX_A, 3n, seqBytes(8, 9));
  assert.deepEqual(recv.decryptPacket(p0), seqBytes(8, 6));
  // 重复 p0 → REPLAY
  assertWgError(() => recv.decryptPacket(p0), 'REPLAY');
  // 窗口内乱序：先收 5，再收 3，仍可解（位图未置位）
  assert.deepEqual(recv.decryptPacket(p5), seqBytes(8, 8));
  assert.deepEqual(recv.decryptPacket(p3), seqBytes(8, 9));
  // p3 重复 → REPLAY；p1（counter 1）正常解
  assertWgError(() => recv.decryptPacket(p3), 'REPLAY');
  assert.deepEqual(recv.decryptPacket(p1), seqBytes(8, 7));
});

test('反重放：超出 2048 位窗口的过旧计数器 → REPLAY', () => {
  const recv: WgRecvSession = new WgRecvSession(IDX_A, KEY_A2B);
  // 最高 5000（首个包直接置 highest）
  assert.deepEqual(
    recv.decryptPacket(craftPacket(KEY_A2B, IDX_A, 5000n, new Uint8Array(1))),
    new Uint8Array(1),
  );
  // counter=1：back = 4999 ≥ 2048 → REPLAY
  assertWgError(() => recv.decryptPacket(craftPacket(KEY_A2B, IDX_A, 1n, new Uint8Array(1))), 'REPLAY');
  // 窗口边界内（counter = 5000-2047 = 2953）可收
  assert.deepEqual(
    recv.decryptPacket(craftPacket(KEY_A2B, IDX_A, 2953n, new Uint8Array(1))),
    new Uint8Array(1),
  );
});

test('篡改密文/tag → DECRYPT；被篡改包不消耗反重放窗口槽位', () => {
  const send: WgSendSession = new WgSendSession(IDX_A, KEY_A2B);
  const recv: WgRecvSession = new WgRecvSession(IDX_A, KEY_A2B);
  const p0: Uint8Array = send.encryptPacket(seqBytes(8, 10));
  const p1: Uint8Array = send.encryptPacket(seqBytes(8, 11));
  // 篡改 counter=0 包的密文首字节
  const bad: Uint8Array = p0.slice();
  bad[16] = (bad[16] ^ 0x01) & 0xff;
  assertWgError(() => recv.decryptPacket(bad), 'DECRYPT');
  // 同 counter 的真包仍可解（窗口未被坏包消耗）
  assert.deepEqual(recv.decryptPacket(p0), seqBytes(8, 10));
  // 篡改 counter 头字节（nonce 变化 → AEAD 认证失败）
  const badCounter: Uint8Array = p1.slice();
  badCounter[8] = 9;
  assertWgError(() => recv.decryptPacket(badCounter), 'DECRYPT');
  assert.deepEqual(recv.decryptPacket(p1), seqBytes(8, 11));
});

test('错误类型/截断/错误 receiver index', () => {
  const send: WgSendSession = new WgSendSession(IDX_A, KEY_A2B);
  const recv: WgRecvSession = new WgRecvSession(IDX_A, KEY_A2B);
  const pkt: Uint8Array = send.encryptPacket(new Uint8Array(4));
  // 截断（< 32B）
  assertWgError(() => recv.decryptPacket(pkt.slice(0, 31)), 'BAD_LEN');
  assertWgError(() => recv.decryptPacket(new Uint8Array(0)), 'BAD_LEN');
  // 类型错（1/2/3/9）
  for (const t of [1, 2, 3, 9]) {
    const badType: Uint8Array = pkt.slice();
    badType[0] = t;
    assertWgError(() => recv.decryptPacket(badType), 'BAD_TYPE');
  }
  // receiver index 不匹配 → STATE
  const wrongRecv: WgRecvSession = new WgRecvSession(0xdeadbeef, KEY_A2B);
  assertWgError(() => wrongRecv.decryptPacket(pkt), 'STATE');
});

test('输出/输入独立拷贝（R8）：改明文/密文不影响会话行为', () => {
  const send: WgSendSession = new WgSendSession(IDX_A, KEY_A2B);
  const recv: WgRecvSession = new WgRecvSession(IDX_A, KEY_A2B);
  const pt: Uint8Array = seqBytes(20, 12);
  const pkt: Uint8Array = send.encryptPacket(pt);
  pt[0] = 0xff; // 改源明文不影响已加密报文
  const out: Uint8Array = recv.decryptPacket(pkt);
  assert.equal(out[0], seqBytes(20, 12)[0]);
  out[0] = 0xee; // 改解密输出不影响后续解密
  const pkt2: Uint8Array = send.encryptPacket(pt);
  assert.equal(recv.decryptPacket(pkt2)[1], seqBytes(20, 12)[1]);
});

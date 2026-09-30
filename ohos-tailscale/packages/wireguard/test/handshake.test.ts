/**
 * 握手测试（两个 peer 实例互发 initiation/response 的完整往返）：
 * - 148B/92B 完整字节级 hex 向量锁定（确定性 ArrayRng + FixedClock）；
 * - 字段结构：type/索引/临时公钥/密文段偏移/mac1 非零/mac2 全零；
 * - 独立键调度推导（测试内第二实现，对照真实报文密文段与 finish() 传输密钥
 *   —— 防对称性错误双方自洽漏检，如评审 finding 1 的 nonce 端序类偏差）；
 * - 零共享参考推导（node:crypto/OpenSSL + 手写 RFC 7693 键控 BLAKE2s，
 *   不 import @ohos-tailscale/crypto）逐字节重推两报文与传输密钥
 *   —— 148B/92B 向量三重锁定：写死锚 == 参考推导 == 模块输出；
 * - 往返正确性与索引/密钥交叉；时间戳 TAI64N 嵌入与单调；
 * - 失败路径：BAD_TYPE/BAD_LEN/MAC/DECRYPT/STATE/ZERO_DH；重钥（二次握手）。
 *
 * 键调度外部依据（2026-09-28 实抓，非凭记忆）：
 * ① 白皮书原文 wireguard.com/papers/wireguard.pdf（抓取后解出正文）：
 *    §5.4.2 msg1 = Kdf1(C,E_pub) → Kdf2(C,DH(E_priv_i,S_pub_r)) 封 static →
 *    Kdf2(C,DH(S_priv_i,S_pub_r)) 封 timestamp（静态-静态 DH）；§5.4.3
 *    msg2 = Kdf1(e) → Kdf1(DH(e_r,e_i)) → Kdf1(DH(e_r,S_pub_i)) →
 *    Kdf3(C,Q) 出 τ/k 封 empty；§5.4.5 传输键 = Kdf2(C_final, ε)。
 * ② wireguard-go device/noise-protocol.go（Create/ConsumeMessageInitiation、
 *    Create/ConsumeMessageResponse、BeginSymmetricSession，psk=全零）。
 * 实现与两处外部依据冲突时以外部为准（现已核对一致）。
 *
 * 完整报文 hex 向量来源（评审 finding：向量不得自产自锁）：
 * wireguard-go（device/ 无 noise-protocol_test.go）、boringtun、wireguard-linux
 * selftest 与白皮书均未发布确定性完整握手向量（临时密钥/时间戳不可注入），
 * 公开渠道不存在可直接写死的官方向量（2026-09-28 web 检索再确认）。故按
 * §5.2 锁定意图以下述独立参考推导落死：
 *   ① 测试内参考推导（零共享代码，见「零共享参考推导」节）：X25519 /
 *      ChaCha20-Poly1305 / 无键 BLAKE2s / HMAC 全部经 node:crypto（OpenSSL
 *      独立实现）；键控 BLAKE2s（node:crypto 无 API，createHash 的 key 选项
 *      被静默忽略）为手写 RFC 7693 实现，KAT 锚定官方 blake2-kat 首向量
 *      48a8997d… 与 CPython hashlib.blake2s 参考值（同 packages/crypto
 *      /test/hash.test.ts 锁定值）；
 *   ② 跨语言第三实现复现：CPython 3.12 hashlib/hmac + pyca-cryptography
 *      47.0.0（OpenSSL 底座）于 2026-09-28 对同组 fixture 逐字节复现下方
 *      两向量（要点：链键推进 = KDF1 = HMAC(HMAC(ck,d),0x01)，不可退化为
 *      单次 HMAC；X25519/BLAKE2s/AEAD 均为 OpenSSL 原语）。
 * 测试每次运行断言三方一致：模块输出 == 写死锚 == 参考推导，任一漂移即失败。
 */

import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  createCipheriv,
  createHash,
  createHmac,
  createPrivateKey,
  createPublicKey,
  diffieHellman,
  type KeyObject,
} from 'node:crypto';
import { ArrayRng, FixedClock, hexDecode, hexEncode, utf8Encode } from '@ohos-tailscale/common';
import {
  aeadSeal,
  blake2s256,
  kdf2Blake2s,
  kdf3Blake2s,
  x25519,
  x25519GenerateKeyPair,
  x25519PublicKeyFromPrivate,
} from '@ohos-tailscale/crypto';
import {
  WG_INITIATION_LEN_BYTES,
  WG_RESPONSE_LEN_BYTES,
  WgHandshakeInitiator,
  WgHandshakeResponder,
  parseWgMessageType,
  tai64nFromWallMs,
  wgComputeMac1,
  wgMac1Key,
  type WgHandshakeOutput,
  type WgInitiationInfo,
} from '../src/index.ts';
import { WgProtocolError } from '../src/errors.ts';

// ---------------------------------------------------------------------------
// 公共夹具
// ---------------------------------------------------------------------------

/** 确定性字节序列（测试夹具）。 */
const seqOf = (n: number, seed: number): Uint8Array => {
  const out: Uint8Array = new Uint8Array(n);
  for (let i = 0; i < n; i += 1) {
    out[i] = (seed + i * 31) % 256;
  }
  return out;
};

const concatOf = (a: Uint8Array, b: Uint8Array): Uint8Array => {
  const out: Uint8Array = new Uint8Array(a.length + b.length);
  out.set(a, 0);
  out.set(b, a.length);
  return out;
};

const flipBit = (src: Uint8Array, index: number, bit: number): Uint8Array => {
  const out: Uint8Array = src.slice();
  out[index] = out[index] ^ (1 << bit);
  return out;
};

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

/** mac1 重签：按 mac1 公式重算 msg 尾部 macs 段的 mac1（mac2 保持 0）。 */
const reSignMac1 = (msg: Uint8Array, mac1Key: Uint8Array): Uint8Array => {
  const out: Uint8Array = msg.slice();
  const mac: Uint8Array = wgComputeMac1(mac1Key, out.subarray(0, out.length - 32));
  out.set(mac, out.length - 32);
  return out;
};

/** 索引池字节 → u32le。 */
const indexOfPool = (pool: Uint8Array): number => {
  const idx: Uint8Array = pool.slice(32);
  return (idx[0] | (idx[1] << 8) | (idx[2] << 16) | (idx[3] << 24)) >>> 0;
};

// 确定性静态密钥对（ArrayRng 前 32 字节）
const staticA = x25519GenerateKeyPair(new ArrayRng(seqOf(32, 11)));
const staticB = x25519GenerateKeyPair(new ArrayRng(seqOf(32, 22)));

// 确定性握手段 rng 池：A/B 各 36B（32B 临时私钥 + 4B 会话索引）
const POOL_A: Uint8Array = seqOf(36, 101);
const POOL_B: Uint8Array = seqOf(36, 202);
const CLOCK_MS: number = 1717000000123;

// ---------------------------------------------------------------------------
// 零共享参考推导（向量锁定参考实现）
// X25519 / ChaCha20-Poly1305 / 无键 BLAKE2s / HMAC 全部走 node:crypto（OpenSSL）；
// 键控 BLAKE2s（node:crypto 无 API）为下方手写 RFC 7693 实现。
// 本节不 import @ohos-tailscale/crypto —— 与被测实现零共享代码，
// 防止"同源原语同一 bug 双方自洽"把错误向量锁死。
// ---------------------------------------------------------------------------

/** 无键 BLAKE2s-256（OpenSSL）。 */
const refBlake2s = (data: Uint8Array): Uint8Array =>
  new Uint8Array(createHash('blake2s256').update(data).digest());

/** HMAC-BLAKE2s-256（OpenSSL，块长 64）。 */
const refHmac = (key: Uint8Array, data: Uint8Array): Uint8Array =>
  new Uint8Array(createHmac('blake2s256', key).update(data).digest());

/** 白皮书 KDF¹：T1 = HMAC(HMAC(CK, IKM), 0x01)（链键推进；不可退化为单次 HMAC）。 */
const refKdf1 = (ck: Uint8Array, ikm: Uint8Array): Uint8Array =>
  refHmac(refHmac(ck, ikm), Uint8Array.from([1]));

/** 白皮书 KDF²：返回 [T1, T2]（R4：定长数组，无 tuple）。 */
const refKdf2 = (ck: Uint8Array, ikm: Uint8Array): Uint8Array[] => {
  const prk: Uint8Array = refHmac(ck, ikm);
  const t1: Uint8Array = refHmac(prk, Uint8Array.from([1]));
  const t2: Uint8Array = refHmac(prk, concatOf(t1, Uint8Array.from([2])));
  return [t1, t2];
};

/** 白皮书 KDF³：返回 [T1, T2, T3]。 */
const refKdf3 = (ck: Uint8Array, ikm: Uint8Array): Uint8Array[] => {
  const prk: Uint8Array = refHmac(ck, ikm);
  const t1: Uint8Array = refHmac(prk, Uint8Array.from([1]));
  const t2: Uint8Array = refHmac(prk, concatOf(t1, Uint8Array.from([2])));
  const t3: Uint8Array = refHmac(prk, concatOf(t2, Uint8Array.from([3])));
  return [t1, t2, t3];
};

/** X25519 私钥 → PKCS8 DER KeyObject（固定前缀 + 32B 标量；node 内部按 RFC 7748 clamp，幂等）。 */
const refX25519Private = (scalar: Uint8Array): KeyObject =>
  createPrivateKey({
    key: concatOf(hexDecode('302e020100300506032b656e04220420'), scalar),
    format: 'der',
    type: 'pkcs8',
  });

/** X25519 标量 → 32B 公钥（SPKI 尾 32 字节）。 */
const refX25519PubOf = (scalar: Uint8Array): Uint8Array => {
  const spki: Uint8Array = new Uint8Array(
    createPublicKey(refX25519Private(scalar)).export({ format: 'der', type: 'spki' }),
  );
  return spki.slice(spki.length - 32);
};

/** RFC 7748 X25519 DH（公钥经 SPKI DER 包装）。 */
const refX25519 = (scalar: Uint8Array, point: Uint8Array): Uint8Array =>
  new Uint8Array(
    diffieHellman({
      privateKey: refX25519Private(scalar),
      publicKey: createPublicKey({
        key: concatOf(hexDecode('302a300506032b656e032100'), point),
        format: 'der',
        type: 'spki',
      }),
    }),
  );

/** ChaCha20-Poly1305 封装（OpenSSL；nonce 恒 12B 全零 = 握手 counter 0；输出 ct||tag）。 */
const refAeadSeal = (key: Uint8Array, plaintext: Uint8Array, aad: Uint8Array): Uint8Array => {
  const cipher = createCipheriv('chacha20-poly1305', key, new Uint8Array(12), {
    authTagLength: 16,
  });
  cipher.setAAD(aad);
  const body: Uint8Array = new Uint8Array(cipher.update(plaintext));
  const tail: Uint8Array = new Uint8Array(cipher.final());
  const tag: Uint8Array = new Uint8Array(cipher.getAuthTag());
  const out: Uint8Array = new Uint8Array(body.length + tail.length + tag.length);
  out.set(body, 0);
  out.set(tail, body.length);
  out.set(tag, body.length + tail.length);
  return out;
};

// ---- 手写 RFC 7693 BLAKE2s-256（仅参考推导的 mac1 段使用；KAT 见下方测试）----

const BLAKE2S_IV: Uint32Array = Uint32Array.from([
  0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
  0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19,
]);

const BLAKE2S_SIGMA: number[][] = [
  [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15],
  [14, 10, 4, 8, 9, 15, 13, 6, 1, 12, 0, 2, 11, 7, 5, 3],
  [11, 8, 12, 0, 5, 2, 15, 13, 10, 14, 3, 6, 7, 1, 9, 4],
  [7, 9, 3, 1, 13, 12, 11, 14, 2, 6, 5, 10, 4, 0, 15, 8],
  [9, 0, 5, 7, 2, 4, 10, 15, 14, 1, 11, 12, 6, 8, 3, 13],
  [2, 12, 6, 10, 0, 11, 8, 3, 4, 13, 7, 5, 15, 14, 1, 9],
  [12, 5, 1, 15, 14, 13, 4, 10, 0, 7, 6, 3, 9, 2, 8, 11],
  [13, 11, 7, 14, 12, 1, 3, 9, 5, 0, 15, 4, 8, 6, 2, 10],
  [6, 15, 14, 9, 11, 3, 0, 8, 12, 2, 13, 7, 1, 4, 10, 5],
  [10, 2, 8, 4, 7, 6, 1, 5, 15, 11, 9, 14, 3, 12, 13, 0],
];

const blake2sRotr32 = (x: number, n: number): number => ((x >>> n) | (x << (32 - n))) >>> 0;

const blake2sG = (
  v: Uint32Array,
  a: number,
  b: number,
  c: number,
  d: number,
  x: number,
  y: number,
): void => {
  v[a] = (v[a] + v[b] + x) >>> 0;
  v[d] = blake2sRotr32(v[d] ^ v[a], 16);
  v[c] = (v[c] + v[d]) >>> 0;
  v[b] = blake2sRotr32(v[b] ^ v[c], 12);
  v[a] = (v[a] + v[b] + y) >>> 0;
  v[d] = blake2sRotr32(v[d] ^ v[a], 8);
  v[c] = (v[c] + v[d]) >>> 0;
  v[b] = blake2sRotr32(v[b] ^ v[c], 7);
};

/** RFC 7693 压缩函数：h 8 字状态就地更新；counter 为含键填充块的累计字节数。 */
const blake2sCompress = (h: Uint32Array, block: Uint8Array, counter: number, last: boolean): void => {
  const v: Uint32Array = new Uint32Array(16);
  for (let i = 0; i < 8; i += 1) {
    v[i] = h[i];
    v[i + 8] = BLAKE2S_IV[i];
  }
  v[12] = (v[12] ^ (counter >>> 0)) >>> 0;
  v[13] = (v[13] ^ (Math.floor(counter / 4294967296) >>> 0)) >>> 0;
  if (last) {
    v[14] = (~v[14]) >>> 0;
  }
  const m: Uint32Array = new Uint32Array(16);
  for (let i = 0; i < 16; i += 1) {
    m[i] =
      (block[i * 4] | (block[i * 4 + 1] << 8) | (block[i * 4 + 2] << 16) | (block[i * 4 + 3] << 24)) >>>
      0;
  }
  for (let r = 0; r < 10; r += 1) {
    const s: number[] = BLAKE2S_SIGMA[r];
    blake2sG(v, 0, 4, 8, 12, m[s[0]], m[s[1]]);
    blake2sG(v, 1, 5, 9, 13, m[s[2]], m[s[3]]);
    blake2sG(v, 2, 6, 10, 14, m[s[4]], m[s[5]]);
    blake2sG(v, 3, 7, 11, 15, m[s[6]], m[s[7]]);
    blake2sG(v, 0, 5, 10, 15, m[s[8]], m[s[9]]);
    blake2sG(v, 1, 6, 11, 12, m[s[10]], m[s[11]]);
    blake2sG(v, 2, 7, 8, 13, m[s[12]], m[s[13]]);
    blake2sG(v, 3, 4, 9, 14, m[s[14]], m[s[15]]);
  }
  for (let i = 0; i < 8; i += 1) {
    h[i] = (h[i] ^ v[i] ^ v[i + 8]) >>> 0;
  }
};

/** RFC 7693 BLAKE2s-256：key 可空；key 非空先按规范处理 64B 键填充块。 */
const blake2sRef = (key: Uint8Array | null, data: Uint8Array): Uint8Array => {
  const h: Uint32Array = Uint32Array.from(BLAKE2S_IV);
  const kk: number = key === null ? 0 : key.length;
  h[0] = (h[0] ^ 0x01010000 ^ (kk << 8) ^ 32) >>> 0;
  let counter = 0;
  if (key !== null) {
    const padded: Uint8Array = new Uint8Array(64);
    padded.set(key, 0);
    counter = 64;
    blake2sCompress(h, padded, counter, data.length === 0);
  }
  let idx = 0;
  while (idx < data.length) {
    const take: number = Math.min(64, data.length - idx);
    const block: Uint8Array = new Uint8Array(64);
    block.set(data.subarray(idx, idx + take), 0);
    counter += take;
    idx += take;
    blake2sCompress(h, block, counter, idx >= data.length);
  }
  if (kk === 0 && data.length === 0) {
    blake2sCompress(h, new Uint8Array(64), 0, true);
  }
  const out: Uint8Array = new Uint8Array(32);
  for (let i = 0; i < 8; i += 1) {
    out[i * 4] = h[i] & 0xff;
    out[i * 4 + 1] = (h[i] >>> 8) & 0xff;
    out[i * 4 + 2] = (h[i] >>> 16) & 0xff;
    out[i * 4 + 3] = (h[i] >>> 24) & 0xff;
  }
  return out;
};

// ---- 参考推导的报文组装（u32le/TAI64N 亦自备，不用被测代码与 ByteWriter）----

/** u32 小端（参考推导自备）。 */
const refU32le = (v: number): Uint8Array => {
  const out: Uint8Array = new Uint8Array(4);
  out[0] = v & 0xff;
  out[1] = (v >>> 8) & 0xff;
  out[2] = (v >>> 16) & 0xff;
  out[3] = (v >>> 24) & 0xff;
  return out;
};

/** TAI64N（参考推导自备：8B BE(2^62+秒) + 4B BE 纳秒，不经被测 tai64nFromWallMs）。 */
const refTai64n = (wallMs: number): Uint8Array => {
  const wholeSeconds: number = Math.floor(wallMs / 1000);
  const nanos: number = (wallMs - wholeSeconds * 1000) * 1000000;
  const out: Uint8Array = new Uint8Array(12);
  const secs: bigint = 4611686018427387904n + BigInt(wholeSeconds);
  for (let i = 0; i < 8; i += 1) {
    out[i] = Number((secs >> BigInt((7 - i) * 8)) & 0xffn);
  }
  out[8] = (nanos >>> 24) & 0xff;
  out[9] = (nanos >>> 16) & 0xff;
  out[10] = (nanos >>> 8) & 0xff;
  out[11] = nanos & 0xff;
  return out;
};

/** 参考推导结果（R4：定长 Uint8Array[] 不适用，纯字段 interface）。 */
interface RefHandshakePackets {
  initiation: Uint8Array;
  response: Uint8Array;
  initiatorSendKey: Uint8Array;
  initiatorRecvKey: Uint8Array;
}

/** 按白皮书键调度从同组 fixture 逐字节重推 initiation/response/传输密钥。 */
const deriveReferenceHandshake = (): RefHandshakePackets => {
  const siPriv: Uint8Array = staticA.privateKey; // 已 clamp 存储；node 内部再 clamp（幂等）
  const siPub: Uint8Array = refX25519PubOf(siPriv);
  const srPub: Uint8Array = refX25519PubOf(staticB.privateKey);
  const eiPriv: Uint8Array = POOL_A.slice(0, 32);
  const erPriv: Uint8Array = POOL_B.slice(0, 32);
  const idxI: number = indexOfPool(POOL_A);
  const idxR: number = indexOfPool(POOL_B);
  const eiPub: Uint8Array = refX25519PubOf(eiPriv);
  const erPub: Uint8Array = refX25519PubOf(erPriv);

  // msg1（白皮书 §5.4.2：-> e, es, s, ss, ts）
  let ck: Uint8Array = refBlake2s(utf8Encode('Noise_IKpsk2_25519_ChaChaPoly_BLAKE2s'));
  let h: Uint8Array = refBlake2s(
    concatOf(refBlake2s(concatOf(ck, utf8Encode('WireGuard v1 zx2c4 Jason@zx2c4.com'))), srPub),
  );
  ck = refKdf1(ck, eiPub);
  h = refBlake2s(concatOf(h, eiPub));
  const kEs: Uint8Array[] = refKdf2(ck, refX25519(eiPriv, srPub));
  ck = kEs[0];
  const encStatic: Uint8Array = refAeadSeal(kEs[1], siPub, h);
  h = refBlake2s(concatOf(h, encStatic));
  const kSs: Uint8Array[] = refKdf2(ck, refX25519(siPriv, srPub));
  ck = kSs[0];
  const encTimestamp: Uint8Array = refAeadSeal(kSs[1], refTai64n(CLOCK_MS), h);
  h = refBlake2s(concatOf(h, encTimestamp));
  const bodyA: Uint8Array = concatOf(
    concatOf(refU32le(1), refU32le(idxI)),
    concatOf(concatOf(eiPub, encStatic), encTimestamp),
  );
  const mac1A: Uint8Array = blake2sRef(
    refBlake2s(concatOf(utf8Encode('mac1----'), srPub)),
    bodyA,
  ).slice(0, 16);
  const initiation: Uint8Array = concatOf(concatOf(bodyA, mac1A), new Uint8Array(16));

  // msg2（白皮书 §5.4.3：<- e, ee, se, psk(0), [empty]）
  ck = refKdf1(ck, erPub);
  h = refBlake2s(concatOf(h, erPub));
  ck = refKdf1(ck, refX25519(erPriv, eiPub));
  ck = refKdf1(ck, refX25519(erPriv, siPub));
  const kPsk: Uint8Array[] = refKdf3(ck, new Uint8Array(32));
  ck = kPsk[0];
  h = refBlake2s(concatOf(h, kPsk[1]));
  const encEmpty: Uint8Array = refAeadSeal(kPsk[2], new Uint8Array(0), h);
  h = refBlake2s(concatOf(h, encEmpty));
  const bodyB: Uint8Array = concatOf(
    concatOf(refU32le(2), refU32le(idxR)),
    concatOf(concatOf(refU32le(idxI), erPub), encEmpty),
  );
  const mac1B: Uint8Array = blake2sRef(
    refBlake2s(concatOf(utf8Encode('mac1----'), siPub)),
    bodyB,
  ).slice(0, 16);
  const response: Uint8Array = concatOf(concatOf(bodyB, mac1B), new Uint8Array(16));

  // 传输键（白皮书 §5.4.5：KDF2(C_final, ε)，发起端 [0]=send/[1]=recv）
  const tk: Uint8Array[] = refKdf2(ck, new Uint8Array(0));
  const packets: RefHandshakePackets = {
    initiation: initiation,
    response: response,
    initiatorSendKey: tk[0],
    initiatorRecvKey: tk[1],
  };
  return packets;
};

test('参考推导 KAT：手写 RFC 7693 键控/无键 BLAKE2s 对照官方 blake2-kat 与 CPython 参考值', () => {
  // 无键知名摘要（RFC 7693；同 packages/crypto/test/hash.test.ts 锁定值）
  assert.equal(
    hexEncode(blake2sRef(null, new Uint8Array(0))),
    '69217a3079908094e11121d042354a7c1f55b6482ca1a51e1b250dfd1ed0eef9',
  );
  assert.equal(
    hexEncode(blake2sRef(null, utf8Encode('abc'))),
    '508c5e8c327c14e2e1a72ba34eeb452f37458b209ed63a294d999b4c86675982',
  );
  // 官方 blake2-kat 首向量：key = 00 01 … 1f，输入为空
  const identity = (n: number): Uint8Array => {
    const out: Uint8Array = new Uint8Array(n);
    for (let i = 0; i < n; i += 1) {
      out[i] = i;
    }
    return out;
  };
  assert.equal(
    hexEncode(blake2sRef(identity(32), new Uint8Array(0))),
    '48a8997da407876b3d79c0d92325ad3b89cbb754d86ab71aee047ad345fd2c49',
  );
  // CPython hashlib.blake2s(key=…) 参考值（同 packages/crypto/test/hash.test.ts:159-167）
  assert.equal(
    hexEncode(blake2sRef(new Uint8Array(32), hexDecode('000102'))),
    '4e568448e16d647faf7f6cb1e362411c2478623fb1039fcac37580f23e047fd8',
  );
  assert.equal(
    hexEncode(blake2sRef(identity(32), identity(64))),
    '8975b0577fd35566d750b362b0897a26c399136df07bababbde6203ff2954ed4',
  );
});

// 字节级锁定向量：写死锚；测试运行时与「零共享参考推导」及模块输出三方比对
const INITIATION_HEX: string =
  '01000000456483a24071df9eb6ead1a6b1758ae76113f7655eef01f70242fa140a97f0ea95' +
  'b0d0164c7c61ea666b0f7c0b94f7caf83c50b51c7e4a2e667bd8c9a33c9770c3ad9d37a329' +
  'c2d2ba399d169d3bcc4a896dabecaee8963710190d9261b01f62908818546cf7841860ae8e' +
  '2fe27a64b8a441a27f97999ef02d1fa49838234d8200000000000000000000000000000000';
const RESPONSE_HEX: string =
  '02000000aac9e807456483a2b1c0e0991a394f2b5d0059487110c95579cc5446f0b35a755c' +
  '2f7256ea2215453eeaf3041010106d5344baab69c4a85643fac04396103e659c8aa579ce2b' +
  '70ea00000000000000000000000000000000';

interface HandshakeResult {
  initiation: Uint8Array;
  response: Uint8Array;
  info: WgInitiationInfo;
  outA: WgHandshakeOutput;
  outB: WgHandshakeOutput;
}

/** 一整场握手：新 initiator/responder 实例互发并 finish（池可换供重钥测试）。 */
const runHandshake = (poolA: Uint8Array = POOL_A, poolB: Uint8Array = POOL_B): HandshakeResult => {
  const clock: FixedClock = new FixedClock(CLOCK_MS);
  const initiator: WgHandshakeInitiator = new WgHandshakeInitiator(
    staticA.privateKey,
    staticB.publicKey,
    new ArrayRng(poolA),
    clock,
  );
  const responder: WgHandshakeResponder = new WgHandshakeResponder(
    staticB.privateKey,
    new ArrayRng(poolB),
    clock,
  );
  const initiation: Uint8Array = initiator.createInitiation();
  const info: WgInitiationInfo = responder.consumeInitiation(initiation);
  const response: Uint8Array = responder.createResponse();
  initiator.consumeResponse(response);
  const outA: WgHandshakeOutput = initiator.finish();
  const outB: WgHandshakeOutput = responder.finish();
  const r: HandshakeResult = {
    initiation: initiation,
    response: response,
    info: info,
    outA: outA,
    outB: outB,
  };
  return r;
};

// ---------------------------------------------------------------------------
// 字节向量与结构
// ---------------------------------------------------------------------------

test('静态密钥派生确定性（x25519GenerateKeyPair 对注入池）', () => {
  assert.equal(
    hexEncode(staticA.publicKey),
    '7506d473bcbd3b0e9520268f1efea1edcf373eea361e299b1c629831ba178147',
  );
  assert.equal(
    hexEncode(staticB.publicKey),
    'fa6fb15897363cb12ffd3987a6a8501a47b9053fc320474b4dc6241ebda2925f',
  );
});

test('createInitiation 输出 148B 字节级向量锁定（锚 == 零共享参考推导 == 模块输出）', () => {
  const clock: FixedClock = new FixedClock(CLOCK_MS);
  const initiator: WgHandshakeInitiator = new WgHandshakeInitiator(
    staticA.privateKey,
    staticB.publicKey,
    new ArrayRng(POOL_A),
    clock,
  );
  const initiation: Uint8Array = initiator.createInitiation();
  const ref: RefHandshakePackets = deriveReferenceHandshake();
  assert.equal(initiation.length, WG_INITIATION_LEN_BYTES);
  assert.equal(hexEncode(initiation), INITIATION_HEX, 'initiation vector mismatch');
  assert.equal(
    hexEncode(ref.initiation),
    INITIATION_HEX,
    'initiation vs zero-shared reference derivation (node:crypto + RFC 7693 keyed blake2s)',
  );
});

test('initiation 字段结构：type/sender/ephemeral/mac1 非零/mac2 全零', () => {
  const clock: FixedClock = new FixedClock(CLOCK_MS);
  const initiator: WgHandshakeInitiator = new WgHandshakeInitiator(
    staticA.privateKey,
    staticB.publicKey,
    new ArrayRng(POOL_A),
    clock,
  );
  const msg: Uint8Array = initiator.createInitiation();
  // type u32le = 1（= 白皮书 type u8 + reserved[3] 的同形字节）
  assert.equal(msg[0], 1);
  assert.deepEqual(msg.slice(1, 4), new Uint8Array(3), 'reserved must be zero');
  assert.equal(parseWgMessageType(1), 1);
  // sender = 池后 4 字节的 u32le
  const dv: DataView = new DataView(msg.buffer, msg.byteOffset);
  assert.equal(dv.getUint32(4, true), indexOfPool(POOL_A), 'sender index mismatch');
  // 临时公钥 = 池前 32 字节 clamp 后的公钥
  const expectEph: Uint8Array = x25519PublicKeyFromPrivate(POOL_A.slice(0, 32));
  assert.deepEqual(msg.slice(8, 40), expectEph, 'ephemeral public mismatch');
  // mac1 非零、mac2 全零
  assert.notDeepEqual(msg.slice(116, 132), new Uint8Array(16), 'mac1 must be computed');
  assert.deepEqual(msg.slice(132), new Uint8Array(16), 'mac2 must be zero without cookie');
});

test('createResponse 输出 92B 字节级向量锁定 + 字段结构（锚 == 零共享参考推导 == 模块输出）', () => {
  const r: HandshakeResult = runHandshake();
  const ref: RefHandshakePackets = deriveReferenceHandshake();
  assert.equal(r.response.length, WG_RESPONSE_LEN_BYTES);
  assert.equal(hexEncode(r.response), RESPONSE_HEX, 'response vector mismatch');
  assert.equal(
    hexEncode(ref.response),
    RESPONSE_HEX,
    'response vs zero-shared reference derivation (node:crypto + RFC 7693 keyed blake2s)',
  );
  // 传输密钥同由参考推导交叉：KDF2(ck_final, ε) 发起端 [0]=send/[1]=recv
  assert.deepEqual(r.outA.sendKey, ref.initiatorSendKey, 'send key vs reference derivation');
  assert.deepEqual(r.outA.recvKey, ref.initiatorRecvKey, 'recv key vs reference derivation');
  assert.equal(r.response[0], 2);
  const dv: DataView = new DataView(r.response.buffer, r.response.byteOffset);
  assert.equal(dv.getUint32(4, true), indexOfPool(POOL_B), 'response sender mismatch');
  assert.equal(
    dv.getUint32(8, true),
    indexOfPool(POOL_A),
    'response receiver must echo initiator index',
  );
  assert.deepEqual(r.response.slice(76), new Uint8Array(16), 'response mac2 must be zero');
});

// ---------------------------------------------------------------------------
// 独立键调度交叉验证（wireguard-go noise-protocol.go 的测试内转录）
// ---------------------------------------------------------------------------

test('键调度独立推导：enc_static/enc_timestamp/enc_empty 与传输密钥逐字节一致', () => {
  // 真实握手产生报文与输出
  const clock: FixedClock = new FixedClock(CLOCK_MS);
  const initiator: WgHandshakeInitiator = new WgHandshakeInitiator(
    staticA.privateKey,
    staticB.publicKey,
    new ArrayRng(POOL_A),
    clock,
  );
  const responder: WgHandshakeResponder = new WgHandshakeResponder(
    staticB.privateKey,
    new ArrayRng(POOL_B),
    clock,
  );
  const initiation: Uint8Array = initiator.createInitiation();
  responder.consumeInitiation(initiation);
  const response: Uint8Array = responder.createResponse();
  initiator.consumeResponse(response);
  const outA: WgHandshakeOutput = initiator.finish();
  const outB: WgHandshakeOutput = responder.finish();

  // ---- 独立实现（对照 CreateMessageInitiation）----
  const zeroNonce: Uint8Array = new Uint8Array(12);
  const mixKey = (ck: Uint8Array, data: Uint8Array): Uint8Array => kdf2Blake2s(ck, data)[0];
  let ck: Uint8Array = blake2s256(utf8Encode('Noise_IKpsk2_25519_ChaChaPoly_BLAKE2s'));
  let h: Uint8Array = blake2s256(concatOf(ck, utf8Encode('WireGuard v1 zx2c4 Jason@zx2c4.com')));
  h = blake2s256(concatOf(h, staticB.publicKey));

  const ePrivA: Uint8Array = POOL_A.slice(0, 32);
  const ePubA: Uint8Array = x25519PublicKeyFromPrivate(ePrivA);
  ck = mixKey(ck, ePubA);
  h = blake2s256(concatOf(h, ePubA));
  // es
  const es: Uint8Array = x25519(ePrivA, staticB.publicKey);
  const kEs: Uint8Array[] = kdf2Blake2s(ck, es);
  ck = kEs[0];
  const encStatic: Uint8Array = aeadSeal(kEs[1], zeroNonce, staticA.publicKey, h);
  assert.deepEqual(initiation.slice(40, 88), encStatic, 'enc_static mismatch vs independent schedule');
  h = blake2s256(concatOf(h, encStatic));
  // ss（双方静态 DH —— psk2 槽位）
  const ss: Uint8Array = x25519(staticA.privateKey, staticB.publicKey);
  const kSs: Uint8Array[] = kdf2Blake2s(ck, ss);
  ck = kSs[0];
  const encTs: Uint8Array = aeadSeal(kSs[1], zeroNonce, tai64nFromWallMs(CLOCK_MS), h);
  assert.deepEqual(initiation.slice(88, 116), encTs, 'enc_timestamp mismatch vs independent schedule');
  h = blake2s256(concatOf(h, encTs));

  // ---- msg2：e, ee, se, psk(0), [empty]（对照 CreateMessageResponse）----
  // 布局：[type4][sender4][receiver4][ephemeral 12..44][enc_empty 44..60][macs]
  const ePrivB: Uint8Array = POOL_B.slice(0, 32);
  const ePubB: Uint8Array = x25519PublicKeyFromPrivate(ePrivB);
  assert.deepEqual(initiation.slice(8, 40), ePubA, 'sanity: msg1 ephemeral');
  assert.deepEqual(response.slice(12, 44), ePubB, 'response ephemeral mismatch');
  ck = mixKey(ck, ePubB);
  h = blake2s256(concatOf(h, ePubB));
  const ee: Uint8Array = x25519(ePrivB, ePubA);
  ck = mixKey(ck, ee);
  const se: Uint8Array = x25519(ePrivB, staticA.publicKey);
  ck = mixKey(ck, se);
  const k3: Uint8Array[] = kdf3Blake2s(ck, new Uint8Array(32));
  ck = k3[0];
  h = blake2s256(concatOf(h, k3[1]));
  const encEmpty: Uint8Array = aeadSeal(k3[2], zeroNonce, new Uint8Array(0), h);
  assert.deepEqual(response.slice(44, 60), encEmpty, 'enc_empty mismatch vs independent schedule');

  // ---- 传输密钥：KDF2(ck_final, 空 ikm)，发起端 [0]=send/[1]=recv ----
  const tk: Uint8Array[] = kdf2Blake2s(ck, new Uint8Array(0));
  assert.deepEqual(outA.sendKey, tk[0], 'initiator send key must be KDF2(ck_final, empty)[0]');
  assert.deepEqual(outA.recvKey, tk[1], 'initiator recv key must be KDF2(ck_final, empty)[1]');
  assert.deepEqual(outB.recvKey, tk[0]);
  assert.deepEqual(outB.sendKey, tk[1]);
});

// ---------------------------------------------------------------------------
// 往返与状态
// ---------------------------------------------------------------------------

test('两 peer 完整握手往返：索引与传输密钥交叉一致 + 返回拷贝语义', () => {
  const r: HandshakeResult = runHandshake();
  const senderA: number = indexOfPool(POOL_A);
  const senderB: number = indexOfPool(POOL_B);
  // consumeInitiation 返回
  assert.equal(r.info.senderIndex, senderA);
  assert.deepEqual(r.info.peerStaticPublic, staticA.publicKey);
  assert.deepEqual(r.info.timestamp, tai64nFromWallMs(CLOCK_MS));
  // finish 输出索引
  assert.equal(r.outA.localIndex, senderA);
  assert.equal(r.outA.peerIndex, senderB);
  assert.equal(r.outB.localIndex, senderB);
  assert.equal(r.outB.peerIndex, senderA);
  // 传输密钥交叉：A.send == B.recv，A.recv == B.send，且为 32B
  assert.deepEqual(r.outA.sendKey, r.outB.recvKey);
  assert.deepEqual(r.outA.recvKey, r.outB.sendKey);
  assert.equal(r.outA.sendKey.length, 32);
  assert.equal(r.outA.recvKey.length, 32);
  // 返回拷贝语义（R8）：改一方返回值不影响另一方的同一密钥视图
  const orig: number = r.outA.sendKey[0];
  r.outA.sendKey[0] = (orig ^ 0xff) & 0xff;
  assert.equal(r.outB.recvKey[0], orig, 'outA.sendKey must be an independent copy');
});

test('时间戳随注入时钟前进（TAI64N 嵌入且严格增大）', () => {
  const clock: FixedClock = new FixedClock(1000000);
  const initiator1: WgHandshakeInitiator = new WgHandshakeInitiator(
    staticA.privateKey,
    staticB.publicKey,
    new ArrayRng(POOL_A),
    clock,
  );
  const responder1: WgHandshakeResponder = new WgHandshakeResponder(
    staticB.privateKey,
    new ArrayRng(POOL_B),
    clock,
  );
  const t1: WgInitiationInfo = responder1.consumeInitiation(initiator1.createInitiation());
  assert.deepEqual(t1.timestamp, tai64nFromWallMs(1000000));
  clock.advanceMs(1);
  const initiator2: WgHandshakeInitiator = new WgHandshakeInitiator(
    staticA.privateKey,
    staticB.publicKey,
    new ArrayRng(POOL_A),
    clock,
  );
  const responder2: WgHandshakeResponder = new WgHandshakeResponder(
    staticB.privateKey,
    new ArrayRng(POOL_B),
    clock,
  );
  const t2: WgInitiationInfo = responder2.consumeInitiation(initiator2.createInitiation());
  // 逐字节比较：后者必须更大（大端 TAI64N 数值序）
  let gt: boolean = false;
  for (let i = 0; i < 12; i += 1) {
    if (t2.timestamp[i] !== t1.timestamp[i]) {
      gt = t2.timestamp[i] > t1.timestamp[i];
      break;
    }
  }
  assert.equal(gt, true, 'timestamp must strictly increase with clock');
});

test('重钥：二次握手（新 rng 池）产出全新会话（新索引/新密钥，交叉仍一致）', () => {
  const first: HandshakeResult = runHandshake();
  const second: HandshakeResult = runHandshake(seqOf(36, 303), seqOf(36, 404));
  assert.notEqual(first.outA.localIndex, second.outA.localIndex);
  assert.notEqual(first.outB.localIndex, second.outB.localIndex);
  assert.notDeepEqual(first.outA.sendKey, second.outA.sendKey);
  assert.deepEqual(second.outA.sendKey, second.outB.recvKey);
  assert.deepEqual(second.outA.recvKey, second.outB.sendKey);
});

// ---------------------------------------------------------------------------
// 失败路径
// ---------------------------------------------------------------------------

test('响应端持错误静态密钥对 → MAC（mac1 键由响应端静态公钥派生，先于解密拦截）', () => {
  const clock: FixedClock = new FixedClock(CLOCK_MS);
  const initiator: WgHandshakeInitiator = new WgHandshakeInitiator(
    staticA.privateKey,
    staticB.publicKey,
    new ArrayRng(POOL_A),
    clock,
  );
  const initiation: Uint8Array = initiator.createInitiation();
  const impostor = x25519GenerateKeyPair(new ArrayRng(seqOf(32, 33)));
  const responder: WgHandshakeResponder = new WgHandshakeResponder(
    impostor.privateKey,
    new ArrayRng(POOL_B),
    clock,
  );
  assertWgError(() => responder.consumeInitiation(initiation), 'MAC');
});

test('发起端用错误对端公钥构造 → 响应端 MAC（同理 mac1 先拦）', () => {
  const clock: FixedClock = new FixedClock(CLOCK_MS);
  const wrongPeer = x25519GenerateKeyPair(new ArrayRng(seqOf(32, 44)));
  const initiator: WgHandshakeInitiator = new WgHandshakeInitiator(
    staticA.privateKey,
    wrongPeer.publicKey,
    new ArrayRng(POOL_A),
    clock,
  );
  const initiation: Uint8Array = initiator.createInitiation();
  const responder: WgHandshakeResponder = new WgHandshakeResponder(
    staticB.privateKey,
    new ArrayRng(POOL_B),
    clock,
  );
  assertWgError(() => responder.consumeInitiation(initiation), 'MAC');
});

test('篡改密文段：仅篡改 → MAC（mac1 覆盖全域）；重签 mac1 后 → DECRYPT', () => {
  const clock: FixedClock = new FixedClock(CLOCK_MS);
  const initiator: WgHandshakeInitiator = new WgHandshakeInitiator(
    staticA.privateKey,
    staticB.publicKey,
    new ArrayRng(POOL_A),
    clock,
  );
  const initiation: Uint8Array = initiator.createInitiation();
  const responder: WgHandshakeResponder = new WgHandshakeResponder(
    staticB.privateKey,
    new ArrayRng(POOL_B),
    clock,
  );
  // mac1 覆盖除 macs 段外全部字节 → 单纯篡改必先被 mac1 拦截
  assertWgError(() => responder.consumeInitiation(flipBit(initiation, 90, 3)), 'MAC');
  assertWgError(() => responder.consumeInitiation(flipBit(initiation, 120, 0)), 'MAC');
  // 攻击者可重签 mac1（mac1 键无秘密性，仅为 DoS 防护）→ 进入 AEAD 后认证失败 → DECRYPT
  const tamperedTs: Uint8Array = reSignMac1(flipBit(initiation, 100, 2), wgMac1Key(staticB.publicKey));
  assertWgError(() => responder.consumeInitiation(tamperedTs), 'DECRYPT');
  const tamperedStatic: Uint8Array = reSignMac1(flipBit(initiation, 50, 6), wgMac1Key(staticB.publicKey));
  assertWgError(() => responder.consumeInitiation(tamperedStatic), 'DECRYPT');
});

test('截断/超长 → BAD_LEN；类型错/64B Cookie Reply → BAD_TYPE（一期不解析）', () => {
  const clock: FixedClock = new FixedClock(CLOCK_MS);
  const initiator: WgHandshakeInitiator = new WgHandshakeInitiator(
    staticA.privateKey,
    staticB.publicKey,
    new ArrayRng(POOL_A),
    clock,
  );
  const initiation: Uint8Array = initiator.createInitiation();
  const responder: WgHandshakeResponder = new WgHandshakeResponder(
    staticB.privateKey,
    new ArrayRng(POOL_B),
    clock,
  );
  assertWgError(() => responder.consumeInitiation(initiation.slice(0, 147)), 'BAD_LEN');
  assertWgError(() => responder.consumeInitiation(concatOf(initiation, new Uint8Array(1))), 'BAD_LEN');
  // type=3（Cookie Reply）但保持 148B → BAD_TYPE
  const fakeCookie: Uint8Array = initiation.slice();
  fakeCookie[0] = 3;
  assertWgError(() => responder.consumeInitiation(fakeCookie), 'BAD_TYPE');
  // 64B Cookie Reply 形状报文同样 BAD_TYPE
  const reply: Uint8Array = new Uint8Array(64);
  reply[0] = 3;
  assertWgError(() => responder.consumeInitiation(reply), 'BAD_TYPE');
  assert.equal(parseWgMessageType(3), 3);
  assert.equal(parseWgMessageType(9), null);
});

test('response receiver index 被改：未重签 → MAC；重签后 → STATE', () => {
  const r: HandshakeResult = runHandshake();
  const forged: Uint8Array = r.response.slice();
  forged[8] = (forged[8] + 1) & 0xff;
  const mac1KeyA: Uint8Array = wgMac1Key(staticA.publicKey);
  const resigned: Uint8Array = reSignMac1(forged, mac1KeyA);
  const clock: FixedClock = new FixedClock(CLOCK_MS);
  const initiator: WgHandshakeInitiator = new WgHandshakeInitiator(
    staticA.privateKey,
    staticB.publicKey,
    new ArrayRng(POOL_A),
    clock,
  );
  initiator.createInitiation();
  assertWgError(() => initiator.consumeResponse(forged), 'MAC');
  assertWgError(() => initiator.consumeResponse(resigned), 'STATE');
});

test('mac2 非零且无已发 cookie → MAC；全零临时公钥 → ZERO_DH', () => {
  const r: HandshakeResult = runHandshake();
  const mac2Bad: Uint8Array = r.response.slice();
  mac2Bad[78] = 1; // mac2 段自 76 起
  const clock: FixedClock = new FixedClock(CLOCK_MS);
  const initiator: WgHandshakeInitiator = new WgHandshakeInitiator(
    staticA.privateKey,
    staticB.publicKey,
    new ArrayRng(POOL_A),
    clock,
  );
  initiator.createInitiation();
  assertWgError(() => initiator.consumeResponse(mac2Bad), 'MAC');

  // 手工构造全零临时公钥的 initiation（148B，mac1 正确重签，mac2 全零）
  const body: Uint8Array = new Uint8Array(WG_INITIATION_LEN_BYTES);
  const dv: DataView = new DataView(body.buffer);
  dv.setUint32(0, 1, true);
  dv.setUint32(4, 12345, true);
  body.set(new Uint8Array(32), 8); // 全零临时公钥 → DH(s_r, 0) = 0
  body.set(seqOf(48, 7), 40); // enc_static 乱数填充
  body.set(seqOf(28, 8), 88); // enc_timestamp 乱数填充
  const signed: Uint8Array = reSignMac1(body, wgMac1Key(staticB.publicKey));
  const responder: WgHandshakeResponder = new WgHandshakeResponder(
    staticB.privateKey,
    new ArrayRng(POOL_B),
    clock,
  );
  assertWgError(() => responder.consumeInitiation(signed), 'ZERO_DH');
});

test('状态机顺序错误 → STATE（各类早调用/重复调用）', () => {
  const clock: FixedClock = new FixedClock(CLOCK_MS);
  const initiator: WgHandshakeInitiator = new WgHandshakeInitiator(
    staticA.privateKey,
    staticB.publicKey,
    new ArrayRng(POOL_A),
    clock,
  );
  const responder: WgHandshakeResponder = new WgHandshakeResponder(
    staticB.privateKey,
    new ArrayRng(POOL_B),
    clock,
  );
  // 未 createInitiation 先 consumeResponse / finish
  assertWgError(() => initiator.consumeResponse(new Uint8Array(92)), 'STATE');
  assertWgError(() => initiator.finish(), 'STATE');
  // 未 consumeInitiation 先 createResponse / finish
  assertWgError(() => responder.createResponse(), 'STATE');
  assertWgError(() => responder.finish(), 'STATE');
  const initiation: Uint8Array = initiator.createInitiation();
  // 重复 createInitiation
  assertWgError(() => initiator.createInitiation(), 'STATE');
  const info: WgInitiationInfo = responder.consumeInitiation(initiation);
  assert.equal(info.senderIndex, indexOfPool(POOL_A));
  // 重复 consumeInitiation
  assertWgError(() => responder.consumeInitiation(initiation), 'STATE');
  const response: Uint8Array = responder.createResponse();
  assertWgError(() => responder.createResponse(), 'STATE');
  initiator.consumeResponse(response);
  assertWgError(() => initiator.consumeResponse(response), 'STATE');
  const outA: WgHandshakeOutput = initiator.finish();
  assertWgError(() => initiator.finish(), 'STATE');
  const outB: WgHandshakeOutput = responder.finish();
  assertWgError(() => responder.finish(), 'STATE');
  assert.equal(outA.localIndex, indexOfPool(POOL_A));
  assert.equal(outB.localIndex, indexOfPool(POOL_B));
});

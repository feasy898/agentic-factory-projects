/**
 * Noise SymmetricState —— ts2021/controlbase 口味（protocol_name = 'Noise_IK_25519_ChaChaPoly_BLAKE2s'，
 * 与真实 tailscale controlbase 的 protocolName 常量一致）。
 * 包内模块，不进公开 barrel；仅 handshake.ts 使用。
 *
 * ⚠ 口味裁定（本包上游核对结论，2026-09-28，证据均为本次实读）：
 * tailscale controlbase（control/controlbase/handshake.go 的 MixDH / symmetricState）对 DH 令牌
 * 采用 rev31 时代形式：`ck, k = HKDF-HMAC-BLAKE2s(ck, dh, 2)`，**不把任何 HKDF 输出混入 h**
 * （即无 temp_h 混入、密钥取 out2）；而现行 Noise 规范 rev34 §5.3 的 MixKeyAndHash 是
 * 三输出（MixHash(out2)、密钥取 out3）。本包按 controlbase 口味实现（本包定位是 ts2021
 * 控制面会话层，须与真实 control 服务器互通），并已用公开的 cacophony 已知答案向量
 * （Noise_IK_25519_ChaChaPoly_BLAKE2s，见 test/external-vector.test.ts）整链逐字节验证通过。
 *
 * 初始化（对齐 controlbase symmetricState.Initialize）：
 * - protocol_name ≤ 32B → h = protocol_name 零填充到 32B；> 32B → h = HASH(protocol_name)。
 *   本协议名 'Noise_IK_25519_ChaChaPoly_BLAKE2s' 为 33 字节，走哈希分支（与 controlbase 的
 *   `s.h = blake2s.Sum256(protocolName)` 一致；长度判定仍写成通用形式）。
 * - ck = h；随后 MixHash(prologue)（只影响 h，不影响 ck）。
 *   预消息（IK 的 `<- s`：响应方静态公钥）由 handshake.ts 在构造后 MixHash——对齐
 *   controlbase ClientDeferred 的 `MixHash(controlKey)` 与 Noise 规范 §5.3 Initialize。
 *
 * 原语：
 * - MixHash(data)：h = HASH(h || data)；
 * - MixKey(ikm)：(ck, k) = HKDF-HMAC-BLAKE2s(ck, ikm, 2)，返回 k 供紧随的 EncryptAndHash
 *   使用（不修改 h —— controlbase 口味，理由见上）；
 * - EncryptAndHash/DecryptAndHash：ChaCha20-Poly1305，nonce = 12B 全零（每个 DH 令牌
 *   派生新密钥，一次性使用，controlbase singleUseCHP 同型），AAD = 当前 h，成功后
 *   h = MixHash(密文/密文域)。
 *
 * Split（对齐 controlbase symmetricState.Split）：(k1, k2) = HKDF-HMAC-BLAKE2s(ck, 空, 2)；
 * k1 为 initiator→responder 方向，k2 为 responder→initiator 方向。派生后擦除 ck。
 */

import {
  aeadOpen,
  aeadSeal,
  blake2s256,
  kdf2Blake2s,
  wipe,
} from '@ohos-tailscale/crypto';
import { AEAD_NONCE_LEN_BYTES } from '@ohos-tailscale/common';
import { NoiseError } from './errors.ts';

const HASH_LEN: number = 32;

export class SymmetricState {
  private ck: Uint8Array;
  private h: Uint8Array;

  public constructor(protocolName: Uint8Array, prologue: Uint8Array) {
    let initial: Uint8Array;
    if (protocolName.length <= HASH_LEN) {
      initial = new Uint8Array(HASH_LEN);
      initial.set(protocolName, 0);
    } else {
      initial = blake2s256(protocolName);
    }
    this.h = initial;
    this.ck = initial.slice();
    this.mixHash(prologue);
  }

  /** h = HASH(h || data)。 */
  public mixHash(data: Uint8Array): void {
    const merged: Uint8Array = new Uint8Array(this.h.length + data.length);
    merged.set(this.h, 0);
    merged.set(data, this.h.length);
    this.h = blake2s256(merged);
  }

  /** 双输出 KDF（controlbase MixDH 形）：ck = out1，返回 out2（新数组，调用方持有）；不改 h。 */
  public mixKey(ikm: Uint8Array): Uint8Array {
    const out: Uint8Array[] = kdf2Blake2s(this.ck, ikm);
    this.ck = out[0];
    return out[1];
  }

  /** 加密一块握手数据：ChaChaPoly(key, n=0, ad=h, plaintext)，h = MixHash(密文)；返回密文（新数组）。 */
  public encryptAndHash(key: Uint8Array, plaintext: Uint8Array): Uint8Array {
    const ciphertext: Uint8Array = aeadSeal(key, new Uint8Array(AEAD_NONCE_LEN_BYTES), plaintext, this.h);
    this.mixHash(ciphertext);
    return ciphertext;
  }

  /** 解密一块握手数据：ad = h，成功后 h = MixHash(密文域)；认证失败抛 NoiseError('DECRYPT')。 */
  public decryptAndHash(key: Uint8Array, ciphertext: Uint8Array): Uint8Array {
    let plaintext: Uint8Array;
    try {
      plaintext = aeadOpen(key, new Uint8Array(AEAD_NONCE_LEN_BYTES), ciphertext, this.h);
    } catch (e) {
      throw new NoiseError('DECRYPT', 'noise: handshake decrypt failed: ' + String(e)) as Error;
    }
    this.mixHash(ciphertext);
    return plaintext;
  }

  /** Split：HKDF(ck, 空, 2) → [k1(initiator→responder), k2(responder→initiator)]；派生后擦除 ck。 */
  public splitKeys(): Uint8Array[] {
    const out: Uint8Array[] = kdf2Blake2s(this.ck, new Uint8Array(0));
    wipe(this.ck);
    return out;
  }
}

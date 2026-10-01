/**
 * 噪声传输态 CipherState（架构契约 §6 transport.ts）：握手 split() 之后的
 * 会话层消息加解密。
 *
 * - nonce = 4B 零 || BE64 计数器，自 0 递增，收发两端计数器独立（契约明文）。
 *   ✅ 上游核对结论（architecture.md §10-U1 的 nonce 编码项，2026-09-28 实读）：
 *   真实 tailscale controlbase 的 nonce.Increment()（control/controlbase/conn.go）
 *   就是 `BigEndian.PutUint64(n[4:], 1+BigEndian.Uint64(n[4:]))` —— BE64 计数器、
 *   前 4B 恒零、counter = 2^64-1 视为耗尽；本实现与之一致。注意这与现行 Noise
 *   规范 §12.3 的 ChaChaPoly nonce（LE64）不同 —— controlbase 刻意为之，本包按
 *   ts2021 互操作目标取 BE64（公开 cacophony 向量的传输段为 LE64，counter ≥ 1
 *   处两者不同，external-vector.test.ts 有对应的差异断言与注释）。
 * - 输出 = 密文 || 16B tag；传输消息无 AAD（零长度数组，对齐 controlbase Seal/Open
 *   的 ad=nil）；
 * - 构造函数为包内自定形态（契约未固定）：key 32B；initialCounter 供测试注入
 *   （缺省 0n），用于覆盖 2^32 计数器边界等向量，正常会话一律缺省；
 * - 达到 MAXNONCE（2^64-1）后拒绝再加解密（NoiseError('STATE')，对齐 controlbase
 *   的 invalidNonce 语义）。
 */

import { AEAD_NONCE_LEN_BYTES, KEY_LEN_BYTES, MAX_U64 } from '@ohos-tailscale/common';
import { aeadOpen, aeadSeal } from '@ohos-tailscale/crypto';
import { NoiseError } from './errors.ts';

/** 由 u64 计数器构造 12B nonce：字节 0..3 恒零，字节 4..11 为 BE64(counter)。 */
export function nonceForCounter(counter: bigint): Uint8Array {
  const nonce: Uint8Array = new Uint8Array(AEAD_NONCE_LEN_BYTES);
  let x: bigint = counter;
  for (let i: number = AEAD_NONCE_LEN_BYTES - 1; i >= 4; i -= 1) {
    nonce[i] = Number(x & 0xffn);
    x >>= 8n;
  }
  return nonce;
}

export class NoiseTransportCipher {
  private key: Uint8Array;
  private counter: bigint;

  public constructor(key: Uint8Array, initialCounter: bigint = 0n) {
    if (key.length !== KEY_LEN_BYTES) {
      throw new NoiseError(
        'STATE',
        'noise: transport key must be ' + String(KEY_LEN_BYTES) + ' bytes, got ' + String(key.length),
      ) as Error;
    }
    if (initialCounter < 0n || initialCounter > MAX_U64) {
      throw new NoiseError('STATE', 'noise: initial counter out of u64 range: ' + String(initialCounter)) as Error;
    }
    this.key = key.slice();
    this.counter = initialCounter;
  }

  /** 加密一条传输消息：返回 密文||tag 新数组；计数器随即 +1。零长度明文合法（keepalive）。 */
  public encrypt(plaintext: Uint8Array): Uint8Array {
    this.assertNonceUsable();
    const out: Uint8Array = aeadSeal(this.key, nonceForCounter(this.counter), plaintext, new Uint8Array(0));
    this.counter += 1n;
    return out;
  }

  /** 解密一条传输消息；任何失败（认证/长度）抛 NoiseError('DECRYPT')。计数器随即 +1。 */
  public decrypt(ciphertextWithTag: Uint8Array): Uint8Array {
    this.assertNonceUsable();
    let out: Uint8Array;
    try {
      out = aeadOpen(this.key, nonceForCounter(this.counter), ciphertextWithTag, new Uint8Array(0));
    } catch (e) {
      throw new NoiseError('DECRYPT', 'noise: transport decrypt failed at counter ' + String(this.counter) + ': ' + String(e)) as Error;
    }
    this.counter += 1n;
    return out;
  }

  private assertNonceUsable(): void {
    if (this.counter >= MAX_U64) {
      throw new NoiseError('STATE', 'noise: nonce space exhausted (counter reached 2^64-1)') as Error;
    }
  }
}

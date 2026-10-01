/**
 * WireGuard Transport Data 会话（白皮书 5.4.4/5.4.5）。
 *
 * 报文 = type u32le=4（type u8 + reserved[3] 的同形写法）|| receiver index u32le
 *       || counter u64le || AEAD(ChaCha20-Poly1305) 密文 + 16B 标签。
 * AEAD nonce = 4B 全零 || counter 的 8B 小端（白皮书特有：传输计数器小端）；
 * AAD 为空 —— counter 本身不参与认证（whitepaper 语义，接收端以解密成败 +
 * 反重放窗口兜底）。keepalive = 零长度明文 → 32B 报文。
 *
 * 反重放：2048 位滑动窗口（白皮书 REJECT 语义）。会话顺序约定：
 * 先解密认证、后推进窗口 —— 未通过认证的报文不消耗窗口槽位（比"先推窗"
 * 更抗窗口耗尽攻击；真实重放包本身标签有效，仍会正确落入 'REPLAY'）。
 */

import { AEAD_NONCE_LEN_BYTES, AEAD_TAG_LEN_BYTES, ByteReader, ByteWriter, KEY_LEN_BYTES, MAX_U64 } from '@ohos-tailscale/common';
import { aeadOpen, aeadSeal } from '@ohos-tailscale/crypto';
import { WG_REPLAY_WINDOW_BITS, WG_TRANSPORT_HEADER_LEN_BYTES, WgMessageType } from './constants.ts';
import { WgProtocolError } from './errors.ts';

/** 窗口位图掩码（2048 位全 1）。 */
const WINDOW_MASK: bigint = (1n << BigInt(WG_REPLAY_WINDOW_BITS)) - 1n;

/** 空明文/AAD（ChaCha20-Poly1305 无关联数据）。 */
const EMPTY: Uint8Array = new Uint8Array(0);

/** 校验 u32 范围会话索引（编程错误用普通 Error）。 */
function assertIndex(v: number, name: string): void {
  if (!Number.isInteger(v) || v < 0 || v > 0xffffffff) {
    throw new Error('wireguard: ' + name + ' must be u32, got ' + String(v));
  }
}

/** 校验 32B 会话键（编程错误用普通 Error）。 */
function assertSessionKey(key: Uint8Array, name: string): void {
  if (key.length !== KEY_LEN_BYTES) {
    throw new Error(
      'wireguard: ' +
        name +
        ' must be ' +
        String(KEY_LEN_BYTES) +
        ' bytes, got ' +
        String(key.length),
    );
  }
}

/**
 * 传输 AEAD nonce：4B 全零 || counter 的 8B **小端**（LE64）。
 * 对齐 wireguard-go：send.go `binary.LittleEndian.PutUint64(nonce[4:], counter)`
 * / receive.go `PutUint64(nonce[0x4:0xc], counter)` —— 最低字节在偏移 4。
 */
function transportNonce(counter: bigint): Uint8Array {
  const nonce: Uint8Array = new Uint8Array(AEAD_NONCE_LEN_BYTES);
  let x: bigint = counter;
  for (let i: number = 4; i <= 11; i += 1) {
    nonce[i] = Number(x & 0xffn);
    x >>= 8n;
  }
  return nonce;
}

/**
 * 发送会话：counter 从 0 自增（u64），输出完整可发报文。
 * 签名严格照办 architecture.md §5 冻结契约：constructor(localIndex, sendKey)。
 *
 * 参数语义（白皮书 5.4.4：receiver index = 接收端为其会话分配的索引）：
 * localIndex 会被原样写入报文的 receiver index 字段 —— 即调用方应传
 * "本端视角的 peerIndex"（对端分配的索引；等价 wireguard-go 的
 * keypair.remoteIndex），与 WgRecvSession 以本端 localIndex 校验构成镜像。
 */
export class WgSendSession {
  private localIndex: number;
  private key: Uint8Array;
  private counter: bigint = 0n;

  public constructor(localIndex: number, sendKey: Uint8Array) {
    assertIndex(localIndex, 'local index');
    assertSessionKey(sendKey, 'send key');
    this.localIndex = localIndex;
    this.key = sendKey.slice();
  }

  /**
   * 加密并输出完整可发报文（16B 头 + 密文 + 16B 标签；新数组）。
   * 计数器耗尽（> u64max）抛 WgProtocolError('STATE')（真实实现应在此之前重钥）。
   */
  public encryptPacket(plaintext: Uint8Array): Uint8Array {
    if (this.counter > MAX_U64) {
      throw new WgProtocolError('STATE', 'send counter exhausted; session must rekey') as Error;
    }
    const sealed: Uint8Array = aeadSeal(this.key, transportNonce(this.counter), plaintext, EMPTY);
    const w: ByteWriter = new ByteWriter(WG_TRANSPORT_HEADER_LEN_BYTES);
    w.writeU32le(WgMessageType.TransportData);
    w.writeU32le(this.localIndex);
    w.writeU64le(this.counter);
    w.writeBytes(sealed);
    this.counter += 1n;
    return w.toUint8Array();
  }
}

/**
 * 接收会话：校验 type=4/receiver/反重放窗口并解密。
 * keepalive 返回零长度数组；重放抛 WgProtocolError('REPLAY')。
 */
export class WgRecvSession {
  private peerIndex: number;
  private key: Uint8Array;
  /** 已见过的最高连续计数器。 */
  private highest: bigint = 0n;
  /** 位图：bit i = 计数器 (highest - i) 已收。 */
  private bitmap: bigint = 0n;
  private hasPacket: boolean = false;

  public constructor(peerIndex: number, recvKey: Uint8Array) {
    assertIndex(peerIndex, 'peer index');
    assertSessionKey(recvKey, 'recv key');
    this.peerIndex = peerIndex;
    this.key = recvKey.slice();
  }

  /**
   * 解密一包：报文 < 32B 抛 'BAD_LEN'；type≠4 抛 'BAD_TYPE'；
   * receiver index 不匹配抛 'STATE'；AEAD 认证失败抛 'DECRYPT'；
   * 重放/过旧（< highest-2047）抛 'REPLAY'。返回零长度明文表示 keepalive。
   */
  public decryptPacket(packet: Uint8Array): Uint8Array {
    if (packet.length < WG_TRANSPORT_HEADER_LEN_BYTES + AEAD_TAG_LEN_BYTES) {
      throw new WgProtocolError(
        'BAD_LEN',
        'transport packet must be at least ' +
          String(WG_TRANSPORT_HEADER_LEN_BYTES + AEAD_TAG_LEN_BYTES) +
          ' bytes, got ' +
          String(packet.length),
      ) as Error;
    }
    const r: ByteReader = new ByteReader(packet);
    const msgType: number = r.readU32le();
    if (msgType !== WgMessageType.TransportData) {
      throw new WgProtocolError(
        'BAD_TYPE',
        'expected transport data (4), got ' + String(msgType),
      ) as Error;
    }
    const receiverIndex: number = r.readU32le();
    if (receiverIndex !== this.peerIndex) {
      throw new WgProtocolError('STATE', 'transport receiver index mismatch') as Error;
    }
    const counter: bigint = r.readU64le();
    const ciphertext: Uint8Array = packet.slice(WG_TRANSPORT_HEADER_LEN_BYTES);

    // 先认证解密，后推进窗口（见文件头注释）
    let plaintext: Uint8Array;
    try {
      plaintext = aeadOpen(this.key, transportNonce(counter), ciphertext, EMPTY);
    } catch (e) {
      const err: Error = e as Error;
      throw new WgProtocolError('DECRYPT', 'transport decrypt failed: ' + err.message) as Error;
    }
    this.assertFreshCounter(counter);
    this.markCounter(counter);
    return plaintext;
  }

  /** 重放/过旧判定：不符抛 WgProtocolError('REPLAY')。 */
  private assertFreshCounter(counter: bigint): void {
    if (!this.hasPacket) {
      return;
    }
    if (counter > this.highest) {
      return;
    }
    const back: bigint = this.highest - counter;
    if (back >= BigInt(WG_REPLAY_WINDOW_BITS)) {
      throw new WgProtocolError('REPLAY', 'counter too old: ' + counter.toString()) as Error;
    }
    if (((this.bitmap >> back) & 1n) === 1n) {
      throw new WgProtocolError('REPLAY', 'counter already received: ' + counter.toString()) as Error;
    }
  }

  /** 窗口推进/置位（assertFreshCounter 通过后调用）。 */
  private markCounter(counter: bigint): void {
    if (!this.hasPacket) {
      this.hasPacket = true;
      this.highest = counter;
      this.bitmap = 1n;
      return;
    }
    if (counter > this.highest) {
      const shift: bigint = counter - this.highest;
      if (shift >= BigInt(WG_REPLAY_WINDOW_BITS)) {
        this.bitmap = 1n;
      } else {
        this.bitmap = (this.bitmap << shift) & WINDOW_MASK;
        this.bitmap |= 1n;
      }
      this.highest = counter;
      return;
    }
    const back: bigint = this.highest - counter;
    this.bitmap |= 1n << back;
  }
}

/**
 * Cookie Reply（type=3）：响应端生成 + 发起端消费 + 64B 编解码。
 *
 * 本模块收口一期预留接口（cookie.ts 头注"响应端 cookie 派发留二期"）。
 * 上游实读依据（2026-10-01，GPU 机 jsdelivr CDN 拉取 wireguard-go master）：
 * - device/noise-protocol.go:112 MessageCookieReply 布局：
 *   Type u32le(=3) ‖ Receiver u32le ‖ Nonce 24B ‖ Cookie 32B（16B cookie + 16B tag），
 *   总长 64B（MessageCookieReplySize）；marshal/unmarshal 全小端。
 * - device/cookie.go：响应端 CreateReply——cookie = BLAKE2s-128(R_m, src)（R_m 每
 *   CookieRefreshTime=120s 轮换的 32B 秘密）；密文 = XChaCha20-Poly1305(
 *   key=BLAKE2s-256("cookie--" ‖ 发起端静态公钥), nonce=reply.Nonce,
 *   plaintext=cookie, AAD=收包 MAC1 字段 msg[smac1:smac2])。
 *   发起端 ConsumeReply——同键同 AAD（AAD=本端最近发送的 MAC1）解密，存为
 *   最近 cookie 供 AddMacs 计算 mac2。
 * - 白皮书对应条目：§5.4.4 MAC1/MAC2（一期已实现，见 cookie.ts）与 §5.4.7
 *   Under Load: Cookie Reply（本模块）。
 *
 * 复用一期骨架：cookie.ts 的 wgCookieKey（"cookie--" 键派生，头注注明"二期 XAEAD
 * 消费"即本处）与 wgComputeCookie（τ = Mac(R_m, A_m←)）；XChaCha20-Poly1305 见
 * crypto 包 xchacha.ts（draft-irtf-cfrg-xchacha-03 向量锚定）。
 *
 * 边界（如实保留）：本模块只做 Cookie Reply 的编解码与生成/消费语义；
 * transport.ts 的报文分发（type=3 路由进本模块）属 UDP 收发环集成，本轮不动
 * （既有 238 基线中 transport 对 type=3 抛 BAD_TYPE 的行为保持原样）。
 */

import { ByteReader, ByteWriter, type Rng } from '@ohos-tailscale/common';
import { blake2s256Keyed, constTimeEqual, xchacha20poly1305Open, xchacha20poly1305Seal } from '@ohos-tailscale/crypto';
import {
  WG_COOKIE_NONCE_LEN_BYTES,
  WG_COOKIE_REPLY_LEN_BYTES,
  WG_MAC_LEN_BYTES,
  WgMessageType,
} from './constants.ts';
import { wgComputeCookie, wgCookieKey } from './cookie.ts';
import { WgProtocolError } from './errors.ts';

/** Cookie Reply 的 32B 密文（16B cookie + 16B Poly1305 tag）。 */
const WG_COOKIE_SEALED_LEN_BYTES: number = WG_MAC_LEN_BYTES * 2;

/** R_m 轮换周期：上游 CookieRefreshTime = 120s（wireguard-go device/constants.go:24）。 */
export const WG_COOKIE_REFRESH_MS: number = 120000;

/** 解码后的 Cookie Reply（字段均为独立拷贝）。 */
export interface WgCookieReply {
  /** 发起端要塞回报文里的 receiver 索引（u32）。 */
  receiver: number;
  /** 24B 随机 nonce。 */
  nonce: Uint8Array;
  /** 32B XChaCha20-Poly1305 密文（cookie ‖ tag）。 */
  cookieSealed: Uint8Array;
}

/** 编码 Cookie Reply → 64B（白皮书 §5.4.7 / wireguard-go noise-protocol.go 布局）。 */
export function cookieReplyEncode(reply: WgCookieReply): Uint8Array {
  if (reply.nonce.length !== WG_COOKIE_NONCE_LEN_BYTES) {
    throw new WgProtocolError(
      'RANGE',
      'cookie reply encode: nonce must be ' +
        String(WG_COOKIE_NONCE_LEN_BYTES) +
        ' bytes, got ' +
        String(reply.nonce.length),
    ) as Error;
  }
  if (reply.cookieSealed.length !== WG_COOKIE_SEALED_LEN_BYTES) {
    throw new WgProtocolError(
      'RANGE',
      'cookie reply encode: sealed cookie must be ' +
        String(WG_COOKIE_SEALED_LEN_BYTES) +
        ' bytes, got ' +
        String(reply.cookieSealed.length),
    ) as Error;
  }
  const w: ByteWriter = new ByteWriter(WG_COOKIE_REPLY_LEN_BYTES);
  w.writeU32le(WgMessageType.CookieReply);
  w.writeU32le(reply.receiver >>> 0);
  w.writeBytes(reply.nonce);
  w.writeBytes(reply.cookieSealed);
  return w.toUint8Array();
}

/** 解码 64B → Cookie Reply。长度非 64 抛 WgProtocolError('BAD_LEN')；type≠3 抛 'BAD_TYPE'。 */
export function cookieReplyDecode(buf: Uint8Array): WgCookieReply {
  if (buf.length !== WG_COOKIE_REPLY_LEN_BYTES) {
    throw new WgProtocolError(
      'BAD_LEN',
      'cookie reply decode: must be ' +
        String(WG_COOKIE_REPLY_LEN_BYTES) +
        ' bytes, got ' +
        String(buf.length),
    ) as Error;
  }
  const r: ByteReader = new ByteReader(buf);
  const type: number = r.readU32le();
  if (type !== WgMessageType.CookieReply) {
    throw new WgProtocolError('BAD_TYPE', 'cookie reply decode: type must be 3, got ' + String(type)) as Error;
  }
  const receiver: number = r.readU32le();
  const nonce: Uint8Array = r.readBytes(WG_COOKIE_NONCE_LEN_BYTES);
  const cookieSealed: Uint8Array = r.readBytes(WG_COOKIE_SEALED_LEN_BYTES);
  const reply: WgCookieReply = { receiver: receiver, nonce: nonce, cookieSealed: cookieSealed };
  return reply;
}

/**
 * 从收到的完整握手报文提取 MAC1 字段（倒数第 32..16 字节）。
 * 报文长度不足 48B（macs 段 + 至少 16B 报文）抛 WgProtocolError('BAD_LEN')。
 * 返回 16B 独立拷贝。
 */
export function extractMac1Field(fullMsg: Uint8Array): Uint8Array {
  if (fullMsg.length < WG_MACS_MIN_LEN_BYTES) {
    throw new WgProtocolError(
      'BAD_LEN',
      'extract mac1: message too short to carry macs, got ' + String(fullMsg.length),
    ) as Error;
  }
  return fullMsg.slice(fullMsg.length - WG_MACS_LEN_TOTAL, fullMsg.length - WG_MAC_LEN_BYTES);
}

const WG_MACS_LEN_TOTAL: number = WG_MAC_LEN_BYTES * 2;
const WG_MACS_MIN_LEN_BYTES: number = WG_MAC_LEN_BYTES * 3;

/**
 * 响应端 Cookie Reply 生成器（wireguard-go CookieChecker.CreateReply 语义）。
 * 状态：R_m（32B 秘密，每 WG_COOKIE_REFRESH_MS 轮换）+ 轮换时刻。
 * Rng/Clock 全部注入（P4）；初始 R_m 首次用到时经 Rng 生成。
 */
export class WgCookieResponder {
  private readonly rng: Rng;
  private secret: Uint8Array | null = null;
  private secretSetMs: number = 0;

  constructor(rng: Rng) {
    this.rng = rng;
  }

  /** 当前 R_m（如未生成先用 Rng 生成）。测试用途。 */
  public ensureSecret(nowMs: number): Uint8Array {
    if (this.secret === null || nowMs - this.secretSetMs >= WG_COOKIE_REFRESH_MS) {
      const next: Uint8Array = new Uint8Array(32);
      this.rng.randomBytes(next);
      this.secret = next;
      this.secretSetMs = nowMs;
    }
    return this.secret;
  }

  /** 强制轮换 R_m（测试轮换边界用）。 */
  public rotateSecret(nowMs: number): void {
    const next: Uint8Array = new Uint8Array(32);
    this.rng.randomBytes(next);
    this.secret = next;
    this.secretSetMs = nowMs;
  }

  /**
   * 生成 Cookie Reply（64B）：
   * cookie = BLAKE2s-128(R_m, srcAddr)；密文 = XChaCha20-Poly1305(
   * wgCookieKey(响应端静态公钥), rng nonce24, cookie, AAD=fullMsg 的 MAC1 字段)。
   * 键输入语义（2026-10-01 对照 wireguard-go receive.go/cookie.go 修正）：
   * CookieChecker.Init(device 静态公钥) → mac2.encryptionKey =
   * BLAKE2s("cookie--" || **响应端**静态公钥)——即被发起端寻址的一方；发起端消费时
   * generator.Init(remoteStatic) 用同一公钥（= 它的对端），两侧同键。
   * fullMsg 须为带 macs 段的完整握手报文（提取其 MAC1 作 AAD，与上游一致）；
   * srcAddr 为对端源地址字节（1..32B，编组由调用方定——上游为 UDP 源地址原始字节）。
   */
  public createReply(
    fullMsg: Uint8Array,
    receiverIndex: number,
    responderStaticPublic: Uint8Array,
    srcAddr: Uint8Array,
    nowMs: number,
  ): Uint8Array {
    const secret: Uint8Array = this.ensureSecret(nowMs);
    const cookie: Uint8Array = wgComputeCookie(secret, srcAddr);
    const aad: Uint8Array = extractMac1Field(fullMsg);
    const key: Uint8Array = wgCookieKey(responderStaticPublic);
    const nonce: Uint8Array = new Uint8Array(WG_COOKIE_NONCE_LEN_BYTES);
    this.rng.randomBytes(nonce);
    const sealed: Uint8Array = xchacha20poly1305Seal(key, nonce, cookie, aad);
    const reply: WgCookieReply = { receiver: receiverIndex, nonce: nonce, cookieSealed: sealed };
    return cookieReplyEncode(reply);
  }

  /**
   * 校验收到的 mac2（wireguard-go CheckMAC2 语义）：
   * R_m 超过轮换周期（按 nowMs）→ false（上游不自动轮换校验侧秘密）；
   * mac2 全零 → true（对端未持有 cookie，常态）；
   * 否则 expected = BLAKE2s-128(BLAKE2s-128(R_m, srcAddr), msg[0:len-16]) 常时比较。
   */
  public verifyMac2(fullMsg: Uint8Array, srcAddr: Uint8Array, nowMs: number): boolean {
    if (this.secret === null || nowMs - this.secretSetMs >= WG_COOKIE_REFRESH_MS) {
      return false;
    }
    if (fullMsg.length < WG_MACS_MIN_LEN_BYTES) {
      return false;
    }
    const mac2: Uint8Array = fullMsg.slice(fullMsg.length - WG_MAC_LEN_BYTES);
    let allZero: boolean = true;
    for (let i: number = 0; i < mac2.length; i += 1) {
      if (mac2[i] !== 0) {
        allZero = false;
        break;
      }
    }
    if (allZero) {
      return true;
    }
    const cookie: Uint8Array = wgComputeCookie(this.secret, srcAddr);
    const expected: Uint8Array = blake2s256Keyed(cookie, fullMsg.subarray(0, fullMsg.length - WG_MAC_LEN_BYTES)).slice(
      0,
      WG_MAC_LEN_BYTES,
    );
    return constTimeEqual(expected, mac2);
  }
}

/** （随机源直接复用 common 注入接口 Rng，不另定义本地同形接口。） */

/**
 * 发起端 Cookie Reply 消费器（wireguard-go CookieGenerator.ConsumeReply 语义）。
 * 持有对端（响应端）静态公钥与"最近发送的 MAC1"（AAD）；consume 成功返回 16B
 * cookie（调用方自行写入 WgCookieCache 供 mac2 计算——与一期 cookie.ts 组合）。
 * 键 = wgCookieKey(对端静态公钥)：上游 generator.Init(remoteStatic)，与响应端
 * checker.Init(本端静态公钥) 得到同一把键（2026-10-01 语义修正，见类上方注释）。
 */
export class WgCookieReplyConsumer {
  private readonly peerStaticPublic: Uint8Array;
  private lastMac1: Uint8Array | null = null;

  constructor(peerStaticPublic: Uint8Array) {
    if (peerStaticPublic.length !== 32) {
      throw new WgProtocolError(
        'RANGE',
        'consumer: peer static public must be 32 bytes, got ' + String(peerStaticPublic.length),
      ) as Error;
    }
    this.peerStaticPublic = peerStaticPublic.slice();
  }

  /** 记录本端最近发送的 MAC1（16B，独立拷贝存储）——consume 的 AAD 来源。 */
  public noteSentMac1(mac1: Uint8Array): void {
    if (mac1.length !== WG_MAC_LEN_BYTES) {
      throw new WgProtocolError(
        'RANGE',
        'consumer: mac1 must be ' + String(WG_MAC_LEN_BYTES) + ' bytes, got ' + String(mac1.length),
      ) as Error;
    }
    this.lastMac1 = mac1.slice();
  }

  /**
   * 消费 64B Cookie Reply：解密成功返回 16B cookie，失败返回 null（含：从未发送
   * MAC1、AAD 不符、键/AEAD 认证失败、报文格式非法——上游对格式非法直接忽略）。
   * 不抛异常（上游 ConsumeReply 返回 bool 语义）。
   */
  public consume(replyBytes: Uint8Array): Uint8Array | null {
    if (this.lastMac1 === null) {
      return null;
    }
    let reply: WgCookieReply;
    try {
      reply = cookieReplyDecode(replyBytes);
    } catch (_e) {
      return null;
    }
    const key: Uint8Array = wgCookieKey(this.peerStaticPublic);
    let cookie: Uint8Array;
    try {
      cookie = xchacha20poly1305Open(key, reply.nonce, reply.cookieSealed, this.lastMac1);
    } catch (_e) {
      return null;
    }
    return cookie;
  }
}

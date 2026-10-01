/**
 * WireGuard 握手状态机（白皮书 5.4.2–5.4.6，psk2 槽位带全零 psk）。
 *
 * 键调度以 wireguard-go noise-protocol.go（interop 基准，本机 oracle 数据面
 * 即 wireguard-go 系）逐行核对为准：
 *   InitialChainKey = HASH(CONSTRUCTION)；InitialHash = HASH(InitialChainKey || IDENTIFIER)
 *   msg1（-> e, es, s, ss, ts）：
 *     hash = HASH(InitialHash || 接收方静态公钥)
 *     mixKey(e.pub)；mixHash(e.pub)
 *     (ck, k1) = KDF2(ck, DH(e, 接收方静态公钥))          —— es
 *     enc_static = AEAD(k1, 0, 发起方静态公钥, hash)；mixHash
 *     (ck, k2) = KDF2(ck, DH(双方静态密钥))               —— ss（psk2 槽位）
 *     enc_timestamp = AEAD(k2, 0, TAI64N, hash)；mixHash
 *   msg2（<- e, ee, se, psk, [empty]）：
 *     mixHash(e.pub)；mixKey(e.pub)
 *     mixKey(DH(e_r, e_i))；mixKey(DH(e_r, s_i))          —— ee、se
 *     (ck, tau, k) = KDF3(ck, psk=32B 全零)；mixHash(tau)
 *     enc_empty = AEAD(k, 0, 空, hash)；mixHash
 *   传输密钥：KDF2(ck_final, 空 ikm)，发起端 [0]=send/[1]=recv，响应端对调。
 * AEAD nonce 恒为 12B 全零（白皮书 counter=0）；KDF = HMAC-BLAKE2s HKDF²/³；
 * HASH = 无键 BLAKE2s-256；每次 DH 输出全零即 WgProtocolError('ZERO_DH')。
 *
 * 注入与确定性（P4）：
 * - 临时私钥 32B 取自注入 rng，随后本端会话索引 senderIndex u32le 也取自 rng
 *   （消耗顺序固定：先 32B 临时私钥，后 4B 索引 —— 测试按此备池）；
 * - TAI64N 时间戳由注入 clock.wallMs() 派生（见 tai64n.ts）。
 *
 * MAC1/MAC2：构造恒算 mac1；mac2 仅在 provideCookie 注入过 cookie 时按公式
 * 计算，否则 16B 全零（非负载态的正确线上形态）。消费时校验 mac1；mac2
 * 非零而无"已发 cookie"可验时拒绝（cookie.ts 的 wgVerifyMac2Field）。
 * 一期不解析 Cookie Reply（type=3 → WgProtocolError('BAD_TYPE')）。
 */

import { type Clock, type Rng, ByteReader, ByteWriter, KEY_LEN_BYTES, utf8Encode } from '@ohos-tailscale/common';
import {
  aeadOpen,
  aeadSeal,
  blake2s256,
  isZeroBytes,
  kdf2Blake2s,
  kdf3Blake2s,
  wipe,
  x25519,
  x25519PublicKeyFromPrivate,
} from '@ohos-tailscale/crypto';
import {
  WG_CONSTRUCTION,
  WG_ENCRYPTED_EMPTY_LEN_BYTES,
  WG_ENCRYPTED_STATIC_LEN_BYTES,
  WG_ENCRYPTED_TIMESTAMP_LEN_BYTES,
  WG_IDENTIFIER,
  WG_INITIATION_LEN_BYTES,
  WG_MAC_LEN_BYTES,
  WG_MACS_LEN_BYTES,
  WG_RESPONSE_LEN_BYTES,
  WG_TIMESTAMP_LEN_BYTES,
  WgMessageType,
} from './constants.ts';
import { WgProtocolError } from './errors.ts';
import {
  wgComputeMac1,
  wgComputeMac2,
  wgMac1Key,
  wgVerifyMac2Field,
} from './cookie.ts';
import { tai64nFromWallMs } from './tai64n.ts';

/** 握手状态（模块私有，R5 数值常量对象模式）。 */
interface WgHandshakeStateE {
  Idle: number;
  Awaiting: number;
  Complete: number;
  Finished: number;
}
const WgHandshakeState: WgHandshakeStateE = { Idle: 0, Awaiting: 1, Complete: 2, Finished: 3 };

/** 握手 AEAD 恒用 12B 全零 nonce（白皮书 counter=0）。 */
const ZERO_NONCE: Uint8Array = new Uint8Array(12);

/** enc_nothing 的空明文 / 传输键派生的空 ikm。 */
const EMPTY_BYTES: Uint8Array = new Uint8Array(0);

/** psk2 槽位的全零 psk（未配置 psk 模式）。 */
const ZERO_PSK: Uint8Array = new Uint8Array(32);

/** 白皮书协议字符串字节（模块级固化，确定性）。 */
const CONSTRUCTION_BYTES: Uint8Array = utf8Encode(WG_CONSTRUCTION);
const IDENTIFIER_BYTES: Uint8Array = utf8Encode(WG_IDENTIFIER);

/** consumeInitiation 的返回（架构契约 §5；字段数组均为独立拷贝）。 */
export interface WgInitiationInfo {
  /** 对端（发起方）选择的会话索引 u32le。 */
  senderIndex: number;
  /** 对端静态公钥 32B（已经本端静态私钥 DH + AEAD 认证）。 */
  peerStaticPublic: Uint8Array;
  /** 12B TAI64N 时间戳（重放比较由调用方负责）。 */
  timestamp: Uint8Array;
}

/** finish() 的返回（架构契约 §5；sendKey/recvKey 为 32B 独立拷贝）。 */
export interface WgHandshakeOutput {
  /** 本端会话索引。 */
  localIndex: number;
  /** 对端会话索引。 */
  peerIndex: number;
  /** 本端 → 对端 发送键 32B。 */
  sendKey: Uint8Array;
  /** 对端 → 本端 接收键 32B。 */
  recvKey: Uint8Array;
}

/** mac1/mac2 字段载体（模块私有；均为拷贝）。 */
interface WgMacFields {
  mac1: Uint8Array;
  mac2: Uint8Array;
}

/** 拼接两个数组为新数组。 */
function concatBytes(a: Uint8Array, b: Uint8Array): Uint8Array {
  const out: Uint8Array = new Uint8Array(a.length + b.length);
  out.set(a, 0);
  out.set(b, a.length);
  return out;
}

/** KDF¹：链键推进（取 KDF² 首输出，等价 wireguard-go mixKey/KDF1）。 */
function kdf1(chainingKey: Uint8Array, ikm: Uint8Array): Uint8Array {
  return kdf2Blake2s(chainingKey, ikm)[0];
}

/** 校验 32B 键长度（构造入参前置校验，编程错误用普通 Error）。 */
function assertKeyLen(b: Uint8Array, name: string): void {
  if (b.length !== KEY_LEN_BYTES) {
    throw new Error(
      'wireguard: ' + name + ' must be ' + String(KEY_LEN_BYTES) + ' bytes, got ' + String(b.length),
    );
  }
}

/** DH 包装：输出全零抛 WgProtocolError('ZERO_DH')（白皮书：对端拒绝，会话不建立）。 */
function dhOrZero(privateKey: Uint8Array, publicKey: Uint8Array): Uint8Array {
  const shared: Uint8Array = x25519(privateKey, publicKey);
  if (isZeroBytes(shared)) {
    throw new WgProtocolError('ZERO_DH', 'X25519 output is all-zero (peer rejected)') as Error;
  }
  return shared;
}

/** 从报文读出 mac1/mac2 字段（长度已由调用方校验；返回拷贝）。 */
function readMacs(msg: Uint8Array): WgMacFields {
  const cut: number = msg.length - WG_MACS_LEN_BYTES;
  const macs: WgMacFields = {
    mac1: msg.slice(cut, cut + WG_MAC_LEN_BYTES),
    mac2: msg.slice(cut + WG_MAC_LEN_BYTES),
  };
  return macs;
}

/** 提取捕获错误的 message（A19 as 转换；A26：catch 变量不带标注）。 */
function caughtMessage(err: Error): string {
  return err.message;
}

/**
 * 校验握手报文 mac1（接收方 = 本端：mac1 键由本端静态公钥派生），不符抛 'MAC'。
 * 白皮书校验序：先验 mac 再进入解密。
 */
function verifyMac1(msg: Uint8Array, localStaticPublic: Uint8Array): void {
  const macs: WgMacFields = readMacs(msg);
  const expect: Uint8Array = wgComputeMac1(
    wgMac1Key(localStaticPublic),
    msg.subarray(0, msg.length - WG_MACS_LEN_BYTES),
  );
  let diff: number = 0;
  for (let i: number = 0; i < WG_MAC_LEN_BYTES; i += 1) {
    diff |= macs.mac1[i] ^ expect[i];
  }
  if (diff !== 0) {
    throw new WgProtocolError('MAC', 'mac1 verification failed') as Error;
  }
}

// ---------------------------------------------------------------------------
// 发起端（Initiator）
// ---------------------------------------------------------------------------

/**
 * 握手发起端。生命周期：createInitiation → consumeResponse → finish（各一次，
 * 顺序错误一律 WgProtocolError('STATE')）。
 */
export class WgHandshakeInitiator {
  private staticPrivate: Uint8Array;
  private staticPublic: Uint8Array;
  private peerStaticPublic: Uint8Array;
  private rng: Rng;
  private clock: Clock;
  private state: number = WgHandshakeState.Idle;
  private senderIndex: number = 0;
  private peerIndex: number = 0;
  private ephemeralPrivate: Uint8Array = new Uint8Array(0);
  private chainingKey: Uint8Array = new Uint8Array(0);
  private hash: Uint8Array = new Uint8Array(0);
  private sendKey: Uint8Array = new Uint8Array(0);
  private recvKey: Uint8Array = new Uint8Array(0);
  /** 最近收到的对端 cookie（provideCookie 注入）；空数组 = 无 → mac2 全零。 */
  private cookie: Uint8Array = new Uint8Array(0);

  public constructor(
    staticPrivate: Uint8Array,
    peerStaticPublic: Uint8Array,
    rng: Rng,
    clock: Clock,
  ) {
    assertKeyLen(staticPrivate, 'static private key');
    assertKeyLen(peerStaticPublic, 'peer static public key');
    this.staticPrivate = staticPrivate.slice();
    this.staticPublic = x25519PublicKeyFromPrivate(staticPrivate);
    this.peerStaticPublic = peerStaticPublic.slice();
    this.rng = rng;
    this.clock = clock;
  }

  /**
   * 【骨架支持】注入"对端曾发来的 cookie"（应来自对端 Cookie Reply 的解密结果），
   * 之后 createInitiation 的 mac2 段按白皮书 mac2 公式计算而非全零。
   * cookie 须 16B，不符抛 Error。
   */
  public provideCookie(cookie: Uint8Array): void {
    if (cookie.length !== WG_MAC_LEN_BYTES) {
      throw new Error(
        'provideCookie: cookie must be ' +
          String(WG_MAC_LEN_BYTES) +
          ' bytes, got ' +
          String(cookie.length),
      );
    }
    this.cookie = cookie.slice();
  }

  /**
   * 构造 148B Handshake Initiation（新数组）。
   * rng 消耗顺序：32B 临时私钥 → 4B 本端会话索引；时间戳取 clock.wallMs()。
   */
  public createInitiation(): Uint8Array {
    if (this.state !== WgHandshakeState.Idle) {
      throw new WgProtocolError('STATE', 'createInitiation requires fresh initiator state') as Error;
    }
    // -> e（临时密钥对）+ 会话索引（文档化的 rng 消耗顺序）
    const ePriv: Uint8Array = new Uint8Array(32);
    this.rng.randomBytes(ePriv);
    const ePub: Uint8Array = x25519PublicKeyFromPrivate(ePriv);
    const idxBytes: Uint8Array = new Uint8Array(4);
    this.rng.randomBytes(idxBytes);
    this.senderIndex =
      (idxBytes[0] | (idxBytes[1] << 8) | (idxBytes[2] << 16) | (idxBytes[3] << 24)) >>> 0;

    // 链键/哈希初始化（接收方 = 对端静态公钥）
    let ck: Uint8Array = blake2s256(CONSTRUCTION_BYTES);
    let h: Uint8Array = blake2s256(
      concatBytes(blake2s256(concatBytes(ck, IDENTIFIER_BYTES)), this.peerStaticPublic),
    );
    // -> e：mixKey 与 mixHash 相互独立
    ck = kdf1(ck, ePub);
    h = blake2s256(concatBytes(h, ePub));
    // -> es
    const esShared: Uint8Array = dhOrZero(ePriv, this.peerStaticPublic);
    const kEs: Uint8Array[] = kdf2Blake2s(ck, esShared);
    ck = kEs[0];
    const keyEs: Uint8Array = kEs[1];
    // -> s
    const encStatic: Uint8Array = aeadSeal(keyEs, ZERO_NONCE, this.staticPublic, h);
    h = blake2s256(concatBytes(h, encStatic));
    wipe(keyEs);
    // -> ss（psk2 槽位：双方静态密钥的 DH）
    const ssShared: Uint8Array = dhOrZero(this.staticPrivate, this.peerStaticPublic);
    const kSs: Uint8Array[] = kdf2Blake2s(ck, ssShared);
    ck = kSs[0];
    const keySs: Uint8Array = kSs[1];
    wipe(esShared);
    wipe(ssShared);
    // -> ts
    const timestamp: Uint8Array = tai64nFromWallMs(this.clock.wallMs());
    const encTimestamp: Uint8Array = aeadSeal(keySs, ZERO_NONCE, timestamp, h);
    h = blake2s256(concatBytes(h, encTimestamp));
    wipe(keySs);

    // 组包：mac1 覆盖 macs 段之前全部字节；mac2 依赖 cookie 骨架状态
    const w: ByteWriter = new ByteWriter(WG_INITIATION_LEN_BYTES);
    w.writeU32le(WgMessageType.HandshakeInitiation);
    w.writeU32le(this.senderIndex);
    w.writeBytes(ePub);
    w.writeBytes(encStatic);
    w.writeBytes(encTimestamp);
    const mac1: Uint8Array = wgComputeMac1(wgMac1Key(this.peerStaticPublic), w.toUint8Array());
    w.writeBytes(mac1);
    w.writeBytes(this.computeMac2Field(w.toUint8Array()));
    const msg: Uint8Array = w.toUint8Array();

    // 状态推进（保留 ePriv/ck/h 供 consumeResponse）
    this.ephemeralPrivate = ePriv;
    this.chainingKey = ck;
    this.hash = h;
    this.state = WgHandshakeState.Awaiting;
    return msg;
  }

  /**
   * 消费 92B Handshake Response；校验 type/长度/mac1/receiver index/解密。
   * 失败抛 WgProtocolError（'BAD_TYPE'|'BAD_LEN'|'MAC'|'ZERO_DH'|'STATE'|'DECRYPT'）。
   */
  public consumeResponse(msg: Uint8Array): void {
    if (this.state !== WgHandshakeState.Awaiting) {
      throw new WgProtocolError('STATE', 'consumeResponse requires createInitiation first') as Error;
    }
    // 校验序：先读类型（类型非法 → BAD_TYPE，含一期不解析的 Cookie Reply），
    // 再做精确长度校验（类型合法但长度不符 → BAD_LEN）
    if (msg.length < 4) {
      throw new WgProtocolError(
        'BAD_LEN',
        'handshake response must be at least 4 bytes, got ' + String(msg.length),
      ) as Error;
    }
    const r: ByteReader = new ByteReader(msg);
    const msgType: number = r.readU32le();
    if (msgType !== WgMessageType.HandshakeResponse) {
      throw new WgProtocolError(
        'BAD_TYPE',
        'expected handshake response (2), got ' + String(msgType),
      ) as Error;
    }
    if (msg.length !== WG_RESPONSE_LEN_BYTES) {
      throw new WgProtocolError(
        'BAD_LEN',
        'handshake response must be ' +
          String(WG_RESPONSE_LEN_BYTES) +
          ' bytes, got ' +
          String(msg.length),
      ) as Error;
    }
    verifyMac1(msg, this.staticPublic);
    const macs: WgMacFields = readMacs(msg);
    // 一期无 Cookie Reply 流程 → 无"已发 cookie"可验 → mac2 必须全零
    wgVerifyMac2Field(macs.mac2, null);
    // msg2 布局：[type][sender（响应端索引）][receiver（= 本端索引）]
    const responderSenderIndex: number = r.readU32le();
    const receiverIndex: number = r.readU32le();
    if (receiverIndex !== this.senderIndex) {
      throw new WgProtocolError('STATE', 'response receiver index mismatch') as Error;
    }
    this.peerIndex = responderSenderIndex;
    const ePub: Uint8Array = r.readBytes(32);
    const encNothing: Uint8Array = r.readBytes(WG_ENCRYPTED_EMPTY_LEN_BYTES);

    // <- e
    this.hash = blake2s256(concatBytes(this.hash, ePub));
    this.chainingKey = kdf1(this.chainingKey, ePub);
    // <- ee
    const eeShared: Uint8Array = dhOrZero(this.ephemeralPrivate, ePub);
    this.chainingKey = kdf1(this.chainingKey, eeShared);
    wipe(eeShared);
    // <- se（DH(s_i, e_r) == DH(e_r, s_i)）
    const seShared: Uint8Array = dhOrZero(this.staticPrivate, ePub);
    this.chainingKey = kdf1(this.chainingKey, seShared);
    wipe(seShared);
    // <- psk（全零）→ tau + key
    const k3: Uint8Array[] = kdf3Blake2s(this.chainingKey, ZERO_PSK);
    this.chainingKey = k3[0];
    const tau: Uint8Array = k3[1];
    const keyEmpty: Uint8Array = k3[2];
    this.hash = blake2s256(concatBytes(this.hash, tau));
    // <- [empty]（认证空载荷）
    let empty: Uint8Array;
    try {
      empty = aeadOpen(keyEmpty, ZERO_NONCE, encNothing, this.hash);
    } catch (e) {
      throw new WgProtocolError('DECRYPT', 'response encrypted_nothing failed: ' + caughtMessage(e as Error)) as Error;
    }
    wipe(keyEmpty);
    if (empty.length !== 0) {
      throw new WgProtocolError('DECRYPT', 'response encrypted_nothing must be empty') as Error;
    }
    this.hash = blake2s256(concatBytes(this.hash, encNothing));
    // 传输密钥：KDF2(ck_final, 空 ikm)，发起端 [0]=send / [1]=recv
    const kt: Uint8Array[] = kdf2Blake2s(this.chainingKey, EMPTY_BYTES);
    this.sendKey = kt[0];
    this.recvKey = kt[1];

    // 中间密钥材料清零（R8 清密钥义务）
    wipe(this.ephemeralPrivate);
    wipe(this.chainingKey);
    wipe(this.hash);
    this.ephemeralPrivate = new Uint8Array(0);
    this.chainingKey = new Uint8Array(0);
    this.hash = new Uint8Array(0);
    this.state = WgHandshakeState.Complete;
  }

  /** 会话密钥产出；consumeResponse 成功后调用一次，否则 WgProtocolError('STATE')。 */
  public finish(): WgHandshakeOutput {
    if (this.state !== WgHandshakeState.Complete) {
      throw new WgProtocolError('STATE', 'finish requires successful consumeResponse') as Error;
    }
    const out: WgHandshakeOutput = {
      localIndex: this.senderIndex,
      peerIndex: this.peerIndex,
      sendKey: this.sendKey.slice(),
      recvKey: this.recvKey.slice(),
    };
    this.state = WgHandshakeState.Finished;
    return out;
  }

  /** mac2 段取值：持有 cookie 时按公式计算，否则 16B 全零。 */
  private computeMac2Field(msgUptoMac2: Uint8Array): Uint8Array {
    if (this.cookie.length === WG_MAC_LEN_BYTES) {
      return wgComputeMac2(this.cookie, msgUptoMac2);
    }
    return new Uint8Array(WG_MAC_LEN_BYTES);
  }
}

// ---------------------------------------------------------------------------
// 响应端（Responder）
// ---------------------------------------------------------------------------

/**
 * 握手响应端。生命周期：consumeInitiation → createResponse → finish（各一次）。
 */
export class WgHandshakeResponder {
  private staticPrivate: Uint8Array;
  private staticPublic: Uint8Array;
  private rng: Rng;
  private clock: Clock;
  private state: number = WgHandshakeState.Idle;
  private senderIndex: number = 0;
  private peerIndex: number = 0;
  private peerStaticPublic: Uint8Array = new Uint8Array(0);
  private peerEphemeral: Uint8Array = new Uint8Array(0);
  private chainingKey: Uint8Array = new Uint8Array(0);
  private hash: Uint8Array = new Uint8Array(0);
  private sendKey: Uint8Array = new Uint8Array(0);
  private recvKey: Uint8Array = new Uint8Array(0);
  /** 【骨架】本端发往对端的最近 cookie（二期 Cookie Reply 生成时写入）。 */
  private lastCookieSent: Uint8Array = new Uint8Array(0);

  public constructor(staticPrivate: Uint8Array, rng: Rng, clock: Clock) {
    assertKeyLen(staticPrivate, 'static private key');
    this.staticPrivate = staticPrivate.slice();
    this.staticPublic = x25519PublicKeyFromPrivate(staticPrivate);
    this.rng = rng;
    this.clock = clock;
  }

  /** 【骨架】响应端登记"已发给该对端的 cookie"（二期 Cookie Reply 生成时调用）。 */
  public provideCookieSent(cookie: Uint8Array): void {
    if (cookie.length !== WG_MAC_LEN_BYTES) {
      throw new Error(
        'provideCookieSent: cookie must be ' +
          String(WG_MAC_LEN_BYTES) +
          ' bytes, got ' +
          String(cookie.length),
      );
    }
    this.lastCookieSent = cookie.slice();
  }

  /**
   * 消费 148B Handshake Initiation，返回对端静态公钥与 TAI64N 时间戳。
   * 失败抛 WgProtocolError（'BAD_TYPE'|'BAD_LEN'|'MAC'|'ZERO_DH'|'STATE'|'DECRYPT'）。
   */
  public consumeInitiation(msg: Uint8Array): WgInitiationInfo {
    if (this.state !== WgHandshakeState.Idle) {
      throw new WgProtocolError('STATE', 'consumeInitiation requires fresh responder state') as Error;
    }
    // 校验序：先读类型（类型非法 → BAD_TYPE，含一期不解析的 Cookie Reply），
    // 再做精确长度校验（类型合法但长度不符 → BAD_LEN）
    if (msg.length < 4) {
      throw new WgProtocolError(
        'BAD_LEN',
        'handshake initiation must be at least 4 bytes, got ' + String(msg.length),
      ) as Error;
    }
    const r: ByteReader = new ByteReader(msg);
    const msgType: number = r.readU32le();
    if (msgType !== WgMessageType.HandshakeInitiation) {
      throw new WgProtocolError(
        'BAD_TYPE',
        'expected handshake initiation (1), got ' + String(msgType),
      ) as Error;
    }
    if (msg.length !== WG_INITIATION_LEN_BYTES) {
      throw new WgProtocolError(
        'BAD_LEN',
        'handshake initiation must be ' +
          String(WG_INITIATION_LEN_BYTES) +
          ' bytes, got ' +
          String(msg.length),
      ) as Error;
    }
    verifyMac1(msg, this.staticPublic);
    const macs: WgMacFields = readMacs(msg);
    // mac2 非零时用"已发给该对端的 cookie"重算 mac2 比对（骨架：无登记则拒绝）
    const expectMac2: Uint8Array | null =
      this.lastCookieSent.length === WG_MAC_LEN_BYTES
        ? wgComputeMac2(
            this.lastCookieSent,
            msg.subarray(0, msg.length - WG_MAC_LEN_BYTES),
          )
        : null;
    wgVerifyMac2Field(macs.mac2, expectMac2);
    const initiatorIndex: number = r.readU32le();
    const ePub: Uint8Array = r.readBytes(32);
    const encStatic: Uint8Array = r.readBytes(WG_ENCRYPTED_STATIC_LEN_BYTES);
    const encTimestamp: Uint8Array = r.readBytes(WG_ENCRYPTED_TIMESTAMP_LEN_BYTES);

    // 链键/哈希初始化（接收方 = 本端静态公钥）
    let ck: Uint8Array = blake2s256(CONSTRUCTION_BYTES);
    let h: Uint8Array = blake2s256(
      concatBytes(blake2s256(concatBytes(ck, IDENTIFIER_BYTES)), this.staticPublic),
    );
    // -> e
    ck = kdf1(ck, ePub);
    h = blake2s256(concatBytes(h, ePub));
    // -> es
    const esShared: Uint8Array = dhOrZero(this.staticPrivate, ePub);
    const kEs: Uint8Array[] = kdf2Blake2s(ck, esShared);
    ck = kEs[0];
    const keyEs: Uint8Array = kEs[1];
    // -> s
    let initiatorStatic: Uint8Array;
    try {
      initiatorStatic = aeadOpen(keyEs, ZERO_NONCE, encStatic, h);
    } catch (e) {
      throw new WgProtocolError('DECRYPT', 'initiation encrypted_static failed: ' + caughtMessage(e as Error)) as Error;
    }
    h = blake2s256(concatBytes(h, encStatic));
    wipe(keyEs);
    // -> ss（psk2 槽位：DH(s_r, s_i) —— 与发起端对称）
    const ssShared: Uint8Array = dhOrZero(this.staticPrivate, initiatorStatic);
    const kSs: Uint8Array[] = kdf2Blake2s(ck, ssShared);
    ck = kSs[0];
    const keySs: Uint8Array = kSs[1];
    wipe(esShared);
    wipe(ssShared);
    // -> ts
    let timestamp: Uint8Array;
    try {
      timestamp = aeadOpen(keySs, ZERO_NONCE, encTimestamp, h);
    } catch (e) {
      throw new WgProtocolError(
        'DECRYPT',
        'initiation encrypted_timestamp failed: ' + caughtMessage(e as Error),
      ) as Error;
    }
    wipe(keySs);
    if (timestamp.length !== WG_TIMESTAMP_LEN_BYTES) {
      throw new WgProtocolError('BAD_LEN', 'decrypted timestamp must be 12 bytes') as Error;
    }
    h = blake2s256(concatBytes(h, encTimestamp));

    this.peerIndex = initiatorIndex;
    this.peerEphemeral = ePub;
    this.peerStaticPublic = initiatorStatic;
    this.chainingKey = ck;
    this.hash = h;
    this.state = WgHandshakeState.Awaiting;
    const info: WgInitiationInfo = {
      senderIndex: initiatorIndex,
      peerStaticPublic: initiatorStatic.slice(),
      timestamp: timestamp.slice(),
    };
    return info;
  }

  /**
   * 构造 92B Handshake Response（新数组）；须在 consumeInitiation 成功后调用。
   * rng 消耗顺序：32B 临时私钥 → 4B 本端会话索引。
   */
  public createResponse(): Uint8Array {
    if (this.state !== WgHandshakeState.Awaiting) {
      throw new WgProtocolError('STATE', 'createResponse requires successful consumeInitiation') as Error;
    }
    // <- e（临时密钥对）+ 会话索引（文档化的 rng 消耗顺序）
    const ePriv: Uint8Array = new Uint8Array(32);
    this.rng.randomBytes(ePriv);
    const ePub: Uint8Array = x25519PublicKeyFromPrivate(ePriv);
    const idxBytes: Uint8Array = new Uint8Array(4);
    this.rng.randomBytes(idxBytes);
    this.senderIndex =
      (idxBytes[0] | (idxBytes[1] << 8) | (idxBytes[2] << 16) | (idxBytes[3] << 24)) >>> 0;

    // <- e
    this.hash = blake2s256(concatBytes(this.hash, ePub));
    this.chainingKey = kdf1(this.chainingKey, ePub);
    // <- ee
    const eeShared: Uint8Array = dhOrZero(ePriv, this.peerEphemeral);
    this.chainingKey = kdf1(this.chainingKey, eeShared);
    wipe(eeShared);
    // <- se
    const seShared: Uint8Array = dhOrZero(ePriv, this.peerStaticPublic);
    this.chainingKey = kdf1(this.chainingKey, seShared);
    wipe(seShared);
    // <- psk（全零）→ tau + key
    const k3: Uint8Array[] = kdf3Blake2s(this.chainingKey, ZERO_PSK);
    this.chainingKey = k3[0];
    const tau: Uint8Array = k3[1];
    const keyEmpty: Uint8Array = k3[2];
    this.hash = blake2s256(concatBytes(this.hash, tau));
    // <- [empty]
    const encNothing: Uint8Array = aeadSeal(keyEmpty, ZERO_NONCE, EMPTY_BYTES, this.hash);
    this.hash = blake2s256(concatBytes(this.hash, encNothing));
    wipe(keyEmpty);
    // 传输密钥：KDF2(ck_final, 空 ikm)，响应端 [0]=recv / [1]=send
    const kt: Uint8Array[] = kdf2Blake2s(this.chainingKey, EMPTY_BYTES);
    this.recvKey = kt[0];
    this.sendKey = kt[1];

    // 组包：mac1 键由对端（发起方）静态公钥派生；mac2 恒全零（见类注释）
    const w: ByteWriter = new ByteWriter(WG_RESPONSE_LEN_BYTES);
    w.writeU32le(WgMessageType.HandshakeResponse);
    w.writeU32le(this.senderIndex);
    w.writeU32le(this.peerIndex);
    w.writeBytes(ePub);
    w.writeBytes(encNothing);
    const mac1: Uint8Array = wgComputeMac1(wgMac1Key(this.peerStaticPublic), w.toUint8Array());
    w.writeBytes(mac1);
    w.writeBytes(new Uint8Array(WG_MAC_LEN_BYTES));
    const msg: Uint8Array = w.toUint8Array();

    // 中间密钥材料清零（R8 清密钥义务）
    wipe(ePriv);
    wipe(this.chainingKey);
    wipe(this.hash);
    this.peerEphemeral = new Uint8Array(0);
    this.chainingKey = new Uint8Array(0);
    this.hash = new Uint8Array(0);
    this.state = WgHandshakeState.Complete;
    return msg;
  }

  /** 会话密钥产出；createResponse 成功后调用一次，否则 WgProtocolError('STATE')。 */
  public finish(): WgHandshakeOutput {
    if (this.state !== WgHandshakeState.Complete) {
      throw new WgProtocolError('STATE', 'finish requires successful createResponse') as Error;
    }
    const out: WgHandshakeOutput = {
      localIndex: this.senderIndex,
      peerIndex: this.peerIndex,
      sendKey: this.sendKey.slice(),
      recvKey: this.recvKey.slice(),
    };
    this.state = WgHandshakeState.Finished;
    return out;
  }
}

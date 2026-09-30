/**
 * Noise IK 握手（架构契约 §6 handshake.ts）—— ts2021 控制面会话层。
 *
 * 协议：Noise_IK_25519_ChaChaPoly_BLAKE2s（NOISE_PROTOCOL_NAME，与真实 tailscale
 * controlbase 的 protocolName 常量逐字一致；33 字节 → 初始化走 HASH 分支）。
 * 消息序列（IK 模式）：
 *   预消息：`<- s`（发起方预先持有响应方静态公钥，双方在 prologue 之后 MixHash 它）
 *   msg A：`-> e, es, s, ss` —— 32B 发起方临时公钥 || 48B enc(发起方静态公钥) || enc(载荷)
 *   msg B：`<- e, ee, se`   —— 32B 响应方临时公钥 || enc(载荷)
 * 即：msg A 固定头 80B（32B e + 48B enc(s)），msg B 固定头 32B + 载荷密文。
 *
 * 与 Noise 规范/tailscale controlbase 的逐项对齐（均为本次实读证据）：
 * - 预消息 `<- s`：prologue 之后 MixHash(响应方静态公钥) —— tailscale controlbase
 *   ClientDeferred（control/controlbase/handshake.go：`// <- s / MixHash(controlKey)`）、
 *   flynn/noise state.go（MixHash(prologue) 后遍历 pre-message）与 Noise 规范 §5.3
 *   Initialize 三方一致；
 * - DH 令牌走 SymmetricState.mixKey（双输出 HKDF：ck=out1、密钥=out2、无 temp_h 混入）
 *   —— controlbase MixDH 口味，理由与向量验证见 symmetric.ts 头注与
 *   test/external-vector.test.ts；
 * - 发起方 es/ss 用其对端静态公钥做 DH；响应方 es = DH(自身静态私钥, 对端临时公钥)、
 *   ss = DH(自身静态私钥, 解出的对端静态公钥)；msg B 的 ee = 双方临时对、
 *   se = DH(响应方临时私钥, 发起方静态公钥) —— 与 controlbase 逐令牌一致；
 * - 握手加密块：ChaChaPoly、全零 nonce（每令牌一次性密钥）、AAD = 当前 h，
 *   成功后 h = MixHash(密文)（controlbase EncryptAndHash/DecryptAndHash 同型）；
 * - split()：(k1, k2) = HKDF(ck, 空, 2)；k1 = initiator→responder、k2 = 反向
 *   （controlbase：client tx=c1/rx=c2，server 镜像）；
 * - prologue 不一致/静态密钥不匹配都表现为首个加密块 AEAD 认证失败 → DECRYPT
 *   （架构契约 §6.1 失败路径表）。
 */

import { KEY_LEN_BYTES, utf8Encode, type Rng } from '@ohos-tailscale/common';
import { x25519, x25519GenerateKeyPair, x25519PublicKeyFromPrivate, wipe, type CryptoKeyPair } from '@ohos-tailscale/crypto';
import { NoiseError } from './errors.ts';
import { SymmetricState } from './symmetric.ts';
import { NoiseTransportCipher } from './transport.ts';

/** ts2021/controlbase Noise 协议名（架构契约 §6；33 字节 → 初始化时 h = HASH(name)）。 */
export const NOISE_PROTOCOL_NAME: string = 'Noise_IK_25519_ChaChaPoly_BLAKE2s';

const EPHEMERAL_LEN: number = KEY_LEN_BYTES; // 32B 临时公钥
const TAG_LEN: number = 16; // AEAD tag
const ENC_STATIC_LEN: number = KEY_LEN_BYTES + TAG_LEN; // 48B enc(静态公钥)
const MSG_A_MIN_LEN: number = EPHEMERAL_LEN + ENC_STATIC_LEN + TAG_LEN; // 96B（空载荷）
const MSG_B_MIN_LEN: number = EPHEMERAL_LEN + TAG_LEN; // 48B（空载荷）

/** readMessageA 的返回：对端握手载荷（明文）+ 对端静态公钥（仅 responder 侧可得）。 */
export interface NoiseIkPayload {
  payload: Uint8Array;
  remoteStatic: Uint8Array;
}

/** split() 的返回：send 为本端→对端方向，recv 为对端→本端方向。 */
export interface NoiseTransportPair {
  send: NoiseTransportCipher;
  recv: NoiseTransportCipher;
}

/** 拼接若干字节数组为新数组（内部工具；输入不被修改）。 */
function concatBytes(parts: Uint8Array[]): Uint8Array {
  let total: number = 0;
  for (const p of parts) {
    total += p.length;
  }
  const out: Uint8Array = new Uint8Array(total);
  let off: number = 0;
  for (const p of parts) {
    out.set(p, off);
    off += p.length;
  }
  return out;
}

export class NoiseIkInitiator {
  private sym: SymmetricState;
  private rng: Rng;
  private staticPrivate: Uint8Array;
  private staticPublic: Uint8Array;
  private remoteStatic: Uint8Array;
  private ephemeralPrivate: Uint8Array = new Uint8Array(0);
  private messageAWritten: boolean = false;
  private messageBRead: boolean = false;
  private sessionSplit: boolean = false;

  public constructor(prologue: Uint8Array, staticPrivate: Uint8Array, remoteStatic: Uint8Array, rng: Rng) {
    if (staticPrivate.length !== KEY_LEN_BYTES) {
      throw new NoiseError(
        'STATE',
        'noise: staticPrivate must be ' + String(KEY_LEN_BYTES) + ' bytes, got ' + String(staticPrivate.length),
      ) as Error;
    }
    if (remoteStatic.length !== KEY_LEN_BYTES) {
      throw new NoiseError(
        'STATE',
        'noise: remoteStatic must be ' + String(KEY_LEN_BYTES) + ' bytes, got ' + String(remoteStatic.length),
      ) as Error;
    }
    this.sym = new SymmetricState(utf8Encode(NOISE_PROTOCOL_NAME), prologue);
    // 预消息 `<- s`：发起方把响应方静态公钥混入 h（prologue 之后、msg A 之前）。
    this.sym.mixHash(remoteStatic);
    this.rng = rng;
    this.staticPrivate = staticPrivate.slice();
    this.staticPublic = x25519PublicKeyFromPrivate(this.staticPrivate);
    this.remoteStatic = remoteStatic.slice();
  }

  /**
   * 写 msg A：`-> e, es, s, ss`。返回 32B e || 48B enc(s) || enc(payload) 新数组
   * （80B 固定头 + 载荷密文，载荷自带 16B tag）。
   */
  public writeMessageA(payload: Uint8Array): Uint8Array {
    if (this.messageAWritten) {
      throw new NoiseError('STATE', 'noise: message A already written') as Error;
    }
    const eph: CryptoKeyPair = x25519GenerateKeyPair(this.rng);
    this.ephemeralPrivate = eph.privateKey;

    this.sym.mixHash(eph.publicKey); // e
    const tempEs: Uint8Array = this.sym.mixKey(x25519(eph.privateKey, this.remoteStatic)); // es
    const encStatic: Uint8Array = this.sym.encryptAndHash(tempEs, this.staticPublic); // s
    const tempSs: Uint8Array = this.sym.mixKey(x25519(this.staticPrivate, this.remoteStatic)); // ss
    const encPayload: Uint8Array = this.sym.encryptAndHash(tempSs, payload);

    this.messageAWritten = true;
    return concatBytes([eph.publicKey, encStatic, encPayload]);
  }

  /** 读 msg B：`<- e, ee, se`。返回对端载荷明文（新数组）；失败抛 NoiseError('DECRYPT')。 */
  public readMessageB(msg: Uint8Array): Uint8Array {
    if (!this.messageAWritten) {
      throw new NoiseError('STATE', 'noise: writeMessageA must run before readMessageB') as Error;
    }
    if (this.messageBRead) {
      throw new NoiseError('STATE', 'noise: message B already read') as Error;
    }
    if (msg.length < MSG_B_MIN_LEN) {
      throw new NoiseError(
        'PROLOGUE',
        'noise: message B too short: ' + String(msg.length) + ' < ' + String(MSG_B_MIN_LEN),
      ) as Error;
    }
    const re: Uint8Array = msg.slice(0, EPHEMERAL_LEN);
    this.sym.mixHash(re); // e（对端）
    const tempEe: Uint8Array = this.sym.mixKey(x25519(this.ephemeralPrivate, re)); // ee
    const tempSe: Uint8Array = this.sym.mixKey(x25519(this.staticPrivate, re)); // se
    const payload: Uint8Array = this.sym.decryptAndHash(tempSe, msg.slice(EPHEMERAL_LEN));
    wipe(this.ephemeralPrivate);
    this.ephemeralPrivate = new Uint8Array(0);
    this.messageBRead = true;
    return payload;
  }

  /**
   * 派生传输态两端 CipherState（msg B 读取成功后调用；早调用/重复调用抛
   * NoiseError('STATE')）。send 绑 k1（本端→对端），recv 绑 k2。
   */
  public split(): NoiseTransportPair {
    if (!this.messageBRead) {
      throw new NoiseError('STATE', 'noise: split() before handshake completed') as Error;
    }
    if (this.sessionSplit) {
      throw new NoiseError('STATE', 'noise: split() already called') as Error;
    }
    this.sessionSplit = true;
    const keys: Uint8Array[] = this.sym.splitKeys();
    const send: NoiseTransportCipher = new NoiseTransportCipher(keys[0]);
    const recv: NoiseTransportCipher = new NoiseTransportCipher(keys[1]);
    const pair: NoiseTransportPair = { send: send, recv: recv };
    return pair;
  }
}

export class NoiseIkResponder {
  private sym: SymmetricState;
  private rng: Rng;
  private staticPrivate: Uint8Array;
  private staticPublic: Uint8Array;
  private remoteStatic: Uint8Array = new Uint8Array(0);
  private remoteEphemeral: Uint8Array = new Uint8Array(0);
  private messageARead: boolean = false;
  private messageBWritten: boolean = false;
  private sessionSplit: boolean = false;

  public constructor(prologue: Uint8Array, staticPrivate: Uint8Array, rng: Rng) {
    if (staticPrivate.length !== KEY_LEN_BYTES) {
      throw new NoiseError(
        'STATE',
        'noise: staticPrivate must be ' + String(KEY_LEN_BYTES) + ' bytes, got ' + String(staticPrivate.length),
      ) as Error;
    }
    this.sym = new SymmetricState(utf8Encode(NOISE_PROTOCOL_NAME), prologue);
    this.rng = rng;
    this.staticPrivate = staticPrivate.slice();
    this.staticPublic = x25519PublicKeyFromPrivate(this.staticPrivate);
    // 预消息 `<- s`：响应方把自己静态公钥混入 h（与发起方混入的 remoteStatic 同值）。
    this.sym.mixHash(this.staticPublic);
  }

  /**
   * 读 msg A。返回对端载荷与对端静态公钥（remoteStatic 为独立拷贝，R8）；
   * 失败抛 NoiseError('DECRYPT'|'PROLOGUE'|'STATE')。
   */
  public readMessageA(msg: Uint8Array): NoiseIkPayload {
    if (this.messageARead) {
      throw new NoiseError('STATE', 'noise: message A already read') as Error;
    }
    if (msg.length < MSG_A_MIN_LEN) {
      throw new NoiseError(
        'PROLOGUE',
        'noise: message A too short: ' + String(msg.length) + ' < ' + String(MSG_A_MIN_LEN),
      ) as Error;
    }
    const re: Uint8Array = msg.slice(0, EPHEMERAL_LEN);
    this.sym.mixHash(re); // e（对端）
    this.remoteEphemeral = re;
    const tempEs: Uint8Array = this.sym.mixKey(x25519(this.staticPrivate, re)); // es
    const encStatic: Uint8Array = msg.slice(EPHEMERAL_LEN, EPHEMERAL_LEN + ENC_STATIC_LEN);
    const peerStatic: Uint8Array = this.sym.decryptAndHash(tempEs, encStatic); // s
    const tempSs: Uint8Array = this.sym.mixKey(x25519(this.staticPrivate, peerStatic)); // ss
    const payload: Uint8Array = this.sym.decryptAndHash(tempSs, msg.slice(EPHEMERAL_LEN + ENC_STATIC_LEN));

    this.remoteStatic = peerStatic.slice();
    this.messageARead = true;
    const result: NoiseIkPayload = { payload: payload, remoteStatic: peerStatic };
    return result;
  }

  /** 写 msg B：`<- e, ee, se`。返回 32B e || enc(payload) 新数组。 */
  public writeMessageB(payload: Uint8Array): Uint8Array {
    if (!this.messageARead) {
      throw new NoiseError('STATE', 'noise: readMessageA must run before writeMessageB') as Error;
    }
    if (this.messageBWritten) {
      throw new NoiseError('STATE', 'noise: message B already written') as Error;
    }
    const eph: CryptoKeyPair = x25519GenerateKeyPair(this.rng);
    this.sym.mixHash(eph.publicKey); // e
    const tempEe: Uint8Array = this.sym.mixKey(x25519(eph.privateKey, this.remoteEphemeral)); // ee
    const tempSe: Uint8Array = this.sym.mixKey(x25519(eph.privateKey, this.remoteStatic)); // se
    const encPayload: Uint8Array = this.sym.encryptAndHash(tempSe, payload);
    this.messageBWritten = true;
    return concatBytes([eph.publicKey, encPayload]);
  }

  /** 派生传输态（writeMessageB 成功后调用）。send 绑 k2（本端→对端），recv 绑 k1。 */
  public split(): NoiseTransportPair {
    if (!this.messageBWritten) {
      throw new NoiseError('STATE', 'noise: split() before handshake completed') as Error;
    }
    if (this.sessionSplit) {
      throw new NoiseError('STATE', 'noise: split() already called') as Error;
    }
    this.sessionSplit = true;
    const keys: Uint8Array[] = this.sym.splitKeys();
    const send: NoiseTransportCipher = new NoiseTransportCipher(keys[1]);
    const recv: NoiseTransportCipher = new NoiseTransportCipher(keys[0]);
    const pair: NoiseTransportPair = { send: send, recv: recv };
    return pair;
  }
}

/**
 * Cookie 机制骨架（白皮书 5.4.4 Cookie MACs / 5.4.7 Under Load）。
 *
 * 公式以白皮书原文（wireguard.com/papers/wireguard.pdf，2026-09-28 抓取并
 * 解出正文）与 wireguard-go device/cookie.go 双重核对：
 * - mac1 = Mac(Hash(LABEL_MAC1 || 接收方静态公钥), msg[0 : offsetof(mac1)])
 *   （白皮书 §5.4.4；wireguard-go CookieGenerator.Init：WGLabelMAC1）
 * - mac2 = Mac(L_m, msg[0 : offsetof(mac2)])，L_m = 最近收到的 cookie 本身
 *   （白皮书 §5.4.4："msg.mac2 := Mac(L_m, msg)"；wireguard-go AddMacs：
 *   blake2s.New128(st.mac2.cookie)）—— 未持有新近 cookie 时 mac2 = 16B 全零
 * - 响应端 cookie 值（二期接入 Cookie Reply）：τ = Mac(R_m, A_m←)，
 *   R_m = 每 2 分钟轮换的 32B 随机秘密，A_m← = 对端源 IP‖端口
 *   （白皮书 §5.4.7；wireguard-go cookie.go:24 secret [blake2s.Size]byte）
 * - Label-Cookie 的真实用途 = Cookie Reply 加密键 Hash(LABEL_COOKIE||S_pub)
 *   （§5.4.7 Xaead 的键；wireguard-go mac2.encryptionKey），不是 mac2 的键
 * 其中 Mac = keyed-BLAKE2s 截断前 16B，Hash = 无键 BLAKE2s-256。
 *
 * 一期边界（architecture.md §5）：不生成/不解析 Cookie Reply（type=3 一律
 * WgProtocolError('BAD_TYPE')）；本模块只做"机制骨架"，负载判定与响应端
 * cookie 派发留待二期接入。
 */

import { blake2s256, blake2s256Keyed } from '@ohos-tailscale/crypto';
import { hexEncode, KEY_LEN_BYTES, utf8Encode } from '@ohos-tailscale/common';
import { WG_MAC_LEN_BYTES } from './constants.ts';
import { WgProtocolError } from './errors.ts';

/** 白皮书 LABEL_MAC1 = "mac1----"（8B）。 */
const LABEL_MAC1: Uint8Array = utf8Encode('mac1----');

/** 白皮书 LABEL_COOKIE = "cookie--"（8B）。 */
const LABEL_COOKIE: Uint8Array = utf8Encode('cookie--');

/** 拼接两个数组为新数组。 */
function concatBytes(a: Uint8Array, b: Uint8Array): Uint8Array {
  const out: Uint8Array = new Uint8Array(a.length + b.length);
  out.set(a, 0);
  out.set(b, a.length);
  return out;
}

/**
 * 派生"给该对端发报文时计算 mac1"的 32B 键：
 * HASH(LABEL_MAC1 || 接收方（对端）静态公钥)。
 * 入参须 32B，不符抛 Error；返回 32B 新数组。
 */
export function wgMac1Key(peerStaticPublic: Uint8Array): Uint8Array {
  if (peerStaticPublic.length !== KEY_LEN_BYTES) {
    throw new Error(
      'wgMac1Key: peer static public must be ' +
        String(KEY_LEN_BYTES) +
        ' bytes, got ' +
        String(peerStaticPublic.length),
    );
  }
  return blake2s256(concatBytes(LABEL_MAC1, peerStaticPublic));
}

/**
 * 派生 Cookie Reply 的加密键（二期 XAEAD 消费）：
 * HASH(LABEL_COOKIE || 本端静态公钥)。
 * 入参须 32B，不符抛 Error；返回 32B 新数组。
 */
export function wgCookieKey(localStaticPublic: Uint8Array): Uint8Array {
  if (localStaticPublic.length !== KEY_LEN_BYTES) {
    throw new Error(
      'wgCookieKey: local static public must be ' +
        String(KEY_LEN_BYTES) +
        ' bytes, got ' +
        String(localStaticPublic.length),
    );
  }
  return blake2s256(concatBytes(LABEL_COOKIE, localStaticPublic));
}

/**
 * mac2 的 MAC 键 = 最近收到的 cookie 本身（白皮书 §5.4.4：Mac(L_m, msg)；
 * wireguard-go AddMacs：blake2s.New128(st.mac2.cookie)）。
 * 本函数只做长度校验并返回独立拷贝（BLAKE2s 键长 1..32B，16B 合法）。
 */
export function wgMac2KeyFromCookie(cookie: Uint8Array): Uint8Array {
  if (cookie.length !== WG_MAC_LEN_BYTES) {
    throw new Error(
      'wgMac2KeyFromCookie: cookie must be ' +
        String(WG_MAC_LEN_BYTES) +
        ' bytes, got ' +
        String(cookie.length),
    );
  }
  return cookie.slice();
}

/**
 * 计算 mac1（16B 新数组）：keyed-BLAKE2s(mac1Key, msg 无 macs 段) 截断 16B。
 * mac1Key 来自 wgMac1Key；msgNoMacs 为报文从第 0 字节到 mac1 字段之前的所有字节。
 */
export function wgComputeMac1(mac1Key: Uint8Array, msgNoMacs: Uint8Array): Uint8Array {
  return blake2s256Keyed(mac1Key, msgNoMacs).slice(0, WG_MAC_LEN_BYTES);
}

/**
 * 计算 mac2（16B 新数组）：keyed-BLAKE2s(mac2Key, msg 到 mac2 字段之前) 截断 16B。
 * mac2Key = 最近收到的 cookie 本身（wgMac2KeyFromCookie）；cookie 缺失时
 * 调用方写全零，不进本函数。
 */
export function wgComputeMac2(mac2Key: Uint8Array, msgUptoMac2: Uint8Array): Uint8Array {
  return blake2s256Keyed(mac2Key, msgUptoMac2).slice(0, WG_MAC_LEN_BYTES);
}

/**
 * 【骨架】响应端负载 cookie 值（16B 新数组）：
 * τ = keyed-BLAKE2s(R_m, A_m←) 截断 16B —— R_m 为每 2 分钟轮换的 32B 随机
 * 秘密（调用方经 Rng 注入并负责轮换），A_m← 为对端源地址字节
 * （白皮书 §5.4.7；wireguard-go cookie.go:98 以源地址为输入）。
 * srcAddr 的确切编组（IP 字节 + 端口序）属传输层细节，二期随 Cookie Reply
 * 一起与上游核对。secretRm 须 32B、srcAddr 1..32B，不符抛 Error。
 */
export function wgComputeCookie(secretRm: Uint8Array, srcAddr: Uint8Array): Uint8Array {
  if (secretRm.length !== 32) {
    throw new Error('wgComputeCookie: secret must be 32 bytes, got ' + String(secretRm.length));
  }
  if (srcAddr.length < 1 || srcAddr.length > 32) {
    throw new Error(
      'wgComputeCookie: source address must be 1..32 bytes, got ' + String(srcAddr.length),
    );
  }
  return blake2s256Keyed(secretRm, srcAddr).slice(0, WG_MAC_LEN_BYTES);
}

/** 缓存条目（A2：纯字段 interface；cookie 为独立拷贝）。 */
interface WgCookieEntry {
  cookie: Uint8Array;
  updatedMs: number;
}

/**
 * 按对端 mac1 键缓存的"最近 cookie"存储（骨架）。
 *
 * 发起端用法：收到 Cookie Reply 后 update(responderMac1Key, cookie, now)，
 * 之后发握手/数据时用 cookieFor 取值计算 mac2；
 * 响应端用法：发送 Cookie Reply 后 update(initiatorMac1Key, cookie, now)，
 * 之后用它校验该对端报文里的 mac2。两类语义机制相同，故共用本类。
 */
export class WgCookieCache {
  private entries: Map<string, WgCookieEntry> = new Map();

  /** 记录/刷新某 mac1 键下的最近 cookie（深拷贝存储，Map 键 = mac1 键 hex）。 */
  public update(mac1Key: Uint8Array, cookie: Uint8Array, nowMs: number): void {
    if (mac1Key.length !== KEY_LEN_BYTES) {
      throw new Error('WgCookieCache.update: mac1 key must be 32 bytes');
    }
    if (cookie.length !== WG_MAC_LEN_BYTES) {
      throw new Error('WgCookieCache.update: cookie must be 16 bytes');
    }
    const entry: WgCookieEntry = { cookie: cookie.slice(), updatedMs: nowMs };
    this.entries.set(hexEncode(mac1Key), entry);
  }

  /** 取某 mac1 键下的最近 cookie；无则 null。返回独立拷贝。 */
  public cookieFor(mac1Key: Uint8Array): Uint8Array | null {
    const entry: WgCookieEntry | undefined = this.entries.get(hexEncode(mac1Key));
    if (entry === undefined) {
      return null;
    }
    return entry.cookie.slice();
  }

  /** 缓存条目数。 */
  public size(): number {
    return this.entries.size;
  }

  /** 清除 updatedMs 早于 nowMs - maxAgeMs 的条目，返回清除条数（骨架：cookie 有效期由调用方裁定）。 */
  public dropStale(nowMs: number, maxAgeMs: number): number {
    let removed: number = 0;
    const keys: string[] = [];
    this.entries.forEach((entry: WgCookieEntry, key: string): void => {
      if (entry.updatedMs < nowMs - maxAgeMs) {
        keys.push(key);
      }
    });
    for (const key of keys) {
      this.entries.delete(key);
      removed += 1;
    }
    return removed;
  }
}

/**
 * 校验收到的 mac2 字段（消费侧骨架）：
 * mac2 全零 → 通过（对端未持有 cookie，常态）；
 * 非零但 expectedMac2 未提供或比对失败 → WgProtocolError('MAC')。
 */
export function wgVerifyMac2Field(mac2: Uint8Array, expectedMac2: Uint8Array | null): void {
  let allZero: boolean = true;
  for (let i: number = 0; i < mac2.length; i += 1) {
    if (mac2[i] !== 0) {
      allZero = false;
      break;
    }
  }
  if (allZero) {
    return;
  }
  if (expectedMac2 === null) {
    throw new WgProtocolError('MAC', 'mac2 present but no cached cookie to verify against') as Error;
  }
  let diff: number = 0;
  for (let i: number = 0; i < mac2.length; i += 1) {
    diff |= mac2[i] ^ expectedMac2[i];
  }
  if (diff !== 0) {
    throw new WgProtocolError('MAC', 'mac2 mismatch') as Error;
  }
}

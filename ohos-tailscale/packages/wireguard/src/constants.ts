/**
 * WireGuard 报文常量（docs/architecture.md §5.1 布局表 + 白皮书 §5.4）。
 *
 * 布局说明：白皮书中 message_type 为 u8 + reserved_zero[3]，与
 * "type u32le" 在字节层面完全一致（如 initiation 首四字节 01 00 00 00），
 * 故本包统一按 u32le 读写类型字段。
 *
 * 所有整数小端（白皮书语义）；键 32B、TAI64N 12B、Poly1305 标签/MAC 各 16B。
 * 常量集合用 R5 常量对象模式（禁 enum/字面量联合）。
 */

/** 报文类型常量对象（R5 模式）。 */
export interface WgMessageTypeE {
  HandshakeInitiation: number;
  HandshakeResponse: number;
  CookieReply: number;
  TransportData: number;
}

export const WgMessageType: WgMessageTypeE = {
  HandshakeInitiation: 1,
  HandshakeResponse: 2,
  CookieReply: 3,
  TransportData: 4,
};

/** 运行时校验：合法报文类型返回原值，否则 null。 */
export function parseWgMessageType(v: number): number | null {
  if (
    v === WgMessageType.HandshakeInitiation ||
    v === WgMessageType.HandshakeResponse ||
    v === WgMessageType.CookieReply ||
    v === WgMessageType.TransportData
  ) {
    return v;
  }
  return null;
}

/** TAI64N 时间戳长度（8B 秒 BE 带偏移 + 4B 纳秒 BE）。 */
export const WG_TIMESTAMP_LEN_BYTES: number = 12;

/** MAC1 / MAC2 字段长度（keyed-BLAKE2s 截断 16B）。 */
export const WG_MAC_LEN_BYTES: number = 16;

/** macs 段总长（mac1 + mac2）。 */
export const WG_MACS_LEN_BYTES: number = 32;

/** Cookie Reply 的 24B 随机 nonce。 */
export const WG_COOKIE_NONCE_LEN_BYTES: number = 24;

/** AEAD 加密后长度：enc(static) = 32 + 16。 */
export const WG_ENCRYPTED_STATIC_LEN_BYTES: number = 48;

/** AEAD 加密后长度：enc(timestamp) = 12 + 16。 */
export const WG_ENCRYPTED_TIMESTAMP_LEN_BYTES: number = 28;

/** AEAD 加密后长度：enc(empty) = 0 + 16。 */
export const WG_ENCRYPTED_EMPTY_LEN_BYTES: number = 16;

/** Transport Data 报文头（type+sender/reserved、receiver、counter）。 */
export const WG_TRANSPORT_HEADER_LEN_BYTES: number = 16;

/** Handshake Initiation 总长 = 4+4+32+48+28+16+16。 */
export const WG_INITIATION_LEN_BYTES: number = 148;

/** Handshake Response 总长 = 4+4+4+32+16+16+16。 */
export const WG_RESPONSE_LEN_BYTES: number = 92;

/** Cookie Reply 总长 = 4+4+24+32。 */
export const WG_COOKIE_REPLY_LEN_BYTES: number = 64;

/** 反重放滑动窗口位数（白皮书 5.4：REJECT-AFTER... window 2048）。 */
export const WG_REPLAY_WINDOW_BITS: number = 2048;

/** 白皮书协议字符串（5.4）：初始链键/哈希派生用。 */
export const WG_CONSTRUCTION: string = 'Noise_IKpsk2_25519_ChaChaPoly_BLAKE2s';

/** 白皮书协议字符串（5.4）：协议标识符。 */
export const WG_IDENTIFIER: string = 'WireGuard v1 zx2c4 Jason@zx2c4.com';

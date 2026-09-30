/**
 * @ohos-tailscale/wireguard 公开入口（barrel）。
 * 导出面 = docs/architecture.md §5 冻结契约 + §1 要求的 peer 索引表
 * 与 cookie 骨架（cookie 机制骨架/peer 索引表为本模块任务书新增，
 * 其余逐名对应契约，未改签名）。
 */

export {
  WG_CONSTRUCTION,
  WG_IDENTIFIER,
  WG_INITIATION_LEN_BYTES,
  WG_RESPONSE_LEN_BYTES,
  WG_COOKIE_REPLY_LEN_BYTES,
  WG_TRANSPORT_HEADER_LEN_BYTES,
  WG_TIMESTAMP_LEN_BYTES,
  WG_MAC_LEN_BYTES,
  WG_MACS_LEN_BYTES,
  WG_COOKIE_NONCE_LEN_BYTES,
  WG_ENCRYPTED_STATIC_LEN_BYTES,
  WG_ENCRYPTED_TIMESTAMP_LEN_BYTES,
  WG_ENCRYPTED_EMPTY_LEN_BYTES,
  WG_REPLAY_WINDOW_BITS,
  WgMessageType,
  type WgMessageTypeE,
  parseWgMessageType,
} from './constants.ts';

export { WgProtocolError } from './errors.ts';

export { tai64nFromWallMs, tai64nDecode, type Tai64N } from './tai64n.ts';

export {
  wgMac1Key,
  wgCookieKey,
  wgMac2KeyFromCookie,
  wgComputeMac1,
  wgComputeMac2,
  wgComputeCookie,
  wgVerifyMac2Field,
  WgCookieCache,
} from './cookie.ts';

export {
  WgHandshakeInitiator,
  WgHandshakeResponder,
  type WgInitiationInfo,
  type WgHandshakeOutput,
} from './handshake.ts';

export { WgSendSession, WgRecvSession } from './transport.ts';

export { WgPeerTable, type WgSessionEntry } from './peers.ts';

/** Cookie Reply（type=3）：二期收口（2026-10-01 夜班，上游 wireguard-go master 对齐）。 */
export {
  WG_COOKIE_REFRESH_MS,
  WgCookieReplyConsumer,
  WgCookieResponder,
  cookieReplyDecode,
  cookieReplyEncode,
  extractMac1Field,
} from './cookie-reply.ts';
export type { WgCookieReply } from './cookie-reply.ts';

/** 报文分发（type=1/2/3/4 接线）：2026-10-01 夜班第 2 面（上游 receive.go/cookie.go 语义）。 */
export { WgPacketDispatcher } from './dispatch.ts';
export type {
  WgCookieConsumerRoute,
  WgCookieResponderRoute,
  WgDispatchResult,
} from './dispatch.ts';

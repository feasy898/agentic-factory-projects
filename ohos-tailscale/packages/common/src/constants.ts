/**
 * 公共常量（跨 ≥2 个包使用才放这里；包私有常量放各包内）。
 * 数值/字符串常量直接 export const；禁 enum（P1/A34）。
 */

/** Curve25519 / WireGuard / Noise 公私钥长度（字节）。 */
export const KEY_LEN_BYTES: number = 32;

/** ChaCha20-Poly1305 nonce 长度（字节）。 */
export const AEAD_NONCE_LEN_BYTES: number = 12;

/** Poly1305 认证标签长度（字节）。 */
export const AEAD_TAG_LEN_BYTES: number = 16;

/** u64 上界（ByteReader/ByteWriter 与协议计数器共用）。 */
export const MAX_U64: bigint = 18446744073709551615n;

/** WireGuard 默认 UDP 端口（protocol-notes §7：实测节点多用 41641）。 */
export const WG_DEFAULT_PORT: number = 41641;

/** DERP 默认 TLS 端口（protocol-notes §3：缺省 = 443）。 */
export const DERP_DEFAULT_PORT: number = 443;

/** DERP/STUN 默认端口（protocol-notes §3：STUNPort 缺省 = 3478，负值 = 不做 STUN）。 */
export const STUN_DEFAULT_PORT: number = 3478;

/** Tailscale CGNAT IPv4 段（protocol-notes §2.2 实测 100.64.0.0/10）。 */
export const CGNAT_V4_CIDR: string = '100.64.0.0/10';

/** Tailscale ULA IPv6 段（protocol-notes §2.2 实测 fd7a:115c:a1e0::/48）。 */
export const TAILNET_ULA_V6_CIDR: string = 'fd7a:115c:a1e0::/48';

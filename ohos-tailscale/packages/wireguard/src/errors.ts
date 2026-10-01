/**
 * wireguard 包错误类型（R7：throw 只允许 Error 子类实例）。
 *
 * code 取值（docs/architecture.md §5 契约）：
 * - 'BAD_TYPE'  报文类型非法/不支持（含一期不支持解析的 Cookie Reply）
 * - 'BAD_LEN'   报文长度不符
 * - 'MAC'       MAC1/MAC2 校验失败
 * - 'DECRYPT'   AEAD 解密认证失败
 * - 'REPLAY'    传输计数器重放/过旧
 * - 'ZERO_DH'   X25519 输出全零（对端拒绝，白皮书 5.4 要求中止）
 * - 'STATE'     状态机顺序错误或报文与会话不匹配
 */

export class WgProtocolError extends Error {
  public code: string;

  public constructor(code: string, message: string) {
    super(message);
    this.name = 'WgProtocolError';
    this.code = code;
  }
}

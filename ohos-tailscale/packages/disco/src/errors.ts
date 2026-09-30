/**
 * disco 包错误（R7 模式，对齐 derp/control 的错误类形态）。
 *
 * code 集合严格为：
 * - 'SHORT'：密封内报文长度不足以承载对应类型（上游 errShort）；
 * - 'TYPE'：密封内报文类型未知（上游 Parse 的 unknown message type 错误）；
 * - 'RANGE'：键/nonce 等长度校验失败。
 */

export class DiscoError extends Error {
  public code: string;

  constructor(code: string, message: string) {
    super(message);
    this.code = code;
  }
}

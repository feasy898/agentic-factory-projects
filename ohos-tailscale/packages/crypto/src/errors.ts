/**
 * crypto 包错误类型与公开数据载体（架构契约 §4；R7：throw 只允许 Error 子类）。
 */

/**
 * 公开密钥对载体（A2：纯字段 interface，用类型标注的对象字面量构造）。
 * publicKey 与 privateKey 均为 32 字节；两个数组都是独立拷贝，调用方持有后可自由改写。
 */
export interface CryptoKeyPair {
  publicKey: Uint8Array;
  privateKey: Uint8Array;
}

/**
 * crypto 包统一错误。
 * code 取值约定（架构契约 §4）：'AUTH'（AEAD 认证失败）、'RANGE'（入参/出参长度不符）、
 * 'INVALID'（其他非法输入）。本包内部不使用其他取值。
 */
export class CryptoError extends Error {
  public code: string;

  public constructor(code: string, message: string) {
    super(message);
    this.name = 'CryptoError';
    this.code = code;
  }
}

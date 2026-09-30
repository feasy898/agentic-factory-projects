/**
 * noise 包错误类型（架构契约 §6；R7：throw 只允许 Error 子类）。
 *
 * code 取值约定（架构契约 §6 固定的四个取值）：
 * - 'DECRYPT'：AEAD 认证失败（握手消息或传输消息解不开，含密文/tag/AAD 篡改、
 *   对端密钥不匹配、prologue 不一致 —— prologue 已并入 h，错 prologue 表现为首个
 *   加密块认证失败，见架构契约 §6.1 失败路径表）；
 * - 'STATE'：会话生命周期/配置非法（split() 早调用或重复调用、握手消息序错乱、
 *   构造参数长度不符、nonce 空间耗尽）；
 * - 'FRAME'：帧编码/解码错误（frame.ts：超长、截断）；
 * - 'PROLOGUE'：握手消息结构非法（长度不足以容纳固定头/字段，发生在任何解密之前）。
 */
export class NoiseError extends Error {
  public code: string;

  public constructor(code: string, message: string) {
    super(message);
    this.name = 'NoiseError';
    this.code = code;
  }
}

/**
 * control 包错误类型（架构契约 §7.1；R7：throw 只允许 Error 子类）。
 *
 * code 取值（架构契约 §7.1 固定的四个取值）：
 * - 'TLV'：TLV 编解码错误（字段流截断、字段值超长、缺 MsgKind、类型化消息的
 *   字段缺失/重复/值长度不符、Endpoints 条目非法）；
 * - 'HTTP'：注入的 HttpTransport 层错误（transport.send/open reject、非 2xx 状态、
 *   流式响应在解出完整帧之前结束）；
 * - 'NOISE'：Noise 会话错误（dial 的握手 msgB 解密失败、传输帧解密失败）；
 * - 'STATE'：客户端生命周期/配置非法（未 dial 先 send/receive、重复 dial、
 *   close 之后使用、构造参数长度不符）。
 */
export class ControlError extends Error {
  public code: string;

  public constructor(code: string, message: string) {
    super(message);
    this.name = 'ControlError';
    this.code = code;
  }
}

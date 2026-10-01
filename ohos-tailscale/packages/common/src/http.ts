/**
 * HTTP 传输注入接口（P3/U4：核心 src 禁 node:net/http/fetch 等平台 API，一律注入）。
 *
 * 本文件是全仓共享注入接口，公开 API 已冻结（docs/architecture.md §注入接口）。
 * 消费方：control（ts2021 长轮询）；derp 的 TLS 直连帧通道不走本接口
 * （upgrade 型双工连接由 derp 包自定义 Dialer 接口，从 app/ 侧注入）。
 *
 * 约定：
 * - HttpRequest/HttpResponse 是纯字段 interface（A2），实现方用对象字面量构造需显式标注类型；
 * - headers 的 Record 键：请求方向按调用方所写原样发送；响应方向实现方必须全部转为小写键；
 * - Record 取值结果按可空处理（A17：可能 undefined）；
 * - 实现必须支持 http 与 https 两类 URL。
 */

/** 一次 HTTP 请求。body 允许为空数组（GET 等）；headers 不含 Host/Content-Length（由实现补齐）。 */
export interface HttpRequest {
  method: string;
  url: string;
  headers: Record<string, string>;
  body: Uint8Array;
}

/** 已完整缓冲的响应（send 用）。 */
export interface HttpResponse {
  /** 1xx 之后、2xx-5xx 的最终状态码 */
  status: number;
  /** 键一律为小写规范名 */
  headers: Record<string, string>;
  body: Uint8Array;
}

/** 流式响应体（open 用，长轮询/服务端推送）。 */
export interface HttpBodyStream {
  /** 读下一段；流正常结束 resolve null；出错 reject Error。返回的 Uint8Array 归调用方所有。 */
  read(): Promise<Uint8Array | null>;
  /** 关闭底层连接；可重复调用。 */
  close(): void;
}

export interface StreamingHttpResponse {
  status: number;
  /** 键一律为小写规范名 */
  headers: Record<string, string>;
  body: HttpBodyStream;
}

export interface HttpTransport {
  /** 发送请求并缓冲完整响应体（适合短请求）。失败（网络/DNS/TLS/超时）reject Error。 */
  send(request: HttpRequest): Promise<HttpResponse>;
  /** 发送请求并保持响应体流式打开（适合长轮询/服务端推送）。 */
  open(request: HttpRequest): Promise<StreamingHttpResponse>;
}

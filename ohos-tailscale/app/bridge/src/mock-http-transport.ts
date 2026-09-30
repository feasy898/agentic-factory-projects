/**
 * MockHttpTransport —— common 冻结注入接口 HttpTransport 的壳侧确定性 mock 实现。
 *
 * 定位（worker-A 纯 TS 推进面，见 docs/build-feasibility-linux.md §4）：
 * 壳工程无法编译（商业 SDK/登录墙），先把「app/ 侧注入层」的形状用 Node 可跑的 mock
 * 钉死并测试，真机实现（@ohos.net.http 包装）落地时替换本文件即可——接口面不变（D4/R2：
 * 平台实现放 app/ 侧，核心库零平台依赖）。
 *
 * 能力：
 * - 路由表脚本化：method + urlSuffix 匹配，handler 返回缓冲响应；
 * - open() 流式：openChunks 队列按序吐出（长轮询/服务端推送形态）；
 * - 全量请求留痕 requests（供测试断言，如 authKey 明文不落传输）；
 * - 无匹配路由 reject（fail-fast，防测试里静默走过场）。
 * 风格遵循 docs/arkts-constraints.md（显式类型/箭头函数常量/常量对象替代 enum）。
 */

import {
  type HttpBodyStream,
  type HttpRequest,
  type HttpResponse,
  type HttpTransport,
  type StreamingHttpResponse,
} from '@ohos-tailscale/common';

/** 脚本化流式响应体：按队列吐 chunk，取尽 resolve null；close 后幂等。 */
export class MockBodyStream implements HttpBodyStream {
  private chunks: Uint8Array[];
  private closed: boolean = false;

  public constructor(chunks: Uint8Array[]) {
    this.chunks = chunks;
  }

  public read(): Promise<Uint8Array | null> {
    if (this.closed) {
      return Promise.resolve(null);
    }
    const next: Uint8Array | undefined = this.chunks.shift();
    if (next === undefined) {
      return Promise.resolve(null);
    }
    return Promise.resolve(next);
  }

  public close(): void {
    this.closed = true;
    this.chunks = [];
  }

  public isClosed(): boolean {
    return this.closed;
  }
}

/** 缓冲响应的路由 handler 形态。 */
export type MockRouteHandler = (request: HttpRequest) => Promise<HttpResponse> | HttpResponse;

/** 一条路由：method 精确匹配 + url 以 urlSuffix 结尾即命中。 */
export interface MockRoute {
  method: string;
  urlSuffix: string;
  status: number;
  headers: Record<string, string>;
  body: Uint8Array;
  handler: MockRouteHandler | null;
}

export interface MockRouteParams {
  method: string;
  urlSuffix: string;
  status?: number;
  headers?: Record<string, string>;
  body?: Uint8Array;
  handler?: MockRouteHandler;
}

const emptyHeaders = (): Record<string, string> => {
  const headers: Record<string, string> = {};
  return headers;
};

export class MockHttpTransport implements HttpTransport {
  /** 全量请求留痕（顺序）。 */
  public requests: HttpRequest[] = [];
  /** open() 建流时吐出的 chunk 队列；空队列 = 立即正常结束。 */
  public openChunks: Uint8Array[] = [];
  /** open() 最近返回的响应体（断言 close 行为用）。 */
  public lastBody: MockBodyStream | null = null;
  /** 置位时 send()/open() 直接 reject（模拟断网）。 */
  public rejectAll: boolean = false;

  private routes: MockRoute[];

  public constructor(routes: MockRoute[] = []) {
    this.routes = routes.slice();
  }

  public addRoute(params: MockRouteParams): void {
    const route: MockRoute = {
      method: params.method,
      urlSuffix: params.urlSuffix,
      status: params.status === undefined ? 200 : params.status,
      headers: params.headers === undefined ? emptyHeaders() : params.headers,
      body: params.body === undefined ? new Uint8Array(0) : params.body,
      handler: params.handler === undefined ? null : params.handler,
    };
    this.routes.push(route);
  }

  private match(request: HttpRequest): MockRoute | null {
    for (const route of this.routes) {
      if (route.method === request.method && request.url.endsWith(route.urlSuffix)) {
        return route;
      }
    }
    return null;
  }

  public async send(request: HttpRequest): Promise<HttpResponse> {
    this.requests.push(request);
    if (this.rejectAll) {
      return Promise.reject(new Error('mock: transport down'));
    }
    const route: MockRoute | null = this.match(request);
    if (route === null) {
      return Promise.reject(new Error('mock: no route for ' + request.method + ' ' + request.url));
    }
    if (route.handler !== null) {
      return Promise.resolve(route.handler(request));
    }
    const resp: HttpResponse = { status: route.status, headers: route.headers, body: route.body };
    return Promise.resolve(resp);
  }

  public async open(request: HttpRequest): Promise<StreamingHttpResponse> {
    this.requests.push(request);
    if (this.rejectAll) {
      return Promise.reject(new Error('mock: transport down'));
    }
    const route: MockRoute | null = this.match(request);
    if (route === null) {
      return Promise.reject(new Error('mock: no route for ' + request.method + ' ' + request.url));
    }
    if (route.status >= 300) {
      const resp: HttpResponse = { status: route.status, headers: route.headers, body: route.body };
      return Promise.resolve({ status: resp.status, headers: resp.headers, body: new MockBodyStream([]) });
    }
    const body: MockBodyStream = new MockBodyStream(this.openChunks);
    this.lastBody = body;
    const resp: StreamingHttpResponse = { status: route.status, headers: route.headers, body: body };
    return Promise.resolve(resp);
  }
}

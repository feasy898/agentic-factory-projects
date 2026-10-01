/**
 * MockControlPlane —— 扮演 ts2021 控制面服务端的壳侧 mock（noise 包 NoiseIkResponder 承载）。
 *
 * 形态与 packages/control/test/client.test.ts 的 FakeControlServer 同构，但定位不同：
 * 那是 control 包的协议测试夹具；本类是 app/ 侧「壳会话联调」的常驻 mock 基础设施
 * （worker-A 交付，归 app/ 工程，不改 packages/）。
 *
 * 行为：
 * - 首个 POST = Noise IK 握手 msgA → 回 msgB，split() 建会话；
 * - 后续 POST = 数据帧：解密留痕 lastPlaintext；能按 RegisterRequest 解码时记 lastRegister；
 * - open() = 长轮询流：吐 responses 队列（queueNetworkMap 加密入队）；
 * - 全量请求体留痕 requestBodies（authKey 明文不落传输的断言面）。
 * 密钥/时钟/随机全走注入（ArrayRng/FixedClock），端到端字节可复现。
 */

import {
  ArrayRng,
  FixedClock,
  utf8Encode,
  type HttpRequest,
  type HttpResponse,
  type HttpTransport,
  type Rng,
  type StreamingHttpResponse,
} from '@ohos-tailscale/common';
import { NoiseIkResponder, noiseFrameDecode, noiseFrameEncode, type NoiseTransportPair } from '@ohos-tailscale/noise';
import {
  CONTROL_NOISE_PROLOGUE,
  controlEncodeMessage,
  networkMapEncode,
  registerRequestDecodeBytes,
  type NetworkMap,
  type RegisterRequest,
} from '@ohos-tailscale/control';
import { MockBodyStream } from './mock-http-transport.ts';

const emptyHeaders = (): Record<string, string> => {
  const headers: Record<string, string> = {};
  return headers;
};

const buffered = (status: number, body: Uint8Array): HttpResponse => {
  const resp: HttpResponse = { status: status, headers: emptyHeaders(), body: body };
  return resp;
};

export class MockControlPlane implements HttpTransport {
  /** 全量请求留痕（method/url/body），authKey 不落传输断言用。 */
  public requests: HttpRequest[] = [];
  /** 握手后解出的对端（客户端）machine 静态公钥（IK 语义验证）。 */
  public clientRemoteStatic: Uint8Array = new Uint8Array(0);
  /** 最近一帧解密出的注册请求（解码失败为 null）。 */
  public lastRegister: RegisterRequest | null = null;
  /** 帧间休眠注入：置位时下一个数据帧直接回 500（断线重连路径用）。 */
  public failNextDataFrame: boolean = false;

  private serverStaticPrivate: Uint8Array;
  private rng: Rng;
  private responder: NoiseIkResponder;
  private pair: NoiseTransportPair | null = null;
  private handshakeDone: boolean = false;
  private responses: Uint8Array[] = [];

  public constructor(serverStaticPrivate: Uint8Array, rng: Rng) {
    this.serverStaticPrivate = serverStaticPrivate;
    this.rng = rng;
    this.responder = new NoiseIkResponder(utf8Encode(CONTROL_NOISE_PROLOGUE), serverStaticPrivate, rng);
  }

  /** 模拟控制面重置会话（等价新连接）：旧密文绝不泄入新会话。 */
  public beginNewSession(): void {
    this.responder = new NoiseIkResponder(utf8Encode(CONTROL_NOISE_PROLOGUE), this.serverStaticPrivate, this.rng);
    this.pair = null;
    this.handshakeDone = false;
    this.responses = [];
    this.lastRegister = null;
  }

  public async send(request: HttpRequest): Promise<HttpResponse> {
    this.requests.push(request);
    if (!this.handshakeDone) {
      const payload = this.responder.readMessageA(request.body);
      this.clientRemoteStatic = payload.remoteStatic;
      const msgB: Uint8Array = this.responder.writeMessageB(new Uint8Array(0));
      this.pair = this.responder.split();
      this.handshakeDone = true;
      return Promise.resolve(buffered(200, msgB));
    }
    if (this.failNextDataFrame) {
      this.failNextDataFrame = false;
      return Promise.resolve(buffered(500, new Uint8Array(0)));
    }
    if (this.pair === null) {
      return Promise.resolve(buffered(500, new Uint8Array(0)));
    }
    const frame = noiseFrameDecode(request.body);
    const plaintext: Uint8Array = this.pair.recv.decrypt(frame.payload);
    try {
      this.lastRegister = registerRequestDecodeBytes(plaintext);
    } catch {
      this.lastRegister = null;
    }
    return Promise.resolve(buffered(200, new Uint8Array(0)));
  }

  public async open(_request: HttpRequest): Promise<StreamingHttpResponse> {
    this.requests.push(_request);
    const body: MockBodyStream = new MockBodyStream(this.responses);
    const resp: StreamingHttpResponse = { status: 200, headers: emptyHeaders(), body: body };
    return Promise.resolve(resp);
  }

  /** 把一条精简版 NetworkMap 加密入队给客户端（MapResponse 形态）。 */
  public queueNetworkMap(map: NetworkMap): void {
    if (this.pair === null) {
      throw new Error('mock control plane: no session established');
    }
    this.responses.push(noiseFrameEncode(this.pair.send.encrypt(controlEncodeMessage(networkMapEncode(map)))));
  }

  /** 便捷构造：确定性服务端（固定池 ArrayRng 派生静态密钥对由调用方生成后传入私钥）。 */
  public static newDeterministic(serverStaticPrivate: Uint8Array): MockControlPlane {
    return new MockControlPlane(serverStaticPrivate, new ArrayRng(MockControlPlane.fillBytes(0xd4, 32)));
  }

  /** 测试工具：fill 填充的 n 字节数组（与 control 测试 makePool 同构）。 */
  public static fillBytes(fill: number, n: number): Uint8Array {
    const out: Uint8Array = new Uint8Array(n);
    for (let i: number = 0; i < n; i += 1) {
      out[i] = fill & 0xff;
    }
    return out;
  }

  /** 测试工具：确定性 32B 密钥（seed 派生，与 control 测试 fixedKey 同构）。 */
  public static fixedKey(seed: number): Uint8Array {
    return MockControlPlane.fillBytes(seed, 32).map((b: number, i: number): number => (seed + i * 3) & 0xff);
  }

  /** 测试/脚手架工具：确定性时钟。 */
  public static newClock(startWallMs: number): FixedClock {
    return new FixedClock(startWallMs);
  }
}

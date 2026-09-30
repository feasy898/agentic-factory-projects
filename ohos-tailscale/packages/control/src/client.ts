/**
 * ControlClient（架构契约 §7.2）—— ts2021 控制面客户端骨架。
 *
 * 分层：TLV 消息（tlv.ts/messages.ts）→ Noise 传输加密（@ohos-tailscale/noise
 * 的 NoiseIkInitiator + NoiseTransportCipher）→ 2B BE 帧前缀（noise.noiseFrameEncode）
 * → HttpTransport（common 注入接口，D4：核心库不碰 socket/TLS）。
 *
 * HTTP 形态（骨架本地约定；契约只钉死 dial 的 POST <controlUrl>/ts2021）：
 * - dial()   : POST <base>/ts2021，body = Noise IK msgA（80B 头 + enc(空载荷)）；
 *              期望 200 + body = msgB（32B e + enc(空载荷)），split() 建会话；
 * - send()   : POST <base>/ts2021，body = frame(enc(controlEncodeMessage(msg)))；
 * - receive(): GET  <base>/ts2021 经 transport.open() 建流式长轮询，跨 chunk
 *              帧重组（NoiseFrameReader）取一帧 → noise 解密 → TLV 解码；
 *              流按需惰性打开并在多次 receive() 间复用；多帧到达时进入
 *              内部 backlog 逐条返回；
 * - close(): 释放当前会话（关流、清空积压帧、丢弃 Noise 传输对并复位会话标记），
 *            客户端可再次 dial() 建立全新会话。
 *
 * 流生命周期与会话恢复（评审第 1 项修复）：
 * - NoiseFrameReader（半帧缓存）与流同生命周期：流建立时取新实例，流提前结束/
 *   读失败时随 this.stream 一起复位——旧流的半帧字节绝不泄入新流；
 * - Noise 传输对（含 recv 计数器）是 dial() 建立的会话态，跨流持续：长轮询流
 *   重连不重置 AEAD 计数器（对端 send 计数器连续，客户端复位反而必败）；
 * - 因此流中断的可恢复形态是"帧间断开"（releaseStream 后新流继续，计数器对齐）；
 *   若半帧在途丢失（AEAD 失步），同会话 receive() 如实抛 'NOISE'，唯一恢复路径
 *   是 close() + dial() 建立全新会话——dial() 会复位全部流级/积压状态，该路径
 *   已可用（评审第 1 项所指"暗示但不可用"的恢复路径）。
 *
 * 契约字段 serverStaticPublic（已裁定增补，评审升级 dwfq-fe173e19-1，架构师批准并
 * 已写入 architecture.md §7.2/§10.3 v1.1）：Noise IK 的发起方必须持有对端（控制面
 * 服务端）静态公钥（noise 包 NoiseIkInitiator 构造签名的 remoteStatic，架构契约 §6），
 * 故 ControlClientConfig 除原六字段外含此必填字段；真实 tailscale 中该值由控制面
 * 密钥发现机制（/key 端点）获得并固定/经配置注入，当前阶段由调用方显式传入。
 *
 * 错误映射（契约 §7.2）：dial 失败抛 ControlError('NOISE'|'HTTP')；transport
 * reject/非 2xx/流提前结束 → 'HTTP'；握手/传输解密失败 → 'NOISE'；生命周期
 * 违规（未 dial 先 send/receive、重复 dial、close 后使用、构造参数非法）→ 'STATE'；
 * send() 编码明文超单帧容量（帧载荷上限 65535B − 16B AEAD tag = 65519B）→ 'TLV'
 * 尺寸预检（评审第 2 项：TLV 层单字段合法上界 65535B 高于通道单帧容量，必须在本包
 * 拦截，noise 包的 NoiseError('FRAME') 不得越过包边界外泄）；流式响应错误弃流
 * （非 2xx open / 读失败 / 流提前结束）一律先 body.close() 关闭底层连接再抛错，
 * 不泄漏长轮询连接（评审第 3 项；HttpBodyStream.close 契约可重复调用）。
 * P4：时钟/随机数全部来自注入的 Clock/Rng；本骨架的 rng 仅被 Noise 消费，
 * clock 记录 dial 完成时刻（dialMonotonicMs）供二期 keepalive/超时调度扩展。
 */

import {
  AEAD_TAG_LEN_BYTES,
  KEY_LEN_BYTES,
  utf8Encode,
  type Clock,
  type HttpRequest,
  type HttpResponse,
  type HttpTransport,
  type Rng,
  type StreamingHttpResponse,
} from '@ohos-tailscale/common';
import { type CryptoKeyPair } from '@ohos-tailscale/crypto';
import {
  NoiseFrameReader,
  NoiseIkInitiator,
  noiseFrameEncode,
  type NoiseFrame,
  type NoiseTransportPair,
} from '@ohos-tailscale/noise';
import { ControlError } from './errors.ts';
import { controlEncodeMessage, controlDecodeMessage, type ControlMessage } from './tlv.ts';

/**
 * ts2021 控制面 Noise prologue。本包本地契约（两端一致即可互操作）；
 * 真实上游取值列入 architecture.md §10-U1 同类核对项，核对后只改此常量。
 */
export const CONTROL_NOISE_PROLOGUE: string = 'ohos-tailscale-control-ts2021';

/** noise 通道单帧载荷上限（noise 包 frame.ts 本地契约：2B BE 前缀的 u16 值域 65535B）。 */
const NOISE_FRAME_BODY_MAX: number = 65535;
/** send() 编码明文上界 = 单帧载荷上限 − AEAD tag（noise 密文布局 = 密文 || 16B tag）。 */
const MAX_SEND_PLAINTEXT_LEN: number = NOISE_FRAME_BODY_MAX - AEAD_TAG_LEN_BYTES;

/** ControlClient 配置（架构契约 §7.2：六字段 + 已裁定增补的 serverStaticPublic，见 §10.3 v1.1）。 */
export interface ControlClientConfig {
  /** 控制面 URL，例 'https://headscale.example.internal'（【取证】§1.2：自定义 ControlURL 必须支持）。 */
  controlUrl: string;
  /** WireGuard 层 nodekey（注册消息与二期 netmap → WG peer 配置推导用）。 */
  nodeKeyPair: CryptoKeyPair;
  /** ts2021 machine key（Noise IK 本端静态密钥对）。 */
  machineKeyPair: CryptoKeyPair;
  /** 控制面服务端 Noise IK 静态公钥（32B；已裁定增补字段，评审升级 dwfq-fe173e19-1）。
   *  真实 tailscale 由控制面密钥发现机制（/key 端点）获得，当前阶段由调用方显式传入。 */
  serverStaticPublic: Uint8Array;
  /** HTTP 传输注入接口（common 冻结 API）。 */
  transport: HttpTransport;
  /** 时钟注入接口（P4）。 */
  clock: Clock;
  /** 随机源注入接口（P4；Noise 临时密钥消费方）。 */
  rng: Rng;
}

/** 校验 32B 密钥长度，返回独立拷贝（R8）。 */
function requireKey32(key: Uint8Array, what: string): Uint8Array {
  if (key.length !== KEY_LEN_BYTES) {
    throw new ControlError(
      'STATE',
      'control client: ' + what + ' must be ' + String(KEY_LEN_BYTES) + ' bytes, got ' + String(key.length),
    ) as Error;
  }
  return key.slice();
}

export class ControlClient {
  private controlUrl: string;
  private machinePrivate: Uint8Array;
  private serverStatic: Uint8Array;
  private nodePublicKey: Uint8Array;
  private transport: HttpTransport;
  private clock: Clock;
  private rng: Rng;

  private dialed: boolean = false;
  private closed: boolean = false;
  private pair: NoiseTransportPair | null = null;
  private stream: StreamingHttpResponse | null = null;
  private frameReader: NoiseFrameReader = new NoiseFrameReader();
  private backlog: Uint8Array[] = [];
  private dialMonoMs: number | null = null;

  public constructor(cfg: ControlClientConfig) {
    if (cfg.controlUrl.length === 0) {
      throw new ControlError('STATE', 'control client: controlUrl must not be empty') as Error;
    }
    this.controlUrl = cfg.controlUrl;
    this.machinePrivate = requireKey32(cfg.machineKeyPair.privateKey, 'machineKeyPair.privateKey');
    this.serverStatic = requireKey32(cfg.serverStaticPublic, 'serverStaticPublic');
    this.nodePublicKey = requireKey32(cfg.nodeKeyPair.publicKey, 'nodeKeyPair.publicKey');
    requireKey32(cfg.nodeKeyPair.privateKey, 'nodeKeyPair.privateKey');
    this.transport = cfg.transport;
    this.clock = cfg.clock;
    this.rng = cfg.rng;
  }

  /** 本端 WireGuard 层 node 公钥（独立拷贝，R8）；注册消息构造用。 */
  public nodeKey(): Uint8Array {
    return this.nodePublicKey.slice();
  }

  /** 当前会话 dial() 完成时刻的单调时钟毫秒（无会话/close 之后为 null）。 */
  public dialMonotonicMs(): number | null {
    return this.dialMonoMs;
  }

  /** 会话地址：去掉 controlUrl 尾部 '/' 后接 '/ts2021'（契约 §7.2：POST controlUrl/ts2021）。 */
  private sessionUrl(): string {
    const base: string = this.controlUrl.replace(new RegExp('/+$'), '');
    return base + '/ts2021';
  }

  private assertUsable(op: string): void {
    if (this.closed) {
      throw new ControlError('STATE', 'control client: ' + op + ' after close()') as Error;
    }
    if (!this.dialed) {
      throw new ControlError('STATE', 'control client: ' + op + ' before dial()') as Error;
    }
  }

  private requirePair(): NoiseTransportPair {
    if (this.pair === null) {
      throw new ControlError('STATE', 'control client: session not established') as Error;
    }
    return this.pair;
  }

  private static octetStreamHeaders(): Record<string, string> {
    const headers: Record<string, string> = { 'content-type': 'application/octet-stream' };
    return headers;
  }

  /**
   * 完成 Noise IK 握手：POST <controlUrl>/ts2021（msgA）→ 200 + msgB → split()。
   * 失败抛 ControlError('HTTP'|'NOISE')；会话进行中重复 dial 抛 ControlError('STATE')；
   * close() 之后允许重新 dial() 建立全新会话（会话恢复路径，评审第 1 项）。
   */
  public async dial(): Promise<void> {
    if (this.dialed) {
      throw new ControlError('STATE', 'control client: dial() already completed') as Error;
    }
    // 新会话从零开始：复位上一会话/上次失败尝试遗留的流、半帧缓存与积压帧
    // （close()+重新 dial() 恢复路径的前提：旧会话的半帧字节不得泄入新会话）。
    this.releaseStream();
    this.backlog = [];
    const initiator: NoiseIkInitiator = new NoiseIkInitiator(
      utf8Encode(CONTROL_NOISE_PROLOGUE),
      this.machinePrivate,
      this.serverStatic,
      this.rng,
    );
    const msgA: Uint8Array = initiator.writeMessageA(new Uint8Array(0));
    const request: HttpRequest = {
      method: 'POST',
      url: this.sessionUrl(),
      headers: ControlClient.octetStreamHeaders(),
      body: msgA,
    };
    let resp: HttpResponse;
    try {
      resp = await this.transport.send(request);
    } catch (e) {
      throw new ControlError('HTTP', 'dial: transport send failed: ' + String(e)) as Error;
    }
    if (resp.status !== 200) {
      throw new ControlError('HTTP', 'dial: unexpected status ' + String(resp.status) + ', want 200') as Error;
    }
    try {
      initiator.readMessageB(resp.body);
    } catch (e) {
      throw new ControlError('NOISE', 'dial: handshake message B rejected: ' + String(e)) as Error;
    }
    this.pair = initiator.split();
    this.dialed = true;
    this.closed = false;
    this.dialMonoMs = this.clock.monotonicMs();
  }

  /**
   * 发送一条控制面消息：TLV 编码 → 尺寸预检 → noise 加密 → 2B BE 帧 →
   * POST <base>/ts2021。编码明文超单帧容量（MAX_SEND_PLAINTEXT_LEN = 65519B）
   * 抛 ControlError('TLV')（评审第 2 项：预检拦在 noiseFrameEncode 之前，
   * NoiseError('FRAME') 不外泄）；非 2xx 响应抛 ControlError('HTTP')。
   */
  public async send(msg: ControlMessage): Promise<void> {
    this.assertUsable('send()');
    const plaintext: Uint8Array = controlEncodeMessage(msg);
    if (plaintext.length > MAX_SEND_PLAINTEXT_LEN) {
      throw new ControlError(
        'TLV',
        'send: encoded message plaintext ' + String(plaintext.length) + ' exceeds one-frame capacity ' +
        String(MAX_SEND_PLAINTEXT_LEN) + ' (frame body ' + String(NOISE_FRAME_BODY_MAX) + ' - tag ' +
        String(AEAD_TAG_LEN_BYTES) + ')',
      ) as Error;
    }
    const frame: Uint8Array = noiseFrameEncode(this.requirePair().send.encrypt(plaintext));
    const request: HttpRequest = {
      method: 'POST',
      url: this.sessionUrl(),
      headers: ControlClient.octetStreamHeaders(),
      body: frame,
    };
    let resp: HttpResponse;
    try {
      resp = await this.transport.send(request);
    } catch (e) {
      throw new ControlError('HTTP', 'send: transport send failed: ' + String(e)) as Error;
    }
    if (resp.status < 200 || resp.status > 299) {
      throw new ControlError('HTTP', 'send: unexpected status ' + String(resp.status)) as Error;
    }
  }

  /**
   * 释放当前流并复位流级状态（评审第 1 项）：先关闭底层连接再置空（评审第 3 项：
   * 错误弃流不泄漏长轮询连接；HttpBodyStream.close 契约可重复调用，故本方法在
   * close()/dial() 复用路径上重复关闭同一流是安全的）。半帧缓存（NoiseFrameReader）
   * 与流同生命周期，随 this.stream 一起丢弃；Noise 传输对（recv 计数器）是会话态，
   * 跨流持续——对端 send 计数器连续，此处复位反而破坏 AEAD 序列。
   */
  private releaseStream(): void {
    if (this.stream !== null) {
      this.stream.body.close();
    }
    this.stream = null;
    this.frameReader = new NoiseFrameReader();
  }

  /**
   * 惰性打开流式长轮询响应（GET <base>/ts2021）；失败/非 2xx 抛 ControlError('HTTP')。
   * 非 2xx 时先关闭该响应的底层流再抛（评审第 3 项：错误路径不泄漏连接）。
   */
  private async ensureStream(): Promise<void> {
    if (this.stream !== null) {
      return;
    }
    this.frameReader = new NoiseFrameReader(); // 新流配新帧重组器（流生命周期不变式）
    const request: HttpRequest = {
      method: 'GET',
      url: this.sessionUrl(),
      headers: ControlClient.octetStreamHeaders(),
      body: new Uint8Array(0),
    };
    let resp: StreamingHttpResponse;
    try {
      resp = await this.transport.open(request);
    } catch (e) {
      throw new ControlError('HTTP', 'receive: transport open failed: ' + String(e)) as Error;
    }
    if (resp.status < 200 || resp.status > 299) {
      resp.body.close();
      throw new ControlError('HTTP', 'receive: unexpected open status ' + String(resp.status)) as Error;
    }
    this.stream = resp;
  }

  /**
   * 从流式响应持续读 chunk 直至 backlog 至少有一帧；流结束/读失败抛
   * ControlError('HTTP')，且经 releaseStream() 关闭底层流并复位半帧缓存
   * （评审第 1/3 项：缓存随流丢弃、连接不泄漏）。
   */
  private async fillBacklog(): Promise<void> {
    await this.ensureStream();
    const stream: StreamingHttpResponse = this.stream as StreamingHttpResponse;
    while (this.backlog.length === 0) {
      let chunk: Uint8Array | null = null;
      try {
        chunk = await stream.body.read();
      } catch (e) {
        this.releaseStream();
        throw new ControlError('HTTP', 'receive: stream read failed: ' + String(e)) as Error;
      }
      if (chunk === null) {
        this.releaseStream();
        throw new ControlError('HTTP', 'receive: stream ended before a full frame') as Error;
      }
      const frames: NoiseFrame[] = this.frameReader.push(chunk);
      for (const frame of frames) {
        this.backlog.push(frame.payload);
      }
    }
  }

  /**
   * 接收一条控制面消息：流式响应读一帧 → noise 解密 → TLV 解码。
   * 未 dial 先调用抛 ControlError('STATE')；解密失败抛 ControlError('NOISE')；
   * TLV 畸形抛 ControlError('TLV')；传输层失败抛 ControlError('HTTP')。
   */
  public async receive(): Promise<ControlMessage> {
    this.assertUsable('receive()');
    if (this.backlog.length === 0) {
      await this.fillBacklog();
    }
    const frame: Uint8Array | undefined = this.backlog.shift();
    if (frame === undefined) {
      throw new ControlError('STATE', 'control client: backlog empty after fill (internal)') as Error;
    }
    let plaintext: Uint8Array;
    try {
      plaintext = this.requirePair().recv.decrypt(frame);
    } catch (e) {
      throw new ControlError('NOISE', 'receive: frame decrypt failed: ' + String(e)) as Error;
    }
    return controlDecodeMessage(plaintext);
  }

  /**
   * 释放当前会话：关闭流式响应、清空积压帧与半帧缓存、丢弃 Noise 传输对并复位
   * 会话标记；可重复调用。close 后 send/receive 抛 ControlError('STATE')，而
   * dial() 可再次调用以建立全新会话（帧丢失 AEAD 失步后的唯一恢复路径，
   * 评审第 1 项）。
   */
  public close(): void {
    this.releaseStream(); // 内含 body.close()（HttpBodyStream.close 契约可重复调用）
    this.backlog = [];
    this.pair = null;
    this.dialed = false;
    this.dialMonoMs = null;
    this.closed = true;
  }
}

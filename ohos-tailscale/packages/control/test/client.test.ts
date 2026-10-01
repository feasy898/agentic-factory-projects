/**
 * ControlClient 全流程测试（架构契约 §7.2 + §7.3 fake transport 部分）：
 *
 * 测试内造脚本化 fake HttpTransport，用 noise 包的 NoiseIkResponder 扮演控制面
 * 服务端（与客户端共用 CONTROL_NOISE_PROLOGUE），把握手 msgB / 后续密文按脚本
 * 返回；全程 FixedClock / ArrayRng 注入，端到端字节可复现：
 * - 模拟注册全流程：dial()（POST <controlUrl>/ts2021 携带 IK msgA）→ 服务端
 *   解出 remoteStatic = 客户端 machine 公钥 → send(RegisterRequest) → 服务端
 *   解密还原 TLV → 回精简版 NetworkMap（MapResponse）→ receive() 等价还原；
 * - receive：响应帧跨 chunk 分片重组（NoiseFrameReader）、多帧 backlog 逐条返回、
 *   流提前结束 → ControlError('HTTP')；
 * - 会话恢复（评审第 1 项）：流帧间断开 → 'HTTP' → 新流继续接收（半帧缓存随流
 *   复位、recv 计数器跨流连续）；半帧在途丢失 → 'HTTP' → 同会话 'NOISE'（AEAD
 *   失步如实暴露）→ close()+dial() 建立新会话恢复；
 * - 失败路径：非 200 → 'HTTP'；transport reject → 'HTTP'；msgB 篡改 → 'NOISE'；
 *   服务端静态密钥不匹配 → 'HTTP'；垃圾密文帧 → 'NOISE'；
 * - 生命周期：未 dial 先 send/receive、重复 dial、close 后使用 → 'STATE'；
 *   构造参数密钥长度非法 → 'STATE'；
 * - 错误路径资源（评审第 3 项）：open 非 2xx / 流读失败弃流时必须 body.close()；
 * - send 尺寸预检（评审第 2 项）：TLV 合法但明文 > 65519B → ControlError('TLV')，
 *   不泄漏 noise 包 NoiseError('FRAME')；边界 65519B 可正常发送；
 * - 确定性：同一脚本两次运行的 dial msgA 与 send 帧字节完全一致。
 */

import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  ArrayRng,
  FixedClock,
  utf8Encode,
  type Clock,
  type HttpBodyStream,
  type HttpRequest,
  type HttpResponse,
  type HttpTransport,
  type Rng,
  type StreamingHttpResponse,
} from '@ohos-tailscale/common';
import { x25519GenerateKeyPair, type CryptoKeyPair } from '@ohos-tailscale/crypto';
import {
  NoiseIkResponder,
  noiseFrameDecode,
  noiseFrameEncode,
  type NoiseFrame,
  type NoiseIkPayload,
  type NoiseTransportPair,
} from '@ohos-tailscale/noise';
import {
  CONTROL_NOISE_PROLOGUE,
  ControlClient,
  ControlError,
  ControlMsgKind,
  ControlTlvType,
  controlEncodeMessage,
  networkMapDecode,
  networkMapEncode,
  registerRequestDecodeBytes,
  registerRequestEncode,
  type ControlClientConfig,
  type ControlMessage,
  type NetworkMap,
  type RegisterRequest,
} from '../src/index.ts';

// ---------- 测试工具（模块级箭头函数 + 显式类型，禁嵌套函数声明） ----------

const makePool = (fill: number, n: number): Uint8Array => {
  const out: Uint8Array = new Uint8Array(n);
  for (let i: number = 0; i < n; i += 1) {
    out[i] = fill & 0xff;
  }
  return out;
};

const fixedKey = (seed: number): Uint8Array => {
  const out: Uint8Array = new Uint8Array(32);
  for (let i: number = 0; i < 32; i += 1) {
    out[i] = (seed + i * 3) & 0xff;
  }
  return out;
};

const emptyHeaders = (): Record<string, string> => {
  const headers: Record<string, string> = {};
  return headers;
};

const buffered = (status: number, body: Uint8Array): HttpResponse => {
  const resp: HttpResponse = { status: status, headers: emptyHeaders(), body: body };
  return resp;
};

const assertControlCode = (fn: () => void, want: string): void => {
  let thrown: boolean = false;
  let got: string = '';
  try {
    fn();
  } catch (e) {
    thrown = true;
    const err: ControlError = e as ControlError;
    got = err.code;
  }
  assert.equal(thrown, true, 'expected ControlError(' + want + ') not thrown');
  assert.equal(got, want, 'unexpected ControlError code');
};

const rejectCode = async (fn: () => Promise<ControlMessage | void>, want: string): Promise<void> => {
  let thrown: boolean = false;
  let got: string = '';
  try {
    await fn();
  } catch (e) {
    thrown = true;
    const err: ControlError = e as ControlError;
    got = err.code;
  }
  assert.equal(thrown, true, 'expected ControlError(' + want + ') not thrown');
  assert.equal(got, want, 'unexpected ControlError code');
};

// ---------- 脚本化 fake 控制面服务端 ----------

/** 流式响应体：按脚本依次吐出 pollChunks，取尽后正常结束（read → null）。 */
class FakeBodyStream implements HttpBodyStream {
  private chunks: Uint8Array[];
  private closed: boolean = false;
  /** 置位时下一次 read() reject（模拟传输层读失败）；读一次后自动复位。 */
  public failNextRead: boolean = false;

  public constructor(chunks: Uint8Array[]) {
    this.chunks = chunks;
  }

  public read(): Promise<Uint8Array | null> {
    if (this.closed) {
      return Promise.resolve(null);
    }
    if (this.failNextRead) {
      this.failNextRead = false;
      return Promise.reject(new Error('fake: read boom'));
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

  /** 供测试断言错误路径是否调用了 close()。 */
  public isClosed(): boolean {
    return this.closed;
  }
}

/**
 * fake 控制面：NoiseIkResponder 扮演服务端。首个 POST 视为握手 msgA（回 msgB），
 * 后续 POST 视为数据帧（解密记录 lastPlaintext），open() 返回按脚本吐帧的流。
 */
class FakeControlServer implements HttpTransport {
  public requests: HttpRequest[] = [];
  public failHandshakeStatus: number = 0;
  public tamperMsgB: boolean = false;
  public throwOnHandshake: boolean = false;
  public msgAPayload: Uint8Array = new Uint8Array(0);
  public clientRemoteStatic: Uint8Array = new Uint8Array(0);
  public lastPlaintext: Uint8Array = new Uint8Array(0);
  /** 非 0 时 open() 返回该状态码（评审第 3 项：非 2xx 弃流路径用）。 */
  public openStatus: number = 0;
  /** open() 建流时转交给 body 的读失败注入（读一次后自动复位）。 */
  public failNextRead: boolean = false;
  /** open() 最近一次创建/返回的响应体（断言错误路径是否 close）。 */
  public lastBody: FakeBodyStream | null = null;

  private responder: NoiseIkResponder;
  private serverStaticPrivate: Uint8Array;
  private rng: Rng;
  private pair: NoiseTransportPair | null = null;
  private handshakeDone: boolean = false;
  private pollChunks: Uint8Array[] = [];

  public constructor(serverStaticPrivate: Uint8Array, rng: Rng) {
    this.serverStaticPrivate = serverStaticPrivate;
    this.rng = rng;
    this.responder = new NoiseIkResponder(utf8Encode(CONTROL_NOISE_PROLOGUE), serverStaticPrivate, rng);
  }

  /**
   * 模拟控制面接受一条新连接：重置握手状态、按同一静态私钥新建 responder、
   * 清空旧会话的推送队列（旧密文不得泄入新会话）。供 close()+dial() 恢复路径测试。
   */
  public beginNewSession(): void {
    this.responder = new NoiseIkResponder(utf8Encode(CONTROL_NOISE_PROLOGUE), this.serverStaticPrivate, this.rng);
    this.pair = null;
    this.handshakeDone = false;
    this.pollChunks = [];
  }

  public async send(request: HttpRequest): Promise<HttpResponse> {
    this.requests.push(request);
    if (this.throwOnHandshake) {
      return Promise.reject(new Error('fake: net down'));
    }
    if (!this.handshakeDone) {
      if (this.failHandshakeStatus > 0) {
        return Promise.resolve(buffered(this.failHandshakeStatus, new Uint8Array(0)));
      }
      const payload: NoiseIkPayload = this.responder.readMessageA(request.body);
      this.msgAPayload = payload.payload;
      this.clientRemoteStatic = payload.remoteStatic;
      let msgB: Uint8Array = this.responder.writeMessageB(new Uint8Array(0));
      if (this.tamperMsgB) {
        msgB = msgB.slice();
        const last: number = msgB.length - 1;
        msgB[last] = (msgB[last] ^ 0x01) & 0xff;
      }
      this.pair = this.responder.split();
      this.handshakeDone = true;
      return Promise.resolve(buffered(200, msgB));
    }
    if (this.pair === null) {
      return Promise.resolve(buffered(500, new Uint8Array(0)));
    }
    const frame: NoiseFrame = noiseFrameDecode(request.body);
    this.lastPlaintext = this.pair.recv.decrypt(frame.payload);
    return Promise.resolve(buffered(200, new Uint8Array(0)));
  }

  public async open(request: HttpRequest): Promise<StreamingHttpResponse> {
    this.requests.push(request);
    const body: FakeBodyStream = new FakeBodyStream(this.pollChunks);
    body.failNextRead = this.failNextRead;
    this.failNextRead = false;
    this.lastBody = body;
    const status: number = this.openStatus > 0 ? this.openStatus : 200;
    const resp: StreamingHttpResponse = { status: status, headers: emptyHeaders(), body: body };
    return Promise.resolve(resp);
  }

  /** 把一条明文控制面消息加密成帧后作为单个 chunk 排队给客户端。 */
  public queueToClient(plaintext: Uint8Array): void {
    if (this.pair === null) {
      throw new Error('fake: no session established');
    }
    this.pollChunks.push(noiseFrameEncode(this.pair.send.encrypt(plaintext)));
  }

  /** 把一条明文控制面消息加密成帧后按 pieceSize 字节分片排队（跨 chunk 重组用）。 */
  public queueToClientSplit(plaintext: Uint8Array, pieceSize: number): void {
    if (this.pair === null) {
      throw new Error('fake: no session established');
    }
    const frame: Uint8Array = noiseFrameEncode(this.pair.send.encrypt(plaintext));
    let off: number = 0;
    while (off < frame.length) {
      const end: number = Math.min(off + pieceSize, frame.length);
      this.pollChunks.push(frame.slice(off, end));
      off = end;
    }
  }

  /** 只送出一帧的前 headBytes 字节（模拟半帧在途丢失后流终止，评审第 1 项复现用）。 */
  public queueToClientPartial(plaintext: Uint8Array, headBytes: number): void {
    if (this.pair === null) {
      throw new Error('fake: no session established');
    }
    const frame: Uint8Array = noiseFrameEncode(this.pair.send.encrypt(plaintext));
    this.pollChunks.push(frame.slice(0, headBytes));
  }

  /** 排队一个原始 chunk（不经加密，用于密文损坏路径）。 */
  public queueRawChunk(chunk: Uint8Array): void {
    this.pollChunks.push(chunk);
  }
}

// ---------- 确定性装配（ArrayRng 固定池 → 全程可复现） ----------

const serverStaticKeys = (): CryptoKeyPair => {
  return x25519GenerateKeyPair(new ArrayRng(makePool(0xb2, 32)));
};

/** makeClient 内部同参数派生的 machine 公钥（断言 IK remoteStatic 用）。 */
const expectedMachinePublic = (): Uint8Array => {
  return x25519GenerateKeyPair(new ArrayRng(makePool(0xa1, 32))).publicKey;
};

const makeServer = (): FakeControlServer => {
  const keys: CryptoKeyPair = serverStaticKeys();
  return new FakeControlServer(keys.privateKey, new ArrayRng(makePool(0xd4, 32)));
};

const makeClient = (transport: HttpTransport, serverStaticPublic: Uint8Array, clock: Clock): ControlClient => {
  const machineKeys: CryptoKeyPair = x25519GenerateKeyPair(new ArrayRng(makePool(0xa1, 32)));
  const nodeKeys: CryptoKeyPair = { publicKey: fixedKey(1), privateKey: fixedKey(2) };
  const cfg: ControlClientConfig = {
    controlUrl: 'https://net.example.test',
    nodeKeyPair: nodeKeys,
    machineKeyPair: machineKeys,
    serverStaticPublic: serverStaticPublic,
    transport: transport,
    clock: clock,
    rng: new ArrayRng(makePool(0xc3, 32)),
  };
  return new ControlClient(cfg);
};

// ---------- 用例 ----------

test('模拟注册全流程：dial → send(RegisterRequest) → 服务端解出 → 回 NetworkMap → receive()', async () => {
  const clock: FixedClock = new FixedClock(1000);
  clock.advanceMs(234); // FixedClock 的 mono 轴从 0 起 → monotonicMs = 234（wall = 1234）
  const serverKeys: CryptoKeyPair = serverStaticKeys();
  const server: FakeControlServer = new FakeControlServer(serverKeys.privateKey, new ArrayRng(makePool(0xd4, 32)));
  const client: ControlClient = makeClient(server, serverKeys.publicKey, clock);

  // 1) dial：IK 握手
  await client.dial();
  assert.equal(server.requests.length, 1);
  assert.equal(server.requests[0].method, 'POST');
  assert.equal(server.requests[0].url, 'https://net.example.test/ts2021', 'dial must POST <controlUrl>/ts2021');
  assert.equal(server.msgAPayload.length, 0, 'msgA payload must be empty in skeleton');
  assert.deepEqual(server.clientRemoteStatic, expectedMachinePublic(), 'IK: server must see client machine public key');
  assert.equal(client.dialMonotonicMs(), 234, 'clock injection must be observable at dial');

  // 2) send(RegisterRequest)：服务端解密还原出等价结构
  const req: RegisterRequest = {
    nodeKey: client.nodeKey(),
    discoKey: fixedKey(60),
    endpoints: ['198.51.100.20:41641', '203.0.113.10:41037'],
  };
  await client.send(registerRequestEncode(req));
  assert.equal(server.requests.length, 2);
  assert.equal(server.requests[1].method, 'POST');
  assert.equal(server.requests[1].url, 'https://net.example.test/ts2021');
  const gotReq: RegisterRequest = registerRequestDecodeBytes(server.lastPlaintext);
  assert.deepEqual(gotReq.nodeKey, req.nodeKey);
  assert.deepEqual(gotReq.discoKey, req.discoKey);
  assert.deepEqual(gotReq.endpoints, req.endpoints);

  // 3) 服务端回精简版 NetworkMap（MapResponse），receive() 等价还原
  const map: NetworkMap = {
    seqNo: 42n,
    packetFilter: new Uint8Array([0x00, 0x01, 0x02, 0x03]),
    peers: [
      { nodeKey: fixedKey(70), discoKey: fixedKey(71), endpoints: ['223.198.166.92:30387'], homeDerpRegionId: 999 },
      { nodeKey: fixedKey(80), discoKey: fixedKey(81), endpoints: [], homeDerpRegionId: 17 },
    ],
  };
  server.queueToClient(controlEncodeMessage(networkMapEncode(map)));
  const got: ControlMessage = await client.receive();
  assert.equal(got.kind, ControlMsgKind.MapResponse);
  const gotMap: NetworkMap = networkMapDecode(got);
  assert.equal(gotMap.seqNo, 42n);
  assert.deepEqual(gotMap.packetFilter, map.packetFilter);
  assert.equal(gotMap.peers.length, 2);
  assert.deepEqual(gotMap.peers[0].nodeKey, fixedKey(70));
  assert.deepEqual(gotMap.peers[0].discoKey, fixedKey(71));
  assert.deepEqual(gotMap.peers[0].endpoints, map.peers[0].endpoints);
  assert.equal(gotMap.peers[0].homeDerpRegionId, 999);
  assert.deepEqual(gotMap.peers[1].nodeKey, fixedKey(80));
  assert.deepEqual(gotMap.peers[1].endpoints, []);
  assert.equal(gotMap.peers[1].homeDerpRegionId, 17);

  // 4) close 释放会话：send/receive → STATE；close()+dial() 恢复路径见专门用例
  client.close();
  await rejectCode((): Promise<void> => client.send(registerRequestEncode(req)), 'STATE');
  await rejectCode((): Promise<ControlMessage> => client.receive(), 'STATE');
});

test('receive：响应帧跨 chunk 分片重组 + backlog 多帧逐条返回 + 流结束', async () => {
  const server: FakeControlServer = makeServer();
  const client: ControlClient = makeClient(server, serverStaticKeys().publicKey, new FixedClock(0));
  await client.dial();

  const first: ControlMessage = { kind: ControlMsgKind.KeepAlive, fields: [] };
  const second: ControlMessage = { kind: ControlMsgKind.Ping, fields: [] };
  server.queueToClientSplit(controlEncodeMessage(first), 3);
  server.queueToClientSplit(controlEncodeMessage(second), 7);

  const gotFirst: ControlMessage = await client.receive();
  assert.equal(gotFirst.kind, ControlMsgKind.KeepAlive, 'frames split into 3-byte chunks must reassemble');
  const gotSecond: ControlMessage = await client.receive();
  assert.equal(gotSecond.kind, ControlMsgKind.Ping, 'second frame must come from backlog in order');

  // 流取尽后再收 → ControlError('HTTP')
  await rejectCode((): Promise<ControlMessage> => client.receive(), 'HTTP');
});

test('dial 失败：非 200 状态 → ControlError(HTTP)，且未进入会话', async () => {
  const server: FakeControlServer = makeServer();
  server.failHandshakeStatus = 503;
  const client: ControlClient = makeClient(server, serverStaticKeys().publicKey, new FixedClock(0));
  await rejectCode((): Promise<void> => client.dial(), 'HTTP');
  assert.equal(client.dialMonotonicMs(), null);
  const req: RegisterRequest = { nodeKey: fixedKey(1), discoKey: fixedKey(2), endpoints: [] };
  await rejectCode((): Promise<void> => client.send(registerRequestEncode(req)), 'STATE');
});

test('dial 失败：transport 层 reject → ControlError(HTTP)', async () => {
  const server: FakeControlServer = makeServer();
  server.throwOnHandshake = true;
  const client: ControlClient = makeClient(server, serverStaticKeys().publicKey, new FixedClock(0));
  await rejectCode((): Promise<void> => client.dial(), 'HTTP');
});

test('dial 失败：msgB 密文被篡改 → ControlError(NOISE)', async () => {
  const server: FakeControlServer = makeServer();
  server.tamperMsgB = true;
  const client: ControlClient = makeClient(server, serverStaticKeys().publicKey, new FixedClock(0));
  await rejectCode((): Promise<void> => client.dial(), 'NOISE');
});

test('dial 失败：客户端配置的 serverStaticPublic 与服务端不符 → ControlError(HTTP)', async () => {
  const server: FakeControlServer = makeServer();
  const client: ControlClient = makeClient(server, fixedKey(90), new FixedClock(0));
  await rejectCode((): Promise<void> => client.dial(), 'HTTP');
});

test('receive 失败：垃圾密文帧 → ControlError(NOISE)', async () => {
  const server: FakeControlServer = makeServer();
  const client: ControlClient = makeClient(server, serverStaticKeys().publicKey, new FixedClock(0));
  await client.dial();
  // 2B 帧头声明 40B 体 + 全零密文（解密必败）
  const garbage: Uint8Array = new Uint8Array(42);
  garbage[0] = 0x00;
  garbage[1] = 0x28;
  server.queueRawChunk(garbage);
  await rejectCode((): Promise<ControlMessage> => client.receive(), 'NOISE');
});

test('生命周期：未 dial 先 send/receive → STATE；重复 dial → STATE；构造参数非法 → STATE', async () => {
  const server: FakeControlServer = makeServer();
  const client: ControlClient = makeClient(server, serverStaticKeys().publicKey, new FixedClock(0));
  const req: RegisterRequest = { nodeKey: fixedKey(1), discoKey: fixedKey(2), endpoints: [] };
  await rejectCode((): Promise<void> => client.send(registerRequestEncode(req)), 'STATE');
  await rejectCode((): Promise<ControlMessage> => client.receive(), 'STATE');

  await client.dial();
  await rejectCode((): Promise<void> => client.dial(), 'STATE');
  client.close();

  // 构造参数：密钥长度不足 32B
  const machineKeys: CryptoKeyPair = x25519GenerateKeyPair(new ArrayRng(makePool(0xa1, 32)));
  const badConfig: ControlClientConfig = {
    controlUrl: 'https://net.example.test',
    nodeKeyPair: { publicKey: fixedKey(1), privateKey: fixedKey(2) },
    machineKeyPair: machineKeys,
    serverStaticPublic: fixedKey(3).slice(0, 31),
    transport: server,
    clock: new FixedClock(0),
    rng: new ArrayRng(makePool(0xc3, 32)),
  };
  assertControlCode((): void => {
    const badClient: ControlClient = new ControlClient(badConfig);
    void badClient;
  }, 'STATE');
  // controlUrl 为空
  const badUrl: ControlClientConfig = {
    controlUrl: '',
    nodeKeyPair: { publicKey: fixedKey(1), privateKey: fixedKey(2) },
    machineKeyPair: machineKeys,
    serverStaticPublic: fixedKey(3),
    transport: server,
    clock: new FixedClock(0),
    rng: new ArrayRng(makePool(0xc3, 32)),
  };
  assertControlCode((): void => {
    const badClient2: ControlClient = new ControlClient(badUrl);
    void badClient2;
  }, 'STATE');

  // close() 释放会话后可重新 dial() 建立全新会话（评审第 1 项恢复路径）
  server.beginNewSession();
  await client.dial();
  const pong: ControlMessage = { kind: ControlMsgKind.Pong, fields: [] };
  server.queueToClient(controlEncodeMessage(pong));
  const got: ControlMessage = await client.receive();
  assert.equal(got.kind, ControlMsgKind.Pong, 'fresh session after close()+dial() must work end to end');
});

test('会话恢复：流帧间断开 → HTTP → 新流继续接收（半帧缓存已复位、计数器跨流连续）', async () => {
  const server: FakeControlServer = makeServer();
  const client: ControlClient = makeClient(server, serverStaticKeys().publicKey, new FixedClock(0));
  await client.dial();

  const first: ControlMessage = { kind: ControlMsgKind.KeepAlive, fields: [] };
  server.queueToClient(controlEncodeMessage(first));
  const gotFirst: ControlMessage = await client.receive();
  assert.equal(gotFirst.kind, ControlMsgKind.KeepAlive);

  // 流内无更多数据 → receive 报 HTTP 并释放流（半帧缓存随流复位，评审第 1 项修复点）
  await rejectCode((): Promise<ControlMessage> => client.receive(), 'HTTP');

  // 服务端在同一 Noise 会话上续推（服务端 send 计数器连续），客户端在新流上恢复接收
  const second: ControlMessage = { kind: ControlMsgKind.Ping, fields: [] };
  server.queueToClient(controlEncodeMessage(second));
  const gotSecond: ControlMessage = await client.receive();
  assert.equal(gotSecond.kind, ControlMsgKind.Ping, 'receive must resume on a fresh poll stream');
});

test('会话恢复：半帧在途丢失 → HTTP → 同会话 NOISE（AEAD 失步）→ close()+dial() 新会话恢复', async () => {
  const server: FakeControlServer = makeServer();
  const client: ControlClient = makeClient(server, serverStaticKeys().publicKey, new FixedClock(0));
  await client.dial();

  const f1: ControlMessage = { kind: ControlMsgKind.KeepAlive, fields: [] };
  server.queueToClient(controlEncodeMessage(f1));
  const got1: ControlMessage = await client.receive();
  assert.equal(got1.kind, ControlMsgKind.KeepAlive);

  // 评审第 1 项复现：f2 只送出前 5 字节即流终止（半帧被缓存）→ HTTP
  const f2: ControlMessage = { kind: ControlMsgKind.Ping, fields: [] };
  server.queueToClientPartial(controlEncodeMessage(f2), 5);
  await rejectCode((): Promise<ControlMessage> => client.receive(), 'HTTP');

  // f2 已丢失（服务端 send 计数器 +1），同会话续推必然 AEAD 失步 → NOISE
  const f3: ControlMessage = { kind: ControlMsgKind.Pong, fields: [] };
  server.queueToClient(controlEncodeMessage(f3));
  await rejectCode((): Promise<ControlMessage> => client.receive(), 'NOISE');

  // 唯一恢复路径：close() + dial() 建立全新会话（此前被重复 dial 检查禁止）
  client.close();
  server.beginNewSession();
  await client.dial();
  const f4: ControlMessage = { kind: ControlMsgKind.KeepAlive, fields: [] };
  server.queueToClient(controlEncodeMessage(f4));
  const got4: ControlMessage = await client.receive();
  assert.equal(got4.kind, ControlMsgKind.KeepAlive, 'close()+dial() must establish a working new session');
});

test('错误路径资源（评审第 3 项）：open 非 2xx → HTTP 且底层流被关闭', async () => {
  const server: FakeControlServer = makeServer();
  const client: ControlClient = makeClient(server, serverStaticKeys().publicKey, new FixedClock(0));
  await client.dial();
  server.openStatus = 401;
  await rejectCode((): Promise<ControlMessage> => client.receive(), 'HTTP');
  assert.notEqual(server.lastBody, null, 'open() must have produced a body');
  const body: FakeBodyStream = server.lastBody as FakeBodyStream;
  assert.equal(body.isClosed(), true, 'non-2xx open response body must be closed before throwing');
});

test('错误路径资源（评审第 3 项）：流读失败 → HTTP、底层流被关闭，新流可恢复', async () => {
  const server: FakeControlServer = makeServer();
  const client: ControlClient = makeClient(server, serverStaticKeys().publicKey, new FixedClock(0));
  await client.dial();
  server.failNextRead = true;
  await rejectCode((): Promise<ControlMessage> => client.receive(), 'HTTP');
  assert.notEqual(server.lastBody, null);
  const dead: FakeBodyStream = server.lastBody as FakeBodyStream;
  assert.equal(dead.isClosed(), true, 'failed stream body must be closed before throwing');
  // 弃流后新流从零对齐（半帧缓存随流复位），同一会话恢复接收
  const ping: ControlMessage = { kind: ControlMsgKind.Ping, fields: [] };
  server.queueToClient(controlEncodeMessage(ping));
  const got: ControlMessage = await client.receive();
  assert.equal(got.kind, ControlMsgKind.Ping, 'receive must resume on a fresh stream after a read failure');
});

test('send 尺寸预检（评审第 2 项）：明文 65520B → ControlError(TLV) 不泄漏 NoiseError；边界 65519B 可发', async () => {
  const server: FakeControlServer = makeServer();
  const client: ControlClient = makeClient(server, serverStaticKeys().publicKey, new FixedClock(0));
  await client.dial();
  // 明文 = 5(MsgKind 字段) + 4(字段头) + N：N=65510 → 65519B 恰为单帧容量上界，放行
  const edgeOk: ControlMessage = {
    kind: ControlMsgKind.MapRequest,
    fields: [{ type: ControlTlvType.PacketFilter, value: makePool(0x2c, 65510) }],
  };
  await client.send(edgeOk);
  assert.equal(server.lastPlaintext.length, 65519, 'boundary plaintext must reach the server intact');
  // N=65511 → 明文 65520B > 65519B：TLV 层合法（单字段 ≤ 65535B）但通道放不下 → 预检 ControlError('TLV')
  const tooBig: ControlMessage = {
    kind: ControlMsgKind.MapRequest,
    fields: [{ type: ControlTlvType.PacketFilter, value: makePool(0x2d, 65511) }],
  };
  await rejectCode((): Promise<void> => client.send(tooBig), 'TLV');
  // 拒绝发生在加密/发送之前：transport 只收到 dial + 首条 send 两次请求
  assert.equal(server.requests.length, 2, 'oversized message must be rejected before any transport send');
});

test('确定性（§7.3）：FixedClock/ArrayRng 注入下同一脚本两次运行字节一致', async () => {
  const runRegistration = async (): Promise<Uint8Array[]> => {
    const keys: CryptoKeyPair = serverStaticKeys();
    const server: FakeControlServer = new FakeControlServer(keys.privateKey, new ArrayRng(makePool(0xd4, 32)));
    const client: ControlClient = makeClient(server, keys.publicKey, new FixedClock(1000));
    await client.dial();
    const req: RegisterRequest = { nodeKey: client.nodeKey(), discoKey: fixedKey(60), endpoints: ['10.0.0.1:41641'] };
    await client.send(registerRequestEncode(req));
    client.close();
    const bodies: Uint8Array[] = [server.requests[0].body, server.requests[1].body];
    return bodies;
  };
  const run1: Uint8Array[] = await runRegistration();
  const run2: Uint8Array[] = await runRegistration();
  assert.deepEqual(run2, run1, 'identical injected entropy must reproduce identical bytes end to end');
});

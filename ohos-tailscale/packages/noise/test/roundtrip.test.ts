/**
 * ts2021 会话层全往返测试（任务要求：用注入传输编写模拟服务器与客户端的完整往返；
 * 架构契约 §6/§7.1 形态，HttpTransport 为 common 冻结注入接口）。
 *
 * 拓扑：TestControlClient（NoiseIkInitiator）⇄ FakeControlTransport（注入）
 *       ⇄ FakeControlServer（NoiseIkResponder，帧重组 + 传输解密 + 应答）。
 * - 握手走 POST /ts2021（send，缓冲响应）；
 * - 客户端消息走 POST /c2s：帧化（noiseFrameEncode）+ 传输加密，服务端逐帧解密；
 * - 服务端推送走 POST /long-poll（open，流式响应）：两帧被切成 3 个 chunk
 *   （半帧 + 粘包混合），客户端用 NoiseFrameReader 重组后解密；
 * - 全程 ArrayRng 固定池 + FixedClock 语义无关（noise 不读时钟），线上字节与
 *   独立 node:crypto 参考实现逐字节对照（确定性向量）。
 */

import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  ArrayRng,
  utf8Encode,
  type HttpBodyStream,
  type HttpRequest,
  type HttpResponse,
  type HttpTransport,
  type Rng,
  type StreamingHttpResponse,
} from '@ohos-tailscale/common';
import { x25519GenerateKeyPair, x25519PublicKeyFromPrivate, type CryptoKeyPair } from '@ohos-tailscale/crypto';
import {
  NoiseError,
  NoiseFrameReader,
  NoiseIkInitiator,
  NoiseIkResponder,
  noiseFrameEncode,
  type NoiseFrame,
  type NoiseIkPayload,
  type NoiseTransportPair,
} from '../src/index.ts';
import { concat2, referenceHandshake, refTransportSeal, u16beBytes, type RefKeys, type RefHandshakeResult } from './reference.test.ts';

// ---------------------------------------------------------------------------
// 固定随机数与共享参数（与 handshake.test.ts 同源，保证跨文件向量一致性）
// ---------------------------------------------------------------------------

const seqPool = (start: number, n: number): Uint8Array => {
  const out: Uint8Array = new Uint8Array(n);
  for (let i: number = 0; i < n; i += 1) {
    out[i] = (start + i) & 0xff;
  }
  return out;
};

const STATIC_I_POOL: Uint8Array = seqPool(0x11, 32);
const STATIC_R_POOL: Uint8Array = seqPool(0x51, 32);
const EPH_I_POOL: Uint8Array = seqPool(0xa1, 32);
const EPH_R_POOL: Uint8Array = seqPool(0xc1, 32);
const PROLOGUE: Uint8Array = utf8Encode('ohos-tailscale/ts2021-prologue-v1');

const TS2021_URL: string = 'https://control.example.net/ts2021';
const C2S_URL: string = 'https://control.example.net/c2s';
const POLL_URL: string = 'https://control.example.net/long-poll';

function baseHeaders(): Record<string, string> {
  const h: Record<string, string> = { 'content-type': 'application/octet-stream' };
  return h;
}

function refKeysOf(iStatic: CryptoKeyPair, rStatic: CryptoKeyPair): RefKeys {
  const keys: RefKeys = {
    iStaticPriv: iStatic.privateKey,
    iStaticPub: iStatic.publicKey,
    rStaticPriv: rStatic.privateKey,
    rStaticPub: rStatic.publicKey,
    iEphPriv: EPH_I_POOL,
    iEphPub: x25519PublicKeyFromPrivate(EPH_I_POOL),
    rEphPriv: EPH_R_POOL,
    rEphPub: x25519PublicKeyFromPrivate(EPH_R_POOL),
  };
  return keys;
}

// ---------------------------------------------------------------------------
// 模拟服务端（Noise 响应方 + 会话层）
// ---------------------------------------------------------------------------

class FakeControlServer {
  private responder: NoiseIkResponder;
  private pair: NoiseTransportPair | null = null;
  private reader: NoiseFrameReader = new NoiseFrameReader();
  private pendingPollChunks: Uint8Array[] = [];

  public lastRemoteStatic: Uint8Array = new Uint8Array(0);
  public handshakePayload: Uint8Array = new Uint8Array(0);
  public lastHandshakeBody: Uint8Array = new Uint8Array(0);
  public received: Uint8Array[] = [];
  public c2sBodies: Uint8Array[] = [];
  public servedPollChunks: Uint8Array[] = [];
  public lastRequestMethod: string = '';
  public lastRequestUrl: string = '';

  public constructor(staticPrivate: Uint8Array, rng: Rng) {
    this.responder = new NoiseIkResponder(PROLOGUE, staticPrivate, rng);
  }

  private requirePair(): NoiseTransportPair {
    if (this.pair === null) {
      throw new NoiseError('STATE', 'fake server: handshake not completed');
    }
    return this.pair;
  }

  /** 服务端排入待推送消息：用自身发送密钥加密、帧化并切成 3 个 chunk（半帧+粘包混合）。 */
  public enqueuePoll(msgs: Uint8Array[]): void {
    const frames: Uint8Array[] = [];
    for (const m of msgs) {
      frames.push(noiseFrameEncode(this.requirePair().send.encrypt(m)));
    }
    const f1: Uint8Array = frames[0];
    const f2: Uint8Array = frames[1];
    const chunk1: Uint8Array = f1.slice(0, 5);
    const chunk2: Uint8Array = concat2(f1.slice(5), f2.slice(0, 3));
    const chunk3: Uint8Array = f2.slice(3);
    this.pendingPollChunks = [chunk1, chunk2, chunk3];
  }

  public pendingBytes(): number {
    return this.reader.pendingBytes();
  }

  public async handleSend(request: HttpRequest): Promise<HttpResponse> {
    this.lastRequestMethod = request.method;
    this.lastRequestUrl = request.url;
    if (request.url === TS2021_URL) {
      const readA: NoiseIkPayload = this.responder.readMessageA(request.body);
      this.lastRemoteStatic = readA.remoteStatic;
      this.handshakePayload = readA.payload;
      const msgB: Uint8Array = this.responder.writeMessageB(new Uint8Array(0));
      this.lastHandshakeBody = msgB;
      this.pair = this.responder.split();
      const resp: HttpResponse = { status: 200, headers: baseHeaders(), body: msgB };
      return resp;
    }
    if (request.url === C2S_URL) {
      this.c2sBodies.push(request.body.slice());
      const frames: NoiseFrame[] = this.reader.push(request.body);
      for (const frame of frames) {
        this.received.push(this.requirePair().recv.decrypt(frame.payload));
      }
      const resp: HttpResponse = { status: 200, headers: baseHeaders(), body: new Uint8Array(0) };
      return resp;
    }
    throw new Error('fake server: unexpected url ' + request.url);
  }

  public async handleOpen(request: HttpRequest): Promise<StreamingHttpResponse> {
    this.lastRequestMethod = request.method;
    this.lastRequestUrl = request.url;
    const stream: HttpBodyStream = new ScriptedBodyStream(this.pendingPollChunks, this.servedPollChunks);
    this.pendingPollChunks = [];
    const resp: StreamingHttpResponse = { status: 200, headers: baseHeaders(), body: stream };
    return resp;
  }
}

class ScriptedBodyStream implements HttpBodyStream {
  private chunks: Uint8Array[];
  private served: Uint8Array[];
  private closed: boolean = false;

  public constructor(chunks: Uint8Array[], served: Uint8Array[]) {
    this.chunks = chunks.slice();
    this.served = served;
  }

  public async read(): Promise<Uint8Array | null> {
    if (this.closed) {
      return null;
    }
    const next: Uint8Array | undefined = this.chunks.shift();
    if (next === undefined) {
      return null;
    }
    this.served.push(next.slice());
    return next;
  }

  public close(): void {
    this.closed = true;
  }
}

class FakeControlTransport implements HttpTransport {
  private server: FakeControlServer;

  public constructor(server: FakeControlServer) {
    this.server = server;
  }

  public async send(request: HttpRequest): Promise<HttpResponse> {
    return this.server.handleSend(request);
  }

  public async open(request: HttpRequest): Promise<StreamingHttpResponse> {
    return this.server.handleOpen(request);
  }
}

// ---------------------------------------------------------------------------
// 模拟客户端（Noise 发起方 + 会话层）
// ---------------------------------------------------------------------------

class TestControlClient {
  private transport: HttpTransport;
  private initiator: NoiseIkInitiator;
  private pair: NoiseTransportPair | null = null;
  private reader: NoiseFrameReader = new NoiseFrameReader();

  public lastDialBody: Uint8Array = new Uint8Array(0);

  public constructor(transport: HttpTransport, initiator: NoiseIkInitiator) {
    this.transport = transport;
    this.initiator = initiator;
  }

  private requirePair(): NoiseTransportPair {
    if (this.pair === null) {
      throw new NoiseError('STATE', 'fake client: dial() not completed');
    }
    return this.pair;
  }

  /** 完成握手：POST /ts2021 → readMessageB → split。 */
  public async dial(): Promise<void> {
    const msgA: Uint8Array = this.initiator.writeMessageA(new Uint8Array(0));
    this.lastDialBody = msgA.slice();
    const req: HttpRequest = { method: 'POST', url: TS2021_URL, headers: baseHeaders(), body: msgA };
    const resp: HttpResponse = await this.transport.send(req);
    if (resp.status !== 200) {
      throw new Error('dial failed: status ' + String(resp.status));
    }
    this.initiator.readMessageB(resp.body);
    this.pair = this.initiator.split();
  }

  /** 发一条会话消息：传输加密 → 帧化 → POST /c2s。返回线上字节供断言。 */
  public async send(plaintext: Uint8Array): Promise<Uint8Array> {
    const body: Uint8Array = noiseFrameEncode(this.requirePair().send.encrypt(plaintext));
    const req: HttpRequest = { method: 'POST', url: C2S_URL, headers: baseHeaders(), body: body };
    const resp: HttpResponse = await this.transport.send(req);
    if (resp.status !== 200) {
      throw new Error('send failed: status ' + String(resp.status));
    }
    return body;
  }

  /** 长轮询接收：open 流式读 chunk → 帧重组 → 传输解密，流结束返回全部明文。 */
  public async receive(): Promise<Uint8Array[]> {
    const req: HttpRequest = { method: 'POST', url: POLL_URL, headers: baseHeaders(), body: new Uint8Array(0) };
    const resp: StreamingHttpResponse = await this.transport.open(req);
    if (resp.status !== 200) {
      throw new Error('receive failed: status ' + String(resp.status));
    }
    const out: Uint8Array[] = [];
    for (;;) {
      const chunk: Uint8Array | null = await resp.body.read();
      if (chunk === null) {
        break;
      }
      const frames: NoiseFrame[] = this.reader.push(chunk);
      for (const frame of frames) {
        out.push(this.requirePair().recv.decrypt(frame.payload));
      }
    }
    resp.body.close();
    return out;
  }

  /** 发一个已损坏的帧（测试失败路径用）。 */
  public async sendRawCorrupted(wire: Uint8Array): Promise<void> {
    const req: HttpRequest = { method: 'POST', url: C2S_URL, headers: baseHeaders(), body: wire };
    const resp: HttpResponse = await this.transport.send(req);
    if (resp.status !== 200) {
      throw new Error('send failed: status ' + String(resp.status));
    }
  }
}

// ---------------------------------------------------------------------------
// 测试
// ---------------------------------------------------------------------------

interface SessionFixture {
  server: FakeControlServer;
  client: TestControlClient;
  keys: RefKeys;
  iStatic: CryptoKeyPair;
}

function buildSession(): SessionFixture {
  const iStatic: CryptoKeyPair = x25519GenerateKeyPair(new ArrayRng(STATIC_I_POOL));
  const rStatic: CryptoKeyPair = x25519GenerateKeyPair(new ArrayRng(STATIC_R_POOL));
  const server: FakeControlServer = new FakeControlServer(rStatic.privateKey, new ArrayRng(EPH_R_POOL));
  const initiator: NoiseIkInitiator = new NoiseIkInitiator(
    PROLOGUE,
    iStatic.privateKey,
    rStatic.publicKey,
    new ArrayRng(EPH_I_POOL),
  );
  const client: TestControlClient = new TestControlClient(new FakeControlTransport(server), initiator);
  const fx: SessionFixture = {
    server: server,
    client: client,
    keys: refKeysOf(iStatic, rStatic),
    iStatic: iStatic,
  };
  return fx;
}

test('ts2021 会话全往返：握手 + 双向消息 + 长轮询推送（注入 HttpTransport）', async (): Promise<void> => {
  const fx: SessionFixture = buildSession();
  const ref: RefHandshakeResult = referenceHandshake(fx.keys, PROLOGUE, new Uint8Array(0), new Uint8Array(0));

  // ---- 1. 握手：客户端 POST /ts2021，线上字节 = 参考 msgA；响应 = 参考 msgB ----
  await fx.client.dial();
  assert.deepEqual(fx.client.lastDialBody, ref.msgA, 'dial wire bytes must equal reference msgA');
  assert.equal(fx.server.lastRequestMethod, 'POST');
  assert.equal(fx.server.lastRequestUrl, TS2021_URL);
  assert.deepEqual(fx.server.lastRemoteStatic, fx.iStatic.publicKey, 'server must authenticate client static key');
  assert.equal(fx.server.handshakePayload.length, 0);
  assert.deepEqual(fx.server.lastHandshakeBody, ref.msgB, 'server msgB must equal reference msgB');

  // ---- 2. 客户端 → 服务端两条消息（计数器 0、1），线上字节与参考对照 ----
  const msg1: Uint8Array = utf8Encode('map-request-#1: nodes, derpmap, dns');
  const msg2: Uint8Array = seqPool(0x60, 700); // 长载荷跨多块
  const wire1: Uint8Array = await fx.client.send(msg1);
  const ct1: Uint8Array = refTransportSeal(ref.iToSend, 0n, msg1);
  assert.deepEqual(wire1, concat2(u16beBytes(ct1.length), ct1), 'c2s wire #1 must equal reference frame');
  const wire2: Uint8Array = await fx.client.send(msg2);
  const ct2: Uint8Array = refTransportSeal(ref.iToSend, 1n, msg2);
  assert.deepEqual(wire2, concat2(u16beBytes(ct2.length), ct2), 'c2s wire #2 must equal reference frame');
  assert.deepEqual(fx.server.received[0], msg1, 'server must decrypt message 1');
  assert.deepEqual(fx.server.received[1], msg2, 'server must decrypt message 2');

  // ---- 3. keepalive：零长度载荷照样成帧加密 ----
  const wire3: Uint8Array = await fx.client.send(new Uint8Array(0));
  const ct3: Uint8Array = refTransportSeal(ref.iToSend, 2n, new Uint8Array(0));
  assert.deepEqual(wire3, concat2(u16beBytes(ct3.length), ct3));
  assert.equal(fx.server.received[2].length, 0);

  // ---- 4. 服务端推送：两帧切 3 chunk（半帧+粘包），客户端重组解密 ----
  const sm1: Uint8Array = utf8Encode('map-response-full: netmap snapshot');
  const sm2: Uint8Array = seqPool(0x90, 260);
  fx.server.enqueuePoll([sm1, sm2]);
  // 参考侧独立重算服务端应当发出的 3 个 chunk（确定性向量）
  const rf1: Uint8Array = concat2(u16beBytes(refTransportSeal(ref.iToRecv, 0n, sm1).length), refTransportSeal(ref.iToRecv, 0n, sm1));
  const rf2: Uint8Array = concat2(u16beBytes(refTransportSeal(ref.iToRecv, 1n, sm2).length), refTransportSeal(ref.iToRecv, 1n, sm2));
  const expectedChunks: Uint8Array[] = [rf1.slice(0, 5), concat2(rf1.slice(5), rf2.slice(0, 3)), rf2.slice(3)];
  const got: Uint8Array[] = await fx.client.receive();
  assert.deepEqual(fx.server.servedPollChunks, expectedChunks, 'served poll chunks must equal reference bytes');
  assert.equal(got.length, 2);
  assert.deepEqual(got[0], sm1, 'client must reassemble+decrypt push #1');
  assert.deepEqual(got[1], sm2, 'client must reassemble+decrypt push #2');
  assert.equal(fx.server.pendingBytes(), 0);

  // ---- 5. 推送后双向继续可用 ----
  const msg3: Uint8Array = utf8Encode('after-poll-message');
  await fx.client.send(msg3);
  assert.deepEqual(fx.server.received[3], msg3);
});

test('会话失败路径：篡改帧 → 服务端 NoiseError(DECRYPT)，会话可恢复', async (): Promise<void> => {
  const fx: SessionFixture = buildSession();
  await fx.client.dial();

  const msg1: Uint8Array = utf8Encode('before-corruption');
  await fx.client.send(msg1);
  assert.deepEqual(fx.server.received[0], msg1);

  // 正常送达第二条，作为篡改的素材
  const good: Uint8Array = await fx.client.send(utf8Encode('to-be-tampered'));
  assert.deepEqual(fx.server.received[1], utf8Encode('to-be-tampered'));

  // 篡改该帧正文后重放 → 服务端在旧计数器上解不开
  const bad: Uint8Array = good.slice();
  bad[10] = (bad[10] ^ 0x40) & 0xff;
  let rejected: boolean = false;
  let gotCode: string = '';
  try {
    await fx.client.sendRawCorrupted(bad);
  } catch (e) {
    rejected = true;
    const err: NoiseError = e as NoiseError;
    gotCode = err.code;
  }
  assert.equal(rejected, true, 'tampered frame must be rejected by server');
  assert.equal(gotCode, 'DECRYPT', 'rejection must be NoiseError(DECRYPT)');

  // 服务端接收计数器未因失败推进 → 客户端下一条（新计数器）仍按序解出
  const msg2: Uint8Array = utf8Encode('after-corruption');
  await fx.client.send(msg2);
  assert.deepEqual(fx.server.received[2], msg2);
  assert.equal(fx.server.pendingBytes(), 0);
});

test('注入边界自检：会话组件的全部不确定来源均来自构造注入的 ArrayRng', async (): Promise<void> => {
  // P4：noise 不读时钟、不读全局随机；临时密钥只经构造注入的 Rng 产生。
  // 同一批池重跑两次，全链路线上字节必须完全一致（端到端可复现）。
  const runA: SessionFixture = buildSession();
  const runB: SessionFixture = buildSession();
  await runA.client.dial();
  await runB.client.dial();
  assert.deepEqual(runA.client.lastDialBody, runB.client.lastDialBody);
  const wa: Uint8Array = await runA.client.send(utf8Encode('determinism-probe'));
  const wb: Uint8Array = await runB.client.send(utf8Encode('determinism-probe'));
  assert.deepEqual(wa, wb, 'identical injected randomness must produce identical wire bytes');
});

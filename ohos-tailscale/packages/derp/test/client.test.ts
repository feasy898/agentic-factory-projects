import { test } from 'node:test';
import assert from 'node:assert/strict';
import nacl from 'tweetnacl';
import { ArrayRng, ByteWriter, FixedClock, utf8Encode } from '@ohos-tailscale/common';
import {
  DerpError,
  type DerpFrame,
  DerpFrameType,
  derpFrameDecode,
  derpFrameEncode,
} from '../src/frame.ts';
import {
  DerpClient,
  type DerpClientConfig,
  type DerpClientEvent,
  DerpClientEventKind,
  DerpClientState,
} from '../src/client.ts';
import { type DerpConnection, type DerpDialer } from '../src/connection.ts';
import { type DerpNode } from '../src/region.ts';

/**
 * AU2 对齐的真实协议流测试：
 *
 *   connect()：ServerKey(Magic(8B)+服务器公钥(32B)) ← / ClientInfo → / ServerInfo ← → Ready
 *   ClientInfo 载荷 = 本端公钥(32B) || nonce(24B) || naclbox(JSON)
 *
 * 独立性策略：假服务器的私钥自造（fill 0x99），公钥用 tweetnacl 侧 scalarMult.base 推导
 * （不经我方 x25519 实现）；ClientInfo 的 naclbox 也用 tweetnacl box.open 从服务器私钥
 * 视角解封验证——整条握手只有"解封用的密码学原语"是外部参考实现。
 */

// ---- 协议常量（死字节，按上游 derp.go） ----

const DERP_MAGIC_UPSTREAM: Uint8Array = Uint8Array.from([0x44, 0x45, 0x52, 0x50, 0xf0, 0x9f, 0x94, 0x91]); // "DERP🔑"
// MeshKey 必须整字段省略（DERPMesh 类型拒收空串，headscale v0.29.4 实测锚定，见 src/client.ts 头注）
const CLIENT_INFO_JSON: string =
  '{"Version":2,"CanAckPings":false,"IsProber":false,"AppName":"ohos-tailscale"}';
const SERVER_PRIVATE_KEY: Uint8Array = new Uint8Array(32).fill(0x99); // 假服务器私钥（自造）
const SERVER_PUBLIC_KEY: Uint8Array = nacl.scalarMult.base(SERVER_PRIVATE_KEY); // tweetnacl 侧独立推导
const CLIENT_PRIVATE_KEY: Uint8Array = new Uint8Array(32).fill(0x22); // 本端 node 私钥
// 本端 node 公钥：必须与私钥配对 naclbox 才能解封；用 tweetnacl 侧独立推导
const CLIENT_PUBLIC_KEY: Uint8Array = nacl.scalarMult.base(CLIENT_PRIVATE_KEY);
const RNG_POOL: Uint8Array = Uint8Array.from([0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88, 0x99]);

// ---- 测试脚手架：脚本化 fake 连接/拨号器（网络全部注入） ----

class FakeConn implements DerpConnection {
  public written: Uint8Array[] = [];
  public closedFlag: boolean = false;
  private script: Uint8Array[];

  constructor(script: Uint8Array[]) {
    this.script = script.slice();
  }

  public async write(data: Uint8Array): Promise<void> {
    this.written.push(data.slice());
  }

  public async read(): Promise<Uint8Array | null> {
    if (this.script.length === 0) {
      return null;
    }
    const next: Uint8Array | undefined = this.script.shift();
    if (next === undefined) {
      return null;
    }
    return next;
  }

  public close(): void {
    this.closedFlag = true;
  }

  public enqueue(chunk: Uint8Array): void {
    this.script.push(chunk);
  }
}

class FakeDialer implements DerpDialer {
  public conn: FakeConn;

  constructor(script: Uint8Array[]) {
    this.conn = new FakeConn(script);
  }

  public async dial(node: DerpNode): Promise<DerpConnection> {
    return this.conn;
  }
}

class BoomDialer implements DerpDialer {
  public async dial(node: DerpNode): Promise<DerpConnection> {
    throw new Error('tls refused');
  }
}

// ---- 小工具 ----

function keyBytes(fill: number): Uint8Array {
  const k: Uint8Array = new Uint8Array(32);
  k.fill(fill);
  return k;
}

function concatBytes(a: Uint8Array, b: Uint8Array): Uint8Array {
  const out: Uint8Array = new Uint8Array(a.length + b.length);
  out.set(a, 0);
  out.set(b, a.length);
  return out;
}

function concat3(a: Uint8Array, b: Uint8Array, c: Uint8Array): Uint8Array {
  const out: Uint8Array = new Uint8Array(a.length + b.length + c.length);
  out.set(a, 0);
  out.set(b, a.length);
  out.set(c, a.length + b.length);
  return out;
}

/** 5 字节帧头死字节构造：type u8 || length u32BE。 */
function frameHeader(type: number, payloadLen: number): Uint8Array {
  const w: ByteWriter = new ByteWriter(5);
  w.writeU8(type);
  w.writeU32be(payloadLen);
  return w.toUint8Array();
}

function mkNode(): DerpNode {
  const n: DerpNode = {
    name: '999',
    hostName: 'derp.example.com',
    certName: '',
    ipv4: '198.51.100.30',
    ipv6: '',
    stunPort: 3478,
    derpPort: 443,
    canPort80: false,
  };
  return n;
}

function mkCfg(dialer: DerpDialer, clock: FixedClock): DerpClientConfig {
  const rng: ArrayRng = new ArrayRng(RNG_POOL);
  const cfg: DerpClientConfig = {
    node: mkNode(),
    nodeKey: CLIENT_PUBLIC_KEY,
    nodePrivateKey: CLIENT_PRIVATE_KEY,
    dialer: dialer,
    clock: clock,
    rng: rng,
  };
  return cfg;
}

function mkCfgWithKeys(dialer: DerpDialer, nodeKey: Uint8Array, nodePrivateKey: Uint8Array): DerpClientConfig {
  const cfg: DerpClientConfig = {
    node: mkNode(),
    nodeKey: nodeKey,
    nodePrivateKey: nodePrivateKey,
    dialer: dialer,
    clock: new FixedClock(0),
    rng: new ArrayRng(RNG_POOL),
  };
  return cfg;
}

/** 假服务器 ServerKey 帧：Magic(8B) || 服务器公钥(32B)。 */
function serverKeyFrame(serverPub: Uint8Array): Uint8Array {
  const payload: Uint8Array = new Uint8Array(DERP_MAGIC_UPSTREAM.length + serverPub.length);
  payload.set(DERP_MAGIC_UPSTREAM, 0);
  payload.set(serverPub, DERP_MAGIC_UPSTREAM.length);
  return derpFrameEncode(DerpFrameType.ServerKey, payload);
}

/** 假服务器 ServerInfo 帧：nonce(24B)+naclbox 形态（40B 占位）；客户端按类型静默跳过。 */
function serverInfoFrame(): Uint8Array {
  return derpFrameEncode(DerpFrameType.ServerInfo, new Uint8Array(40));
}

function recvPacketFrame(src: Uint8Array, packet: Uint8Array): Uint8Array {
  return derpFrameEncode(DerpFrameType.RecvPacket, concatBytes(src, packet));
}

/** 用 tweetnacl 从"假服务器私钥"视角独立解封 ClientInfo 的 naclbox 段。 */
function openedClientInfoJson(clientInfoPayload: Uint8Array): Uint8Array {
  const opened: Uint8Array | null = nacl.box.open(
    clientInfoPayload.slice(56), // 16B tag + 密文
    clientInfoPayload.slice(32, 56), // nonce 24B
    clientInfoPayload.slice(0, 32), // 本端公钥（theirPublicKey）
    SERVER_PRIVATE_KEY, // mySecretKey
  );
  assert.ok(opened !== null, 'tweetnacl must open ClientInfo naclbox');
  return opened;
}

function derpCodeOf(e: Error): string | null {
  if (e instanceof DerpError) {
    return e.code;
  }
  return null;
}

async function grabError(p: Promise<DerpClientEvent | null | void>): Promise<Error | null> {
  try {
    await p;
  } catch (e) {
    return e as Error;
  }
  return null;
}

async function grabCode(p: Promise<DerpClientEvent | null | void>): Promise<string | null> {
  const e: Error | null = await grabError(p);
  if (e === null) {
    return null;
  }
  return derpCodeOf(e);
}

/** 生命周期错误（状态机非法迁移/拨号失败）：必须是普通 Error，不得占用契约 code 集合。 */
async function assertLifecycleError(p: Promise<DerpClientEvent | null | void>, pattern: RegExp): Promise<void> {
  const e: Error | null = await grabError(p);
  assert.ok(e !== null, 'expected an error');
  if (e !== null) {
    assert.equal(derpCodeOf(e), null);
    assert.match(e.message, pattern);
  }
}

// ---- 握手/连接 ----

test('connect 握手：ServerKey(Magic+公钥) → ClientInfo(naclbox JSON) → ServerInfo → Ready', async (): Promise<void> => {
  const clock: FixedClock = new FixedClock(1000);
  const dialer: FakeDialer = new FakeDialer([serverKeyFrame(SERVER_PUBLIC_KEY), serverInfoFrame()]);
  const client: DerpClient = new DerpClient(mkCfg(dialer, clock));
  assert.equal(client.getState(), DerpClientState.Idle);
  assert.equal(client.serverKey(), null);
  await client.connect();
  assert.equal(client.getState(), DerpClientState.Ready);
  // 服务器公钥取自 ServerKey 载荷后 32B，且返回独立拷贝
  const sk: Uint8Array | null = client.serverKey();
  assert.ok(sk !== null);
  if (sk !== null) {
    assert.deepEqual(sk, SERVER_PUBLIC_KEY);
    sk.fill(0x00);
    assert.deepEqual(client.serverKey(), SERVER_PUBLIC_KEY);
  }

  // 客户端在握手中只应发出一帧：ClientInfo
  assert.equal(dialer.conn.written.length, 1);
  const written: Uint8Array = dialer.conn.written[0];
  const jsonLen: number = utf8Encode(CLIENT_INFO_JSON).length;
  assert.equal(jsonLen, 77); // JSON 载荷宽度死值（MeshKey 整字段省略后）
  const payloadLen: number = 32 + 24 + jsonLen + 16; // 公钥 || nonce || tag+密文
  assert.equal(written.length, 5 + payloadLen);
  assert.deepEqual(written.slice(0, 5), frameHeader(0x02, payloadLen)); // 帧头死字节：0x02 + u32BE
  const f: DerpFrame = derpFrameDecode(written);
  assert.equal(f.type, DerpFrameType.ClientInfo);
  const payload: Uint8Array = f.payload;
  assert.deepEqual(payload.slice(0, 32), CLIENT_PUBLIC_KEY); // 前段 = 本端公钥（与封私钥配对）
  // nonce = 注入 ArrayRng 的前 24B（9B 池循环两圈 + 6B）
  assert.deepEqual(
    payload.slice(32, 56),
    Uint8Array.from([
      0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88, 0x99,
      0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88, 0x99,
      0x11, 0x22, 0x33, 0x44, 0x55, 0x66,
    ]),
  );
  // naclbox 用 tweetnacl 独立解封：明文必须是上游 ClientInfo 的 JSON
  assert.deepEqual(
    Array.from(openedClientInfoJson(payload)),
    Array.from(utf8Encode(CLIENT_INFO_JSON)),
  );

  client.close();
  assert.equal(client.getState(), DerpClientState.Closed);
  assert.ok(dialer.conn.closedFlag);
});

test('connect：ServerKey 帧分片到达也能重组（含帧头内切分）', async (): Promise<void> => {
  const frame: Uint8Array = serverKeyFrame(SERVER_PUBLIC_KEY);
  const dialer: FakeDialer = new FakeDialer([
    frame.slice(0, 2), // 魔数前 2B（头内切分）
    frame.slice(2, 9),
    frame.slice(9),
    serverInfoFrame(),
  ]);
  const client: DerpClient = new DerpClient(mkCfg(dialer, new FixedClock(0)));
  await client.connect();
  assert.equal(client.getState(), DerpClientState.Ready);
  assert.deepEqual(client.serverKey(), SERVER_PUBLIC_KEY);
});

test('connect：ServerKey 载荷过短（< Magic+32B）→ FRAME，状态归 Closed，连接关闭', async (): Promise<void> => {
  const dialer: FakeDialer = new FakeDialer([
    derpFrameEncode(DerpFrameType.ServerKey, concatBytes(DERP_MAGIC_UPSTREAM, new Uint8Array(31))),
  ]);
  const client: DerpClient = new DerpClient(mkCfg(dialer, new FixedClock(0)));
  assert.equal(await grabCode(client.connect()), 'FRAME');
  assert.equal(client.getState(), DerpClientState.Closed);
  assert.ok(dialer.conn.closedFlag);
});

test('connect：ServerKey 魔数错误 → FRAME（非 DERP 问候）', async (): Promise<void> => {
  const badMagic: Uint8Array = DERP_MAGIC_UPSTREAM.slice();
  badMagic[7] = 0x92; // 末字节改坏
  const dialer: FakeDialer = new FakeDialer([
    derpFrameEncode(DerpFrameType.ServerKey, concatBytes(badMagic, SERVER_PUBLIC_KEY)),
  ]);
  const client: DerpClient = new DerpClient(mkCfg(dialer, new FixedClock(0)));
  assert.equal(await grabCode(client.connect()), 'FRAME');
  assert.equal(client.getState(), DerpClientState.Closed);
});

test('connect：握手期先收到非 ServerKey 帧 → FRAME', async (): Promise<void> => {
  const dialer: FakeDialer = new FakeDialer([
    derpFrameEncode(DerpFrameType.KeepAlive, new Uint8Array(0)),
    serverKeyFrame(SERVER_PUBLIC_KEY),
    serverInfoFrame(),
  ]);
  const client: DerpClient = new DerpClient(mkCfg(dialer, new FixedClock(0)));
  assert.equal(await grabCode(client.connect()), 'FRAME');
});

test('connect：ServerKey 阶段 EOF（空脚本）→ FRAME；再次 connect 抛生命周期 Error', async (): Promise<void> => {
  const dialer: FakeDialer = new FakeDialer([]);
  const client: DerpClient = new DerpClient(mkCfg(dialer, new FixedClock(0)));
  assert.equal(await grabCode(client.connect()), 'FRAME');
  assert.equal(client.getState(), DerpClientState.Closed);
  assert.ok(dialer.conn.closedFlag);
  await assertLifecycleError(client.connect(), /connect requires state/);
});

test('connect：ClientInfo 已发但 ServerInfo 阶段 EOF → FRAME', async (): Promise<void> => {
  const dialer: FakeDialer = new FakeDialer([serverKeyFrame(SERVER_PUBLIC_KEY)]);
  const client: DerpClient = new DerpClient(mkCfg(dialer, new FixedClock(0)));
  assert.equal(await grabCode(client.connect()), 'FRAME');
  assert.equal(client.getState(), DerpClientState.Closed);
  assert.ok(dialer.conn.closedFlag);
  // ClientInfo 已发出（协议失败发生在其后）
  assert.equal(dialer.conn.written.length, 1);
  assert.equal(derpFrameDecode(dialer.conn.written[0]).type, DerpFrameType.ClientInfo);
});

test('connect：拨号失败 → 生命周期 Error 且状态归 Closed', async (): Promise<void> => {
  const client: DerpClient = new DerpClient(mkCfg(new BoomDialer(), new FixedClock(0)));
  await assertLifecycleError(client.connect(), /derp dial failed/);
  assert.equal(client.getState(), DerpClientState.Closed);
});

// ---- 构造校验/状态守卫/close ----

test('构造校验：nodeKey / nodePrivateKey 长度非法 → RANGE', (): void => {
  assert.throws(
    (): DerpClient => new DerpClient(mkCfgWithKeys(new FakeDialer([]), new Uint8Array(31), keyBytes(0x22))),
    (e: Error): boolean => derpCodeOf(e) === 'RANGE',
  );
  assert.throws(
    (): DerpClient => new DerpClient(mkCfgWithKeys(new FakeDialer([]), keyBytes(0x21), new Uint8Array(33))),
    (e: Error): boolean => derpCodeOf(e) === 'RANGE',
  );
});

test('状态守卫：未连接时收发全部拒绝（生命周期 Error）', async (): Promise<void> => {
  const client: DerpClient = new DerpClient(mkCfg(new FakeDialer([]), new FixedClock(0)));
  await assertLifecycleError(client.sendPacket(keyBytes(0xaa), new Uint8Array(0)), /sendPacket requires state/);
  await assertLifecycleError(client.sendPing().then((): void => {}), /sendPing requires state/);
  await assertLifecycleError(client.sendKeepAlive(), /sendKeepAlive requires state/);
  await assertLifecycleError(client.notePreferred(true), /notePreferred requires state/);
  await assertLifecycleError(client.receive(), /receive requires state/);
});

test('close：幂等；close 后 receive/sendPacket 拒绝', async (): Promise<void> => {
  const dialer: FakeDialer = new FakeDialer([serverKeyFrame(SERVER_PUBLIC_KEY), serverInfoFrame()]);
  const client: DerpClient = new DerpClient(mkCfg(dialer, new FixedClock(0)));
  await client.connect();
  client.close();
  client.close();
  assert.ok(dialer.conn.closedFlag);
  await assertLifecycleError(client.receive(), /receive requires state/);
  await assertLifecycleError(client.sendPacket(keyBytes(0xaa), new Uint8Array(0)), /sendPacket requires state/);
});

// ---- 收发 ----

test('sendPacket：帧字节 = SendPacket(dstKey || packet)；dstKey 长度非法 → RANGE', async (): Promise<void> => {
  const dialer: FakeDialer = new FakeDialer([serverKeyFrame(SERVER_PUBLIC_KEY), serverInfoFrame()]);
  const client: DerpClient = new DerpClient(mkCfg(dialer, new FixedClock(0)));
  await client.connect();
  await client.sendPacket(keyBytes(0xaa), Uint8Array.from([0x01, 0x02, 0x03]));
  assert.equal(dialer.conn.written.length, 2);
  // 全帧死字节：头(0x04 + u32BE 35) || dstKey(32B) || packet
  const expected: Uint8Array = concat3(
    frameHeader(DerpFrameType.SendPacket, 35),
    keyBytes(0xaa),
    Uint8Array.from([0x01, 0x02, 0x03]),
  );
  assert.deepEqual(dialer.conn.written[1], expected);
  assert.equal(await grabCode(client.sendPacket(new Uint8Array(31), new Uint8Array(0))), 'RANGE');
});

test('sendPing/sendKeepAlive/notePreferred：帧字节与注入随机数', async (): Promise<void> => {
  const dialer: FakeDialer = new FakeDialer([serverKeyFrame(SERVER_PUBLIC_KEY), serverInfoFrame()]);
  const client: DerpClient = new DerpClient(mkCfg(dialer, new FixedClock(0)));
  await client.connect(); // ClientInfo nonce 先消耗 rng 24B（游标落在池内 6）
  const pingData: Uint8Array = await client.sendPing();
  assert.deepEqual(pingData, Uint8Array.from([0x77, 0x88, 0x99, 0x11, 0x22, 0x33, 0x44, 0x55]));
  assert.equal(dialer.conn.written.length, 2);
  assert.deepEqual(dialer.conn.written[1], concatBytes(frameHeader(DerpFrameType.Ping, 8), pingData));
  await client.notePreferred(true);
  assert.deepEqual(dialer.conn.written[2], Uint8Array.from([0x07, 0x00, 0x00, 0x00, 0x01, 0x01]));
  await client.notePreferred(false);
  // 长度字段恒为 1（单字节载荷），值为 0x00
  assert.deepEqual(dialer.conn.written[3], Uint8Array.from([0x07, 0x00, 0x00, 0x00, 0x01, 0x00]));
  await client.sendKeepAlive();
  assert.deepEqual(dialer.conn.written[4], Uint8Array.from([0x06, 0x00, 0x00, 0x00, 0x00]));
});

test('按 key 订阅：RecvPacket 只上抛已订阅来源，未订阅来源静默跳过', async (): Promise<void> => {
  const dialer: FakeDialer = new FakeDialer([
    serverKeyFrame(SERVER_PUBLIC_KEY),
    serverInfoFrame(),
    recvPacketFrame(keyBytes(0xbb), Uint8Array.from([0x02])), // 未订阅 → 跳过
    recvPacketFrame(keyBytes(0xaa), Uint8Array.from([0x01])),
    recvPacketFrame(keyBytes(0xbb), Uint8Array.from([0x02])), // 未订阅 → 跳过
    recvPacketFrame(keyBytes(0xaa), Uint8Array.from([0x03])),
  ]);
  const client: DerpClient = new DerpClient(mkCfg(dialer, new FixedClock(0)));
  assert.equal(client.isPeerSubscribed(keyBytes(0xaa)), false);
  client.subscribePeer(keyBytes(0xaa));
  assert.equal(client.isPeerSubscribed(keyBytes(0xaa)), true);
  await client.connect();

  const ev1: DerpClientEvent | null = await client.receive();
  assert.notEqual(ev1, null);
  if (ev1 !== null) {
    assert.equal(ev1.kind, DerpClientEventKind.RecvPacket);
    assert.deepEqual(ev1.srcKey, keyBytes(0xaa));
    assert.deepEqual(ev1.packet, Uint8Array.from([0x01]));
    assert.equal(ev1.data.length, 0);
    assert.equal(ev1.rttMs, -1);
  }
  const ev2: DerpClientEvent | null = await client.receive();
  assert.notEqual(ev2, null);
  if (ev2 !== null) {
    assert.deepEqual(ev2.srcKey, keyBytes(0xaa));
    assert.deepEqual(ev2.packet, Uint8Array.from([0x03]));
  }
  const ev3: DerpClientEvent | null = await client.receive();
  assert.equal(ev3, null); // EOF

  assert.deepEqual(client.subscribedPeerKeys(), [keyBytes(0xaa)]);
  client.unsubscribePeer(keyBytes(0xaa));
  assert.equal(client.isPeerSubscribed(keyBytes(0xaa)), false);
  assert.deepEqual(client.subscribedPeerKeys(), []);
});

test('按 key 订阅：重复订阅去重、保序、取消中间项；返回拷贝', (): void => {
  const client: DerpClient = new DerpClient(mkCfg(new FakeDialer([]), new FixedClock(0)));
  client.subscribePeer(keyBytes(0xaa));
  client.subscribePeer(keyBytes(0xbb));
  client.subscribePeer(keyBytes(0xaa));
  client.subscribePeer(keyBytes(0xcc));
  const keys: Uint8Array[] = client.subscribedPeerKeys();
  assert.equal(keys.length, 3);
  assert.deepEqual(keys, [keyBytes(0xaa), keyBytes(0xbb), keyBytes(0xcc)]);
  keys[0].fill(0x00); // 返回拷贝，不影响内部表
  assert.deepEqual(client.subscribedPeerKeys()[0], keyBytes(0xaa));
  client.unsubscribePeer(keyBytes(0xbb));
  assert.deepEqual(client.subscribedPeerKeys(), [keyBytes(0xaa), keyBytes(0xcc)]);
  client.unsubscribePeer(keyBytes(0xdd)); // 未订阅 no-op
  assert.throws(
    (): void => { client.subscribePeer(new Uint8Array(31)); },
    (e: Error): boolean => derpCodeOf(e) === 'RANGE',
  );
});

test('receive：ServerPing 自动回 Pong；ServerInfo/PeerPresent/Health/Restarting/KeepAlive 静默消费', async (): Promise<void> => {
  const pingPayload: Uint8Array = Uint8Array.from([0xde, 0xad, 0xbe, 0xef, 0x00, 0x00, 0x00, 0x01]);
  const dialer: FakeDialer = new FakeDialer([
    serverKeyFrame(SERVER_PUBLIC_KEY),
    serverInfoFrame(),
    derpFrameEncode(DerpFrameType.Ping, pingPayload),
    derpFrameEncode(DerpFrameType.KeepAlive, new Uint8Array(0)),
    derpFrameEncode(DerpFrameType.ServerInfo, new Uint8Array(40)),
    derpFrameEncode(DerpFrameType.PeerPresent, new Uint8Array(40)),
    derpFrameEncode(DerpFrameType.Health, utf8Encode('duplicate connection')),
    derpFrameEncode(DerpFrameType.Restarting, Uint8Array.from([0x00, 0x00, 0x07, 0x08, 0x00, 0x00, 0x1c, 0x20])),
  ]);
  const client: DerpClient = new DerpClient(mkCfg(dialer, new FixedClock(0)));
  await client.connect();
  const ev: DerpClientEvent | null = await client.receive();
  assert.equal(ev, null); // 全部帧被处理，EOF 返回 null
  // 客户端只额外发出了 Pong（Ping 载荷原样回显）
  assert.equal(dialer.conn.written.length, 2);
  assert.deepEqual(dialer.conn.written[1], concatBytes(frameHeader(DerpFrameType.Pong, 8), pingPayload));
});

test('receive：PeerGone 事件（载荷 = 32B key + 1B reason，事件取前 32B）', async (): Promise<void> => {
  const dialer: FakeDialer = new FakeDialer([
    serverKeyFrame(SERVER_PUBLIC_KEY),
    serverInfoFrame(),
    derpFrameEncode(DerpFrameType.PeerGone, concatBytes(keyBytes(0xbb), Uint8Array.from([0x01]))),
  ]);
  const client: DerpClient = new DerpClient(mkCfg(dialer, new FixedClock(0)));
  await client.connect();
  const ev: DerpClientEvent | null = await client.receive();
  assert.notEqual(ev, null);
  if (ev !== null) {
    assert.equal(ev.kind, DerpClientEventKind.PeerGone);
    assert.deepEqual(ev.srcKey, keyBytes(0xbb));
    assert.equal(ev.packet.length, 0);
    assert.equal(ev.data.length, 0);
    assert.equal(ev.rttMs, -1);
  }
});

test('receive：PeerGone 载荷短于 32B → FRAME', async (): Promise<void> => {
  const dialer: FakeDialer = new FakeDialer([
    serverKeyFrame(SERVER_PUBLIC_KEY),
    serverInfoFrame(),
    derpFrameEncode(DerpFrameType.PeerGone, new Uint8Array(31)),
  ]);
  const client: DerpClient = new DerpClient(mkCfg(dialer, new FixedClock(0)));
  await client.connect();
  assert.equal(await grabCode(client.receive()), 'FRAME');
});

test('receive：方向错位/未知帧类型拒绝（FRAME）；close 后拒绝', async (): Promise<void> => {
  const dialer: FakeDialer = new FakeDialer([
    serverKeyFrame(SERVER_PUBLIC_KEY),
    serverInfoFrame(),
    derpFrameEncode(DerpFrameType.NotePreferred, Uint8Array.from([0x01])), // 客户端→服务器方向
    Uint8Array.from([0x63, 0x00, 0x00, 0x00, 0x01, 0xff]), // 未知类型帧（手工构造：encode 层拒绝）
  ]);
  const client: DerpClient = new DerpClient(mkCfg(dialer, new FixedClock(0)));
  await client.connect();
  assert.equal(await grabCode(client.receive()), 'FRAME'); // 方向错位
  assert.equal(await grabCode(client.receive()), 'FRAME'); // 未知类型 0x63
  client.close();
  await assertLifecycleError(client.receive(), /receive requires state/); // close 后拒绝
});

test('receive：RecvPacket 载荷短于 srcKey → FRAME', async (): Promise<void> => {
  const dialer: FakeDialer = new FakeDialer([
    serverKeyFrame(SERVER_PUBLIC_KEY),
    serverInfoFrame(),
    derpFrameEncode(DerpFrameType.RecvPacket, Uint8Array.from([0x01, 0x02])),
  ]);
  const client: DerpClient = new DerpClient(mkCfg(dialer, new FixedClock(0)));
  client.subscribePeer(keyBytes(0xaa));
  await client.connect();
  assert.equal(await grabCode(client.receive()), 'FRAME');
});

test('sendPing → Pong 往返 RTT（注入 Clock）与无匹配回显 rttMs=-1', async (): Promise<void> => {
  const clock: FixedClock = new FixedClock(1000);
  const dialer: FakeDialer = new FakeDialer([serverKeyFrame(SERVER_PUBLIC_KEY), serverInfoFrame()]);
  const client: DerpClient = new DerpClient(mkCfg(dialer, clock));
  await client.connect();
  const pingData: Uint8Array = await client.sendPing();
  clock.advanceMs(123);
  dialer.conn.enqueue(derpFrameEncode(DerpFrameType.Pong, pingData));
  const ev: DerpClientEvent | null = await client.receive();
  assert.notEqual(ev, null);
  if (ev !== null) {
    assert.equal(ev.kind, DerpClientEventKind.Pong);
    assert.deepEqual(ev.data, pingData);
    assert.equal(ev.rttMs, 123);
  }
  // 无匹配的 Pong → rttMs = -1
  dialer.conn.enqueue(derpFrameEncode(DerpFrameType.Pong, Uint8Array.from([0xee, 0xee])));
  const ev2: DerpClientEvent | null = await client.receive();
  assert.notEqual(ev2, null);
  if (ev2 !== null) {
    assert.equal(ev2.kind, DerpClientEventKind.Pong);
    assert.equal(ev2.rttMs, -1);
  }
});

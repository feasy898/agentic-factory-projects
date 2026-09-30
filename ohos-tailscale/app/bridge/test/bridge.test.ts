/**
 * app/bridge 测试 —— 壳 ↔ 协议包 mock 集成（Node node:test，确定性密钥/时钟/随机）。
 *
 * 覆盖：
 * 1) MockHttpTransport：路由/留痕/流式/断网注入；
 * 2) 全链路：ShellControlSession × MockControlPlane（Noise IK 握手 → 注册 → netmap → UI 快照）；
 * 3) 状态映射：ShellSessionState→ShellConnState（Index.ets ConnState 逐值锁定）；
 * 4) 纪律断言：authKey 明文不落任何请求体；close 后 authKey 不驻留、复用抛 STATE；
 * 5) 装配 fail-fast：坏参数在触网前拒绝。
 */

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { ArrayRng, FixedClock, utf8Encode, type HttpRequest } from '@ohos-tailscale/common';
import { x25519GenerateKeyPair, type CryptoKeyPair } from '@ohos-tailscale/crypto';
import { ControlError, ControlMsgKind, type NetworkMap } from '@ohos-tailscale/control';
import {
  MockControlPlane,
  MockHttpTransport,
  ShellConnState,
  ShellControlSession,
  ShellSessionState,
  uiConnStateOf,
  type ShellSessionParams,
} from '../src/index.ts';

// ---------- 测试工具（模块级箭头函数 + 显式类型，禁嵌套函数声明） ----------

const serverStaticKeys = (): CryptoKeyPair => {
  return x25519GenerateKeyPair(new ArrayRng(MockControlPlane.fillBytes(0xb2, 32)));
};

const machineKeys = (): CryptoKeyPair => {
  return x25519GenerateKeyPair(new ArrayRng(MockControlPlane.fillBytes(0xa1, 32)));
};

const nodeKeys = (): CryptoKeyPair => {
  return { publicKey: MockControlPlane.fixedKey(1), privateKey: MockControlPlane.fixedKey(2) };
};

const makeSession = (
  transport: MockControlPlane,
  serverStaticPublic: Uint8Array,
  authKey: string,
): ShellControlSession => {
  const params: ShellSessionParams = {
    controlUrl: 'https://net.example.test',
    machineKeyPair: machineKeys(),
    nodeKeyPair: nodeKeys(),
    discoKey: MockControlPlane.fixedKey(60),
    serverStaticPublic: serverStaticPublic,
    authKey: authKey,
    transport: transport,
    clock: new FixedClock(1000),
    rng: new ArrayRng(MockControlPlane.fillBytes(0xc3, 32)),
  };
  return new ShellControlSession(params);
};

/** 显式克隆装配参数（禁对象 spread，逐字段拷贝）。 */
const cloneParams = (p: ShellSessionParams): ShellSessionParams => {
  const out: ShellSessionParams = {
    controlUrl: p.controlUrl,
    machineKeyPair: p.machineKeyPair,
    nodeKeyPair: p.nodeKeyPair,
    discoKey: p.discoKey,
    serverStaticPublic: p.serverStaticPublic,
    authKey: p.authKey,
    transport: p.transport,
    clock: p.clock,
    rng: p.rng,
  };
  return out;
};

const controlErrorOf = async (fn: () => Promise<unknown>): Promise<string> => {
  let thrown: boolean = false;
  let code: string = '';
  try {
    await fn();
  } catch (e) {
    thrown = true;
    code = (e as ControlError).code;
  }
  assert.equal(thrown, true, 'expected ControlError not thrown');
  return code;
};

const bodyContains = (body: Uint8Array, needle: Uint8Array): boolean => {
  if (needle.length === 0 || body.length < needle.length) {
    return false;
  }
  for (let i: number = 0; i <= body.length - needle.length; i += 1) {
    let hit: boolean = true;
    for (let j: number = 0; j < needle.length; j += 1) {
      if (body[i + j] !== needle[j]) {
        hit = false;
        break;
      }
    }
    if (hit) {
      return true;
    }
  }
  return false;
};

// ---------- 用例 ----------

test('MockHttpTransport：路由命中/未命中 fail-fast/请求留痕/流式吐 chunk/断网注入', async () => {
  const transport: MockHttpTransport = new MockHttpTransport();
  transport.addRoute({
    method: 'POST',
    urlSuffix: '/api/short',
    status: 200,
    body: utf8Encode('pong'),
  });

  const req: HttpRequest = {
    method: 'POST',
    url: 'https://net.example.test/api/short',
    headers: {},
    body: new Uint8Array([0x01]),
  };
  const resp = await transport.send(req);
  assert.equal(resp.status, 200);
  assert.deepEqual(resp.body, utf8Encode('pong'));
  assert.equal(transport.requests.length, 1);

  await assert.rejects(
    (): Promise<unknown> => transport.send({ method: 'POST', url: 'https://net.example.test/nope', headers: {}, body: new Uint8Array(0) }),
    /no route/,
  );

  transport.addRoute({ method: 'GET', urlSuffix: '/api/poll', status: 200 });
  transport.openChunks = [utf8Encode('he'), utf8Encode('ll'), utf8Encode('o')];
  const stream = await transport.open({ method: 'GET', url: 'https://net.example.test/api/poll', headers: {}, body: new Uint8Array(0) });
  const collected: Uint8Array[] = [];
  for (;;) {
    const chunk: Uint8Array | null = await stream.body.read();
    if (chunk === null) {
      break;
    }
    collected.push(chunk);
  }
  assert.deepEqual(Buffer.concat(collected), Buffer.from(utf8Encode('hello')));
  stream.body.close();
  assert.equal(transport.lastBody?.isClosed(), true);

  transport.rejectAll = true;
  await assert.rejects((): Promise<unknown> => transport.send(req), /transport down/);
});

test('壳会话 × mock 控制面：login→pollMap 全链路，状态与 netmap 等价', async () => {
  const serverKeys: CryptoKeyPair = serverStaticKeys();
  const plane: MockControlPlane = MockControlPlane.newDeterministic(serverKeys.privateKey);
  const session: ShellControlSession = makeSession(plane, serverKeys.publicKey, 'tskey-auth-testkey123456');

  assert.equal(session.statusSnapshot().uiConnState, ShellConnState.Disconnected, 'idle → Disconnected');
  await session.login(['198.51.100.20:41641', '203.0.113.10:41037']);
  assert.equal(session.statusSnapshot().uiConnState, ShellConnState.Connecting, 'login 后 → Connecting');

  // 服务端侧等价还原注册请求（IK 语义 + 字段逐项）
  assert.deepEqual(plane.clientRemoteStatic, machineKeys().publicKey, 'IK：服务端看到的 machine 公钥须一致');
  const reg = plane.lastRegister;
  assert.notEqual(reg, null, '注册请求须能按 RegisterRequest 解码');
  assert.deepEqual(reg?.nodeKey, nodeKeys().publicKey);
  assert.deepEqual(reg?.discoKey, MockControlPlane.fixedKey(60));
  assert.deepEqual(reg?.endpoints, ['198.51.100.20:41641', '203.0.113.10:41037']);

  // 控制面下发 netmap（2 peers）→ pollMap 等价还原 + 会话转 Online
  const map: NetworkMap = {
    seqNo: 42n,
    packetFilter: new Uint8Array([0x00, 0x01, 0x02, 0x03]),
    peers: [
      { nodeKey: MockControlPlane.fixedKey(70), discoKey: MockControlPlane.fixedKey(71), endpoints: ['223.198.166.92:30387'], homeDerpRegionId: 999 },
      { nodeKey: MockControlPlane.fixedKey(80), discoKey: MockControlPlane.fixedKey(81), endpoints: [], homeDerpRegionId: 17 },
    ],
  };
  plane.queueNetworkMap(map);
  const got: NetworkMap = await session.pollMap();
  assert.equal(got.seqNo, 42n);
  assert.equal(got.peers.length, 2);
  assert.deepEqual(got.peers[0].nodeKey, MockControlPlane.fixedKey(70));
  assert.deepEqual(got.peers[1].homeDerpRegionId, 17);

  const snap = session.statusSnapshot();
  assert.equal(snap.sessionState, ShellSessionState.Online);
  assert.equal(snap.uiConnState, ShellConnState.Connected, 'Online → Connected（Index.ets 语义）');
  assert.equal(snap.peerCount, 2);
  assert.equal(snap.seqNo, 42n);
  assert.equal(snap.detail, 'peers=2 seq=42 derpRegions=999,17');
});

test('authKey 纪律：明文不落任何请求体；close 后不驻留、复用抛 STATE', async () => {
  const serverKeys: CryptoKeyPair = serverStaticKeys();
  const plane: MockControlPlane = MockControlPlane.newDeterministic(serverKeys.privateKey);
  const authKey: string = 'tskey-auth-secretZ9';
  const session: ShellControlSession = makeSession(plane, serverKeys.publicKey, authKey);

  await session.login([]);
  plane.queueNetworkMap({ seqNo: 1n, packetFilter: new Uint8Array(0), peers: [] });
  await session.pollMap();

  const needle: Uint8Array = utf8Encode(authKey);
  for (const req of plane.requests) {
    assert.equal(bodyContains(req.body, needle), false, 'authKey 明文不得出现在任何请求体');
    assert.equal(bodyContains(utf8Encode(req.method + ' ' + req.url), needle), false, 'authKey 明文不得出现在 method/url');
  }

  assert.equal(session.authKeyResident(), true);
  session.close();
  assert.equal(session.authKeyResident(), false, 'close 后 authKey 必须离开内存');
  assert.equal(session.statusSnapshot().sessionState, ShellSessionState.Closed);
  assert.equal(session.statusSnapshot().uiConnState, ShellConnState.Disconnected);
  await assert.rejects((): Promise<unknown> => session.pollMessage());
});

test('状态映射：ShellSessionState→ShellConnState 与 Index.ets 常量逐值锁定', () => {
  // Index.ets: ConnState = { Disconnected: 0, Connecting: 1, Connected: 2 }（镜像契约）
  assert.equal(ShellConnState.Disconnected, 0);
  assert.equal(ShellConnState.Connecting, 1);
  assert.equal(ShellConnState.Connected, 2);
  assert.equal(uiConnStateOf(ShellSessionState.Idle), 0);
  assert.equal(uiConnStateOf(ShellSessionState.Connecting), 1);
  assert.equal(uiConnStateOf(ShellSessionState.Online), 2);
  assert.equal(uiConnStateOf(ShellSessionState.Closed), 0);
});

test('装配 fail-fast：坏参数在触网前拒绝；未登录 poll 抛 STATE；重复 login 拒绝', async () => {
  const serverKeys: CryptoKeyPair = serverStaticKeys();
  const plane: MockControlPlane = MockControlPlane.newDeterministic(serverKeys.privateKey);
  const base = (): ShellSessionParams => ({
    controlUrl: 'https://net.example.test',
    machineKeyPair: machineKeys(),
    nodeKeyPair: nodeKeys(),
    discoKey: MockControlPlane.fixedKey(60),
    serverStaticPublic: serverKeys.publicKey,
    authKey: 'tskey-auth-ok',
    transport: plane,
    clock: new FixedClock(0),
    rng: new ArrayRng(MockControlPlane.fillBytes(0xc3, 32)),
  });

  assert.throws((): unknown => makeSession(plane, new Uint8Array(16), 'tskey-auth-ok'), /serverStaticPublic/);
  const pDisco: ShellSessionParams = cloneParams(base());
  pDisco.discoKey = new Uint8Array(31);
  assert.throws((): unknown => new ShellControlSession(pDisco), /discoKey/);
  const pAuthEmpty: ShellSessionParams = cloneParams(base());
  pAuthEmpty.authKey = '';
  assert.throws((): unknown => new ShellControlSession(pAuthEmpty), /authKey/);
  const pAuthSpace: ShellSessionParams = cloneParams(base());
  pAuthSpace.authKey = 'has space';
  assert.throws((): unknown => new ShellControlSession(pAuthSpace), /authKey/);
  const pAuthCjk: ShellSessionParams = cloneParams(base());
  pAuthCjk.authKey = '中文键';
  assert.throws((): unknown => new ShellControlSession(pAuthCjk), /authKey/);
  const pUrl: ShellSessionParams = cloneParams(base());
  pUrl.controlUrl = '';
  assert.throws((): unknown => new ShellControlSession(pUrl), /controlUrl/);

  const session: ShellControlSession = makeSession(plane, serverKeys.publicKey, 'tskey-auth-ok');
  const code: string = await controlErrorOf((): Promise<unknown> => session.pollMessage());
  assert.equal(code, 'STATE', '未登录 poll 必须 ControlError(STATE)');
  assert.equal(plane.requests.length, 0, 'fail-fast 路径不得产生任何网络请求');

  await session.login([]);
  await assert.rejects((): Promise<unknown> => session.login([]), /already logged in/);
});

test('非 MapResponse 消息跳过续收；close 后 ControlError(STATE)', async () => {
  const serverKeys: CryptoKeyPair = serverStaticKeys();
  const plane: MockControlPlane = MockControlPlane.newDeterministic(serverKeys.privateKey);
  const session: ShellControlSession = makeSession(plane, serverKeys.publicKey, 'tskey-auth-ok');
  await session.login([]);

  // 服务端推 KeepAlive + MapResponse：pollMap 应跳过 KeepAlive 拿到 MapResponse
  plane.queueNetworkMap({ seqNo: 7n, packetFilter: new Uint8Array(0), peers: [] });
  const map: NetworkMap = await session.pollMap();
  assert.equal(map.seqNo, 7n);
  assert.equal(session.statusSnapshot().sessionState, ShellSessionState.Online);

  session.close();
  const code: string = await controlErrorOf((): Promise<unknown> => session.pollMap());
  assert.equal(code, 'STATE');
});

test('消息种类常量引用一致（ControlMsgKind.MapResponse 驱动 Online 转换）', () => {
  assert.equal(ControlMsgKind.MapResponse, 2);
});

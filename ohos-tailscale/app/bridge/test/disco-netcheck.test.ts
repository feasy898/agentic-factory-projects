/**
 * app/bridge 发现面测试 —— 壳 ↔ disco/netcheck mock 集成（Node node:test，确定性）。
 *
 * 覆盖：
 * 1) STUN 探测全链路：总线 NAT 仿真 → MockStunServer → ShellStunProbe（映射地址 + RTT）；
 * 2) STUN TxID 配对否定（错 txid / 非 STUN 报文 → null）；
 * 3) disco Ping→Pong 全链路（wrapper 密封/解封 + Pong src=NAT 公网视图）；
 * 4) disco CallMeMaybe 端点列表往返；
 * 5) 噪声/错钥容错（非 disco 报文、密封给第三方公钥的报文 → None 不抛错）；
 * 6) 总线弃报计数（目的端未绑定）。
 */

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { ArrayRng, FixedClock, type Clock, type Rng } from '@ohos-tailscale/common';
import { x25519GenerateKeyPair, type CryptoKeyPair } from '@ohos-tailscale/crypto';
import { discoSeal, pingEncode, type DiscoEndpoint } from '@ohos-tailscale/disco';
import { StunTransaction, stunResponse } from '@ohos-tailscale/netcheck';
import {
  mapIp16FromV4,
  MockStunServer,
  parseEndpoint,
  UdpDatagramBus,
} from '../src/mock-udp-bus.ts';
import {
  ShellDiscoClient,
  ShellDiscoEventKind,
  ShellStunProbe,
} from '../src/shell-discovery.ts';

// ---------- 测试工具（模块级箭头函数 + 显式类型） ----------

const discoKeys = (fill: number): CryptoKeyPair => {
  return x25519GenerateKeyPair(new ArrayRng(new Uint8Array(32).fill(fill)));
};

const makeBus = (): UdpDatagramBus => {
  return new UdpDatagramBus();
};

const makeDiscoClient = (
  bus: UdpDatagramBus,
  localEndpoint: string,
  natPublic: string,
  keys: CryptoKeyPair,
  peerPublic: Uint8Array,
  rng: Rng,
): ShellDiscoClient => {
  const socket = bus.bind({ endpoint: localEndpoint, natPublic: natPublic });
  const client: ShellDiscoClient = new ShellDiscoClient({
    socket: socket,
    peerDiscoPublic: peerPublic,
    myDiscoPrivate: keys.privateKey,
    nodeKey: null,
    rng: rng,
  });
  return client;
};

// ---------- 用例 ----------

test('STUN 探测全链路：NAT 公网映射回填 + RTT 可注入', () => {
  const bus: UdpDatagramBus = makeBus();
  const server: MockStunServer = new MockStunServer(bus, '74.125.140.127:3478');
  const socket = bus.bind({ endpoint: '198.51.100.20:41641', natPublic: '203.0.113.10:41037' });
  const clock: FixedClock = new FixedClock(0);
  const probe: ShellStunProbe = new ShellStunProbe({
    socket: socket,
    stunEndpoint: '74.125.140.127:3478',
    rng: new ArrayRng(new Uint8Array(32).fill(0x11)),
    clock: clock,
  });

  const result = probe.run((): void => {
    server.handleInbound();
    clock.advanceMs(50);
  });
  assert.notEqual(result, null, '配对到响应');
  assert.deepEqual(result?.ip, new Uint8Array([156, 238, 240, 81]), '映射地址=公网 IPv4 原始字节');
  assert.equal(result?.port, 41037);
  assert.equal(result?.rttMs, 50, 'RTT=注入时钟推进量');
  assert.equal(result?.txid.length, 12);
  assert.equal(server.responded, 1);
  assert.equal(server.rejected, 0);
  assert.equal(bus.delivered, 2);
  assert.equal(bus.dropped, 0);
});

test('STUN TxID 配对否定：错 txid 与非 STUN 报文均不配对', () => {
  const clock: Clock = new FixedClock(0);
  const rng: Rng = new ArrayRng(new Uint8Array(32).fill(0x22));
  const tx: StunTransaction = new StunTransaction(rng, clock);

  const wrongTxid: Uint8Array = new Uint8Array(12).fill(0x77);
  assert.equal(tx.matchResponse(stunResponse(wrongTxid, new Uint8Array([1, 2, 3, 4]), 80)), null, '错 txid 不配对');
  assert.equal(tx.matchResponse(new Uint8Array([0x00, 0x01, 0x02, 0x03])), null, '非 STUN 报文不配对');
});

test('disco Ping→Pong 全链路：密封/解封 + Pong src=NAT 公网视图', () => {
  const bus: UdpDatagramBus = makeBus();
  const aKeys: CryptoKeyPair = discoKeys(0xa1);
  const bKeys: CryptoKeyPair = discoKeys(0xb2);
  const aNat: string = '203.0.113.10:41037';
  const bNat: string = '223.198.166.92:30387';
  const clientA: ShellDiscoClient = makeDiscoClient(bus, '198.51.100.20:41641', aNat, aKeys, bKeys.publicKey, new ArrayRng(new Uint8Array(64).fill(0x31)));
  const clientB: ShellDiscoClient = makeDiscoClient(bus, '10.0.0.8:41641', bNat, bKeys, aKeys.publicKey, new ArrayRng(new Uint8Array(64).fill(0x32)));
  clientA.peerEndpoint = '10.0.0.8:41641';
  clientB.peerEndpoint = aNat;

  const txid: Uint8Array = clientA.sendPing();
  assert.equal(txid.length, 12);

  const atB = clientB.poll();
  assert.equal(atB.kind, ShellDiscoEventKind.Ping, 'B 收到 Ping');
  assert.deepEqual(atB.ping?.txid, txid);
  assert.deepEqual(atB.senderPublic, aKeys.publicKey, '发端身份=disco 公钥（与 NAT 无关）');
  assert.equal(atB.fromEndpoint, aNat, '观察源=NAT 公网端点');

  const atA = clientA.poll();
  assert.equal(atA.kind, ShellDiscoEventKind.Pong, 'A 收到自动 Pong');
  assert.deepEqual(atA.pong?.txid, txid);
  // 上游语义：Pong.Src = Ping 发起端被 Pong 发送端观察到的地址（A 据此学得自己的公网映射）
  assert.deepEqual(
    atA.pong?.srcIp16,
    mapIp16FromV4(new Uint8Array([156, 238, 240, 81])),
    'Pong src ip16=A 被 B 观察到的 v4-mapped 公网地址',
  );
  assert.equal(atA.pong?.srcPort, 41037);
  assert.deepEqual(atA.senderPublic, bKeys.publicKey);
});

test('disco CallMeMaybe：端点列表经总线往返等价', () => {
  const bus: UdpDatagramBus = makeBus();
  const aKeys: CryptoKeyPair = discoKeys(0xa1);
  const bKeys: CryptoKeyPair = discoKeys(0xb2);
  const clientA: ShellDiscoClient = makeDiscoClient(bus, '198.51.100.20:41641', '203.0.113.10:41037', aKeys, bKeys.publicKey, new ArrayRng(new Uint8Array(64).fill(0x41)));
  const clientB: ShellDiscoClient = makeDiscoClient(bus, '10.0.0.8:41641', '223.198.166.92:30387', bKeys, aKeys.publicKey, new ArrayRng(new Uint8Array(64).fill(0x42)));
  clientA.peerEndpoint = '10.0.0.8:41641';
  clientB.peerEndpoint = '203.0.113.10:41037';

  const ep1: DiscoEndpoint = { ip16: mapIp16FromV4(new Uint8Array([223, 198, 166, 92])), port: 30387 };
  const ep2: DiscoEndpoint = { ip16: mapIp16FromV4(new Uint8Array([74, 125, 140, 127])), port: 3478 };
  clientB.sendCallMeMaybe({ myNumber: [ep1, ep2] });

  const atA = clientA.poll();
  assert.equal(atA.kind, ShellDiscoEventKind.CallMeMaybe);
  assert.equal(atA.callMeMaybe?.myNumber.length, 2);
  assert.deepEqual(atA.callMeMaybe?.myNumber[0].ip16, ep1.ip16);
  assert.equal(atA.callMeMaybe?.myNumber[0].port, 30387);
  assert.deepEqual(atA.callMeMaybe?.myNumber[1].ip16, ep2.ip16);
  assert.equal(atA.callMeMaybe?.myNumber[1].port, 3478);
});

test('容错：非 disco 报文与密封给第三方的报文均归 None，不抛错', () => {
  const bus: UdpDatagramBus = makeBus();
  const aKeys: CryptoKeyPair = discoKeys(0xa1);
  const bKeys: CryptoKeyPair = discoKeys(0xb2);
  const cKeys: CryptoKeyPair = discoKeys(0xc1);
  const socketA = bus.bind({ endpoint: '198.51.100.20:41641', natPublic: '203.0.113.10:41037' });
  const clientA: ShellDiscoClient = new ShellDiscoClient({
    socket: socketA,
    peerDiscoPublic: bKeys.publicKey,
    myDiscoPrivate: aKeys.privateKey,
    nodeKey: null,
    rng: new ArrayRng(new Uint8Array(64).fill(0x51)),
  });
  clientA.peerEndpoint = '10.0.0.8:41641';

  // 噪声：非 disco 形态
  socketA.inbound.push({ from: '10.0.0.8:41641', data: new Uint8Array([0xde, 0xad, 0xbe, 0xef]) });
  assert.equal(clientA.poll().kind, ShellDiscoEventKind.None, '噪声归 None');

  // 错钥：密封给 C 公钥，A 解封必败（上游 Open !ok 语义）
  const nonce24: Uint8Array = new Uint8Array(24).fill(0x09);
  const sealed = discoSeal(pingEncode({ txid: new Uint8Array(12).fill(0x05), nodeKey: null, padding: 0 }), cKeys.privateKey, cKeys.publicKey, nonce24);
  socketA.inbound.push({ from: '10.0.0.8:41641', data: sealed.wrapper });
  assert.equal(clientA.poll().kind, ShellDiscoEventKind.None, '错钥解封失败归 None');

  // 队空：None + from 为空串
  const empty = clientA.poll();
  assert.equal(empty.kind, ShellDiscoEventKind.None);
  assert.equal(empty.fromEndpoint, '');
});

test('总线弃报计数：目的端点未绑定 → dropped++，不影响发送端', () => {
  const bus: UdpDatagramBus = makeBus();
  const socket = bus.bind({ endpoint: '198.51.100.20:41641' });
  socket.send('203.0.113.9:9999', new Uint8Array([0x01]));
  assert.equal(bus.dropped, 1);
  assert.equal(bus.delivered, 0);
  assert.equal(socket.sent, 1);
  assert.equal(parseEndpoint('203.0.113.10:41037')?.port, 41037);
  assert.equal(parseEndpoint('bad-endpoint'), null);
});

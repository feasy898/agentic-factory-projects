/**
 * Peer 索引表测试 + 两 peer 实例互发握手的端到端往返（经索引表分发）：
 * - 登记/查询/移除对端（深拷贝语义）；
 * - installSession 装订握手产出 → entryByLocalIndex 分发收包 → entryByPeerId 发包；
 * - localIndex 冲突替换（重钥语义）与 removePeer 级联；
 * - 双向数据面往返 + keepalive + 二次握手换钥后旧索引路由被替换。
 */

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { ArrayRng, FixedClock } from '@ohos-tailscale/common';
import { x25519GenerateKeyPair } from '@ohos-tailscale/crypto';
import {
  WgHandshakeInitiator,
  WgHandshakeResponder,
  WgPeerTable,
  type WgHandshakeOutput,
  type WgSessionEntry,
} from '../src/index.ts';

/** 确定性字节序列（测试夹具）。 */
const seqBytes = (n: number, seed: number): Uint8Array => {
  const out: Uint8Array = new Uint8Array(n);
  for (let i: number = 0; i < n; i += 1) {
    out[i] = (seed + i * 31) % 256;
  }
  return out;
};

const staticA = x25519GenerateKeyPair(new ArrayRng(seqBytes(32, 11)));
const staticB = x25519GenerateKeyPair(new ArrayRng(seqBytes(32, 22)));
const POOL_A: Uint8Array = seqBytes(36, 101);
const POOL_B: Uint8Array = seqBytes(36, 202);

/** 两个节点（A=发起端）各自视角的索引表 + 一场握手的产出（A2/A15：具名 interface，禁内联字面量类型）。 */
interface TwoNodes {
  tableA: WgPeerTable;
  tableB: WgPeerTable;
  outA: WgHandshakeOutput;
  outB: WgHandshakeOutput;
}

const buildTwoNodes = (): TwoNodes => {
  const tableA: WgPeerTable = new WgPeerTable();
  const tableB: WgPeerTable = new WgPeerTable();
  tableA.registerPeer('b', staticB.publicKey);
  tableB.registerPeer('a', staticA.publicKey);
  const clock: FixedClock = new FixedClock(1717000000123);
  const initiator: WgHandshakeInitiator = new WgHandshakeInitiator(
    staticA.privateKey,
    staticB.publicKey,
    new ArrayRng(POOL_A),
    clock,
  );
  const responder: WgHandshakeResponder = new WgHandshakeResponder(
    staticB.privateKey,
    new ArrayRng(POOL_B),
    clock,
  );
  responder.consumeInitiation(initiator.createInitiation());
  initiator.consumeResponse(responder.createResponse());
  const outA: WgHandshakeOutput = initiator.finish();
  const outB: WgHandshakeOutput = responder.finish();
  const r: TwoNodes = { tableA: tableA, tableB: tableB, outA: outA, outB: outB };
  return r;
};

test('registerPeer/staticPublicOf/removePeer/peerIds（深拷贝语义）', () => {
  // 独立密钥对：拷贝语义测试需要改写源数组，不能动共享夹具
  const scratch = x25519GenerateKeyPair(new ArrayRng(seqBytes(32, 77)));
  const table: WgPeerTable = new WgPeerTable();
  assert.equal(table.peerCount(), 0);
  table.registerPeer('b', staticB.publicKey);
  table.registerPeer('a', staticA.publicKey);
  assert.equal(table.peerCount(), 2);
  assert.deepEqual(table.peerIds(), ['b', 'a']);
  assert.equal(table.hasPeer('b'), true);
  assert.equal(table.hasPeer('zz'), false);
  table.registerPeer('scratch', scratch.publicKey);
  const got: Uint8Array | null = table.staticPublicOf('scratch');
  assert.deepEqual(got, scratch.publicKey);
  // 返回拷贝：改返回值/改源不影响表内
  const orig: number = scratch.publicKey[0];
  (got as Uint8Array)[0] = 0xff;
  const again: Uint8Array | null = table.staticPublicOf('scratch');
  assert.notEqual(again, null);
  assert.equal((again as Uint8Array)[0], orig, 'returned array must be a copy');
  scratch.publicKey[0] = 0x55;
  const third: Uint8Array | null = table.staticPublicOf('scratch');
  assert.equal((third as Uint8Array)[0], orig, 'stored static public must be a copy');
  // 移除
  assert.equal(table.removePeer('zz'), false);
  assert.equal(table.removePeer('scratch'), true);
  assert.equal(table.removePeer('scratch'), false);
  assert.equal(table.peerCount(), 2);
  assert.equal(table.staticPublicOf('scratch'), null);
});

test('端到端：握手 → 装订索引表 → 双向互发数据与 keepalive', () => {
  const n = buildTwoNodes();
  const entryA: WgSessionEntry = n.tableA.installSession('b', n.outA, 1000);
  const entryB: WgSessionEntry = n.tableB.installSession('a', n.outB, 1000);
  assert.equal(n.tableA.sessionCount(), 1);
  assert.equal(n.tableB.sessionCount(), 1);
  // 索引装订正确性：A 侧 localIndex/peerIndex 与 B 侧互为镜像
  assert.equal(entryA.localIndex, n.outA.localIndex);
  assert.equal(entryA.peerIndex, n.outA.peerIndex);
  assert.equal(entryB.localIndex, n.outA.peerIndex, 'B.localIndex must equal A.peerIndex');
  assert.equal(entryB.peerIndex, n.outA.localIndex);
  // A → B：receiver index = entryA.peerIndex = B 侧 localIndex
  const payload: Uint8Array = seqBytes(120, 7);
  const pktAB: Uint8Array = entryA.sendSession.encryptPacket(payload);
  const hopB: WgSessionEntry | null = n.tableB.entryByLocalIndex(entryB.localIndex);
  assert.notEqual(hopB, null);
  assert.deepEqual((hopB as WgSessionEntry).recvSession.decryptPacket(pktAB), payload);
  // B → A
  const payloadBA: Uint8Array = seqBytes(64, 8);
  const pktBA: Uint8Array = entryB.sendSession.encryptPacket(payloadBA);
  const hopA: WgSessionEntry | null = n.tableA.entryByLocalIndex(entryA.localIndex);
  assert.deepEqual((hopA as WgSessionEntry).recvSession.decryptPacket(pktBA), payloadBA);
  // entryByPeerId 视图等价
  assert.equal(n.tableA.entryByPeerId('b'), entryA);
  assert.equal(n.tableB.entryByPeerId('a'), entryB);
  // keepalive 双向
  const ka: Uint8Array = entryA.sendSession.encryptPacket(new Uint8Array(0));
  assert.equal((hopB as WgSessionEntry).recvSession.decryptPacket(ka).length, 0);
  const kb: Uint8Array = entryB.sendSession.encryptPacket(new Uint8Array(0));
  assert.equal((hopA as WgSessionEntry).recvSession.decryptPacket(kb).length, 0);
  // 未知索引/未知对端
  assert.equal(n.tableA.entryByLocalIndex(0xdeadbeef), null);
  assert.equal(n.tableA.entryByPeerId('zz'), null);
});

test('重钥替换：二次握手装订后 localIndex 路由更新、旧条目让位', () => {
  const n = buildTwoNodes();
  const entryA1: WgSessionEntry = n.tableA.installSession('b', n.outA, 1000);
  // 二次握手（新 rng 池 → 新索引/新密钥）
  const clock: FixedClock = new FixedClock(1717000000200);
  const initiator2: WgHandshakeInitiator = new WgHandshakeInitiator(
    staticA.privateKey,
    staticB.publicKey,
    new ArrayRng(seqBytes(36, 111)),
    clock,
  );
  const responder2: WgHandshakeResponder = new WgHandshakeResponder(
    staticB.privateKey,
    new ArrayRng(seqBytes(36, 222)),
    clock,
  );
  responder2.consumeInitiation(initiator2.createInitiation());
  initiator2.consumeResponse(responder2.createResponse());
  const outA2: WgHandshakeOutput = initiator2.finish();
  const outB2: WgHandshakeOutput = responder2.finish();
  assert.notEqual(outA2.localIndex, entryA1.localIndex, 'sanity: new local index differs');
  // A 侧重钥装订（整体替换语义）：仍是 1 个会话，旧 localIndex 路由移除
  const entryA2: WgSessionEntry = n.tableA.installSession('b', outA2, 2000);
  assert.equal(n.tableA.sessionCount(), 1);
  assert.equal(n.tableA.entryByPeerId('b'), entryA2);
  assert.equal(n.tableA.entryByLocalIndex(entryA1.localIndex), null, 'old local index route must be dropped');
  assert.equal(n.tableA.entryByLocalIndex(entryA2.localIndex), entryA2);
  // B 侧同步重钥后新路由可互通
  n.tableB.installSession('a', outB2, 2000);
  const payload: Uint8Array = seqBytes(16, 9);
  const pkt: Uint8Array = entryA2.sendSession.encryptPacket(payload);
  const hopB2: WgSessionEntry | null = n.tableB.entryByLocalIndex(outA2.peerIndex);
  assert.notEqual(hopB2, null);
  assert.deepEqual((hopB2 as WgSessionEntry).recvSession.decryptPacket(pkt), payload);
});

test('localIndex 跨对端冲突：新条目顶替占用（白皮书重钥语义）', () => {
  const table: WgPeerTable = new WgPeerTable();
  table.registerPeer('p1', staticA.publicKey);
  table.registerPeer('p2', staticB.publicKey);
  const fakeOut: WgHandshakeOutput = {
    localIndex: 42,
    peerIndex: 1,
    sendKey: seqBytes(32, 5),
    recvKey: seqBytes(32, 6),
  };
  table.installSession('p1', fakeOut, 0);
  const e1: WgSessionEntry | null = table.entryByLocalIndex(42);
  assert.notEqual(e1, null);
  assert.equal((e1 as WgSessionEntry).peerId, 'p1');
  table.installSession('p2', fakeOut, 1); // 同 localIndex、不同对端 → 顶替
  const e2: WgSessionEntry | null = table.entryByLocalIndex(42);
  assert.equal((e2 as WgSessionEntry).peerId, 'p2');
  assert.equal(table.entryByPeerId('p1'), null, 'p1 old entry must be dropped');
  assert.equal(table.sessionCount(), 1);
});

test('removeSession/removePeer 级联与未登记对端拒绝', () => {
  const n = buildTwoNodes();
  n.tableA.installSession('b', n.outA, 1000);
  assert.throws(() => n.tableA.installSession('ghost', n.outA, 1000), /unknown peer/);
  // removePeer 级联移除会话
  assert.equal(n.tableA.removePeer('b'), true);
  assert.equal(n.tableA.sessionCount(), 0);
  assert.equal(n.tableA.entryByPeerId('b'), null);
  // removeSession
  n.tableB.installSession('a', n.outB, 1000);
  assert.equal(n.tableB.removeSession(n.outB.localIndex), true);
  assert.equal(n.tableB.removeSession(n.outB.localIndex), false);
  assert.equal(n.tableB.sessionCount(), 0);
  // registerPeer 长度校验
  assert.throws(() => n.tableA.registerPeer('bad', seqBytes(31, 1)));
});

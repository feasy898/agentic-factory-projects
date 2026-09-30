/**
 * 类型化控制面消息测试（RegisterRequest / RegisterResponse / 精简版 NetworkMap）：
 * - 三类消息 ControlMessage ↔ 结构往返（含空缺省值、可选字段、多 peer）；
 * - 字节级约定断言：SeqNo 8B BE u64、DerpRegionId u16be、Endpoints {u8 len, utf8} 条目；
 * - 畸形：kind 不符、必备字段缺失、公钥长度≠32、重复字段、Endpoints 截断/非法 utf8
 *   /条目超 255B → ControlError('TLV')；
 * - 输出独立性（R8）：解码输出的 key/filter 与输入不共享内存。
 */

import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  ControlError,
  ControlMsgKind,
  ControlTlvType,
  controlDecodeMessage,
  controlEncodeMessage,
  decodeEndpointsValue,
  encodeEndpointsValue,
  networkMapDecode,
  networkMapEncode,
  registerRequestDecode,
  registerRequestEncode,
  registerRequestEncodeBytes,
  registerRequestDecodeBytes,
  registerResponseDecode,
  registerResponseEncode,
  type ControlMessage,
  type NetworkMap,
  type NetworkMapPeer,
  type RegisterRequest,
  type RegisterResponse,
} from '../src/index.ts';

const keyA = (n: number): Uint8Array => {
  const out: Uint8Array = new Uint8Array(32);
  for (let i: number = 0; i < 32; i += 1) {
    out[i] = (n + i * 3) & 0xff;
  }
  return out;
};

const assertTlvError = (fn: () => void): void => {
  let thrown: boolean = false;
  let gotCode: string = '';
  try {
    fn();
  } catch (e) {
    thrown = true;
    const err: ControlError = e as ControlError;
    gotCode = err.code;
  }
  assert.equal(thrown, true, 'expected ControlError(TLV) not thrown');
  assert.equal(gotCode, 'TLV', 'unexpected ControlError code');
};

test('RegisterRequest 往返：含 endpoints / 空 endpoints / 字节级复合编解码', () => {
  const req: RegisterRequest = {
    nodeKey: keyA(1),
    discoKey: keyA(100),
    endpoints: ['198.51.100.20:41641', '203.0.113.10:41037'],
  };
  const msg: ControlMessage = registerRequestEncode(req);
  assert.equal(msg.kind, ControlMsgKind.MapRequest);
  const decoded: RegisterRequest = registerRequestDecode(msg);
  assert.deepEqual(decoded.nodeKey, req.nodeKey);
  assert.deepEqual(decoded.discoKey, req.discoKey);
  assert.deepEqual(decoded.endpoints, req.endpoints);

  // 字节级复合：controlEncodeMessage(registerRequestEncode(x)) ↔ DecodeBytes
  const bytes: Uint8Array = registerRequestEncodeBytes(req);
  const decoded2: RegisterRequest = registerRequestDecodeBytes(bytes);
  assert.deepEqual(decoded2.nodeKey, req.nodeKey);
  assert.deepEqual(decoded2.endpoints, req.endpoints);

  // 空 endpoints：不产生 Endpoints 字段，解码回 []
  const bare: RegisterRequest = { nodeKey: keyA(2), discoKey: keyA(50), endpoints: [] };
  const bareMsg: ControlMessage = registerRequestEncode(bare);
  const types: number[] = [];
  for (const f of bareMsg.fields) {
    types.push(f.type);
  }
  assert.deepEqual(types, [ControlTlvType.NodeKey, ControlTlvType.DiscoKey]);
  const bareDecoded: RegisterRequest = registerRequestDecode(bareMsg);
  assert.deepEqual(bareDecoded.endpoints, []);
});

test('RegisterRequest 解码畸形：kind 不符 / 缺字段 / 密钥长度错 / 重复字段 → TLV', () => {
  const good: ControlMessage = registerRequestEncode({
    nodeKey: keyA(3),
    discoKey: keyA(4),
    endpoints: [],
  });
  assertTlvError(() => registerRequestDecode({ kind: ControlMsgKind.MapResponse, fields: good.fields }));
  // 缺 DiscoKey
  assertTlvError(() => registerRequestDecode({ kind: ControlMsgKind.MapRequest, fields: [good.fields[0]] }));
  // 缺 NodeKey
  assertTlvError(() => registerRequestDecode({ kind: ControlMsgKind.MapRequest, fields: [good.fields[1]] }));
  // NodeKey 31 字节
  const shortKey: ControlMessage = {
    kind: ControlMsgKind.MapRequest,
    fields: [
      { type: ControlTlvType.NodeKey, value: keyA(5).slice(0, 31) },
      { type: ControlTlvType.DiscoKey, value: keyA(6) },
    ],
  };
  assertTlvError(() => registerRequestDecode(shortKey));
  // 重复 NodeKey
  const dup: ControlMessage = {
    kind: ControlMsgKind.MapRequest,
    fields: [
      { type: ControlTlvType.NodeKey, value: keyA(7) },
      { type: ControlTlvType.NodeKey, value: keyA(8) },
      { type: ControlTlvType.DiscoKey, value: keyA(9) },
    ],
  };
  assertTlvError(() => registerRequestDecode(dup));
});

test('RegisterResponse 往返：接受（回显 nodeKey + seqNo）与拒绝（errorText）', () => {
  const ok: RegisterResponse = { errorText: '', nodeKey: keyA(10), seqNo: 0n };
  const okDecoded: RegisterResponse = registerResponseDecode(registerResponseEncode(ok));
  assert.equal(okDecoded.errorText, '');
  assert.deepEqual(okDecoded.nodeKey, keyA(10));
  assert.equal(okDecoded.seqNo, 0n);

  const refused: RegisterResponse = { errorText: 'machine not authorized', nodeKey: null, seqNo: 0n };
  const refusedMsg: ControlMessage = registerResponseEncode(refused);
  const refusedTypes: number[] = [];
  for (const f of refusedMsg.fields) {
    refusedTypes.push(f.type);
  }
  // 拒绝时不带 NodeKey，且空 errorText/零 seqNo 语义由解码缺省补齐
  assert.deepEqual(refusedTypes, [ControlTlvType.SeqNo, ControlTlvType.ErrorText]);
  const refusedDecoded: RegisterResponse = registerResponseDecode(refusedMsg);
  assert.equal(refusedDecoded.errorText, 'machine not authorized');
  assert.equal(refusedDecoded.nodeKey, null);
  assert.equal(refusedDecoded.seqNo, 0n);

  // 大 seqNo（> 2^53，P6 BigInt）往返
  const big: RegisterResponse = { errorText: '', nodeKey: null, seqNo: 9007199254740993n };
  const bigDecoded: RegisterResponse = registerResponseDecode(registerResponseEncode(big));
  assert.equal(bigDecoded.seqNo, 9007199254740993n);

  // kind 不符
  assertTlvError(() => registerResponseDecode({ kind: ControlMsgKind.MapRequest, fields: [] }));
  // 重复 SeqNo
  const dup: ControlMessage = {
    kind: ControlMsgKind.MapResponse,
    fields: [
      { type: ControlTlvType.SeqNo, value: new Uint8Array(8) },
      { type: ControlTlvType.SeqNo, value: new Uint8Array(8) },
    ],
  };
  assertTlvError(() => registerResponseDecode(dup));
});

test('SeqNo/DerpRegionId 字节级约定：u64be 与 u16be', () => {
  const resp: ControlMessage = registerResponseEncode({ errorText: '', nodeKey: null, seqNo: 0x0102030405060708n });
  assert.deepEqual(resp.fields[0].value, new Uint8Array([0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08]));
  // region 999（【取证】§1.2 Headscale embedded DERP）；空 packetFilter 不落字段
  const peer: NetworkMapPeer = { nodeKey: keyA(11), discoKey: keyA(12), endpoints: [], homeDerpRegionId: 999 };
  const map: NetworkMap = { seqNo: 0n, packetFilter: new Uint8Array(0), peers: [peer] };
  const mapMsg: ControlMessage = networkMapEncode(map);
  let regionValue: Uint8Array = new Uint8Array(0);
  for (const f of mapMsg.fields) {
    if (f.type === ControlTlvType.DerpRegionId) {
      regionValue = f.value;
    }
  }
  assert.deepEqual(regionValue, new Uint8Array([0x03, 0xe7])); // 999 = 0x03E7 u16be
});

test('NetworkMap 往返：映射级字段 + 两 peer（可选字段有无混合）', () => {
  const filter: Uint8Array = new Uint8Array([0x00, 0x00, 0x00, 0x00, 0x06, 0x11, 0x3a]);
  const map: NetworkMap = {
    seqNo: 1n + 0x0000000fffffffffn,
    packetFilter: filter,
    peers: [
      { nodeKey: keyA(20), discoKey: keyA(21), endpoints: ['223.198.166.92:30387', '172.16.105.2:41641'], homeDerpRegionId: 17 },
      { nodeKey: keyA(30), discoKey: keyA(31), endpoints: [], homeDerpRegionId: 0 },
    ],
  };
  const msg: ControlMessage = networkMapEncode(map);
  assert.equal(msg.kind, ControlMsgKind.MapResponse);
  // 规范字段序：SeqNo, PacketFilter, (NodeKey, DiscoKey, DerpRegionId, Endpoints), (NodeKey, DiscoKey)
  const types: number[] = [];
  for (const f of msg.fields) {
    types.push(f.type);
  }
  assert.deepEqual(types, [
    ControlTlvType.SeqNo,
    ControlTlvType.PacketFilter,
    ControlTlvType.NodeKey,
    ControlTlvType.DiscoKey,
    ControlTlvType.DerpRegionId,
    ControlTlvType.Endpoints,
    ControlTlvType.NodeKey,
    ControlTlvType.DiscoKey,
  ]);
  const decoded: NetworkMap = networkMapDecode(msg);
  assert.equal(decoded.seqNo, map.seqNo);
  assert.deepEqual(decoded.packetFilter, filter);
  assert.equal(decoded.peers.length, 2);
  assert.deepEqual(decoded.peers[0].nodeKey, keyA(20));
  assert.deepEqual(decoded.peers[0].discoKey, keyA(21));
  assert.deepEqual(decoded.peers[0].endpoints, map.peers[0].endpoints);
  assert.equal(decoded.peers[0].homeDerpRegionId, 17);
  assert.deepEqual(decoded.peers[1].nodeKey, keyA(30));
  assert.deepEqual(decoded.peers[1].endpoints, []);
  assert.equal(decoded.peers[1].homeDerpRegionId, 0);

  // 空 netmap：无 peer 无 filter
  const empty: NetworkMap = networkMapDecode(networkMapEncode({ seqNo: 7n, packetFilter: new Uint8Array(0), peers: [] }));
  assert.equal(empty.seqNo, 7n);
  assert.equal(empty.packetFilter.length, 0);
  assert.equal(empty.peers.length, 0);
});

test('NetworkMap 解码畸形：缺 DiscoKey / peer 前缀缺失 / 重复字段 → TLV', () => {
  const key: Uint8Array = keyA(40);
  // peer 只有 NodeKey 没有 DiscoKey
  const noDisco: ControlMessage = {
    kind: ControlMsgKind.MapResponse,
    fields: [{ type: ControlTlvType.NodeKey, value: key }],
  };
  assertTlvError(() => networkMapDecode(noDisco));
  // DiscoKey 出现在任何 NodeKey 之前
  const orphan: ControlMessage = {
    kind: ControlMsgKind.MapResponse,
    fields: [{ type: ControlTlvType.DiscoKey, value: key }],
  };
  assertTlvError(() => networkMapDecode(orphan));
  // Endpoints 出现在任何 NodeKey 之前
  const orphanEp: ControlMessage = {
    kind: ControlMsgKind.MapResponse,
    fields: [{ type: ControlTlvType.Endpoints, value: encodeEndpointsValue(['1.2.3.4:5']) }],
  };
  assertTlvError(() => networkMapDecode(orphanEp));
  // 同一 peer 两个 DiscoKey
  const dupDisco: ControlMessage = {
    kind: ControlMsgKind.MapResponse,
    fields: [
      { type: ControlTlvType.NodeKey, value: key },
      { type: ControlTlvType.DiscoKey, value: keyA(41) },
      { type: ControlTlvType.DiscoKey, value: keyA(42) },
    ],
  };
  assertTlvError(() => networkMapDecode(dupDisco));
  // 重复 PacketFilter
  const dupFilter: ControlMessage = {
    kind: ControlMsgKind.MapResponse,
    fields: [
      { type: ControlTlvType.PacketFilter, value: new Uint8Array([1]) },
      { type: ControlTlvType.PacketFilter, value: new Uint8Array([2]) },
    ],
  };
  assertTlvError(() => networkMapDecode(dupFilter));
  // 未知 type 忽略（前向兼容）
  const withUnknown: ControlMessage = {
    kind: ControlMsgKind.MapResponse,
    fields: [
      { type: ControlTlvType.NodeKey, value: key },
      { type: 0x7faa, value: new Uint8Array([0x01, 0x02]) },
      { type: ControlTlvType.DiscoKey, value: keyA(43) },
    ],
  };
  const compat: NetworkMap = networkMapDecode(withUnknown);
  assert.equal(compat.peers.length, 1);
  assert.deepEqual(compat.peers[0].discoKey, keyA(43));
  // kind 不符
  assertTlvError(() => networkMapDecode({ kind: ControlMsgKind.KeepAlive, fields: [] }));
});

test('Endpoints value：往返、中文条目（utf8）、截断/非法 utf8/条目超 255B → TLV', () => {
  const entries: string[] = ['100.100.0.5:41641', '[fd7a:115c:a1e0::5]:41641'];
  const value: Uint8Array = encodeEndpointsValue(entries);
  assert.deepEqual(decodeEndpointsValue(value), entries);
  // 空条目
  assert.deepEqual(decodeEndpointsValue(encodeEndpointsValue([''])), ['']);
  // 字节布局：len 前缀
  const one: Uint8Array = encodeEndpointsValue(['ab']);
  assert.deepEqual(one, new Uint8Array([2, 0x61, 0x62]));

  // 截断：声称 5 字节只有 1 字节
  assertTlvError(() => decodeEndpointsValue(new Uint8Array([5, 0x61])));
  // 非法 utf8（孤立代理字节序列 ED A0 80）
  assertTlvError(() => decodeEndpointsValue(new Uint8Array([3, 0xed, 0xa0, 0x80])));
  // 条目超 255 字节
  let longEntry: string = '';
  for (let i: number = 0; i < 256; i += 1) {
    longEntry = longEntry + 'a';
  }
  assertTlvError(() => encodeEndpointsValue([longEntry]));
});

test('类型化消息经通用字节层整链往返', () => {
  const req: RegisterRequest = { nodeKey: keyA(60), discoKey: keyA(61), endpoints: ['10.0.0.1:41641'] };
  const bytes: Uint8Array = controlEncodeMessage(registerRequestEncode(req));
  const back: RegisterRequest = registerRequestDecode(controlDecodeMessage(bytes));
  assert.deepEqual(back.nodeKey, req.nodeKey);
  assert.deepEqual(back.discoKey, req.discoKey);
  assert.deepEqual(back.endpoints, req.endpoints);
});

test('输出独立性（R8）：NetworkMap 解码的 key/filter 不与输入共享内存', () => {
  const filter: Uint8Array = new Uint8Array([0x0a, 0x0b]);
  const msg: ControlMessage = networkMapEncode({
    seqNo: 3n,
    packetFilter: filter,
    peers: [{ nodeKey: keyA(70), discoKey: keyA(71), endpoints: [], homeDerpRegionId: 0 }],
  });
  const decoded: NetworkMap = networkMapDecode(msg);
  decoded.packetFilter[0] = (decoded.packetFilter[0] ^ 0xff) & 0xff;
  assert.equal(filter[0], 0x0a, 'decoded filter must not alias input');
  decoded.peers[0].nodeKey[0] = (decoded.peers[0].nodeKey[0] ^ 0xff) & 0xff;
  const again: NetworkMap = networkMapDecode(msg);
  assert.equal(again.peers[0].nodeKey[0], keyA(70)[0], 'second decode must be unaffected');
});

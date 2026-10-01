/**
 * 通用 TLV 编解码测试（架构契约 §7.1 + §7.3 TLV 部分）：
 * - 任意字段集编解码往返；空 value 字段；65535B 上界可用、65536B 抛 ControlError('TLV')；
 * - 大端字节序精确布局；未知 type 保序保留不丢；
 * - 消息层：kind 落为首个 MsgKind 字段（u8）往返；缺 MsgKind / 首字段非
 *   MsgKind / MsgKind value 长度≠1 / 截断（半头、缺值）抛 ControlError('TLV')；
 * - parseControlTlvType / parseControlMsgKind 已知返回原值、未知返回 null；
 * - 输出独立性（R8）：编码/解码输出与输入不共享内存。
 */

import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  ControlError,
  ControlMsgKind,
  ControlTlvType,
  controlDecodeMessage,
  controlEncodeMessage,
  controlTlvDecode,
  controlTlvEncode,
  parseControlMsgKind,
  parseControlTlvType,
  type ControlMessage,
  type ControlTlvField,
} from '../src/index.ts';

const field = (type: number, value: Uint8Array): ControlTlvField => {
  const f: ControlTlvField = { type: type, value: value };
  return f;
};

const seqPool = (start: number, n: number): Uint8Array => {
  const out: Uint8Array = new Uint8Array(n);
  for (let i: number = 0; i < n; i += 1) {
    out[i] = (start + i) & 0xff;
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

test('字段编解码往返：多字段、空 value、未知 type 保序保留', () => {
  const unknownType: number = 0x7f1a; // 契约类型表之外的 type
  const fields: ControlTlvField[] = [
    field(ControlTlvType.NodeKey, seqPool(0xa0, 32)),
    field(ControlTlvType.Endpoints, new Uint8Array(0)),
    field(unknownType, new Uint8Array([0xde, 0xad, 0xbe, 0xef])),
    field(ControlTlvType.ErrorText, new Uint8Array([0x68, 0x69])),
  ];
  const encoded: Uint8Array = controlTlvEncode(fields);
  assert.equal(encoded.length, (2 + 2 + 32) + (2 + 2 + 0) + (2 + 2 + 4) + (2 + 2 + 2));
  const decoded: ControlTlvField[] = controlTlvDecode(encoded);
  assert.equal(decoded.length, 4);
  assert.equal(decoded[0].type, ControlTlvType.NodeKey);
  assert.deepEqual(decoded[0].value, fields[0].value);
  assert.equal(decoded[1].type, ControlTlvType.Endpoints);
  assert.equal(decoded[1].value.length, 0);
  assert.equal(decoded[2].type, unknownType, 'unknown type must be preserved');
  assert.deepEqual(decoded[2].value, fields[2].value);
  assert.equal(decoded[3].type, ControlTlvType.ErrorText);
  assert.deepEqual(decoded[3].value, fields[3].value);
  // parseControlTlvType：未知 type 确为 null，其余已知
  assert.equal(parseControlTlvType(unknownType), null);
  for (const known of decoded) {
    if (known.type !== unknownType) {
      assert.equal(parseControlTlvType(known.type), known.type);
    }
  }
});

test('字段编码字节布局：type 与 length 均为 u16 大端', () => {
  const encoded: Uint8Array = controlTlvEncode([field(0x0002, new Uint8Array([0xaa, 0xbb]))]);
  assert.deepEqual(encoded, new Uint8Array([0x00, 0x02, 0x00, 0x02, 0xaa, 0xbb]));
  // type 0x0102 / len 1
  const wide: Uint8Array = controlTlvEncode([field(0x0102, new Uint8Array([0x5a]))]);
  assert.deepEqual(wide, new Uint8Array([0x01, 0x02, 0x00, 0x01, 0x5a]));
});

test('字段 value 上界：65535B 可往返，65536B 抛 ControlError(TLV)', () => {
  const max: Uint8Array = seqPool(0x00, 65535);
  const encoded: Uint8Array = controlTlvEncode([field(ControlTlvType.PacketFilter, max)]);
  assert.equal(encoded.length, 4 + 65535);
  const decoded: ControlTlvField[] = controlTlvDecode(encoded);
  assert.equal(decoded.length, 1);
  assert.equal(decoded[0].value.length, 65535);
  assert.deepEqual(decoded[0].value, max);

  assertTlvError(() => controlTlvEncode([field(ControlTlvType.PacketFilter, seqPool(0x00, 65536))]));
});

test('空字段流：编码为空、解码为空数组', () => {
  const encoded: Uint8Array = controlTlvEncode([]);
  assert.equal(encoded.length, 0);
  assert.deepEqual(controlTlvDecode(encoded), []);
});

test('消息层往返：kind 落为首个 MsgKind 字段（u8）', () => {
  const msg: ControlMessage = {
    kind: ControlMsgKind.MapRequest,
    fields: [field(ControlTlvType.NodeKey, seqPool(0x11, 32)), field(ControlTlvType.SeqNo, seqPool(0x22, 8))],
  };
  const bytes: Uint8Array = controlEncodeMessage(msg);
  // 首字段即 MsgKind：type=0x0001、len=0x0001、value=kind
  assert.deepEqual(bytes.slice(0, 5), new Uint8Array([0x00, 0x01, 0x00, 0x01, ControlMsgKind.MapRequest]));
  const decoded: ControlMessage = controlDecodeMessage(bytes);
  assert.equal(decoded.kind, ControlMsgKind.MapRequest);
  assert.equal(decoded.fields.length, 2);
  assert.equal(decoded.fields[0].type, ControlTlvType.NodeKey);
  assert.deepEqual(decoded.fields[0].value, msg.fields[0].value);
  assert.equal(decoded.fields[1].type, ControlTlvType.SeqNo);
  assert.deepEqual(decoded.fields[1].value, msg.fields[1].value);
});

test('parseControlMsgKind：已知五类返回原值，未知返回 null', () => {
  assert.equal(parseControlMsgKind(ControlMsgKind.MapRequest), ControlMsgKind.MapRequest);
  assert.equal(parseControlMsgKind(ControlMsgKind.MapResponse), ControlMsgKind.MapResponse);
  assert.equal(parseControlMsgKind(ControlMsgKind.KeepAlive), ControlMsgKind.KeepAlive);
  assert.equal(parseControlMsgKind(ControlMsgKind.Ping), ControlMsgKind.Ping);
  assert.equal(parseControlMsgKind(ControlMsgKind.Pong), ControlMsgKind.Pong);
  assert.equal(parseControlMsgKind(0), null);
  assert.equal(parseControlMsgKind(6), null);
  assert.equal(parseControlMsgKind(255), null);
});

test('消息解码畸形：空流/首字段非 MsgKind/MsgKind value 长度≠1 → ControlError(TLV)', () => {
  // 空字段流 → 缺 MsgKind
  assertTlvError(() => controlDecodeMessage(new Uint8Array(0)));
  // 首字段为 NodeKey 而非 MsgKind（type=0x0002, len=1）
  assertTlvError(() => controlDecodeMessage(new Uint8Array([0x00, 0x02, 0x00, 0x01, 0x01])));
  // MsgKind value 2 字节
  assertTlvError(() => controlDecodeMessage(new Uint8Array([0x00, 0x01, 0x00, 0x02, 0x01, 0x02])));
  // MsgKind value 0 字节
  assertTlvError(() => controlDecodeMessage(new Uint8Array([0x00, 0x01, 0x00, 0x00])));
});

test('字段解码截断：半头/只有 type/缺值 → ControlError(TLV)', () => {
  assertTlvError(() => controlTlvDecode(new Uint8Array([0x00]))); // 半头
  assertTlvError(() => controlTlvDecode(new Uint8Array([0x00, 0x02, 0x00]))); // 头缺 1 字节
  assertTlvError(() => controlTlvDecode(new Uint8Array([0x00, 0x02, 0x00, 0x04, 0x01, 0x02]))); // 缺值 2 字节
  // 尾随残缺字段：完整字段后再来半头
  assertTlvError(() => controlTlvDecode(new Uint8Array([0x00, 0x01, 0x00, 0x00, 0x00])));
});

test('解码端到端确定性：同一字段集编码字节恒定', () => {
  const fields: ControlTlvField[] = [field(ControlTlvType.DiscoKey, seqPool(0x33, 32))];
  assert.deepEqual(controlTlvEncode(fields), controlTlvEncode(fields));
});

test('输出独立性（R8）：encode/decode 输出不与输入共享内存', () => {
  const value: Uint8Array = seqPool(0x44, 8);
  const encoded: Uint8Array = controlTlvEncode([field(ControlTlvType.PacketFilter, value)]);
  value[0] = (value[0] ^ 0xff) & 0xff;
  assert.equal(encoded[4], 0x44, 'encode output must not alias field value');

  const decoded: ControlTlvField[] = controlTlvDecode(encoded);
  decoded[0].value[1] = (decoded[0].value[1] ^ 0xff) & 0xff;
  assert.equal(encoded[5], 0x45, 'decoded value must not alias input bytes');

  const msg: ControlMessage = { kind: ControlMsgKind.Ping, fields: [] };
  const msgBytes: Uint8Array = controlEncodeMessage(msg);
  const decodedMsg: ControlMessage = controlDecodeMessage(msgBytes);
  assert.equal(decodedMsg.kind, ControlMsgKind.Ping);
  assert.equal(decodedMsg.fields.length, 0);
});

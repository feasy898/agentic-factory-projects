/**
 * 通用 TLV 编解码（架构契约 §7.1）—— 控制面消息的字节层。
 *
 * 线格式（本包本地契约，两端一致即可互操作）：
 *   字段 = type u16be || length u16be || value(length 字节)
 *   消息 = TLV 字段序列；controlEncodeMessage 把 kind 落为首个 MsgKind 字段
 *          （type=0x01、length=1、value=u8），controlDecodeMessage 反向取出。
 *
 * 语义约定：
 * - 未知 type 不丢：controlTlvDecode 原样保留（保序），供前向兼容与上层透传；
 * - 截断（半头/缺值）与超长（单字段 value > 65535）抛 ControlError('TLV')；
 * - 所有返回的 value 均为独立拷贝（R8），与输入字节不共享内存。
 */

import { ByteReader, ByteWriter } from '@ohos-tailscale/common';
import { ControlError } from './errors.ts';
import { ControlTlvType } from './types.ts';

/** 单个 TLV 字段。value 为调用方所给字节的拷贝语义见编解码函数注释（R8）。 */
export interface ControlTlvField {
  type: number;
  value: Uint8Array;
}

/** 一条控制面消息：kind（MsgKind 的 u8 值）+ 除 MsgKind 外的字段序列。 */
export interface ControlMessage {
  kind: number;
  fields: ControlTlvField[];
}

/** 单字段头字节数（type u16be + length u16be）。 */
const FIELD_HEADER_LEN: number = 4;
/** 单字段 value 上界 = u16 表示域。 */
const MAX_FIELD_VALUE_LEN: number = 65535;
/** MsgKind 字段 value 固定 1 字节（u8）。 */
const MSG_KIND_VALUE_LEN: number = 1;

/**
 * 编码 TLV 字段流。返回新数组；输入字段对象与其 value 不被修改。
 * 单字段 value 超过 65535B 抛 ControlError('TLV')。
 */
export function controlTlvEncode(fields: ControlTlvField[]): Uint8Array {
  const writer: ByteWriter = new ByteWriter(64);
  for (const field of fields) {
    if (field.value.length > MAX_FIELD_VALUE_LEN) {
      throw new ControlError(
        'TLV',
        'tlv encode: field type ' + String(field.type) + ' value too large: ' +
        String(field.value.length) + ' > ' + String(MAX_FIELD_VALUE_LEN),
      ) as Error;
    }
    writer.writeU16be(field.type);
    writer.writeU16be(field.value.length);
    writer.writeBytes(field.value);
  }
  return writer.toUint8Array();
}

/**
 * 解码完整 TLV 字段流（须恰好覆盖到末尾，尾随残缺字段视为截断）。
 * 未知 type 原样保留、保序；value 为独立拷贝（R8）。
 * 头/值截断抛 ControlError('TLV')。
 */
export function controlTlvDecode(bytes: Uint8Array): ControlTlvField[] {
  const reader: ByteReader = new ByteReader(bytes);
  const fields: ControlTlvField[] = [];
  while (!reader.atEnd()) {
    if (reader.remaining < FIELD_HEADER_LEN) {
      throw new ControlError(
        'TLV',
        'tlv decode: truncated field header at offset ' + String(reader.offset) +
        ' (remaining ' + String(reader.remaining) + ')',
      ) as Error;
    }
    const type: number = reader.readU16be();
    const len: number = reader.readU16be();
    if (reader.remaining < len) {
      throw new ControlError(
        'TLV',
        'tlv decode: truncated value for type ' + String(type) + ' at offset ' +
        String(reader.offset) + ' (need ' + String(len) + ', have ' + String(reader.remaining) + ')',
      ) as Error;
    }
    const value: Uint8Array = reader.readBytes(len);
    const field: ControlTlvField = { type: type, value: value };
    fields.push(field);
  }
  return fields;
}

/**
 * 编码一条完整控制面消息：kind 落为首个 MsgKind 字段（u8），其余字段原样跟随。
 * kind 不在 0..255 抛 ControlError('TLV')。
 */
export function controlEncodeMessage(msg: ControlMessage): Uint8Array {
  if (!Number.isInteger(msg.kind) || msg.kind < 0 || msg.kind > 0xff) {
    throw new ControlError('TLV', 'message encode: kind out of u8 range: ' + String(msg.kind)) as Error;
  }
  const msgKind: number = ControlTlvType.MsgKind;
  const kindField: ControlTlvField = { type: msgKind, value: new Uint8Array([msg.kind]) };
  const fields: ControlTlvField[] = [kindField];
  for (const f of msg.fields) {
    fields.push(f);
  }
  return controlTlvEncode(fields);
}

/**
 * 解码一条完整控制面消息：首个字段必须是 MsgKind 且 value 恰为 1 字节；
 * 缺 MsgKind（空消息或首字段类型不符）或 value 长度不符抛 ControlError('TLV')。
 * 余下字段原样进入 msg.fields（未知 type 保留不丢）。kind 不做已知性校验
 * （通用层保持前向兼容，已知性校验用 parseControlMsgKind）。
 */
export function controlDecodeMessage(bytes: Uint8Array): ControlMessage {
  const fields: ControlTlvField[] = controlTlvDecode(bytes);
  if (fields.length === 0) {
    throw new ControlError('TLV', 'message decode: missing MsgKind (empty field stream)') as Error;
  }
  const first: ControlTlvField = fields[0];
  if (first.type !== ControlTlvType.MsgKind) {
    throw new ControlError(
      'TLV',
      'message decode: first field type ' + String(first.type) + ' is not MsgKind (' +
      String(ControlTlvType.MsgKind) + ')',
    ) as Error;
  }
  if (first.value.length !== MSG_KIND_VALUE_LEN) {
    throw new ControlError(
      'TLV',
      'message decode: MsgKind value length ' + String(first.value.length) + ', want ' +
      String(MSG_KIND_VALUE_LEN),
    ) as Error;
  }
  const rest: ControlTlvField[] = [];
  for (let i: number = 1; i < fields.length; i += 1) {
    rest.push(fields[i]);
  }
  const msg: ControlMessage = { kind: first.value[0], fields: rest };
  return msg;
}

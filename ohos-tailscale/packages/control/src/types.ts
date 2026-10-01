/**
 * TLV 类型码与消息类别表（架构契约 §7.1；R5 常量对象 + 运行时校验函数模式，
 * 不用 enum / 字面量联合）。
 *
 * 线格式（架构契约 §7.1，本包本地契约、两端一致即可互操作）：
 *   字段 = type u16be || length u16be || value(length 字节)
 *   消息 = TLV 字段序列；首个字段必须是 MsgKind（value 为 u8）
 */

/** TLV 字段类型码（架构契约 §7.1 固定 { 0x01..0x08 }）。 */
export interface ControlTlvTypeE {
  MsgKind: number;
  NodeKey: number;
  DiscoKey: number;
  Endpoints: number;
  DerpRegionId: number;
  PacketFilter: number;
  SeqNo: number;
  ErrorText: number;
}

export const ControlTlvType: ControlTlvTypeE = {
  MsgKind: 0x01,
  NodeKey: 0x02,
  DiscoKey: 0x03,
  Endpoints: 0x04,
  DerpRegionId: 0x05,
  PacketFilter: 0x06,
  SeqNo: 0x07,
  ErrorText: 0x08,
};

/** 校验 v 是否为已知 TLV 类型码；已知返回 v 原值，未知返回 null。 */
export function parseControlTlvType(v: number): number | null {
  if (
    v === ControlTlvType.MsgKind ||
    v === ControlTlvType.NodeKey ||
    v === ControlTlvType.DiscoKey ||
    v === ControlTlvType.Endpoints ||
    v === ControlTlvType.DerpRegionId ||
    v === ControlTlvType.PacketFilter ||
    v === ControlTlvType.SeqNo ||
    v === ControlTlvType.ErrorText
  ) {
    return v;
  }
  return null;
}

/** 控制面消息类别（架构契约 §7.1 固定 { 1..5 }）。 */
export interface ControlMsgKindE {
  MapRequest: number;
  MapResponse: number;
  KeepAlive: number;
  Ping: number;
  Pong: number;
}

export const ControlMsgKind: ControlMsgKindE = {
  MapRequest: 1,
  MapResponse: 2,
  KeepAlive: 3,
  Ping: 4,
  Pong: 5,
};

/** 校验 v 是否为已知消息类别；已知返回 v 原值，未知返回 null。 */
export function parseControlMsgKind(v: number): number | null {
  if (
    v === ControlMsgKind.MapRequest ||
    v === ControlMsgKind.MapResponse ||
    v === ControlMsgKind.KeepAlive ||
    v === ControlMsgKind.Ping ||
    v === ControlMsgKind.Pong
  ) {
    return v;
  }
  return null;
}

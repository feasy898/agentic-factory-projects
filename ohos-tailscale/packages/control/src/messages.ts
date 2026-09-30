/**
 * 类型化控制面消息（架构契约 §7.1 字段表之上的结构层；任务要求的
 * RegisterRequest/RegisterResponse 与精简版 NetworkMap）。
 *
 * 语义仿 tailcfg 的注册/网络映射结构（【取证】§4/§8），字段取值取自契约的
 * 8 个 TLV 类型码；注册/映射复用契约消息类别的 MapRequest/MapResponse
 * （契约 §7.3 全流程即 dial → MapRequest → MapResponse）。
 *
 * 字段值编码约定（本包本地契约，value 均为裸字节）：
 *   NodeKey/DiscoKey : 32B 原始公钥（KEY_LEN_BYTES）
 *   Endpoints        : { u8 len, utf8("ip:port") } 重复条目（架构契约 §7.1）
 *   DerpRegionId     : u16be（0 = 未下发；region 999 需 2 字节，【取证】§1.2）
 *   PacketFilter     : 原始规则字节（一期透传，不做结构化解析，【取证】§4）
 *   SeqNo            : 8B BE u64 → BigInt（P6）
 *   ErrorText        : utf8 字符串（'' = 无错误）
 *
 * 编码输出为规范化字段序；解码按字段逐个归类：
 * - RegisterRequest（kind=MapRequest）：NodeKey/DiscoKey 必备且恰好一次；
 *   Endpoints 可选（缺省 []）；未知 type 忽略（前向兼容）；
 * - RegisterResponse（kind=MapResponse）：ErrorText 缺省 ''，NodeKey 缺省 null，
 *   SeqNo 缺省 0n；
 * - NetworkMap（kind=MapResponse）：SeqNo/PacketFilter 为映射级字段；
 *   每个 NodeKey 字段开启一个新 peer（DiscoKey 必备，DerpRegionId/Endpoints
 *   可选，归属其前最近的 NodeKey）；映射级字段不得出现在首个 NodeKey 之后
 *   重复，peer 级字段缺 NodeKey 前缀抛 ControlError('TLV')。
 *
 * 所有解码输出的 Uint8Array 均为独立拷贝（R8）。重复出现的同义字段一律抛
 * ControlError('TLV')（确定性优先，不做 last-wins）。
 */

import { KEY_LEN_BYTES, utf8Decode, utf8Encode, ByteReader, ByteWriter } from '@ohos-tailscale/common';
import { ControlError } from './errors.ts';
import { ControlMsgKind, ControlTlvType } from './types.ts';
import { controlEncodeMessage, controlDecodeMessage, type ControlMessage, type ControlTlvField } from './tlv.ts';

/** Endpoints 单条目最大字节数（u8 长度域）。 */
const ENDPOINT_LEN_MAX: number = 255;
/** DerpRegionId 字段值字节数（u16be）。 */
const DERP_REGION_ID_LEN: number = 2;
/** SeqNo 字段值字节数（u64be）。 */
const SEQ_NO_LEN: number = 8;

/** 注册请求（客户端 → 控制面；仿 tailcfg.RegisterRequest 的精简集）。 */
export interface RegisterRequest {
  /** WireGuard 层 node 公钥（32B）。 */
  nodeKey: Uint8Array;
  /** disco 发现协议公钥（32B）。 */
  discoKey: Uint8Array;
  /** 候选 UDP 端点列表（"ip:port"；STUN 派生公网映射 + 内网地址）。 */
  endpoints: string[];
}

/** 注册响应（控制面 → 客户端）。errorText 为 '' 表示注册被接受。 */
export interface RegisterResponse {
  /** 非空 = 控制面拒绝原因（ErrorText 字段）。 */
  errorText: string;
  /** 控制面回显的 node 公钥（32B）；未回显时为 null。 */
  nodeKey: Uint8Array | null;
  /** 控制面当前 netmap 序号（未下发时 0n）。 */
  seqNo: bigint;
}

/** 精简版 NetworkMap 中的单个 peer（仿 tailcfg.Node 的精简集）。 */
export interface NetworkMapPeer {
  /** WireGuard 层 node 公钥（32B，peer 身份）。 */
  nodeKey: Uint8Array;
  /** disco 发现协议公钥（32B，必备）。 */
  discoKey: Uint8Array;
  /** 该 peer 的候选 UDP 端点（缺省 []）。 */
  endpoints: string[];
  /** home DERP region ID（缺省 0 = 未下发）。 */
  homeDerpRegionId: number;
}

/** 精简版 NetworkMap（仿 tailcfg.NetworkMap 的精简集）。 */
export interface NetworkMap {
  /** netmap 序号（客户端以 SeqNo 请求增量；u64）。 */
  seqNo: bigint;
  /** 入站包过滤规则（原样透传字节；缺省空数组）。 */
  packetFilter: Uint8Array;
  /** peer 列表（编码序）。 */
  peers: NetworkMapPeer[];
}

/** 把 endpoints 列表编码为 Endpoints 字段 value：{ u8 len, utf8 } 重复条目。 */
export function encodeEndpointsValue(entries: string[]): Uint8Array {
  const writer: ByteWriter = new ByteWriter(32);
  for (const entry of entries) {
    const encoded: Uint8Array = utf8Encode(entry);
    if (encoded.length > ENDPOINT_LEN_MAX) {
      throw new ControlError(
        'TLV',
        'endpoints encode: entry longer than ' + String(ENDPOINT_LEN_MAX) + ' bytes: ' +
        String(encoded.length),
      ) as Error;
    }
    writer.writeU8(encoded.length);
    writer.writeBytes(encoded);
  }
  return writer.toUint8Array();
}

/** 解码 Endpoints 字段 value（{ u8 len, utf8 } 重复条目）；截断/非法 utf8 抛 ControlError('TLV')。 */
export function decodeEndpointsValue(value: Uint8Array): string[] {
  const reader: ByteReader = new ByteReader(value);
  const entries: string[] = [];
  while (!reader.atEnd()) {
    const len: number = reader.readU8();
    let raw: Uint8Array;
    try {
      raw = reader.readBytes(len);
    } catch (e) {
      throw new ControlError('TLV', 'endpoints decode: truncated entry (need ' + String(len) + '): ' + String(e)) as Error;
    }
    let text: string;
    try {
      text = utf8Decode(raw);
    } catch (e) {
      throw new ControlError('TLV', 'endpoints decode: invalid utf8 entry: ' + String(e)) as Error;
    }
    entries.push(text);
  }
  return entries;
}

/** 校验 msg.kind 并返回（不符抛 ControlError('TLV')）。 */
function requireKind(msg: ControlMessage, want: number, what: string): void {
  if (msg.kind !== want) {
    throw new ControlError(
      'TLV',
      what + ': unexpected kind ' + String(msg.kind) + ', want ' + String(want),
    ) as Error;
  }
}

/** 取定长字段值（独立拷贝）；长度不符抛 ControlError('TLV')。 */
function expectFixedValue(value: Uint8Array, want: number, what: string): Uint8Array {
  if (value.length !== want) {
    throw new ControlError(
      'TLV',
      what + ': value length ' + String(value.length) + ', want ' + String(want),
    ) as Error;
  }
  return value.slice();
}

/** 校验 32B 公钥字段并返回拷贝。 */
function expectKeyValue(value: Uint8Array, what: string): Uint8Array {
  return expectFixedValue(value, KEY_LEN_BYTES, what);
}

/** 解码 u16be 字段值。 */
function expectU16Value(value: Uint8Array, what: string): number {
  const raw: Uint8Array = expectFixedValue(value, DERP_REGION_ID_LEN, what);
  const reader: ByteReader = new ByteReader(raw);
  return reader.readU16be();
}

/** 解码 u64be 字段值（P6：u64 槽位一律 BigInt）。 */
function expectU64Value(value: Uint8Array, what: string): bigint {
  const raw: Uint8Array = expectFixedValue(value, SEQ_NO_LEN, what);
  const reader: ByteReader = new ByteReader(raw);
  return reader.readU64be();
}

/** 编码 RegisterRequest → ControlMessage（kind=MapRequest；字段序 NodeKey, DiscoKey, Endpoints?）。 */
export function registerRequestEncode(req: RegisterRequest): ControlMessage {
  const fields: ControlTlvField[] = [
    { type: ControlTlvType.NodeKey, value: expectKeyValue(req.nodeKey, 'register request nodeKey') },
    { type: ControlTlvType.DiscoKey, value: expectKeyValue(req.discoKey, 'register request discoKey') },
  ];
  if (req.endpoints.length > 0) {
    const field: ControlTlvField = { type: ControlTlvType.Endpoints, value: encodeEndpointsValue(req.endpoints) };
    fields.push(field);
  }
  const msg: ControlMessage = { kind: ControlMsgKind.MapRequest, fields: fields };
  return msg;
}

/** 编码 ControlMessage → 字节并回解为 ControlMessage 的便捷复合（测试/调试用）。 */
export function registerRequestEncodeBytes(req: RegisterRequest): Uint8Array {
  return controlEncodeMessage(registerRequestEncode(req));
}

/** 解码 ControlMessage → RegisterRequest；kind 不符/必备字段缺失/重复/长度不符抛 ControlError('TLV')。 */
export function registerRequestDecode(msg: ControlMessage): RegisterRequest {
  requireKind(msg, ControlMsgKind.MapRequest, 'register request decode');
  let nodeKey: Uint8Array | null = null;
  let discoKey: Uint8Array | null = null;
  let endpoints: string[] | null = null;
  const reqFields: ControlTlvField[] = msg.fields;
  for (const field of reqFields) {
    if (field.type === ControlTlvType.NodeKey) {
      if (nodeKey !== null) {
        throw new ControlError('TLV', 'register request decode: duplicate NodeKey') as Error;
      }
      nodeKey = expectKeyValue(field.value, 'register request NodeKey');
    } else if (field.type === ControlTlvType.DiscoKey) {
      if (discoKey !== null) {
        throw new ControlError('TLV', 'register request decode: duplicate DiscoKey') as Error;
      }
      discoKey = expectKeyValue(field.value, 'register request DiscoKey');
    } else if (field.type === ControlTlvType.Endpoints) {
      if (endpoints !== null) {
        throw new ControlError('TLV', 'register request decode: duplicate Endpoints') as Error;
      }
      endpoints = decodeEndpointsValue(field.value);
    }
    // 未知 type：忽略（前向兼容）。
  }
  if (nodeKey === null) {
    throw new ControlError('TLV', 'register request decode: missing NodeKey') as Error;
  }
  if (discoKey === null) {
    throw new ControlError('TLV', 'register request decode: missing DiscoKey') as Error;
  }
  const req: RegisterRequest = {
    nodeKey: nodeKey,
    discoKey: discoKey,
    endpoints: endpoints === null ? [] : endpoints,
  };
  return req;
}

/** 从原始字节解码 RegisterRequest（controlDecodeMessage + registerRequestDecode）。 */
export function registerRequestDecodeBytes(bytes: Uint8Array): RegisterRequest {
  return registerRequestDecode(controlDecodeMessage(bytes));
}

/** 编码 RegisterResponse → ControlMessage（kind=MapResponse；字段序 NodeKey?, SeqNo, ErrorText?）。 */
export function registerResponseEncode(resp: RegisterResponse): ControlMessage {
  const fields: ControlTlvField[] = [];
  if (resp.nodeKey !== null) {
    const keyField: ControlTlvField = {
      type: ControlTlvType.NodeKey,
      value: expectKeyValue(resp.nodeKey, 'register response nodeKey'),
    };
    fields.push(keyField);
  }
  const writer: ByteWriter = new ByteWriter(SEQ_NO_LEN);
  writer.writeU64be(resp.seqNo);
  const seqField: ControlTlvField = { type: ControlTlvType.SeqNo, value: writer.toUint8Array() };
  fields.push(seqField);
  if (resp.errorText !== '') {
    const errField: ControlTlvField = { type: ControlTlvType.ErrorText, value: utf8Encode(resp.errorText) };
    fields.push(errField);
  }
  const msg: ControlMessage = { kind: ControlMsgKind.MapResponse, fields: fields };
  return msg;
}

/** 解码 ControlMessage → RegisterResponse；kind 不符/重复字段抛 ControlError('TLV')。 */
export function registerResponseDecode(msg: ControlMessage): RegisterResponse {
  requireKind(msg, ControlMsgKind.MapResponse, 'register response decode');
  let nodeKey: Uint8Array | null = null;
  let seqNo: bigint | null = null;
  let errorText: string | null = null;
  const respFields: ControlTlvField[] = msg.fields;
  for (const field of respFields) {
    if (field.type === ControlTlvType.NodeKey) {
      if (nodeKey !== null) {
        throw new ControlError('TLV', 'register response decode: duplicate NodeKey') as Error;
      }
      nodeKey = expectKeyValue(field.value, 'register response NodeKey');
    } else if (field.type === ControlTlvType.SeqNo) {
      if (seqNo !== null) {
        throw new ControlError('TLV', 'register response decode: duplicate SeqNo') as Error;
      }
      seqNo = expectU64Value(field.value, 'register response SeqNo');
    } else if (field.type === ControlTlvType.ErrorText) {
      if (errorText !== null) {
        throw new ControlError('TLV', 'register response decode: duplicate ErrorText') as Error;
      }
      let text: string;
      try {
        text = utf8Decode(field.value);
      } catch (e) {
        throw new ControlError('TLV', 'register response decode: invalid utf8 ErrorText: ' + String(e)) as Error;
      }
      errorText = text;
    }
    // 未知 type：忽略（前向兼容）。
  }
  const resp: RegisterResponse = {
    errorText: errorText === null ? '' : errorText,
    nodeKey: nodeKey,
    seqNo: seqNo === null ? 0n : seqNo,
  };
  return resp;
}

/** 编码 NetworkMap → ControlMessage（kind=MapResponse；SeqNo, PacketFilter?, 逐 peer 字段组）。 */
export function networkMapEncode(map: NetworkMap): ControlMessage {
  const fields: ControlTlvField[] = [];
  const writer: ByteWriter = new ByteWriter(SEQ_NO_LEN);
  writer.writeU64be(map.seqNo);
  const seqField: ControlTlvField = { type: ControlTlvType.SeqNo, value: writer.toUint8Array() };
  fields.push(seqField);
  if (map.packetFilter.length > 0) {
    const filterField: ControlTlvField = { type: ControlTlvType.PacketFilter, value: map.packetFilter.slice() };
    fields.push(filterField);
  }
  for (const peer of map.peers) {
    const keyField: ControlTlvField = {
      type: ControlTlvType.NodeKey,
      value: expectKeyValue(peer.nodeKey, 'network map peer nodeKey'),
    };
    fields.push(keyField);
    const discoField: ControlTlvField = {
      type: ControlTlvType.DiscoKey,
      value: expectKeyValue(peer.discoKey, 'network map peer discoKey'),
    };
    fields.push(discoField);
    if (peer.homeDerpRegionId !== 0) {
      const regionWriter: ByteWriter = new ByteWriter(DERP_REGION_ID_LEN);
      regionWriter.writeU16be(peer.homeDerpRegionId);
      const regionField: ControlTlvField = { type: ControlTlvType.DerpRegionId, value: regionWriter.toUint8Array() };
      fields.push(regionField);
    }
    if (peer.endpoints.length > 0) {
      const endpointsField: ControlTlvField = {
        type: ControlTlvType.Endpoints,
        value: encodeEndpointsValue(peer.endpoints),
      };
      fields.push(endpointsField);
    }
  }
  const msg: ControlMessage = { kind: ControlMsgKind.MapResponse, fields: fields };
  return msg;
}

/**
 * 解码 ControlMessage → NetworkMap。逐字段归类：
 * SeqNo/PacketFilter 为映射级；NodeKey 开启新 peer；DiscoKey/DerpRegionId/
 * Endpoints 归属当前 peer（缺 NodeKey 前缀、peer 缺 DiscoKey、重复字段、
 * kind 不符均抛 ControlError('TLV')）；未知 type 忽略。
 */
export function networkMapDecode(msg: ControlMessage): NetworkMap {
  requireKind(msg, ControlMsgKind.MapResponse, 'network map decode');
  let seqNo: bigint | null = null;
  let packetFilter: Uint8Array | null = null;
  const peers: NetworkMapPeer[] = [];
  let cur: NetworkMapPeer | null = null;
  let curHasDisco: boolean = false;
  let curHasRegion: boolean = false;
  let curHasEndpoints: boolean = false;

  const mapFields: ControlTlvField[] = msg.fields;
  for (const field of mapFields) {
    if (field.type === ControlTlvType.SeqNo) {
      if (seqNo !== null) {
        throw new ControlError('TLV', 'network map decode: duplicate SeqNo') as Error;
      }
      seqNo = expectU64Value(field.value, 'network map SeqNo');
    } else if (field.type === ControlTlvType.PacketFilter) {
      if (packetFilter !== null) {
        throw new ControlError('TLV', 'network map decode: duplicate PacketFilter') as Error;
      }
      packetFilter = field.value.slice();
    } else if (field.type === ControlTlvType.NodeKey) {
      if (cur !== null && !curHasDisco) {
        throw new ControlError('TLV', 'network map decode: peer missing DiscoKey') as Error;
      }
      const peer: NetworkMapPeer = {
        nodeKey: expectKeyValue(field.value, 'network map peer NodeKey'),
        discoKey: new Uint8Array(0),
        endpoints: [],
        homeDerpRegionId: 0,
      };
      peers.push(peer);
      cur = peer;
      curHasDisco = false;
      curHasRegion = false;
      curHasEndpoints = false;
    } else if (field.type === ControlTlvType.DiscoKey) {
      if (cur === null) {
        throw new ControlError('TLV', 'network map decode: DiscoKey before any NodeKey') as Error;
      }
      if (curHasDisco) {
        throw new ControlError('TLV', 'network map decode: duplicate DiscoKey in one peer') as Error;
      }
      cur.discoKey = expectKeyValue(field.value, 'network map peer DiscoKey');
      curHasDisco = true;
    } else if (field.type === ControlTlvType.DerpRegionId) {
      if (cur === null) {
        throw new ControlError('TLV', 'network map decode: DerpRegionId before any NodeKey') as Error;
      }
      if (curHasRegion) {
        throw new ControlError('TLV', 'network map decode: duplicate DerpRegionId in one peer') as Error;
      }
      cur.homeDerpRegionId = expectU16Value(field.value, 'network map peer DerpRegionId');
      curHasRegion = true;
    } else if (field.type === ControlTlvType.Endpoints) {
      if (cur === null) {
        throw new ControlError('TLV', 'network map decode: Endpoints before any NodeKey') as Error;
      }
      if (curHasEndpoints) {
        throw new ControlError('TLV', 'network map decode: duplicate Endpoints in one peer') as Error;
      }
      cur.endpoints = decodeEndpointsValue(field.value);
      curHasEndpoints = true;
    }
    // 未知 type：忽略（前向兼容；通用层 ControlMessage 仍保留原字段）。
  }
  if (cur !== null && !curHasDisco) {
    throw new ControlError('TLV', 'network map decode: peer missing DiscoKey') as Error;
  }
  const map: NetworkMap = {
    seqNo: seqNo === null ? 0n : seqNo,
    packetFilter: packetFilter === null ? new Uint8Array(0) : packetFilter,
    peers: peers,
  };
  return map;
}

/** 从原始字节解码 NetworkMap（controlDecodeMessage + networkMapDecode）。 */
export function networkMapDecodeBytes(bytes: Uint8Array): NetworkMap {
  return networkMapDecode(controlDecodeMessage(bytes));
}

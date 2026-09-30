/**
 * tailcfg 兼容层（AU3 对齐）——真实控制面（tailscale control / Headscale）在
 * ts2021 Noise 连接上传输的是 tailcfg 结构的 JSON（POST /machine/register 与
 * POST /machine/map），不是本包 messages.ts 的本地 TLV 契约。本模块提供最小
 * JSON 编解码，让 ControlClient 之外新增的互操作客户端能对真实服务器注册与拉取
 * 网络地图。
 *
 * ✅ 上游核对（AU3，2026-09-29 实读 tailscale main tailcfg.go @ L1318/L1372/L1436、
 *    headscale v0.29.4 hscontrol/noise.go）：
 * - RegisterRequest JSON 字段：Version(CapabilityVersion, 当前上游
 *   CurrentCapabilityVersion=148)、NodeKey/OldNodeKey（"nodekey:<64hex>"）、NLKey、
 *   Auth:{AuthKey}（preauth key 模式）、Expiry(RFC3339)、Followup、Hostinfo:{...}、
 *   Ephemeral、Tailnet；
 * - RegisterResponse JSON：User/Login（对象）、NodeKeyExpired、MachineAuthorized、
 *   AuthURL、NodeKeySignature、Error；
 * - MapRequest JSON：Version、Compress("")、KeepAlive、NodeKey、DiscoKey、Stream、
 *   Hostinfo、Endpoints、ReadOnly、OmitPeers；
 * - MapResponse：服务器以 chunked 流返回多行 JSON（每行一个对象）。
 *
 * JSON 使用约定（ArkTS）：本模块是全仓唯一触碰 JSON 的模块；JSON.parse 返回值一律
 * 立即 `as` 到具名 interface，字段访问走类型化路径；ArkTS 侧实际可用性记入约束文档
 * U 项（U3/U5 同族），真机验证前不解除。
 */

import { ControlError } from './errors.ts';

/** 上游 CurrentCapabilityVersion（tailcfg.go L200，2026-09-29 实读 main）。 */
export const TAILCFG_CURRENT_CAPABILITY_VERSION: number = 148;

/** nodekey/discokey 的 64 位小写十六进制表示包装（"nodekey:xxxx…" 形态）。 */
export function formatNodeKey(publicKey: Uint8Array, prefix: 'nodekey' | 'discokey'): string {
  let hex: string = '';
  for (let i: number = 0; i < publicKey.length; i += 1) {
    hex += HEX_DIGITS.charAt(publicKey[i] >> 4);
    hex += HEX_DIGITS.charAt(publicKey[i] & 0x0f);
  }
  return prefix + ':' + hex;
}

const HEX_DIGITS: string = '0123456789abcdef';

/** 注册请求载荷（编码为 JSON；可选字段不赋值时 JSON.stringify 会整字段省略）。 */
export interface TailcfgRegisterRequest {
  Version: number;
  NodeKey: string;
  OldNodeKey?: string;
  NLKey: string;
  Auth: TailcfgRegisterAuth | null;
  Expiry: string;
  Followup: string;
  Hostinfo: TailcfgHostinfo;
  Ephemeral: boolean;
  Tailnet: string;
}

/** 注册鉴权载体（preauth key 模式只填 AuthKey）。 */
export interface TailcfgRegisterAuth {
  AuthKey: string;
}

/** 极简 Hostinfo（真实服务器至少消费 Hostname）。 */
export interface TailcfgHostinfo {
  Hostname: string;
  OS: string;
}

/** 组装注册请求 JSON。expiry 为 RFC3339 字符串（如 '2030-01-01T00:00:00Z'）。 */
export function encodeRegisterRequest(params: RegisterRequestParams): string {
  let auth: TailcfgRegisterAuth | null = null;
  if (params.authKey !== null) {
    const authPayload: TailcfgRegisterAuth = { AuthKey: params.authKey };
    auth = authPayload;
  }
  const req: TailcfgRegisterRequest = {
    Version: params.capabilityVersion,
    NodeKey: formatNodeKey(params.nodeKeyPublic, 'nodekey'),
    NLKey: 'nlpub:' + ZERO_KEY_HEX,
    Auth: auth,
    Expiry: params.expiryRfc3339,
    Followup: '',
    Hostinfo: { Hostname: params.hostname, OS: params.os },
    Ephemeral: params.ephemeral,
    Tailnet: '',
  };
  if (params.oldNodeKeyPublic !== null) {
    req.OldNodeKey = formatNodeKey(params.oldNodeKeyPublic, 'nodekey');
  }
  return JSON.stringify(req);
}

/** 注册请求参数（null 字段按上游 omitempty 语义省略/置零）。 */
export interface RegisterRequestParams {
  capabilityVersion: number;
  nodeKeyPublic: Uint8Array;
  oldNodeKeyPublic: Uint8Array | null;
  authKey: string | null;
  expiryRfc3339: string;
  hostname: string;
  os: string;
  ephemeral: boolean;
}

const ZERO_KEY_HEX: string = '0000000000000000000000000000000000000000000000000000000000000000';

/** 注册响应（解析后的字段视图；User/Login 原样保留 JSON 文本）。 */
export interface TailcfgRegisterResponse {
  machineAuthorized: boolean;
  nodeKeyExpired: boolean;
  authUrl: string;
  error: string;
  nodeKeyChallenge: string;
  raw: string;
}

/** 解析注册响应 JSON；Error 非空时抛 ControlError('HTTP')。 */
export function decodeRegisterResponse(jsonText: string): TailcfgRegisterResponse {
  const parsed = JSON.parse(jsonText) as ParsedRegisterResponse;
  const out: TailcfgRegisterResponse = {
    machineAuthorized: parsed.MachineAuthorized === true,
    nodeKeyExpired: parsed.NodeKeyExpired === true,
    authUrl: typeof parsed.AuthURL === 'string' ? parsed.AuthURL : '',
    error: typeof parsed.Error === 'string' ? parsed.Error : '',
    nodeKeyChallenge: typeof parsed.NodeKeyChallenge === 'string' ? parsed.NodeKeyChallenge : '',
    raw: jsonText,
  };
  if (out.error !== '') {
    throw new ControlError('HTTP', 'tailcfg: register rejected: ' + out.error) as Error;
  }
  return out;
}

interface ParsedRegisterResponse {
  MachineAuthorized?: boolean;
  NodeKeyExpired?: boolean;
  AuthURL?: string;
  Error?: string;
  NodeKeyChallenge?: string;
}

/** 地图请求载荷。 */
export interface TailcfgMapRequest {
  Version: number;
  Compress: string;
  KeepAlive: boolean;
  NodeKey: string;
  DiscoKey: string;
  Stream: boolean;
  Hostinfo: TailcfgHostinfo;
  Endpoints: string[];
  ReadOnly: boolean;
  OmitPeers: boolean;
}

/** 组装地图请求 JSON。 */
export function encodeMapRequest(params: MapRequestParams): string {
  const req: TailcfgMapRequest = {
    Version: params.capabilityVersion,
    Compress: '',
    KeepAlive: false,
    NodeKey: formatNodeKey(params.nodeKeyPublic, 'nodekey'),
    DiscoKey: formatNodeKey(params.discoKeyPublic, 'discokey'),
    Stream: params.stream,
    Hostinfo: { Hostname: params.hostname, OS: params.os },
    Endpoints: [],
    ReadOnly: false,
    OmitPeers: false,
  };
  return JSON.stringify(req);
}

export interface MapRequestParams {
  capabilityVersion: number;
  nodeKeyPublic: Uint8Array;
  discoKeyPublic: Uint8Array;
  stream: boolean;
  hostname: string;
  os: string;
}

/** 地图响应的极简视图（首帧自检用：能解析、知道有多少 peer 即可）。 */
export interface TailcfgMapResponseView {
  keepAlive: boolean;
  peerCount: number;
  rawPreview: string;
}

/** 从一行 MapResponse JSON 提取极简视图（不做完整 tailcfg 解码）。 */
export function decodeMapResponseSummary(jsonText: string): TailcfgMapResponseView {
  const parsed = JSON.parse(jsonText) as ParsedMapResponse;
  const peers: ParsedMapPeerEntry[] | undefined = parsed.Peers;
  const count: number = peers === undefined || peers === null ? 0 : peers.length;
  const out: TailcfgMapResponseView = {
    keepAlive: parsed.KeepAlive === true,
    peerCount: count,
    rawPreview: jsonText.length > 120 ? jsonText.slice(0, 120) + '…' : jsonText,
  };
  return out;
}

/** Peers 数组元素占位（本模块只取数组长度，不读 peer 字段；完整解码属二期）。 */
interface ParsedMapPeerEntry { }

interface ParsedMapResponse {
  KeepAlive?: boolean;
  Peers?: ParsedMapPeerEntry[];
}

/** 供互操作客户端生成统一错误（ControlError code='HTTP'）。 */
export function tailcfgError(message: string): ControlError {
  return new ControlError('HTTP', 'tailcfg: ' + message);
}

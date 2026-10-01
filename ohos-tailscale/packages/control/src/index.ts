/**
 * @ohos-tailscale/control 公开入口（barrel）。
 * 导出面 = docs/architecture.md §7 冻结契约 + 类型化消息层（RegisterRequest/
 * RegisterResponse/精简版 NetworkMap，任务书要求）；逐名显式导出。
 */

export { ControlError } from './errors.ts';

export {
  ControlTlvType,
  type ControlTlvTypeE,
  parseControlTlvType,
  ControlMsgKind,
  type ControlMsgKindE,
  parseControlMsgKind,
} from './types.ts';

export {
  controlTlvEncode,
  controlTlvDecode,
  controlEncodeMessage,
  controlDecodeMessage,
  type ControlTlvField,
  type ControlMessage,
} from './tlv.ts';

export {
  type RegisterRequest,
  registerRequestEncode,
  registerRequestDecode,
  registerRequestEncodeBytes,
  registerRequestDecodeBytes,
  type RegisterResponse,
  registerResponseEncode,
  registerResponseDecode,
  type NetworkMapPeer,
  type NetworkMap,
  networkMapEncode,
  networkMapDecode,
  networkMapDecodeBytes,
  encodeEndpointsValue,
  decodeEndpointsValue,
} from './messages.ts';

export { CONTROL_NOISE_PROLOGUE, ControlClient, type ControlClientConfig } from './client.ts';

export {
  TAILCFG_CURRENT_CAPABILITY_VERSION,
  formatNodeKey,
  encodeRegisterRequest,
  decodeRegisterResponse,
  encodeMapRequest,
  decodeMapResponseSummary,
  tailcfgError,
  type TailcfgRegisterRequest,
  type TailcfgRegisterAuth,
  type TailcfgHostinfo,
  type TailcfgRegisterResponse,
  type RegisterRequestParams,
  type TailcfgMapRequest,
  type MapRequestParams,
  type TailcfgMapResponseView,
} from './tailcfg.ts';

export {
  encodeMachineRequest,
  HttpOverNoiseReader,
  type HttpOverNoiseResponse,
} from './noisehttp.ts';

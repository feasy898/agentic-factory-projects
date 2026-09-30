/**
 * @ohos-tailscale/noise 公开入口（barrel）。
 * 导出面 = docs/architecture.md §6 冻结契约，逐名显式导出；
 * 内部模块 symmetric.ts（SymmetricState）与 transport.ts 的 nonceForCounter
 * 不进公开 API。
 */

export {
  NOISE_PROTOCOL_NAME,
  NoiseIkInitiator,
  NoiseIkResponder,
  type NoiseIkPayload,
  type NoiseTransportPair,
} from './handshake.ts';

export { NoiseTransportCipher } from './transport.ts';

export { noiseFrameEncode, noiseFrameDecode, NoiseFrameReader, type NoiseFrame } from './frame.ts';

export { NoiseError } from './errors.ts';

export {
  CONTROLBASE_PROTOCOL_VERSION,
  CONTROLBASE_PROLOGUE_PREFIX,
  CONTROLBASE_MAX_FRAME_BYTES,
  CONTROLBASE_MAX_PLAINTEXT_BYTES,
  ControlBaseSession,
  controlbaseBuildInitiation,
  controlbaseCompleteHandshake,
  controlbaseClientHandshake,
  type ControlBaseDuplex,
  type ControlBaseInitiation,
} from './controlbase.ts';

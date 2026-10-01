/**
 * @ohos-tailscale/crypto 公开入口（barrel）。
 * 导出面 = docs/architecture.md §4 冻结契约，逐名显式导出；
 * 内部原语（chacha20Block/chacha20Xor/poly1305Mac/blake2sCore/hmacBlake2s 等）
 * 仅在包内模块与测试中可见，不进公开 API。
 */

export { CryptoError, type CryptoKeyPair } from './errors.ts';

export {
  x25519GenerateKeyPair,
  x25519PublicKeyFromPrivate,
  x25519,
  isZeroBytes,
} from './x25519.ts';

export { aeadSeal, aeadOpen } from './aead.ts';

export {
  sha256,
  hmacSha256,
  blake2s256,
  blake2s256Keyed,
  kdf2Blake2s,
  kdf3Blake2s,
  kdf2Sha256,
  kdf3Sha256,
} from './hash.ts';

export { constTimeEqual, wipe } from './util.ts';

export {
  naclboxSharedKey,
  naclboxSeal,
  naclboxOpen,
  salsa20Poly1305Seal,
  salsa20Poly1305Open,
} from './naclbox.ts';

/** XChaCha20-Poly1305 / HChaCha20（2026-10-01 夜班新增；Cookie Reply 消费方，draft-irtf-cfrg-xchacha-03 向量锚定）。 */
export {
  XNONCE_LEN_BYTES,
  hchacha20,
  xchacha20poly1305Open,
  xchacha20poly1305Seal,
} from './xchacha.ts';

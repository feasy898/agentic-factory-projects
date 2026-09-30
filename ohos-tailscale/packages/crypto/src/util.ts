/**
 * 字节工具（架构契约 §4 util.ts）。
 */

/**
 * 常时比较：逐字节 XOR 累加，全程不因内容提前返回。
 * 长度不等时直接返回 false（长度本身不是秘密，契约明示此语义）。
 */
export function constTimeEqual(a: Uint8Array, b: Uint8Array): boolean {
  if (a.length !== b.length) {
    return false;
  }
  let diff: number = 0;
  for (let i: number = 0; i < a.length; i += 1) {
    diff |= a[i] ^ b[i];
  }
  return diff === 0;
}

/**
 * 用全零覆写缓冲区（清密钥/中间值用；无法对抗 GC 拷贝，只能尽到清理义务）。
 * 零长度为数组是 no-op。
 */
export function wipe(b: Uint8Array): void {
  for (let i: number = 0; i < b.length; i += 1) {
    b[i] = 0;
  }
}

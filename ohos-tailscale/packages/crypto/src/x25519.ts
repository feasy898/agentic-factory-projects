/**
 * X25519（RFC 7748 §5/§6/§7）—— BigInt Montgomery 阶梯实现。
 *
 * - 域素数 p = 2^255 - 19；曲线 Curve25519：v^2 = u^3 + A*u^2 + u，A = 486662。
 * - 标量 clamp（RFC 7748 §5）：bits[0..2] 清零、bit[255] 清零、bit[254] 置一，
 *   即 k[0] &= 248、k[31] &= 127、k[31] |= 64。
 * - 语义等价 Go curve25519.X25519(scalar, point)：输入输出均为 32 字节小端。
 *   入参出参长度不符抛 CryptoError('RANGE')（架构契约 §4）。
 *
 * 注：BigInt 运算本身不保证常时（V8 大数实现无此承诺）；本实现与 RFC 7748 的
 * cswap 结构一致，但抗侧信强度受运行时约束，WireGuard 对等语义（全零共享密钥
 * 视为对端拒绝）由调用方经 isZeroBytes 兜底。
 */

import { KEY_LEN_BYTES, type Rng } from '@ohos-tailscale/common';
import { CryptoError, type CryptoKeyPair } from './errors.ts';

/** 域素数 p = 2^255 - 19。 */
const P: bigint = (1n << 255n) - 19n;
/** RFC 7748 伪代码中的 a24 = (A - 2) / 4 = 121665。 */
const A24: bigint = 121665n;

/** 曲线基点 u = 9（32 字节小端）；模块加载时按位填定，无随机性。 */
const BASE_POINT: Uint8Array = new Uint8Array(32);
BASE_POINT[0] = 9;

/** 校验 32 字节长度，不符抛 CryptoError('RANGE')。 */
function assertLen32(b: Uint8Array, name: string): void {
  if (b.length !== KEY_LEN_BYTES) {
    throw new CryptoError(
      'RANGE',
      'x25519: ' + name + ' must be ' + String(KEY_LEN_BYTES) + ' bytes, got ' + String(b.length),
    ) as Error;
  }
}

/** 小端字节序 → BigInt（输入非空）。 */
function decodeLittleEndian(b: Uint8Array): bigint {
  let r: bigint = 0n;
  for (let i: number = b.length - 1; i >= 0; i -= 1) {
    r = (r << 8n) | BigInt(b[i]);
  }
  return r;
}

/** BigInt → 定长小端字节序（截断高位）。 */
function encodeLittleEndian(v: bigint, len: number): Uint8Array {
  const out: Uint8Array = new Uint8Array(len);
  let x: bigint = v;
  for (let i: number = 0; i < len; i += 1) {
    out[i] = Number(x & 0xffn);
    x >>= 8n;
  }
  return out;
}

/** 归约到 [0, P)。调用方保证 v ≥ 0；减法先 +P 再取模。 */
function mod(v: bigint): bigint {
  return v % P;
}

/** BigInt 模幂（平方-乘），用于 z2^(p-2) 求逆。 */
function modPow(base: bigint, exponent: bigint): bigint {
  let result: bigint = 1n;
  let b: bigint = mod(base);
  let e: bigint = exponent;
  while (e > 0n) {
    if ((e & 1n) === 1n) {
      result = mod(result * b);
    }
    b = mod(b * b);
    e >>= 1n;
  }
  return result;
}

/**
 * RFC 7748 X25519：标量乘法 X25519(k, u)。
 * 内部对 scalar 做 clamp（幂等：clamp 过的输入再 clamp 不变）；
 * u 的高位掩码（RFC 7748 §5：X25519 必须掩去 u 最高位）。
 * 返回 32 字节新数组（独立拷贝，不与入参共享内存）。
 * 输出全零不在此拦截 —— WireGuard 语义由调用方用 isZeroBytes 检查。
 */
export function x25519(scalar: Uint8Array, point: Uint8Array): Uint8Array {
  assertLen32(scalar, 'scalar');
  assertLen32(point, 'point');

  const k: Uint8Array = scalar.slice();
  k[0] = k[0] & 248;
  k[31] = k[31] & 127;
  k[31] = k[31] | 64;
  const kInt: bigint = decodeLittleEndian(k);

  const u: Uint8Array = point.slice();
  u[31] = u[31] & 127;
  const x1: bigint = mod(decodeLittleEndian(u));

  // RFC 7748 §5 Montgomery 阶梯，254 位迭代（bit 255 已被 clamp 清零）。
  let x2: bigint = 1n;
  let z2: bigint = 0n;
  let x3: bigint = x1;
  let z3: bigint = 1n;
  let swap: bigint = 0n;
  for (let t: number = 254; t >= 0; t -= 1) {
    const kt: bigint = (kInt >> BigInt(t)) & 1n;
    swap = swap ^ kt;
    // 条件交换：BigInt 运算非常时，这里选择直白的分支交换（语义与 cswap 一致）。
    if (swap === 1n) {
      const tx: bigint = x2;
      x2 = x3;
      x3 = tx;
      const tz: bigint = z2;
      z2 = z3;
      z3 = tz;
    }
    swap = kt;

    const a: bigint = mod(x2 + z2);
    const aa: bigint = mod(a * a);
    const b: bigint = mod(x2 - z2 + P);
    const bb: bigint = mod(b * b);
    const e: bigint = mod(aa - bb + P);
    const c: bigint = mod(x3 + z3);
    const d: bigint = mod(x3 - z3 + P);
    const da: bigint = mod(d * a);
    const cb: bigint = mod(c * b);
    const daPcb: bigint = mod(da + cb);
    const daMcb: bigint = mod(da - cb + P);
    x3 = mod(daPcb * daPcb);
    z3 = mod(daMcb * daMcb);
    z3 = mod(x1 * z3);
    x2 = mod(aa * bb);
    z2 = mod(e * mod(aa + mod(A24 * e)));
  }
  if (swap === 1n) {
    const tx: bigint = x2;
    x2 = x3;
    x3 = tx;
    const tz: bigint = z2;
    z2 = z3;
    z3 = tz;
  }

  // 返回 x2 * z2^(p-2) mod p（z2 = 0 时结果为 0，即低阶点 → 全零输出）。
  const inv: bigint = modPow(z2, P - 2n);
  return encodeLittleEndian(mod(x2 * inv), KEY_LEN_BYTES);
}

/**
 * 由 32 字节私钥派生公钥：clamp 后对基点 u=9 做标量乘法
 * （等价 Go curve25519.X25519(k, basepoint)）。
 * 返回 32 字节新数组。
 */
export function x25519PublicKeyFromPrivate(privateKey: Uint8Array): Uint8Array {
  return x25519(privateKey, BASE_POINT);
}

/**
 * 生成 X25519 密钥对：从注入的 rng 取 32 随机字节，clamp 后作为 privateKey
 * 存储并派生 publicKey（契约：存储的是 clamp 后的私钥）。
 * publicKey/privateKey 均为新分配数组，与 rng 内部状态无共享。
 */
export function x25519GenerateKeyPair(rng: Rng): CryptoKeyPair {
  const privateKey: Uint8Array = new Uint8Array(KEY_LEN_BYTES);
  rng.randomBytes(privateKey);
  privateKey[0] = privateKey[0] & 248;
  privateKey[31] = privateKey[31] & 127;
  privateKey[31] = privateKey[31] | 64;
  const publicKey: Uint8Array = x25519(privateKey, BASE_POINT);
  const pair: CryptoKeyPair = { publicKey: publicKey, privateKey: privateKey };
  return pair;
}

/**
 * 常时语义的全零检测：逐字节 OR 归约，总时长只依赖数组长度不依赖内容。
 * WireGuard 语义：X25519 输出全零 = 对端拒绝（低阶点），握手必须中止。
 * 空数组返回 true。
 */
export function isZeroBytes(b: Uint8Array): boolean {
  let v: number = 0;
  for (let i: number = 0; i < b.length; i += 1) {
    v |= b[i];
  }
  return v === 0;
}

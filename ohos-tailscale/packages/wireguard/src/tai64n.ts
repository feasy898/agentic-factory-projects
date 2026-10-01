/**
 * TAI64N 时间戳（白皮书 5.4：TAI64N，12 字节 = 8B 大端秒（带 2^62 偏移）+ 4B 大端纳秒）。
 *
 * 本包约定：时间戳由注入的 Clock.wallMs()（Unix 毫秒）派生：
 *   秒 = floor(wallMs / 1000)，纳秒 = (wallMs % 1000) * 10^6。
 * TAI64 标签 = 2^62 + Unix 秒（白皮书 "secs since 1970 + 2^62"）。
 * 12 字节按大端拼接，字节序即数值序 → 逐字节比较即可判定新旧。
 */

import { ByteReader, ByteWriter } from '@ohos-tailscale/common';
import { WG_TIMESTAMP_LEN_BYTES } from './constants.ts';

/** TAI64 无秒纪元标签：2^62。 */
const TAI64_LABEL: bigint = 4611686018427387904n;

/** 解码结果载体（A2：纯字段 interface）。 */
export interface Tai64N {
  /** 含 2^62 标签的大端秒值。 */
  seconds: bigint;
  /** 纳秒部分（0..999999999）。 */
  nanos: number;
}

/**
 * 由 Unix 毫秒编码 TAI64N（12B 新数组）。
 * wallMs 非有限或为负抛 Error（TAI64N 编码不支持负时刻）。
 */
export function tai64nFromWallMs(wallMs: number): Uint8Array {
  if (!Number.isFinite(wallMs) || wallMs < 0) {
    throw new Error('tai64n: wallMs must be a non-negative finite number, got ' + String(wallMs));
  }
  const wholeSeconds: number = Math.floor(wallMs / 1000);
  const nanos: number = (wallMs - wholeSeconds * 1000) * 1000000;
  const writer: ByteWriter = new ByteWriter(WG_TIMESTAMP_LEN_BYTES);
  writer.writeU64be(TAI64_LABEL + BigInt(wholeSeconds));
  writer.writeU32be(nanos);
  return writer.toUint8Array();
}

/**
 * 解码 12B TAI64N；长度不符抛 Error。
 * 返回新载体对象（含输入的独立字段值，无共享内存）。
 */
export function tai64nDecode(t: Uint8Array): Tai64N {
  if (t.length !== WG_TIMESTAMP_LEN_BYTES) {
    throw new Error(
      'tai64n: must be ' + String(WG_TIMESTAMP_LEN_BYTES) + ' bytes, got ' + String(t.length),
    );
  }
  const reader: ByteReader = new ByteReader(t);
  const seconds: bigint = reader.readU64be();
  const nanos: number = reader.readU32be();
  const out: Tai64N = { seconds: seconds, nanos: nanos };
  return out;
}

/**
 * 字节流 reader/writer（P5：一切字节一律 Uint8Array）。
 *
 * 约定（docs/architecture.md §common）：
 * - 多字节整数同时提供大端（be）与小端（le）两个方法，方法名显式区分，不做重载；
 *   WireGuard 报文字段一律小端，Noise/ts2021 帧长度一律大端（详见架构文档）。
 * - u64 槽位一律 BigInt（P6），超范围抛 Error。
 * - readBytes/takeRemaining 返回独立拷贝（slice），调用方修改不影响内部缓冲。
 */

export class ByteReader {
  private buf: Uint8Array;
  private pos: number = 0;

  constructor(buf: Uint8Array) {
    this.buf = buf;
  }

  public get offset(): number {
    return this.pos;
  }

  public get remaining(): number {
    return this.buf.length - this.pos;
  }

  public atEnd(): boolean {
    return this.pos >= this.buf.length;
  }

  private need(n: number): void {
    if (n < 0) {
      throw new Error('ByteReader: negative length ' + String(n));
    }
    if (this.buf.length - this.pos < n) {
      throw new Error(
        'ByteReader: out of range (need ' + String(n) + ' bytes at offset ' +
        String(this.pos) + ', have ' + String(this.buf.length - this.pos) + ')',
      );
    }
  }

  public readU8(): number {
    this.need(1);
    const v: number = this.buf[this.pos];
    this.pos += 1;
    return v;
  }

  public readU16be(): number {
    this.need(2);
    const hi: number = this.buf[this.pos];
    const lo: number = this.buf[this.pos + 1];
    this.pos += 2;
    return hi * 256 + lo;
  }

  public readU16le(): number {
    this.need(2);
    const lo: number = this.buf[this.pos];
    const hi: number = this.buf[this.pos + 1];
    this.pos += 2;
    return hi * 256 + lo;
  }

  public readU32be(): number {
    this.need(4);
    let v: number = 0;
    for (let i: number = 0; i < 4; i += 1) {
      v = v * 256 + this.buf[this.pos + i];
    }
    this.pos += 4;
    return v;
  }

  public readU32le(): number {
    this.need(4);
    let v: number = 0;
    for (let i: number = 3; i >= 0; i -= 1) {
      v = v * 256 + this.buf[this.pos + i];
    }
    this.pos += 4;
    return v;
  }

  public readU64be(): bigint {
    this.need(8);
    let v: bigint = 0n;
    for (let i: number = 0; i < 8; i += 1) {
      v = (v << 8n) | BigInt(this.buf[this.pos + i]);
    }
    this.pos += 8;
    return v;
  }

  public readU64le(): bigint {
    this.need(8);
    let v: bigint = 0n;
    for (let i: number = 7; i >= 0; i -= 1) {
      v = (v << 8n) | BigInt(this.buf[this.pos + i]);
    }
    this.pos += 8;
    return v;
  }

  /** LEB128 无符号变长整数（DERP 帧长度用）；最多 10 字节，溢出抛 Error。 */
  public readUvarint(): bigint {
    let v: bigint = 0n;
    let shift: bigint = 0n;
    for (let i: number = 0; i < 10; i += 1) {
      this.need(1);
      const b: number = this.buf[this.pos];
      this.pos += 1;
      if (i === 9 && b > 0x01) {
        throw new Error('ByteReader: uvarint overflows 64 bits');
      }
      v |= BigInt(b & 0x7f) << shift;
      if ((b & 0x80) === 0) {
        return v;
      }
      shift += 7n;
    }
    throw new Error('ByteReader: uvarint too long (over 10 bytes)');
  }

  /** 读取 n 字节并返回独立拷贝。 */
  public readBytes(n: number): Uint8Array {
    this.need(n);
    const out: Uint8Array = this.buf.slice(this.pos, this.pos + n);
    this.pos += n;
    return out;
  }

  /** 读取全部剩余字节（独立拷贝）。 */
  public takeRemaining(): Uint8Array {
    return this.readBytes(this.remaining);
  }

  public skip(n: number): void {
    this.need(n);
    this.pos += n;
  }
}

export class ByteWriter {
  private buf: Uint8Array;
  private len: number = 0;

  constructor(initialCapacity: number = 64) {
    const cap: number = initialCapacity < 16 ? 16 : initialCapacity;
    this.buf = new Uint8Array(cap);
  }

  public get length(): number {
    return this.len;
  }

  private ensure(extra: number): void {
    const required: number = this.len + extra;
    if (required <= this.buf.length) {
      return;
    }
    let cap: number = this.buf.length;
    while (cap < required) {
      cap = cap * 2;
    }
    const next: Uint8Array = new Uint8Array(cap);
    next.set(this.buf.subarray(0, this.len));
    this.buf = next;
  }

  private checkU8(v: number): void {
    if (!Number.isInteger(v) || v < 0 || v > 0xff) {
      throw new Error('ByteWriter: u8 out of range: ' + String(v));
    }
  }

  private checkU16(v: number): void {
    if (!Number.isInteger(v) || v < 0 || v > 0xffff) {
      throw new Error('ByteWriter: u16 out of range: ' + String(v));
    }
  }

  private checkU32(v: number): void {
    if (!Number.isInteger(v) || v < 0 || v > 0xffffffff) {
      throw new Error('ByteWriter: u32 out of range: ' + String(v));
    }
  }

  private checkU64(v: bigint): void {
    if (v < 0n || v > 0xffffffffffffffffn) {
      throw new Error('ByteWriter: u64 out of range: ' + v.toString());
    }
  }

  public writeU8(v: number): void {
    this.checkU8(v);
    this.ensure(1);
    this.buf[this.len] = v;
    this.len += 1;
  }

  public writeU16be(v: number): void {
    this.checkU16(v);
    this.ensure(2);
    this.buf[this.len] = Math.floor(v / 256);
    this.buf[this.len + 1] = v % 256;
    this.len += 2;
  }

  public writeU16le(v: number): void {
    this.checkU16(v);
    this.ensure(2);
    this.buf[this.len] = v % 256;
    this.buf[this.len + 1] = Math.floor(v / 256);
    this.len += 2;
  }

  public writeU32be(v: number): void {
    this.checkU32(v);
    this.ensure(4);
    let x: number = v;
    for (let i: number = 3; i >= 0; i -= 1) {
      this.buf[this.len + i] = x % 256;
      x = Math.floor(x / 256);
    }
    this.len += 4;
  }

  public writeU32le(v: number): void {
    this.checkU32(v);
    this.ensure(4);
    let x: number = v;
    for (let i: number = 0; i < 4; i += 1) {
      this.buf[this.len + i] = x % 256;
      x = Math.floor(x / 256);
    }
    this.len += 4;
  }

  public writeU64be(v: bigint): void {
    this.checkU64(v);
    this.ensure(8);
    let x: bigint = v;
    for (let i: number = 7; i >= 0; i -= 1) {
      this.buf[this.len + i] = Number(x & 0xffn);
      x >>= 8n;
    }
    this.len += 8;
  }

  public writeU64le(v: bigint): void {
    this.checkU64(v);
    this.ensure(8);
    let x: bigint = v;
    for (let i: number = 0; i < 8; i += 1) {
      this.buf[this.len + i] = Number(x & 0xffn);
      x >>= 8n;
    }
    this.len += 8;
  }

  /** LEB128 无符号变长整数；超 64 位抛 Error。 */
  public writeUvarint(v: bigint): void {
    this.checkU64(v);
    let x: bigint = v;
    for (;;) {
      const b: number = Number(x & 0x7fn);
      x >>= 7n;
      if (x === 0n) {
        this.writeU8(b);
        return;
      }
      this.writeU8(b | 0x80);
    }
  }

  public writeBytes(b: Uint8Array): void {
    this.ensure(b.length);
    this.buf.set(b, this.len);
    this.len += b.length;
  }

  /** 已写字节的独立拷贝。 */
  public toUint8Array(): Uint8Array {
    return this.buf.slice(0, this.len);
  }

  public reset(): void {
    this.len = 0;
  }
}

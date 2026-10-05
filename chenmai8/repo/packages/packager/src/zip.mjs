/**
 * 极简 ZIP 读写（零第三方依赖，node:zlib deflate）。
 *
 * 写：deflate（收益不足时自动退回 store），固定时间戳保证同输入字节可复现。
 * 读：仅供自验收扫描 zip 内文件（解析 central directory + inflateRaw）。
 */
import { deflateRawSync, inflateRawSync } from "node:zlib";

// ---- CRC32 ----
const CRC_TABLE = (() => {
  const t = new Int32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    t[n] = c;
  }
  return t;
})();

export function crc32(buf) {
  let c = 0xffffffff;
  for (let i = 0; i < buf.length; i++) c = CRC_TABLE[(c ^ buf[i]) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

// 固定 DOS 时间（2026-01-01 00:00:00）→ 同输入产出同字节，包可复现。
const FIXED_DOS_TIME = 0;
const FIXED_DOS_DATE = (((2026 - 1980) & 0x7f) << 9) | (1 << 5) | 1;

function utf8Name(name) {
  const buf = Buffer.from(name, "utf8");
  if (buf.length > 0xffff) throw new Error(`zip 条目名过长: ${name}`);
  return buf;
}

/**
 * createZip(entries: [{ name, data: Buffer }]) → Buffer
 * 条目名按传入顺序写入；名字含目录时须用 "/"（zip 规范）。
 */
export function createZip(entries) {
  if (entries.length > 0xffff) throw new Error("zip 条目数超上限 65535");
  const seen = new Set();
  const localParts = [];
  const centralParts = [];
  let offset = 0;
  for (const { name, data } of entries) {
    if (seen.has(name)) throw new Error(`zip 条目重名: ${name}`);
    seen.add(name);
    if (!Buffer.isBuffer(data)) throw new Error(`zip 条目 ${name} 的 data 必须是 Buffer`);
    const nameBuf = utf8Name(name);
    const crc = crc32(data);
    let method = 8;
    let payload = deflateRawSync(data, { level: 9 });
    if (payload.length >= data.length) {
      method = 0;
      payload = data;
    }
    const local = Buffer.alloc(30);
    local.writeUInt32LE(0x04034b50, 0);
    local.writeUInt16LE(20, 4); // version needed
    local.writeUInt16LE(0x0800, 6); // flags: UTF-8 文件名
    local.writeUInt16LE(method, 8);
    local.writeUInt16LE(FIXED_DOS_TIME, 10);
    local.writeUInt16LE(FIXED_DOS_DATE, 12);
    local.writeUInt32LE(crc, 14);
    local.writeUInt32LE(payload.length, 18);
    local.writeUInt32LE(data.length, 22);
    local.writeUInt16LE(nameBuf.length, 26);
    local.writeUInt16LE(0, 28);
    localParts.push(local, nameBuf, payload);

    const central = Buffer.alloc(46);
    central.writeUInt32LE(0x02014b50, 0);
    central.writeUInt16LE(20, 4); // version made by
    central.writeUInt16LE(20, 6); // version needed
    central.writeUInt16LE(0x0800, 8);
    central.writeUInt16LE(method, 10);
    central.writeUInt16LE(FIXED_DOS_TIME, 12);
    central.writeUInt16LE(FIXED_DOS_DATE, 14);
    central.writeUInt32LE(crc, 16);
    central.writeUInt32LE(payload.length, 20);
    central.writeUInt32LE(data.length, 24);
    central.writeUInt16LE(nameBuf.length, 28);
    central.writeUInt32LE(0, 38); // external attrs
    central.writeUInt32LE(offset, 42); // local header 偏移
    centralParts.push(central, nameBuf);

    offset += 30 + nameBuf.length + payload.length;
  }
  const centralStart = offset;
  const centralBuf = Buffer.concat(centralParts);
  if (centralStart + centralBuf.length > 0xffffffff) throw new Error("zip 总体积超 4GB 边界（不应发生）");
  const eocd = Buffer.alloc(22);
  // EOCD 布局：sig(0-3) 本盘号(4-5) CD起始盘(6-7) 本盘条目数(8-9) 总条目数(10-11)
  //            CD大小(12-15) CD偏移(16-19) 注释长度(20-21)
  eocd.writeUInt32LE(0x06054b50, 0);
  eocd.writeUInt16LE(entries.length, 8);
  eocd.writeUInt16LE(entries.length, 10);
  eocd.writeUInt32LE(centralBuf.length, 12);
  eocd.writeUInt32LE(centralStart, 16);
  return Buffer.concat([...localParts, centralBuf, eocd]);
}

// ---- 只读解析（自验收用） ----

/**
 * readZip(buf) → Map<name, Buffer>（按 central directory 顺序）。
 * 仅支持本模块产出的 zip（method 0/8、无 data descriptor、无 zip64）。
 */
export function readZip(buf) {
  const eocdSig = 0x06054b50;
  let eocd = -1;
  for (let i = buf.length - 22; i >= 0 && i > buf.length - 22 - 0xffff; i--) {
    if (buf.readUInt32LE(i) === eocdSig) {
      eocd = i;
      break;
    }
  }
  if (eocd < 0) throw new Error("不是 zip（找不到 EOCD）");
  const count = buf.readUInt16LE(eocd + 10);
  const centralOffset = buf.readUInt32LE(eocd + 16);
  const out = new Map();
  let p = centralOffset;
  for (let i = 0; i < count; i++) {
    if (buf.readUInt32LE(p) !== 0x02014b50) throw new Error(`central directory 损坏（条目 ${i}）`);
    const method = buf.readUInt16LE(p + 10);
    const csize = buf.readUInt32LE(p + 20);
    const usize = buf.readUInt32LE(p + 24);
    const nameLen = buf.readUInt16LE(p + 28);
    const extraLen = buf.readUInt16LE(p + 30);
    const commentLen = buf.readUInt16LE(p + 32);
    const localOff = buf.readUInt32LE(p + 42);
    const name = buf.toString("utf8", p + 46, p + 46 + nameLen);
    const lh = localOff;
    if (buf.readUInt32LE(lh) !== 0x04034b50) throw new Error(`local header 损坏（${name}）`);
    const lNameLen = buf.readUInt16LE(lh + 26);
    const lExtraLen = buf.readUInt16LE(lh + 28);
    const dataStart = lh + 30 + lNameLen + lExtraLen;
    const raw = buf.subarray(dataStart, dataStart + csize);
    let data;
    if (method === 0) data = Buffer.from(raw);
    else if (method === 8) data = inflateRaw(raw);
    else throw new Error(`不支持的压缩方法 ${method}（${name}）`);
    if (data.length !== usize) throw new Error(`条目 ${name} 解压后长度不符`);
    out.set(name, data);
    p += 46 + nameLen + extraLen + commentLen;
  }
  return out;
}

function inflateRaw(raw) {
  try {
    return inflateRawSync(raw);
  } catch (err) {
    throw new Error(`zip 条目解压失败: ${err.message}`);
  }
}

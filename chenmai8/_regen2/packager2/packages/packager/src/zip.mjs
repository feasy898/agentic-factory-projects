/**
 * 自研 zip（spec packager.md §3.4，冻结）：
 * - 写：deflate level 9（收益不足即回退 store）；固定 DOS 时间戳 2026-01-01（同输入字节可复现）；
 *   UTF-8 文件名 flag 0x0800；重名拒绝；条目名含目录须用 "/"。
 * - 读：readZip 仅供自验收（central directory + inflateRaw；仅支持 method 0/8、
 *   无 data descriptor、无 zip64）。
 * 另导出 crc32（IEEE CRC-32，PNG/zip 通用；gen-pngs.mjs 复用）。
 */
import { deflateRawSync, inflateRawSync } from "node:zlib";

const CRC_TABLE = (() => {
  const t = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? (0xedb88320 ^ (c >>> 1)) >>> 0 : c >>> 1;
    t[n] = c >>> 0;
  }
  return t;
})();

export function crc32(buf) {
  let c = 0xffffffff;
  for (let i = 0; i < buf.length; i++) c = (CRC_TABLE[(c ^ buf[i]) & 0xff] ^ (c >>> 8)) >>> 0;
  return (c ^ 0xffffffff) >>> 0;
}

// 固定 DOS 时间戳 2026-01-01 00:00:00（DOS 时间自 1980 年起）：
// date = ((2026-1980)<<9) | (1<<5) | 1 = 23585；time = 0。
const DOS_TIME = 0;
const DOS_DATE = ((2026 - 1980) << 9) | (1 << 5) | 1;
const UTF8_FLAG = 0x0800;

/** entries: 按最终条目顺序的 [name, Buffer] 数组。返回 zip Buffer。 */
export function writeZip(entries) {
  const seen = new Set();
  const parts = [];
  const centrals = [];
  let offset = 0;
  for (const [name, contentIn] of entries) {
    if (typeof name !== "string" || name.length === 0) {
      throw new Error(`zip: 非法条目名: ${JSON.stringify(name)}`);
    }
    if (name.includes("\\")) throw new Error(`zip: 条目名含目录须用 "/" 分隔: ${name}`);
    if (seen.has(name)) throw new Error(`zip: 重名条目: ${name}`);
    seen.add(name);
    const content = Buffer.isBuffer(contentIn) ? contentIn : Buffer.from(contentIn, "utf8");
    if (content.length > 0xffffffff) throw new Error(`zip: 条目过大（zip64 不支持）: ${name}`);

    const crc = crc32(content);
    let method = 8;
    let data = deflateRawSync(content, { level: 9 });
    if (data.length >= content.length) {
      method = 0;
      data = content;
    }

    const nameBuf = Buffer.from(name, "utf8");
    const lfh = Buffer.alloc(30);
    lfh.writeUInt32LE(0x04034b50, 0); // local file header signature
    lfh.writeUInt16LE(20, 4); // version needed
    lfh.writeUInt16LE(UTF8_FLAG, 6); // flags: UTF-8 文件名
    lfh.writeUInt16LE(method, 8);
    lfh.writeUInt16LE(DOS_TIME, 10);
    lfh.writeUInt16LE(DOS_DATE, 12);
    lfh.writeUInt32LE(crc, 14);
    lfh.writeUInt32LE(data.length, 18);
    lfh.writeUInt32LE(content.length, 22);
    lfh.writeUInt16LE(nameBuf.length, 26);
    lfh.writeUInt16LE(0, 28); // extra len
    parts.push(lfh, nameBuf, data);

    const cdh = Buffer.alloc(46);
    cdh.writeUInt32LE(0x02014b50, 0); // central directory signature
    cdh.writeUInt16LE(20, 4); // version made by
    cdh.writeUInt16LE(20, 6); // version needed
    cdh.writeUInt16LE(UTF8_FLAG, 8);
    cdh.writeUInt16LE(method, 10);
    cdh.writeUInt16LE(DOS_TIME, 12);
    cdh.writeUInt16LE(DOS_DATE, 14);
    cdh.writeUInt32LE(crc, 16);
    cdh.writeUInt32LE(data.length, 20);
    cdh.writeUInt32LE(content.length, 24);
    cdh.writeUInt16LE(nameBuf.length, 28);
    cdh.writeUInt32LE(offset, 42); // local header 偏移
    centrals.push(cdh, nameBuf);

    offset += 30 + nameBuf.length + data.length;
  }

  const cdSize = centrals.reduce((n, b) => n + b.length, 0);
  if (offset > 0xffffffff || cdSize > 0xffffffff || entries.length > 0xffff) {
    throw new Error("zip: 归档过大（zip64 不支持）");
  }
  const eocd = Buffer.alloc(22);
  eocd.writeUInt32LE(0x06054b50, 0);
  eocd.writeUInt16LE(entries.length, 8);
  eocd.writeUInt16LE(entries.length, 10);
  eocd.writeUInt32LE(cdSize, 12);
  eocd.writeUInt32LE(offset, 16);
  return Buffer.concat([...parts, ...centrals, eocd]);
}

/** 读 zip（自验收用）：返回 Map<name, Buffer>（按 central directory 顺序）。 */
export function readZip(buf) {
  if (!Buffer.isBuffer(buf)) throw new Error("zip: readZip 需要 Buffer");
  let eocd = -1;
  const maxComment = 0xffff;
  for (let i = buf.length - 22; i >= Math.max(0, buf.length - 22 - maxComment); i--) {
    if (buf.readUInt32LE(i) === 0x06054b50) {
      eocd = i;
      break;
    }
  }
  if (eocd < 0) throw new Error("zip: 未找到 EOCD（不是 zip 或已截断）");
  const count = buf.readUInt16LE(eocd + 10);
  const cdOffset = buf.readUInt32LE(eocd + 16);
  let p = cdOffset;
  const map = new Map();
  for (let i = 0; i < count; i++) {
    if (p + 46 > buf.length || buf.readUInt32LE(p) !== 0x02014b50) {
      throw new Error("zip: central directory 损坏");
    }
    const flags = buf.readUInt16LE(p + 8);
    const method = buf.readUInt16LE(p + 10);
    const compSize = buf.readUInt32LE(p + 20);
    const nameLen = buf.readUInt16LE(p + 28);
    const extraLen = buf.readUInt16LE(p + 30);
    const commentLen = buf.readUInt16LE(p + 32);
    const lfhOffset = buf.readUInt32LE(p + 42);
    const name = buf.toString("utf8", p + 46, p + 46 + nameLen);
    if (flags & 0x0008) throw new Error(`zip: 不支持 data descriptor（${name}）`);
    if (flags & 0x0040 || flags & 0x0080) throw new Error(`zip: 不支持加密（${name}）`);
    if (method !== 0 && method !== 8) throw new Error(`zip: 仅支持 method 0/8（${name} 是 ${method}）`);

    if (lfhOffset + 30 > buf.length || buf.readUInt32LE(lfhOffset) !== 0x04034b50) {
      throw new Error(`zip: local header 损坏（${name}）`);
    }
    const lNameLen = buf.readUInt16LE(lfhOffset + 26);
    const lExtraLen = buf.readUInt16LE(lfhOffset + 28);
    const dataStart = lfhOffset + 30 + lNameLen + lExtraLen;
    const raw = buf.subarray(dataStart, dataStart + compSize);
    const content = method === 0 ? Buffer.from(raw) : inflateRawSync(raw);
    map.set(name, content);
    p += 46 + nameLen + extraLen + commentLen;
  }
  return map;
}

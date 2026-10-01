/**
 * 极简 ZIP 读写（零第三方依赖，node:zlib deflate）——spec packager.md §3.4（冻结）。
 *
 * 写：deflate level 9（收益不足即回退 store）；固定 DOS 时间戳 2026-01-01
 * （同输入字节可复现——改时间字段会破坏"重复构建字节一致"断言）；UTF-8 文件名
 * flag 0x0800；重名拒绝；条目名含目录须用 "/"。
 * 读：readZip 仅供自验收（central directory + inflateRaw；仅支持 method 0/8、
 * 无 data descriptor、无 zip64）。
 */
import { deflateRawSync, inflateRawSync } from "node:zlib";

// ---- CRC32（亦被 test/fixture/gen-pngs.mjs 复用于 PNG chunk） ----
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

// 固定 DOS 时间（2026-01-01 00:00:00）：((2026-1980)&0x7f)<<9 | 1<<5 | 1。
const FIXED_DOS_TIME = 0;
const FIXED_DOS_DATE = (((2026 - 1980) & 0x7f) << 9) | (1 << 5) | 1;

const LOCAL_SIG = 0x04034b50;
const CENTRAL_SIG = 0x02014b50;
const EOCD_SIG = 0x06054b50;

function nameBuffer(name) {
  const buf = Buffer.from(name, "utf8");
  if (buf.length > 0xffff) throw new Error(`zip 条目名过长: ${name}`);
  return buf;
}

/**
 * createZip(entries: [{ name, data: Buffer }]) → Buffer
 * 条目按传入顺序写入（渠道 zip 的条目序 = 规则 structure 顺序，由调用方保证）。
 */
export function createZip(entries) {
  if (!Array.isArray(entries) || entries.length > 0xffff) throw new Error("zip 条目数超上限 65535");
  const seen = new Set();
  const localParts = [];
  const centralParts = [];
  let offset = 0;
  for (const { name, data } of entries) {
    if (seen.has(name)) throw new Error(`zip 条目重名: ${name}`);
    seen.add(name);
    if (!Buffer.isBuffer(data)) throw new Error(`zip 条目 ${name} 的 data 必须是 Buffer`);
    const nameBuf = nameBuffer(name);
    const crc = crc32(data);
    // deflate level 9；膨胀（收益不足）即回退 store
    let method = 8;
    let payload = deflateRawSync(data, { level: 9 });
    if (payload.length >= data.length) {
      method = 0;
      payload = data;
    }
    const local = Buffer.alloc(30);
    local.writeUInt32LE(LOCAL_SIG, 0);
    local.writeUInt16LE(20, 4); // version needed
    local.writeUInt16LE(0x0800, 6); // flags bit11：UTF-8 文件名
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
    central.writeUInt32LE(CENTRAL_SIG, 0);
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
  // EOCD：sig(0) 盘号(4,6) 本盘条目数(8) 总条目数(10) CD大小(12) CD偏移(16) 注释长(20)
  const eocd = Buffer.alloc(22);
  eocd.writeUInt32LE(EOCD_SIG, 0);
  eocd.writeUInt16LE(entries.length, 8);
  eocd.writeUInt16LE(entries.length, 10);
  eocd.writeUInt32LE(centralBuf.length, 12);
  eocd.writeUInt32LE(centralStart, 16);
  return Buffer.concat([...localParts, centralBuf, eocd]);
}

// ---- 只读解析（自验收用） ----

/**
 * readZip(buf) → Map<name, Buffer>，按键入顺序 = central directory 条目顺序。
 * 仅支持本模块产出的 zip（method 0/8、无 data descriptor、无 zip64）。
 */
export function readZip(buf) {
  let eocd = -1;
  for (let i = buf.length - 22; i >= 0 && i > buf.length - 22 - 0xffff; i--) {
    if (buf.readUInt32LE(i) === EOCD_SIG) {
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
    if (buf.readUInt32LE(p) !== CENTRAL_SIG) throw new Error(`central directory 损坏（条目 ${i}）`);
    const method = buf.readUInt16LE(p + 10);
    const csize = buf.readUInt32LE(p + 20);
    const usize = buf.readUInt32LE(p + 24);
    const nameLen = buf.readUInt16LE(p + 28);
    const extraLen = buf.readUInt16LE(p + 30);
    const commentLen = buf.readUInt16LE(p + 32);
    const localOff = buf.readUInt32LE(p + 42);
    const name = buf.toString("utf8", p + 46, p + 46 + nameLen);
    if (buf.readUInt32LE(localOff) !== LOCAL_SIG) throw new Error(`local header 损坏（${name}）`);
    const lNameLen = buf.readUInt16LE(localOff + 26);
    const lExtraLen = buf.readUInt16LE(localOff + 28);
    const dataStart = localOff + 30 + lNameLen + lExtraLen;
    const raw = buf.subarray(dataStart, dataStart + csize);
    let data;
    if (method === 0) data = Buffer.from(raw);
    else if (method === 8) {
      try {
        data = inflateRawSync(raw);
      } catch (err) {
        throw new Error(`zip 条目解压失败: ${err.message}`);
      }
    } else throw new Error(`不支持的压缩方法 ${method}（${name}）`);
    if (data.length !== usize) throw new Error(`条目 ${name} 解压后长度不符`);
    out.set(name, data);
    p += 46 + nameLen + extraLen + commentLen;
  }
  return out;
}

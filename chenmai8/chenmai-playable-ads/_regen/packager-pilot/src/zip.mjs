/**
 * 自研 zip（M4，spec §3.4 冻结行为）：
 *  - 写：deflate level 9（收益不足回退 store）；固定 DOS 时间戳 2026-01-01（同输入字节可复现）；
 *    UTF-8 文件名 flag 0x0800；重名拒绝；条目名目录分隔符必须 '/'。
 *  - 读：readZip 仅供自验收（central directory + inflateRaw；仅 method 0/8、
 *    无 data descriptor、无 zip64、无加密）。
 * 零第三方运行时依赖。
 */
import { deflateRawSync, inflateRawSync } from "node:zlib";

// 2026-01-01 00:00:00 本地时间 → DOS 时间戳（可复现性断言的前提，勿改）。
export const FIXED_DOS_TIME = 0; // (0h<<11)|(0min<<5)|(0s/2)
export const FIXED_DOS_DATE = ((2026 - 1980) << 9) | (1 << 5) | 1; // 23585

const CRC_TABLE = (() => {
  const t = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    t[n] = c >>> 0;
  }
  return t;
})();

/** 标准 IEEE CRC-32（PNG/zip 共用）。 */
export function crc32(buf) {
  let c = 0xffffffff;
  for (let i = 0; i < buf.length; i++) c = CRC_TABLE[(c ^ buf[i]) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

const SIG_LOCAL = 0x04034b50;
const SIG_CENTRAL = 0x02014b50;
const SIG_EOCD = 0x06054b50;
const FLAG_UTF8 = 0x0800;

/** 校验条目名：非空、不含 '\'、不以 '/' 结尾（不写目录占位条目）。 */
function checkName(name) {
  if (typeof name !== "string" || name.length === 0) throw new Error("zip: 条目名不能为空");
  if (name.includes("\\")) throw new Error(`zip: 条目名目录分隔符须用 '/': ${name}`);
  if (name.endsWith("/")) throw new Error(`zip: 不支持目录占位条目: ${name}`);
  if (name.startsWith("/")) throw new Error(`zip: 条目名不允许根相对: ${name}`);
}

/** 顺序写 zip。entries: 可迭代的 [name, Buffer]。 */
export function writeZip(entries) {
  const list = [...entries];
  const seen = new Set();
  for (const [name] of list) {
    checkName(name);
    if (seen.has(name)) throw new Error(`zip: 重名条目: ${name}`);
    seen.add(name);
  }

  const locals = [];
  const centrals = [];
  let offset = 0;
  for (const [name, data] of list) {
    const nameBuf = Buffer.from(name, "utf8");
    const usize = data.length;
    const crc = crc32(data);
    const deflated = deflateRawSync(data, { level: 9 });
    const useDeflate = deflated.length < usize; // 收益不足回退 store
    const method = useDeflate ? 8 : 0;
    const stored = useDeflate ? deflated : data;

    const local = Buffer.alloc(30 + nameBuf.length);
    local.writeUInt32LE(SIG_LOCAL, 0);
    local.writeUInt16LE(20, 4); // version needed
    local.writeUInt16LE(FLAG_UTF8, 6);
    local.writeUInt16LE(method, 8);
    local.writeUInt16LE(FIXED_DOS_TIME, 10);
    local.writeUInt16LE(FIXED_DOS_DATE, 12);
    local.writeUInt32LE(crc, 14);
    local.writeUInt32LE(stored.length, 18);
    local.writeUInt32LE(usize, 22);
    local.writeUInt16LE(nameBuf.length, 26);
    local.writeUInt16LE(0, 28); // extra len
    nameBuf.copy(local, 30);
    locals.push(local, stored);

    const central = Buffer.alloc(46 + nameBuf.length);
    central.writeUInt32LE(SIG_CENTRAL, 0);
    central.writeUInt16LE(0x0314, 4); // version made by: unix / 2.0
    central.writeUInt16LE(20, 6);
    central.writeUInt16LE(FLAG_UTF8, 8);
    central.writeUInt16LE(method, 10);
    central.writeUInt16LE(FIXED_DOS_TIME, 12);
    central.writeUInt16LE(FIXED_DOS_DATE, 14);
    central.writeUInt32LE(crc, 16);
    central.writeUInt32LE(stored.length, 20);
    central.writeUInt32LE(usize, 24);
    central.writeUInt16LE(nameBuf.length, 28);
    central.writeUInt16LE(0, 30); // extra len
    central.writeUInt16LE(0, 32); // comment len
    central.writeUInt16LE(0, 34); // disk start
    central.writeUInt16LE(0, 36); // internal attrs
    central.writeUInt32LE(0, 38); // external attrs
    central.writeUInt32LE(offset, 42); // local header offset
    nameBuf.copy(central, 46);
    centrals.push(central);

    offset += local.length + stored.length;
  }

  const cdBody = Buffer.concat(centrals);
  const eocd = Buffer.alloc(22);
  eocd.writeUInt32LE(SIG_EOCD, 0);
  eocd.writeUInt16LE(0, 4);
  eocd.writeUInt16LE(0, 6);
  eocd.writeUInt16LE(list.length, 8);
  eocd.writeUInt16LE(list.length, 10);
  eocd.writeUInt32LE(cdBody.length, 12);
  eocd.writeUInt32LE(offset, 16);
  eocd.writeUInt16LE(0, 20); // comment len
  return Buffer.concat([...locals, cdBody, eocd]);
}

/**
 * 读 zip → Map<条目名, Buffer>（保条目顺序）。仅支持 method 0/8、无 data descriptor、
 * 无 zip64、无加密；CRC 不符即抛错。
 */
export function readZip(buf) {
  const eocdOff = findEocd(buf);
  const count = buf.readUInt16LE(eocdOff + 10);
  const cdSize = buf.readUInt32LE(eocdOff + 12);
  const cdOff = buf.readUInt32LE(eocdOff + 16);
  if (cdOff + cdSize > buf.length) throw new Error("zip: central directory 越界");

  const out = new Map();
  let p = cdOff;
  for (let i = 0; i < count; i++) {
    if (p + 46 > buf.length || buf.readUInt32LE(p) !== SIG_CENTRAL) {
      throw new Error(`zip: central directory 损坏（条目 ${i}）`);
    }
    const flags = buf.readUInt16LE(p + 8);
    const method = buf.readUInt16LE(p + 10);
    const crc = buf.readUInt32LE(p + 16);
    const csize = buf.readUInt32LE(p + 20);
    const usize = buf.readUInt32LE(p + 24);
    const nameLen = buf.readUInt16LE(p + 28);
    const extraLen = buf.readUInt16LE(p + 30);
    const commentLen = buf.readUInt16LE(p + 32);
    const localOff = buf.readUInt32LE(p + 42);
    const name = buf.toString("utf8", p + 46, p + 46 + nameLen);
    p += 46 + nameLen + extraLen + commentLen;

    if (flags & 0x0001) throw new Error(`zip: 不支持加密条目: ${name}`);
    if (flags & 0x0008) throw new Error(`zip: 不支持 data descriptor 条目: ${name}`);
    if (method !== 0 && method !== 8) throw new Error(`zip: 不支持的压缩方法 ${method}: ${name}`);
    if (csize === 0xffffffff || usize === 0xffffffff || localOff === 0xffffffff) {
      throw new Error(`zip: 不支持 zip64 条目: ${name}`);
    }

    if (localOff + 30 > buf.length || buf.readUInt32LE(localOff) !== SIG_LOCAL) {
      throw new Error(`zip: local header 损坏: ${name}`);
    }
    const lNameLen = buf.readUInt16LE(localOff + 26);
    const lExtraLen = buf.readUInt16LE(localOff + 28);
    const dataStart = localOff + 30 + lNameLen + lExtraLen;
    if (dataStart + csize > buf.length) throw new Error(`zip: 条目数据越界: ${name}`);
    const raw = buf.subarray(dataStart, dataStart + csize);
    const content = method === 8 ? inflateRawSync(raw) : Buffer.from(raw);
    if (content.length !== usize) throw new Error(`zip: 解压长度不符: ${name}`);
    if (crc32(content) !== crc) throw new Error(`zip: CRC 校验失败: ${name}`);
    out.set(name, content);
  }
  return out;
}

function findEocd(buf) {
  const min = Math.max(0, buf.length - 22 - 0xffff);
  for (let i = buf.length - 22; i >= min; i--) {
    if (buf.readUInt32LE(i) !== SIG_EOCD) continue;
    const commentLen = buf.readUInt16LE(i + 20);
    if (i + 22 + commentLen === buf.length) return i;
  }
  throw new Error("zip: 未找到 EOCD（不是 zip 或带注释结尾）");
}

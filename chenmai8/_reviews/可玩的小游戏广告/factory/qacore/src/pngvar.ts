/**
 * 截图灰度方差（CHK05 输入，qacore spec §3 魔法数字表）：
 * 截图 → 灰度（Pillow convert("L") 同式：L24 整数式 (19595R+38470G+7471B+0x8000)>>16）
 * → 降采样 64×64（Pillow resize 默认 BICUBIC：A=-0.5 核、系数按和归一、
 * 缩小时支撑窗按 1/scale 展宽做抗锯齿）→ 像素方差。方差 < 30.0 判空白。
 *
 * R1（决策 §4）已知：跨实现数值仍有微漂（浮点路径不完全同），契约层只锁
 * "空白/非空白状态全等"（D5），数值容差由资产包回填声明；本实现按 Pillow
 * 语义对齐后语料对照相对差 ≤2%（2026-09-30 语料实测，见 REUSED-ASSETS/台账）。
 * 本模块零第三方依赖：PNG 解码用 node:zlib（Chromium 截图为 8-bit 非隔行 PNG，
 * 支持灰度/RGB/调色板/灰度+A/RGB+A 各 color type）。
 */
import { inflateSync } from "node:zlib";

const CRC_TABLE: number[] = (() => {
  const table: number[] = [];
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    table[n] = c >>> 0;
  }
  return table;
})();

function crc32(buf: Uint8Array): number {
  let c = 0xffffffff;
  for (let i = 0; i < buf.length; i++) c = CRC_TABLE[(c ^ buf[i]!) & 0xff]! ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

interface PngImage {
  width: number;
  height: number;
  /** IHDR color type（0=灰度 2=RGB 3=调色板 4=灰度+A 6=RGB+A）。 */
  colorType: number;
  /** 每像素 8-bit 展开后的通道值（0-255）。 */
  channels: number;
  data: Uint8Array;
  palette: Array<[number, number, number]> | null;
}

const CHANNELS_BY_COLOR: Record<number, number> = { 0: 1, 2: 3, 3: 1, 4: 2, 6: 4 };

function paeth(a: number, b: number, c: number): number {
  const p = a + b - c;
  const pa = Math.abs(p - a), pb = Math.abs(p - b), pc = Math.abs(p - c);
  if (pa <= pb && pa <= pc) return a;
  return pb <= pc ? b : c;
}

export function decodePng(buf: Uint8Array): PngImage {
  const sig = [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a];
  if (buf.length < 8 || sig.some((b, i) => buf[i] !== b)) {
    throw new Error("pngvar: 非 PNG 数据（签名不符）");
  }
  let pos = 8;
  let width = 0, height = 0, bitDepth = 0, colorType = 0, interlace = 0;
  const idat: Buffer[] = [];
  let palette: Array<[number, number, number]> | null = null;
  while (pos + 8 <= buf.length) {
    const dv = new DataView(buf.buffer, buf.byteOffset + pos, 8);
    const len = dv.getUint32(0);
    const type = Buffer.from(buf.subarray(pos + 4, pos + 8)).toString("latin1");
    const dataStart = pos + 8;
    const dataEnd = dataStart + len;
    if (dataEnd + 4 > buf.length) throw new Error("pngvar: chunk 越界");
    // PNG 的 CRC 覆盖 chunk type + chunk data（不含长度域）。
    const crcOver = buf.subarray(pos + 4, dataEnd);
    const crcGot = new DataView(buf.buffer, buf.byteOffset + dataEnd, 4).getUint32(0);
    if (crc32(crcOver) !== crcGot) throw new Error(`pngvar: ${type} chunk CRC 不符`);
    if (type === "IHDR") {
      const ih = new DataView(buf.buffer, buf.byteOffset + dataStart, len);
      width = ih.getUint32(0);
      height = ih.getUint32(4);
      bitDepth = ih.getUint8(8);
      colorType = ih.getUint8(9);
      interlace = ih.getUint8(12);
    } else if (type === "PLTE") {
      palette = [];
      const data = buf.subarray(dataStart, dataEnd);
      for (let i = 0; i + 2 < data.length; i += 3) {
        palette.push([data[i]!, data[i + 1]!, data[i + 2]!]);
      }
    } else if (type === "IDAT") {
      idat.push(Buffer.from(buf.subarray(dataStart, dataEnd)));
    } else if (type === "IEND") {
      break;
    }
    pos = dataEnd + 4;
  }
  if (width <= 0 || height <= 0) throw new Error("pngvar: IHDR 缺失或非法");
  if (bitDepth !== 8) throw new Error(`pngvar: 不支持的位深 ${bitDepth}（仅 8-bit）`);
  if (interlace !== 0) throw new Error("pngvar: 不支持隔行 PNG");
  const channels = CHANNELS_BY_COLOR[colorType];
  if (channels === undefined) throw new Error(`pngvar: 不支持的 color type ${colorType}`);

  const raw = inflateSync(Buffer.concat(idat));
  const stride = width * channels;
  const out = new Uint8Array(stride * height);
  const bpp = channels;
  let rp = 0;
  for (let y = 0; y < height; y++) {
    const filter = raw[rp++]!;
    const row = y * stride;
    for (let x = 0; x < stride; x++) {
      const cur = raw[rp++]!;
      const left = x >= bpp ? out[row + x - bpp]! : 0;
      const up = y > 0 ? out[row - stride + x]! : 0;
      const ul = y > 0 && x >= bpp ? out[row - stride + x - bpp]! : 0;
      let v: number;
      switch (filter) {
        case 0: v = cur; break;
        case 1: v = cur + left; break;
        case 2: v = cur + up; break;
        case 3: v = cur + ((left + up) >> 1); break;
        case 4: v = cur + paeth(left, up, ul); break;
        default: throw new Error(`pngvar: 未知行滤波 ${filter}`);
      }
      out[row + x] = v & 0xff;
    }
  }
  return { width, height, colorType, channels, data: out, palette };
}

/**
 * Pillow convert("L") 同式：L24 整数式 (19595R + 38470G + 7471B + 0x8000) >> 16
 * （ITU-R 601-2 亮度、四舍五入；0x8000 = 半位进位）。
 */
function toGray(img: PngImage): Float64Array {
  const n = img.width * img.height;
  const gray = new Float64Array(n);
  const d = img.data, ch = img.channels;
  if (img.colorType === 0) {
    for (let i = 0; i < n; i++) gray[i] = d[i * ch]!;
    return gray;
  }
  for (let i = 0; i < n; i++) {
    let r: number, g: number, b: number;
    if (img.palette) {
      const idx = d[i]!;
      const p = img.palette[idx] ?? [0, 0, 0];
      [r, g, b] = p;
    } else {
      r = d[i * ch]!;
      g = d[i * ch + 1]!;
      b = d[i * ch + 2]!;
    }
    gray[i] = (19595 * r + 38470 * g + 7471 * b + 0x8000) >> 16;
  }
  return gray;
}

// Pillow BICUBIC 核（A = -0.5，Resample.c cubic_interp）。
const CUBIC_A = -0.5;
function cubic(x: number): number {
  if (x < 0) x = -x;
  if (x < 1.0) return ((CUBIC_A + 2.0) * x - (CUBIC_A + 3.0)) * x * x + 1.0;
  if (x < 2.0) return (CUBIC_A * (x - 5.0) * x + 8.0 * CUBIC_A) * x - 4.0 * CUBIC_A;
  return 0.0;
}

interface Coeffs { kk: Float64Array; xmin: number; xw: number }

function precomputeCoeffs(inSize: number, outSize: number): Coeffs[] {
  // Pillow Resample.c：scale = out/in；缩小时（scale<1）支撑窗按 1/scale 展宽、
  // 核参数乘 scale（抗锯齿）；放大时支撑窗固定 2.0。
  const scale = outSize / inSize;
  const support = scale < 1.0 ? 2.0 / scale : 2.0;
  const coeffs: Coeffs[] = [];
  for (let i = 0; i < outSize; i++) {
    const center = (i + 0.5) * inSize / outSize - 0.5;
    let xmin = Math.ceil(center - support);
    let xmax = Math.floor(center + support);
    if (xmin < 0) xmin = 0;
    if (xmax >= inSize) xmax = inSize - 1;
    const xw = xmax - xmin + 1;
    const kk = new Float64Array(xw);
    let sum = 0;
    for (let j = 0; j < xw; j++) {
      const x = center - (xmin + j);
      const w = scale < 1.0 ? cubic(x * scale) : cubic(x);
      kk[j] = w;
      sum += w;
    }
    // Pillow precompute_coeffs：系数按和归一（保持亮度）。
    for (let j = 0; j < xw; j++) kk[j] = kk[j]! / sum;
    coeffs.push({ kk, xmin, xw });
  }
  return coeffs;
}

/** 单通道双三次缩放（先横向后纵向，float 中间量，末端 clip8(0.5+v) 取整）。 */
function resizeBicubic(src: Float64Array, w: number, h: number, ow: number, oh: number): Float64Array {
  const tmp = new Float64Array(ow * h);
  const ch = precomputeCoeffs(w, ow);
  for (let y = 0; y < h; y++) {
    for (let ox = 0; ox < ow; ox++) {
      const { kk, xmin, xw } = ch[ox]!;
      let acc = 0;
      for (let j = 0; j < xw; j++) acc += src[y * w + xmin + j]! * kk[j]!;
      tmp[y * ow + ox] = acc;
    }
  }
  const out = new Float64Array(ow * oh);
  const cv = precomputeCoeffs(h, oh);
  for (let oy = 0; oy < oh; oy++) {
    const { kk, xmin, xw } = cv[oy]!;
    for (let ox = 0; ox < ow; ox++) {
      let acc = 0;
      for (let j = 0; j < xw; j++) acc += tmp[(xmin + j) * ow + ox]! * kk[j]!;
      // clip8(0.5 + v)：Pillow 的 UINT8 收尾取整。
      let v = acc + 0.5;
      v = v < 0 ? 0 : v > 255 ? 255 : v;
      out[oy * ow + ox] = Math.floor(v);
    }
  }
  return out;
}

/**
 * 截图灰度方差：convert("L") → resize((64,64)) → 像素方差（总体方差，除 N）。
 */
export function grayscaleVariance(png: Uint8Array): number {
  const img = decodePng(png);
  const gray = toGray(img);
  const small = resizeBicubic(gray, img.width, img.height, 64, 64);
  let mean = 0;
  for (let i = 0; i < small.length; i++) mean += small[i]!;
  mean /= small.length;
  let variance = 0;
  for (let i = 0; i < small.length; i++) {
    const d = small[i]! - mean;
    variance += d * d;
  }
  return variance / small.length;
}

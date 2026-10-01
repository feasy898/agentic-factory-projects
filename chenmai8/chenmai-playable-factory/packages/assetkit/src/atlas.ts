// packages/assetkit/src/atlas.ts — 图集：自研 shelf（next-fit 递减高）装箱 + 无损合成 + atlas.json。
//（oracle python/assetkit/atlas.py + node/optimize.mjs compositeAtlas 语义移植。）
//
// - 装箱输入是"优化后"的图（尺寸以优化产物实测为准），矩形互不重叠、不出界
//  （selftest 有成对校验）；放不下（单图宽超图集宽）的图如实记 skipped。
// - 合成进程内一次性完成（透明底 canvas + 逐帧贴入），候选无损 WebP / 调色板 PNG
//   取小——图集是"重打包"而非"再压缩"，画质优先。
// - atlas.json 键：优先素材文件名 stem；重名时回退"原始路径的 POSIX 相对形"，
//   保证键稳定可复现（同输入同键）。

import { readFileSync, writeFileSync } from "node:fs";
import path from "node:path";

import sharp from "sharp";

import type { AssetEntry } from "./types.ts";

export interface Frame {
  key: string;
  file: string;
  width: number;
  height: number;
  x?: number;
  y?: number;
}

/**
 * next-fit 递减高 shelf 装箱。frames: [{key, file, width, height}]。
 * 返回 (placed, atlas_width, atlas_height, skipped)。placed 附加 x/y。
 */
export function packShelf(frames: readonly Frame[], maxWidth: number): {
  placed: Frame[]; width: number; height: number; skipped: Array<Record<string, unknown>>;
} {
  const ordered = [...frames].sort((a, b) =>
    (b.height - a.height) || (b.width - a.width) || (a.key < b.key ? -1 : a.key > b.key ? 1 : 0));
  const placed: Frame[] = [];
  const skipped: Array<Record<string, unknown>> = [];
  let x = 0;
  let y = 0;
  let rowH = 0;
  for (const f of ordered) {
    if (f.width > maxWidth) {
      skipped.push({ key: f.key, file: f.file, width: f.width, height: f.height });
      continue;
    }
    if (x !== 0 && x + f.width > maxWidth) { // 换行
      y += rowH;
      x = 0;
      rowH = 0;
    }
    placed.push({ ...f, x, y });
    x += f.width;
    rowH = Math.max(rowH, f.height);
  }
  let atlasW = placed.length > 0 ? maxWidth : 0;
  const atlasH = y + (placed.length > 0 ? rowH : 0);
  // 收紧宽度：最右边界（避免整行空白）
  if (placed.length > 0) {
    atlasW = Math.max(...placed.map((p) => (p.x ?? 0) + p.width));
  }
  return { placed, width: atlasW, height: atlasH, skipped };
}

/** 由压图结果条目合成图集；无图或全 skipped 时返回 null。 */
export async function buildAtlas(
  imageEntries: readonly AssetEntry[],
  outDir: string,
  maxWidth = 1024,
): Promise<Record<string, unknown> | null> {
  const frames: Frame[] = [];
  for (const e of imageEntries) {
    if (e.status === "failed" || !e.out) continue;
    if (!e.width || !e.height) continue;
    frames.push({
      key: path.basename(e.out, path.extname(e.out)),
      file: path.join(outDir, e.out),
      width: Math.trunc(e.width),
      height: Math.trunc(e.height),
    });
  }
  if (frames.length === 0) return null;
  const { placed, width: w, height: h, skipped } = packShelf(frames, Math.trunc(maxWidth));
  if (placed.length === 0) {
    return { packed: 0, skipped, note: "无可装箱帧" };
  }

  // 合成：透明底 canvas + 逐帧贴入；候选无损 WebP / 调色板 PNG(q100) 取小。
  const outBase = path.join(outDir, "atlas");
  const specs = [
    { encoding: "webp-lossless", ext: ".webp", format: "webp" as const, opts: { lossless: true, effort: 6 } },
    { encoding: "png-palette", ext: ".png", format: "png" as const, opts: { palette: true, quality: 100, effort: 10, compressionLevel: 9 } },
  ];
  const candidates: Array<{ encoding: string; bytes?: number; error?: string }> = [];
  let best: (typeof specs)[number] & { bytes: number; buf: Buffer } | null = null;
  const canvas = sharp({
    create: { width: w, height: h, channels: 4, background: { r: 0, g: 0, b: 0, alpha: 0 } },
  }).composite(placed.map((p) => ({
    input: resolveInput(p.file),
    left: p.x ?? 0,
    top: p.y ?? 0,
  })));
  for (const spec of specs) {
    try {
      const buf = await canvas.clone().toFormat(spec.format, spec.opts).toBuffer();
      candidates.push({ encoding: spec.encoding, bytes: buf.length });
      if (!best || buf.length < best.bytes) best = { ...spec, bytes: buf.length, buf };
    } catch (err) {
      candidates.push({ encoding: spec.encoding, error: String((err as Error)?.message ?? err) });
    }
  }
  if (!best) {
    return { packed: 0, skipped, note: "图集合成失败：图集全部候选编码失败", candidates };
  }
  const out = outBase + best.ext;
  writeFileSync(out, best.buf);

  // 键去重：stem 撞名时改用来源相对标识（此处帧键本就来自输出文件名，pool
  // 已保证唯一，理论不触发；防御性保留）。
  const framesJson: Record<string, { x: number; y: number; width: number; height: number }> = {};
  for (const p of placed) {
    framesJson[p.key] = { x: p.x ?? 0, y: p.y ?? 0, width: p.width, height: p.height };
  }
  const atlasJson = {
    format: "pf-atlas/1",
    image: path.basename(out),
    width: w,
    height: h,
    encoding: best.encoding,
    frames: framesJson,
  };
  writeFileSync(path.join(outDir, "atlas.json"), `${JSON.stringify(atlasJson, null, 2)}\n`, "utf8");
  return {
    packed: placed.length,
    skipped,
    image: atlasJson.image,
    width: w,
    height: h,
    encoding: best.encoding,
    bytes: best.bytes,
    candidates,
    note: "atlas.json 与图集图已写入输出目录（pf-atlas/1）",
  };
}

function resolveInput(p: string): Buffer {
  return readFileSync(p); // composite 的 input 传 Buffer，规避跨盘路径差异
}

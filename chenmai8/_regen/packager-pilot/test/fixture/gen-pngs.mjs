#!/usr/bin/env node
/**
 * 生成占位工程 fixture 的纯色 PNG（零依赖：node:zlib + 自研 crc32）。
 * 一次性工具；产物 img/*.png 已入库，仅在需要改动时重跑：
 *   node packages/packager/test/fixture/gen-pngs.mjs
 */
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { deflateSync } from "node:zlib";

import { crc32 } from "../../src/zip.mjs";
const OUT = path.join(path.dirname(fileURLToPath(import.meta.url)), "match3-dist");

function chunk(type, data) {
  const len = Buffer.alloc(4);
  len.writeUInt32BE(data.length, 0);
  const body = Buffer.concat([Buffer.from(type, "ascii"), data]);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(body), 0);
  return Buffer.concat([len, body, crc]);
}

/** 生成 width×height 纯色 RGB PNG（8bit/通道，无滤波）。 */
function makePng(width, height, [r, g, b]) {
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(width, 0);
  ihdr.writeUInt32BE(height, 4);
  ihdr[8] = 8; // bit depth
  ihdr[9] = 2; // color type: truecolor RGB
  const row = Buffer.alloc(1 + width * 3);
  for (let x = 0; x < width; x++) {
    row[1 + x * 3] = r;
    row[1 + x * 3 + 1] = g;
    row[1 + x * 3 + 2] = b;
  }
  const raw = Buffer.concat(Array.from({ length: height }, () => row));
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk("IHDR", ihdr),
    chunk("IDAT", deflateSync(raw, { level: 9 })),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}

const COLORS = {
  "bg.png": [30, 34, 62],
  "piece-0.png": [231, 76, 60],
  "piece-1.png": [46, 204, 113],
  "piece-2.png": [52, 152, 219],
};

mkdirSync(path.join(OUT, "img"), { recursive: true });
for (const [name, rgb] of Object.entries(COLORS)) {
  const file = path.join(OUT, "img", name);
  writeFileSync(file, makePng(name === "bg.png" ? 32 : 16, name === "bg.png" ? 32 : 16, rgb));
  console.log(`wrote ${file}`);
}

#!/usr/bin/env node
// assetkit Node 助手：压图多编码竞标 + 图集合成（M5）。
//
// 由 python/assetkit 由同一份 JSON 任务驱动（stdin 进、stdout 末行 JSON 出），
// 图像处理统一走本仓 devDependency 的 sharp（仓库根 node_modules 解析）。
// 设计约束：
// - 逐 job 独立 try/catch：单素材失败不拖垮整批，失败原因如实回传；
// - 候选编码竞标取最小，绝不写出比原始更大的文件（"宁保留不增大"由
//   python 侧执行——本助手只报各候选字节数与所选编码）；
// - stdout 只在末尾打印一行 JSON（进度/告警走 stderr），python 侧按末行解析。

import { readFileSync, statSync, writeFileSync } from "node:fs";
import path from "node:path";
import sharp from "sharp";

const PNG_PLAIN_MAX_SRC_BYTES = 3_000_000; // 超大图（照片类）跳过 PNG 候选，省时且必有 WebP 更小

function candidateSpecs(originalBytes, quality) {
  const specs = [
    { encoding: "webp-lossy", ext: ".webp", opts: { quality, effort: 6 } },
    { encoding: "webp-nearlossless", ext: ".webp", opts: { nearLossless: true, quality: 100, effort: 6 } },
    { encoding: "png-palette", ext: ".png", opts: { palette: true, quality: 90, effort: 10, compressionLevel: 9 } },
  ];
  if (originalBytes <= PNG_PLAIN_MAX_SRC_BYTES) {
    specs.push({ encoding: "png-plain", ext: ".png", opts: { compressionLevel: 9 } });
  }
  return specs;
}

/** 单图压图竞标：返回结果对象（不抛——失败记 ok:false）。 */
async function optimizeOne(job, globalOpts) {
  const src = path.resolve(job.src);
  const outBase = path.resolve(job.outBase);
  const originalBytes = statSync(src).size;
  const meta = await sharp(src).metadata();
  const notes = [];
  if ((meta.pages || 1) > 1) {
    notes.push(`动图按静态首帧处理（pages=${meta.pages}）`);
  }
  let pipeline = sharp(src);
  const maxEdge = Number(globalOpts.maxEdge) || 0;
  if (maxEdge > 0 && Math.max(meta.width, meta.height) > maxEdge) {
    pipeline = pipeline.resize({ width: maxEdge, height: maxEdge, fit: "inside", withoutEnlargement: true });
    notes.push(`已按 --max-edge=${maxEdge} 等比缩放`);
  }
  const candidates = [];
  let best = null;
  for (const spec of candidateSpecs(originalBytes, globalOpts.quality)) {
    try {
      const buf = await pipeline.clone()
        .toFormat(spec.ext === ".png" ? "png" : "webp", spec.opts)
        .toBuffer();
      candidates.push({ encoding: spec.encoding, bytes: buf.length });
      if (!best || buf.length < best.bytes) best = { ...spec, bytes: buf.length, buf };
    } catch (err) {
      candidates.push({ encoding: spec.encoding, error: String((err && err.message) || err) });
    }
  }
  if (!best) {
    return { id: job.id, ok: false, reason: "全部候选编码失败", originalBytes, candidates };
  }
  const out = outBase + best.ext;
  writeFileSync(out, best.buf);
  const finalMeta = await sharp(best.buf).metadata();
  return {
    id: job.id,
    ok: true,
    originalBytes,
    width: finalMeta.width,
    height: finalMeta.height,
    alpha: Boolean(finalMeta.hasAlpha),
    notes,
    candidates,
    chosen: { encoding: best.encoding, ext: best.ext, bytes: best.bytes, out },
  };
}

/** shelf 装箱结果合成单张图集：候选无损 WebP / 调色板 PNG 取小。 */
async function compositeAtlas(atlas) {
  const outBase = path.resolve(atlas.outBase);
  const canvas = sharp({
    create: {
      width: atlas.width,
      height: atlas.height,
      channels: 4,
      background: { r: 0, g: 0, b: 0, alpha: 0 },
    },
  }).composite(atlas.parts.map((p) => ({ input: path.resolve(p.src), left: p.x, top: p.y })));
  const candidates = [];
  let best = null;
  const specs = [
    { encoding: "webp-lossless", ext: ".webp", format: "webp", opts: { lossless: true, effort: 6 } },
    { encoding: "png-palette", ext: ".png", format: "png", opts: { palette: true, quality: 100, effort: 10, compressionLevel: 9 } },
  ];
  for (const spec of specs) {
    try {
      const buf = await canvas.clone().toFormat(spec.format, spec.opts).toBuffer();
      candidates.push({ encoding: spec.encoding, bytes: buf.length });
      if (!best || buf.length < best.bytes) best = { ...spec, bytes: buf.length, buf };
    } catch (err) {
      candidates.push({ encoding: spec.encoding, error: String((err && err.message) || err) });
    }
  }
  if (!best) return { ok: false, reason: "图集全部候选编码失败", candidates };
  const out = outBase + best.ext;
  writeFileSync(out, best.buf);
  return {
    ok: true,
    candidates,
    chosen: { encoding: best.encoding, ext: best.ext, bytes: best.bytes, out },
    width: atlas.width,
    height: atlas.height,
  };
}

async function main() {
  const payload = JSON.parse(readFileSync(0, "utf8"));
  const results = [];
  for (const job of payload.jobs || []) {
    try {
      results.push(await optimizeOne(job, payload));
    } catch (err) {
      results.push({ id: job.id, ok: false, reason: String((err && err.message) || err) });
    }
  }
  let atlasResult = null;
  if (payload.atlas) {
    try {
      atlasResult = await compositeAtlas(payload.atlas);
    } catch (err) {
      atlasResult = { ok: false, reason: String((err && err.message) || err) };
    }
  }
  process.stdout.write(JSON.stringify({ results, atlas: atlasResult }) + "\n");
}

main().catch((err) => {
  process.stderr.write(`[assetkit-node] 致命错误: ${(err && err.stack) || err}\n`);
  process.exit(1);
});

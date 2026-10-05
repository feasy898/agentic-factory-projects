// packages/assetkit/src/images.ts — 压图：sharp 多编码竞标（oracle images.py + node/optimize.mjs
// 语义移植；宿主适配：oracle 的 python→node 子进程助手改为进程内 await，其余逐条对齐）。
//
// "竞标取最小、永不增大"：全部候选都打不过原始字节时保留原图（复制进输出目录，
// 报告里 encoding="original"，如实不算优化成果）。输出平面文件名，重名自动加序号。
//
// 候选集（optimize.mjs candidateSpecs 同表）：
//   webp-lossy(quality) / webp-nearlossless / png-palette(q90) /
//   png-plain（仅原始 ≤ 3MB 时参标——超大图跳过省时且必有 WebP 更小）

import { copyFileSync, statSync, writeFileSync } from "node:fs";
import path from "node:path";

import sharp from "sharp";

import type { AssetEntry, Material } from "./types.ts";

const PNG_PLAIN_MAX_SRC_BYTES = 3_000_000; // 超大图（照片类）跳过 PNG 候选，省时且必有 WebP 更小

interface CandidateSpec {
  encoding: string;
  ext: string;
  format: "png" | "webp";
  opts: Record<string, unknown>;
}

function candidateSpecs(originalBytes: number, quality: number): CandidateSpec[] {
  const specs: CandidateSpec[] = [
    { encoding: "webp-lossy", ext: ".webp", format: "webp", opts: { quality, effort: 6 } },
    { encoding: "webp-nearlossless", ext: ".webp", format: "webp", opts: { nearLossless: true, quality: 100, effort: 6 } },
    { encoding: "png-palette", ext: ".png", format: "png", opts: { palette: true, quality: 90, effort: 10, compressionLevel: 9 } },
  ];
  if (originalBytes <= PNG_PLAIN_MAX_SRC_BYTES) {
    specs.push({ encoding: "png-plain", ext: ".png", format: "png", opts: { compressionLevel: 9 } });
  }
  return specs;
}

/** 输出平面命名池：stem 冲突时追加 -2/-3…（同 stem 不同扩展也算冲突，
 *  避免不同目录同名素材在 optmap 指向上产生歧义）。大小写不敏感。 */
export class NamePool {
  private used = new Set<string>();
  private outDir: string;
  constructor(outDir: string) {
    this.outDir = outDir;
  }
  base(stem: string): string {
    let cand = stem;
    let i = 2;
    while (this.used.has(cand.toLowerCase())) {
      cand = `${stem}-${i}`;
      i += 1;
    }
    this.used.add(cand.toLowerCase());
    return path.join(this.outDir, cand);
  }
}

/** 单图压图竞标：返回结果对象（不抛——失败记 ok:false，逐 job 独立不拖垮整批）。 */
async function optimizeOne(
  src: string,
  outBase: string,
  quality: number,
  maxEdge: number,
): Promise<{
  ok: boolean; reason?: string; originalBytes: number;
  width?: number | null; height?: number | null; alpha?: boolean;
  notes: string[]; candidates: Array<{ encoding: string; bytes?: number; error?: string }>;
  chosen?: { encoding: string; ext: string; bytes: number; out: string };
}> {
  const originalBytes = statSync(src).size;
  const meta = await sharp(src).metadata();
  const notes: string[] = [];
  if ((meta.pages ?? 1) > 1) {
    notes.push(`动图按静态首帧处理（pages=${meta.pages}）`);
  }
  let pipe = sharp(src);
  if (maxEdge > 0 && Math.max(meta.width ?? 0, meta.height ?? 0) > maxEdge) {
    pipe = pipe.resize({ width: maxEdge, height: maxEdge, fit: "inside", withoutEnlargement: true });
    notes.push(`已按 --max-edge=${maxEdge} 等比缩放`);
  }
  const candidates: Array<{ encoding: string; bytes?: number; error?: string }> = [];
  let best: (CandidateSpec & { bytes: number; buf: Buffer }) | null = null;
  for (const spec of candidateSpecs(originalBytes, quality)) {
    try {
      const buf = await pipe.clone().toFormat(spec.format, spec.opts).toBuffer();
      candidates.push({ encoding: spec.encoding, bytes: buf.length });
      if (!best || buf.length < best.bytes) best = { ...spec, bytes: buf.length, buf };
    } catch (err) {
      candidates.push({ encoding: spec.encoding, error: String((err as Error)?.message ?? err) });
    }
  }
  if (!best) {
    return { ok: false, reason: "全部候选编码失败", originalBytes, notes, candidates };
  }
  const out = outBase + best.ext;
  writeFileSync(out, best.buf);
  const finalMeta = await sharp(best.buf).metadata();
  return {
    ok: true,
    originalBytes,
    width: finalMeta.width ?? null,
    height: finalMeta.height ?? null,
    alpha: Boolean(finalMeta.hasAlpha),
    notes,
    candidates,
    chosen: { encoding: best.encoding, ext: best.ext, bytes: best.bytes, out },
  };
}

/** 压图全部 image 素材，返回逐素材结果条目（含原始/优化字节数）。 */
export async function optimizeImages(
  materials: readonly Material[],
  outDir: string,
  { quality = 75, maxEdge = 0 }: { quality?: number; maxEdge?: number } = {},
): Promise<AssetEntry[]> {
  const images = materials.filter((m) => m.kind === "image");
  if (images.length === 0) return [];
  const pool = new NamePool(outDir);

  const entries: AssetEntry[] = [];
  for (const m of images) {
    const base = pool.base(path.basename(m.src, path.extname(m.src)));
    let r: Awaited<ReturnType<typeof optimizeOne>>;
    try {
      r = await optimizeOne(m.src, base, Math.trunc(quality), Math.trunc(maxEdge));
    } catch (err) {
      entries.push({ key: m.key, src: m.src, kind: "image", status: "failed",
        note: String((err as Error)?.message ?? err) });
      continue;
    }
    if (!r.ok) {
      entries.push({ key: m.key, src: m.src, kind: "image", status: "failed",
        note: r.reason ?? "未知失败" });
      continue;
    }
    const chosen = r.chosen!;
    if (chosen.bytes >= r.originalBytes) {
      // 竞标全输：保留原图（复制进输出目录，保持自包含），如实记录。
      const outFile = base + extOf(m.src).toLowerCase();
      copyFileSync(m.src, outFile);
      entries.push({
        key: m.key, src: m.src, kind: "image",
        status: "kept-original",
        out: path.basename(outFile), encoding: "original",
        originalBytes: r.originalBytes, optimizedBytes: r.originalBytes,
        reductionPct: 0.0,
        width: r.width, height: r.height,
        candidates: r.candidates,
        note: "全部候选编码不小于原始字节，保留原图" + (r.notes.length ? `；${r.notes.join("；")}` : ""),
      });
      continue;
    }
    entries.push({
      key: m.key, src: m.src, kind: "image",
      status: "optimized",
      out: path.basename(chosen.out), encoding: chosen.encoding,
      originalBytes: r.originalBytes, optimizedBytes: chosen.bytes,
      reductionPct: round1((1 - chosen.bytes / r.originalBytes) * 100),
      width: r.width, height: r.height,
      alpha: r.alpha,
      candidates: r.candidates,
      note: r.notes.join("；"),
    });
  }
  return entries;
}

function extOf(p: string): string {
  const base = p.slice(Math.max(p.lastIndexOf("/") + 1, p.lastIndexOf("\\") + 1));
  const j = base.lastIndexOf(".");
  return j <= 0 ? "" : base.slice(j);
}

/** python round(x, 1) 近似（HALF-UP；报告数值非冻结契约，位级不锁）。 */
function round1(x: number): number {
  return Math.round(x * 10) / 10;
}

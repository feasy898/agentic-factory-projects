// packages/assetkit/src/pipeline.ts — 编排：收集 → 压图 → 音频 → 字体 → 图集 → optmap + report。
//（oracle python/assetkit/pipeline.py run_assetkit 语义移植；pf make 的接线入口。）
//
// 输出目录整体重建（先清空）——素材管线是纯函数式的：同输入同输出，残留产物
// 只会造成"哪次生成的"的歧义。汇总降幅只统计"素材本身"（图/音/字），图集是
// 附加产物单列（它不是替换关系，计入会虚增降幅）。

import { mkdirSync, readFileSync, rmSync, statSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { ASSETKIT_VERSION, OPTMAP_NAME, REPORT_NAME, AssetkitError } from "./index.ts";
import { buildAtlas } from "./atlas.ts";
import { transcodeAudio } from "./audio.ts";
import { collect } from "./collect.ts";
import { specSubsetText, subsetFonts } from "./fonts.ts";
import { optimizeImages } from "./images.ts";
import type { AssetEntry } from "./types.ts";

export const EXTRA_SUBSET_TEXT_DEFAULT = ""; // 数字已内建于字符集（得分必然要渲染）

export interface RunAssetkitOptions {
  inputs?: readonly string[];
  out: string;
  spec?: string | null;
  imageQuality?: number;
  audioBitrate?: number;
  maxEdge?: number;
  atlas?: boolean;
  atlasMaxWidth?: number;
  extraText?: string;
  minReductionPct?: number | null;
  /** 进程内直跑，log 仅留默认实现（oracle _log_print 同形）。 */
  log?: (msg: string) => void;
}

interface Totals {
  count: number;
  originalBytes: number;
  optimizedBytes: number;
  reductionPct: number;
  minReductionPct: number | null;
  minReductionMet: boolean | null;
}

export interface AssetkitReport {
  assetkitVersion: string;
  generatedAt: string;
  spec: string | null;
  outDir: string;
  subsetTextChars: number;
  materials: { image: AssetEntry[]; audio: AssetEntry[]; font: AssetEntry[] };
  totals: Totals;
  atlas: Record<string, unknown> | null;
  notes: string[];
}

function defaultLog(msg: string): void {
  console.log(`[assetkit] ${msg}`);
}

/**
 * 跑完整素材管线，返回报告 dict（同时落 report.json / asset-optmap.json）。
 * 抛 AssetkitError（exit_code 1=处理失败，2=用法/环境错误）。
 */
export async function runAssetkit(opts: RunAssetkitOptions): Promise<AssetkitReport> {
  const {
    inputs = [], out, spec = null,
    imageQuality = 75, audioBitrate = 48_000, maxEdge = 0,
    atlas = true, atlasMaxWidth = 1024,
    extraText = EXTRA_SUBSET_TEXT_DEFAULT,
    minReductionPct = null,
    log = defaultLog,
  } = opts;

  const outDir = resolve(out);
  const specPath = spec ? resolve(spec) : null;
  if (specPath !== null && !isFile(specPath)) {
    throw new AssetkitError(`spec 不存在：${specPath}`, 2);
  }

  const materials = collect(inputs, specPath, repoRootDefault());
  if (existsDir(outDir)) rmSync(outDir, { recursive: true, force: true });
  mkdirSync(outDir, { recursive: true });

  const countOf = (kind: string): number => materials.filter((m) => m.kind === kind).length;
  log(`素材 ${materials.length} 个（image ${countOf("image")} / audio ${countOf("audio")}`
    + ` / font ${countOf("font")}）→ ${outDir}`);

  const notes: string[] = [];
  const imageEntries = await optimizeImages(materials, outDir,
    { quality: imageQuality, maxEdge });
  const audioEntries = transcodeAudio(materials, outDir, { bitrate: audioBitrate });
  let specJson: Record<string, unknown> | null = null;
  if (specPath !== null) {
    specJson = JSON.parse(readText(specPath)) as Record<string, unknown>;
  }
  const subsetText = specSubsetText(specJson, extraText);
  const fontEntries = await subsetFonts(materials, outDir, subsetText);

  const allEntries = [...imageEntries, ...audioEntries, ...fontEntries];
  const failed = allEntries.filter((e) => e.status === "failed");
  if (failed.length > 0) {
    for (const e of failed) notes.push(`素材 ${e.key} 处理失败：${e.note}`);
    throw new AssetkitError(
      `${failed.length} 个素材处理失败（见 report.json notes）；`
      + "素材管线宁可失败不可带病出报告", 1);
  }

  let atlasInfo: Record<string, unknown> | null = null;
  if (atlas && imageEntries.length > 0) {
    atlasInfo = await buildAtlas(imageEntries, outDir, atlasMaxWidth);
    if (atlasInfo && atlasInfo.note) notes.push(`图集：${atlasInfo.note}`);
  }

  const originalTotal = allEntries.reduce((s, e) => s + (e.originalBytes ?? 0), 0);
  const optimizedTotal = allEntries.reduce((s, e) => s + (e.optimizedBytes ?? 0), 0);
  const reductionPct = originalTotal > 0
    ? Math.round((1 - optimizedTotal / originalTotal) * 100 * 100) / 100
    : 0.0;

  let minMet: boolean | null = null;
  if (minReductionPct !== null && minReductionPct !== undefined) {
    minMet = originalTotal > 0 && reductionPct >= minReductionPct;
  }

  const optEntries = allEntries
    .filter((e) => e.out)
    .map((e) => ({
      key: e.key, src: e.src, out: e.out ?? null,
      kind: e.kind, encoding: e.encoding ?? null,
      originalBytes: e.originalBytes ?? null, optimizedBytes: e.optimizedBytes ?? null,
    }));
  writeFileSync(pathJoin(outDir, OPTMAP_NAME), `${JSON.stringify({
    version: 1,
    outDir,
    entries: optEntries,
  }, null, 2)}\n`, "utf8");

  const report: AssetkitReport = {
    assetkitVersion: ASSETKIT_VERSION,
    generatedAt: new Date().toISOString().slice(0, 19),
    spec: specPath,
    outDir,
    subsetTextChars: subsetText.length,
    materials: { image: imageEntries, audio: audioEntries, font: fontEntries },
    totals: {
      count: allEntries.length,
      originalBytes: originalTotal,
      optimizedBytes: optimizedTotal,
      reductionPct,
      minReductionPct: minReductionPct ?? null,
      minReductionMet: minMet,
    },
    atlas: atlasInfo,
    notes,
  };
  writeFileSync(pathJoin(outDir, REPORT_NAME), `${JSON.stringify(report, null, 2)}\n`, "utf8");

  const packed = (atlasInfo as { packed?: unknown } | null)?.packed;
  log(`汇总：${originalTotal.toLocaleString("en-US")}B → ${optimizedTotal.toLocaleString("en-US")}B（降 ${reductionPct}%）`
    + (typeof packed === "number" && packed > 0 ? `；图集 ${packed} 帧` : ""));
  for (const n of notes) log(`注意：${n}`);
  return report;
}

// ---------------------------------------------------------------- 小工具

function isFile(p: string): boolean {
  try {
    return statSync(p).isFile();
  } catch {
    return false;
  }
}

function existsDir(p: string): boolean {
  try {
    return statSync(p).isDirectory();
  } catch {
    return false;
  }
}

function readText(p: string): string {
  return readFileSync(p, "utf8");
}

function pathJoin(a: string, b: string): string {
  return join(a, b);
}

/** 仓库根。宿主适配（登记）：oracle collect 的 repo_root=None → Path.cwd()，factory
 *  单栈固定为仓库根（本模块位于 packages/assetkit/src/，上三级即根）——与模板构建
 *  脚本的 REPO_ROOT 同判，消除"spec 相对仓库根素材"对调用目录的敏感性。 */
function repoRootDefault(): string {
  return resolve(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
}

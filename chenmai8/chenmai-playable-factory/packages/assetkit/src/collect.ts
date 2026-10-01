// packages/assetkit/src/collect.ts — 素材收集（oracle python/assetkit/collect.py 语义移植）。
//
// 目录/文件参数 + spec 声明素材 → 去重后的素材清单。spec 声明素材的路径解析次序
// 与模板构建脚本（packages/templates/*/build.mjs）逐字对齐：先相对 spec 文件目录，
// 再相对仓库根；两处都不存在则不收集（由构建脚本按"缺素材回退"语义告警，
// assetkit 不越权替构建器裁决）。

import { readdirSync, readFileSync, statSync } from "node:fs";
import { resolve } from "node:path";

import type { Material } from "./types.ts";

export const IMAGE_EXTS = new Set([".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"]);
export const AUDIO_EXTS = new Set([".wav", ".mp3", ".m4a", ".aac", ".ogg", ".oga", ".opus", ".flac", ".wma"]);
export const FONT_EXTS = new Set([".ttf", ".otf", ".ttc"]);

export type { Material };

/** 小写扩展名（含点；无扩展名/纯点文件名返回 ""——与 pathlib.Path.suffix 同形）。 */
export function extname(path: string): string {
  const base = path.slice(Math.max(path.lastIndexOf("/") + 1, path.lastIndexOf("\\") + 1));
  const j = base.lastIndexOf(".");
  return j <= 0 ? "" : base.slice(j).toLowerCase();
}

export function classify(path: string): "image" | "audio" | "font" | null {
  const ext = extname(path);
  if (IMAGE_EXTS.has(ext)) return "image";
  if (AUDIO_EXTS.has(ext)) return "audio";
  if (FONT_EXTS.has(ext)) return "font";
  return null;
}

function normAbs(p: string): string {
  return resolve(p.replaceAll("\\", "/"));
}

function isFile(p: string): boolean {
  try {
    return statSync(p).isFile();
  } catch {
    return false;
  }
}

/** 按声明顺序取 spec.assets 里的全部素材相对路径串（存在性后置判断）。 */
export function specAssetRelPaths(spec: Record<string, unknown>): string[] {
  const assets = (spec.assets ?? {}) as {
    background?: unknown; sprites?: Record<string, unknown>;
    audio?: Record<string, unknown>; fontSubset?: unknown;
  };
  const rels: string[] = [];
  if (typeof assets.background === "string" && assets.background) rels.push(assets.background);
  for (const rel of Object.values(assets.sprites ?? {})) {
    if (typeof rel === "string" && rel) rels.push(rel);
  }
  for (const rel of Object.values(assets.audio ?? {})) {
    if (typeof rel === "string" && rel) rels.push(rel);
  }
  if (typeof assets.fontSubset === "string" && assets.fontSubset) rels.push(assets.fontSubset);
  return rels;
}

/** 与模板构建脚本同次序的相对路径解析；找不到返回 null。 */
export function resolveSpecAsset(rel: string, specDir: string, repoRoot: string): string | null {
  for (const base of [specDir, repoRoot]) {
    const cand = resolve(base, rel);
    if (isFile(cand)) return cand;
  }
  return null;
}

/**
 * 收集素材：spec 声明优先（键用声明串），其后目录/文件参数（键用绝对路径）。
 * 同一文件只收一次（按规范化绝对路径去重，先到先得）。目录递归收集，符号链接
 * 目录不跟随（防环）。不可识别扩展名的文件直接忽略（收集面即三类素材）。
 * 不存在的输入路径静默忽略：调用方（CLI/make）只关心收进了什么，报告里有逐素材
 * 清单，缺了什么一目了然。
 */
export function collect(
  inputs: readonly string[],
  specPath: string | null,
  repoRoot: string | null = null,
): Material[] {
  const root = repoRoot ? normAbs(repoRoot) : process.cwd();
  const found = new Map<string, Material>();

  const add = (src: string, key: string): void => {
    const absSrc = normAbs(src);
    if (found.has(absSrc)) return;
    const kind = classify(absSrc);
    if (kind === null) return;
    found.set(absSrc, { src: absSrc, key, kind });
  };

  // 1) spec 声明素材（键 = spec 里的声明串，模板构建脚本按同串接线）
  if (specPath !== null) {
    const specFile = normAbs(specPath);
    if (!isFile(specFile)) {
      throw new Error(`spec 不存在：${specFile}`);
    }
    const spec = JSON.parse(readFileSync(specFile, "utf8")) as Record<string, unknown>;
    const specDir = resolve(specFile, "..");
    for (const rel of specAssetRelPaths(spec)) {
      const absPath = resolveSpecAsset(rel, specDir, root);
      if (absPath !== null) add(absPath, rel);
    }
  }

  // 2) 显式输入（目录递归 / 单文件）
  const walk = (dir: string, prefix: string): void => {
    let entries;
    try {
      entries = readdirSync(dir, { withFileTypes: true });
    } catch {
      return;
    }
    for (const e of entries) {
      if (e.isSymbolicLink()) continue; // 符号链接不跟随（防环）
      const abs = `${dir}/${e.name}`;
      if (e.isDirectory()) walk(abs, `${prefix}${e.name}/`);
      else if (e.isFile()) add(abs, normAbs(abs));
    }
  };
  for (const item of inputs) {
    let st;
    try {
      st = statSync(item);
    } catch {
      continue; // 不存在的输入路径静默忽略
    }
    if (st.isDirectory()) walk(normAbs(item), "");
    else if (st.isFile()) add(item, normAbs(item));
  }

  return [...found.values()];
}

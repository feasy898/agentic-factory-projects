/// <reference path="./deps.d.ts" />
// packages/assetkit/src/fonts.ts — 字体子集（oracle python/assetkit/fonts.py 语义移植）。
//
// 字符集 = spec.i18n.strings 全语言值 ∪ meta.title ∪ 数字（得分/倒计时必然要渲染）
// ∪ extraText。字体缺字形不报错：如实报告覆盖率（哪些请求字符在原字体 cmap 里就
// 没有），子集里自然只含有字形的部分。
//
// 宿主适配（决策 §2.2 迁移表）：oracle fontTools subsetter → subset-font（harfbuzzjs）
// 做子集化（woff2 直出）；cmap 覆盖率判定与子集复核用 fontkit。行为契约不变：
// 输出格式 woff2、覆盖率如实报告、无空子集（一个命中字形都没有就不产出）。

import { readFileSync, statSync, writeFileSync } from "node:fs";
import path from "node:path";

import { openSync } from "fontkit";
import subsetFont from "subset-font";

import type { AssetEntry, Material } from "./types.ts";

export const DIGITS = "0123456789";

/** fontkit 打开的字体（ttc 集合取第 0 个——oracle fontNumber=0 同语义）。 */
type AnyFont = { hasGlyphForCodePoint(cp: number): boolean };

function openFont(src: string): AnyFont {
  const f = openSync(src) as unknown as AnyFont & { fonts?: AnyFont[] };
  if (Array.isArray(f.fonts)) return f.fonts[0] as AnyFont;
  return f;
}

/**
 * 取"可被子集化的字体字节"：普通字体原样返回；TTC 集合（harfbuzzjs 不解析 ttcf
 * 容器——oracle fontTools 经 fontNumber=0 取成员，此处同语义）把成员 0 重建为独立
 * sfnt：表目录原样拷贝、表数据按原偏移聚拢并改写目录内偏移（4 字节对齐；
 * 校验和保留原值——子集化不做校验和验证）。宿主适配，已登记。
 */
export function fontBytesForSubset(src: string): Buffer {
  const raw = readFileSync(src);
  if (raw.subarray(0, 4).toString("binary") !== "ttcf") return raw;
  const numFonts = raw.readUInt32BE(8);
  void numFonts;
  const member = raw.readUInt32BE(12); // 成员 0
  const numTables = raw.readUInt16BE(member + 4);
  const dirSize = 12 + numTables * 16;
  const tables: Array<{ tag: string; offset: number; length: number }> = [];
  for (let i = 0; i < numTables; i++) {
    const e = member + 12 + i * 16;
    tables.push({
      tag: raw.subarray(e, e + 4).toString("binary"),
      offset: raw.readUInt32BE(e + 8),
      length: raw.readUInt32BE(e + 12),
    });
  }
  const aligned = (n: number): number => (n + 3) & ~3;
  const total = dirSize + tables.reduce((s, t) => s + aligned(t.length), 0);
  const buf = Buffer.alloc(total);
  raw.copy(buf, 0, member, member + dirSize);
  let p = dirSize;
  for (let i = 0; i < tables.length; i++) {
    const t = tables[i]!;
    raw.copy(buf, p, t.offset, t.offset + t.length);
    buf.writeUInt32BE(p, 12 + i * 16 + 8); // 表目录 entry 的 offset 字段
    p += aligned(t.length);
  }
  return buf;
}

/** 汇总 spec 里的全部应上屏字符（去重、保持首次出现序；跳过空白字符）。 */
export function specSubsetText(spec: Record<string, unknown> | null, extraText = ""): string {
  const chars: string[] = [];
  const seen = new Set<string>();
  const push = (s: string): void => {
    for (const ch of s) {
      if (!seen.has(ch) && !/\s/.test(ch)) {
        seen.add(ch);
        chars.push(ch);
      }
    }
  };
  if (spec) {
    push(String((spec.meta as { title?: unknown } | undefined)?.title ?? ""));
    const strings = ((spec.i18n as { strings?: unknown } | undefined)?.strings ?? {}) as
      Record<string, unknown>;
    for (const table of Object.values(strings)) {
      if (table && typeof table === "object") {
        for (const v of Object.values(table as Record<string, unknown>)) {
          if (typeof v === "string") push(v);
        }
      }
    }
  }
  push(DIGITS);
  push(extraText ?? "");
  return chars.join("");
}

function round1(x: number): number {
  return Math.round(x * 10) / 10;
}

/** 子集化全部 font 素材；返回逐素材结果条目（含字符覆盖率）。 */
export async function subsetFonts(
  materials: readonly Material[],
  outDir: string,
  text: string,
): Promise<AssetEntry[]> {
  const fonts = materials.filter((m) => m.kind === "font");
  if (fonts.length === 0) return [];

  const entries: AssetEntry[] = [];
  for (const m of fonts) {
    const originalBytes = statSync(m.src).size;
    let requested: string[];
    let covered: string[];
    let font: AnyFont | null = null;
    try {
      font = openFont(m.src);
      // python str 迭代 = 码点；JS 同用 for...of（Array.from）逐码点。
      const uniq = new Set<string>(text);
      requested = [...uniq].sort();
      covered = requested.filter((ch) => font!.hasGlyphForCodePoint(ch.codePointAt(0)!));
    } catch (exc) {
      entries.push({
        key: m.key, src: m.src, kind: "font", status: "failed",
        originalBytes, optimizedBytes: originalBytes, reductionPct: 0.0,
        note: `字体解析失败：${String(exc)}`,
      });
      continue;
    }
    if (covered.length === 0) {
      entries.push({
        key: m.key, src: m.src, kind: "font",
        status: "kept-original",
        originalBytes, optimizedBytes: originalBytes, reductionPct: 0.0,
        charsRequested: requested.length, charsCovered: 0,
        note: "请求字符在该字体 cmap 中一个都没有，不产出空子集",
      });
      continue;
    }
    let data: Buffer;
    try {
      data = await subsetFont(fontBytesForSubset(m.src), covered.join(""), { targetFormat: "woff2" });
    } catch (exc) {
      // 字体解析/子集化失败：保留原始并记录，不阻塞
      entries.push({
        key: m.key, src: m.src, kind: "font",
        status: "kept-original",
        originalBytes, optimizedBytes: originalBytes, reductionPct: 0.0,
        note: `子集化失败，保留原始：${String(exc)}`,
      });
      continue;
    }
    // 格式魔数复核（oracle flavor_used 同逻辑；woff2 直出时即 wOF2）。
    const head = data.subarray(0, 4).toString("binary");
    const flavorUsed = head === "wOF2" ? "woff2" : head === "wOFF" ? "woff" : "ttf";
    const ext = { woff2: ".woff2", woff: ".woff", ttf: ".ttf" }[flavorUsed]!;
    const outBase = `${path.basename(m.src, path.extname(m.src))}.subset${ext}`;
    const outFile = path.resolve(path.join(outDir, outBase));
    // 显式遏制断言（fail-loud）：basename 已剥目录分量，理论上不可能越出 outDir；
    // 此断言把"构造上安全"变成"构造上安全且被校验"。
    if (!outFile.startsWith(path.resolve(outDir) + path.sep)) {
      entries.push({
        key: m.key, src: m.src, kind: "font", status: "failed",
        originalBytes, optimizedBytes: originalBytes, reductionPct: 0.0,
        note: `产物路径越界（防御断言）：${outFile}`,
      });
      continue;
    }
    writeFileSync(outFile, data);

    const noteParts = [`字符覆盖 ${covered.length}/${requested.length}`];
    const missing = requested.filter((ch) => !covered.includes(ch));
    if (missing.length > 0) {
      const shown = missing.slice(0, 12).join("");
      const more = missing.length > 12 ? `（另 ${missing.length - 12} 字略）` : "";
      noteParts.push(`字体缺 ${missing.length} 字形：${JSON.stringify(shown)}${more}`);
    }
    if (data.length >= originalBytes) {
      noteParts.push(`子集不小于原始（${data.length}B ≥ ${originalBytes}B），仅作记录仍落盘`);
    }
    entries.push({
      key: m.key, src: m.src, kind: "font",
      status: data.length < originalBytes ? "optimized" : "kept-original",
      out: path.basename(outFile), encoding: flavorUsed,
      originalBytes, optimizedBytes: data.length,
      reductionPct: data.length < originalBytes ? round1((1 - data.length / originalBytes) * 100) : 0.0,
      charsRequested: requested.length, charsCovered: covered.length,
      note: noteParts.join("；"),
    });
  }
  return entries;
}

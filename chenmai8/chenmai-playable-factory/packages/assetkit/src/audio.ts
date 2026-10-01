// packages/assetkit/src/audio.ts — 音频：ffmpeg 转低码率 AAC（.m4a）。
//（oracle python/assetkit/audio.py 语义移植：单栈宿主 subprocess.run → spawnSync。）
//
// ffmpeg 缺席或单文件转码失败都不阻塞流水线：该素材保留原始并如实记录（宁可
// 不减不假报）。元数据全剥（-map_metadata -1），广告素材不需要封面/作者信息。

import { spawnSync } from "node:child_process";
import { statSync } from "node:fs";
import path from "node:path";

import type { AssetEntry, Material } from "./types.ts";

/** 定位 ffmpeg：环境变量 PF_ASSETKIT_FFMPEG 优先，其后 PATH。 */
export function findFfmpeg(): string | null {
  const custom = process.env.PF_ASSETKIT_FFMPEG;
  if (custom) {
    try {
      if (statSync(custom).isFile()) return custom;
    } catch { /* 不存在则继续 PATH 探测 */ }
  }
  // shutil.which 同义：spawnSync 一次 -version 探测（ENOENT 即 PATH 无 ffmpeg）。
  const probe = spawnSync("ffmpeg", ["-version"], { timeout: 15_000, windowsHide: true });
  return probe.error ? null : "ffmpeg";
}

function round1(x: number): number {
  return Math.round(x * 10) / 10;
}

/** 转码全部 audio 素材为 .m4a；返回逐素材结果条目。 */
export function transcodeAudio(
  materials: readonly Material[],
  outDir: string,
  { bitrate = 48_000 }: { bitrate?: number } = {},
): AssetEntry[] {
  const audios = materials.filter((m) => m.kind === "audio");
  if (audios.length === 0) return [];
  const ffmpeg = findFfmpeg();
  const entries: AssetEntry[] = [];
  if (ffmpeg === null) {
    for (const m of audios) {
      const size = statSync(m.src).size;
      entries.push({
        key: m.key, src: m.src, kind: "audio",
        status: "kept-original", encoding: "original",
        originalBytes: size, optimizedBytes: size, reductionPct: 0.0,
        note: "ffmpeg 不可用（PATH 无 ffmpeg，可用 PF_ASSETKIT_FFMPEG 指定），保留原始",
      });
    }
    return entries;
  }

  for (const m of audios) {
    const originalBytes = statSync(m.src).size;
    const outFile = path.join(outDir, `${path.basename(m.src, path.extname(m.src))}.m4a`);
    const cmd = [
      ffmpeg, "-y", "-nostdin", "-i", m.src,
      "-vn", "-map_metadata", "-1",
      "-codec:a", "aac", "-b:a", `${Math.trunc(bitrate)}`,
      "-f", "ipod", outFile,
    ];
    let proc;
    try {
      proc = spawnSync(cmd[0]!, cmd.slice(1), {
        timeout: 120_000, encoding: "utf8", windowsHide: true,
      });
    } catch (exc) {
      proc = { error: exc as Error, status: null, stderr: "", stdout: "" };
    }
    if (proc.error) {
      // 启动失败/超时（oracle 捕 OSError/SubprocessError 同语义）：保留原始，不阻塞。
      entries.push({
        key: m.key, src: m.src, kind: "audio",
        status: "kept-original", encoding: "original",
        originalBytes, optimizedBytes: originalBytes, reductionPct: 0.0,
        note: `ffmpeg 启动失败：${String(proc.error)}`,
      });
      continue;
    }
    const ok = proc.status === 0 && statSize(outFile) > 0;
    if (!ok) {
      const tail = (proc.stderr ?? "").trim().split(/\r?\n/).slice(-3).join("\n");
      entries.push({
        key: m.key, src: m.src, kind: "audio",
        status: "kept-original", encoding: "original",
        originalBytes, optimizedBytes: originalBytes, reductionPct: 0.0,
        note: tail
          ? `转码失败（exit ${proc.status}），保留原始：${tail}`
          : "转码失败，保留原始",
      });
      continue;
    }
    const newBytes = statSize(outFile);
    if (newBytes >= originalBytes) {
      entries.push({
        key: m.key, src: m.src, kind: "audio",
        status: "kept-original", encoding: "original",
        out: null,
        originalBytes, optimizedBytes: originalBytes, reductionPct: 0.0,
        note: `低码率转码不小于原始（${newBytes}B ≥ ${originalBytes}B），保留原始`,
      });
      continue;
    }
    entries.push({
      key: m.key, src: m.src, kind: "audio",
      status: "optimized", out: path.basename(outFile), encoding: `aac-${Math.trunc(bitrate)}`,
      originalBytes, optimizedBytes: newBytes,
      reductionPct: round1((1 - newBytes / originalBytes) * 100),
      note: "",
    });
  }
  return entries;
}

function statSize(p: string): number {
  try {
    return statSync(p).size;
  } catch {
    return 0;
  }
}

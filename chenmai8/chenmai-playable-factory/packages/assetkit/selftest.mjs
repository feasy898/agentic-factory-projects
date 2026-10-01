// packages/assetkit/selftest.mjs — 端到端自测（oracle python/assetkit/selftest.py 语义移植，
// `python -m assetkit selftest` → `node packages/assetkit/selftest.mjs`）。
//
// 在仓库 tmp/assetkit-selftest/ 下合成一套"全类型"素材（压图两类：平色带 alpha 的
// 游戏件 / 渐变噪声的照片类；低码率音频：合成正弦 WAV；字体：本机系统字体里挑出
// 覆盖中文字形与阿拉伯字形的各一个，只读输入、绝不入库），带一份合成 spec（i18n
// 中/阿字符串 + sprite/audio 声明），跑完整管线后逐项断言：
//   1. 汇总降幅 ≥30%（--min-reduction 同款语义，minReductionMet=true）；
//   2. 游戏件压图生效且不增大；照片类走有损 WebP 且大幅下降；
//   3. WAV → 低码率 AAC 生效且明显变小；
//   4. 中文字体子集含全部请求中文字形；阿拉伯字体子集含全部请求阿拉伯字形；
//      子集 ≤40KB（assetkit.md 字体线）；
//   5. 图集：帧数=可装箱图数、帧两两不重叠、全部在界内、图集图可解码且尺寸一致；
//   6. asset-optmap.json / report.json 落盘，optmap 键与素材一一对应。
//
// 系统字体候选缺失时字体项如实记 SKIP（不假绿）；其余项缺一即 FAIL（exit 1）。

import { existsSync, mkdirSync, readFileSync, rmSync, statSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import process from "node:process";

import { openSync } from "fontkit";
import sharp from "sharp";

const REPO_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
const TMP_ROOT = join(REPO_ROOT, "tmp", "assetkit-selftest");

const ZH_FONT_CANDIDATES = ["msyh.ttc", "msyhbd.ttc", "simhei.ttf"];
const AR_FONT_CANDIDATES = ["arial.ttf", "tahoma.ttf", "times.ttf", "segoeui.ttf", "calibri.ttf"];

const ZH_TEXT = "得分通关啦立即下载拖动宝石三色连成一线";
const AR_TEXT = "مرحبا بكم في اللعبة اسحب الجواهر";

// ---------------------------------------------------------------- 合成素材（确定性 fixture）

/** 平色圆角"宝石"（带 alpha 抗锯齿边）：模拟游戏小件，量化编码应大幅受益。 */
async function synthGem(path) {
  const size = 128;
  const rgba = Buffer.alloc(size * size * 4, 0);
  const inRoundedRect = (x, y, x0, y0, x1, y1, r) => {
    if (x < x0 || x > x1 || y < y0 || y > y1) return false;
    const cx = Math.min(Math.max(x, x0 + r), x1 - r);
    const cy = Math.min(Math.max(y, y0 + r), y1 - r);
    const dx = x - cx;
    const dy = y - cy;
    return dx * dx + dy * dy <= r * r;
  };
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      let r = 0;
      let g = 0;
      let b = 0;
      let a = 0;
      if (inRoundedRect(x, y, 8, 8, size - 9, size - 9, 28)) {
        [r, g, b, a] = [46, 134, 222, 235];
      }
      if (inRoundedRect(x, y, 24, 20, size - 45, size - 61, 16)) {
        [r, g, b, a] = [120, 190, 255, 255];
      }
      // 菱形（顶点 (64,36)/(88,64)/(64,92)/(40,64)）：|dx|+|dy| ≤ 28。
      const dx = Math.abs(x - size / 2);
      const dy = Math.abs(y - size / 2);
      if (dx + dy <= 28) [r, g, b, a] = [28, 96, 176, 255];
      const o = (y * size + x) * 4;
      rgba[o] = r;
      rgba[o + 1] = g;
      rgba[o + 2] = b;
      rgba[o + 3] = a;
    }
  }
  await sharp(rgba, { raw: { width: size, height: size, channels: 4 } }).png().toFile(path);
}

/** 渐变 + 伪随机噪声的"照片"类大图：有损 WebP 应大幅受益。 */
async function synthPhoto(path) {
  const w = 512;
  const h = 512;
  // 确定性伪随机（mulberry32，种子 20261008；fixture 不锁与 oracle 同值）。
  let s = 20261008 >>> 0;
  const rand = () => {
    s = (s + 0x6d2b79f5) >>> 0;
    let t = s;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
  const rgb = Buffer.alloc(w * h * 3, 0);
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const n = Math.floor(rand() * 48);
      const o = (y * w + x) * 3;
      rgb[o] = ((Math.trunc((x * 255) / w) + n) % 256);
      rgb[o + 1] = ((Math.trunc((y * 255) / h) + n) % 256);
      rgb[o + 2] = ((n * 5) % 256);
    }
  }
  await sharp(rgb, { raw: { width: w, height: h, channels: 3 } }).png().toFile(path);
}

/** 0.5s 440Hz 正弦 + 衰减包络的 16-bit 单声道 WAV（提示音的代理）。手写 RIFF 头。 */
function synthWav(path) {
  const rate = 22050;
  const dur = 0.5;
  const n = Math.trunc(rate * dur);
  const data = Buffer.alloc(n * 2);
  for (let i = 0; i < n; i++) {
    const t = i / rate;
    const env = Math.exp(-4.0 * t);
    const v = Math.round(32000 * env * Math.sin(2 * Math.PI * 440.0 * t));
    data.writeInt16LE(v, i * 2);
  }
  const header = Buffer.alloc(44);
  header.write("RIFF", 0);
  header.writeUInt32LE(36 + data.length, 4);
  header.write("WAVE", 8);
  header.write("fmt ", 12);
  header.writeUInt32LE(16, 16);
  header.writeUInt16LE(1, 20); // PCM
  header.writeUInt16LE(1, 22); // mono
  header.writeUInt32LE(rate, 24);
  header.writeUInt32LE(rate * 2, 28);
  header.writeUInt16LE(2, 32);
  header.writeUInt16LE(16, 34);
  header.write("data", 36);
  header.writeUInt32LE(data.length, 40);
  writeFileSync(path, Buffer.concat([header, data]));
}

function sizeOf(p) {
  return statSync(p).size;
}

/** 从候选里挑第一个"存在且覆盖全部 must_cover 字形"的系统字体（只读）。 */
function pickFont(candidates, mustCover) {
  for (const name of candidates) {
    const p = `C:/Windows/Fonts/${name}`;
    if (!existsSync(p)) continue;
    try {
      const f = openFont(p);
      const chars = [...new Set(mustCover)].filter((ch) => !/\s/.test(ch));
      if (chars.every((ch) => f.hasGlyphForCodePoint(ch.codePointAt(0)))) return p;
    } catch { /* 解析失败换下一个候选 */ }
  }
  return null;
}

function openFont(p) {
  const f = openSync(p);
  return Array.isArray(f?.fonts) ? f.fonts[0] : f;
}

function writeSpec(tmp) {
  const spec = {
    specVersion: "1.0.0",
    meta: { projectId: "assetkit-selftest", title: "素材自测", seed: 1 },
    game: { template: "match3", params: {}, difficulty: { targetLevel: 0.5 },
      attract: { nearWin: true }, durationBudgetSec: { target: 20, max: 30 } },
    flow: { tutorial: { enabled: true, gesture: "tap", maxSec: 3 },
      endScreen: { showScore: true, ctaKey: "cta", landingUrl: "https://example.com/lp" } },
    assets: {
      sprites: { "piece-0": "selftest-gem.png" },
      audio: { tap: "selftest-sfx.wav" },
    },
    i18n: {
      defaultLocale: "zh",
      locales: ["zh", "ar"],
      strings: {
        zh: { cta: "立即下载", tutorial: ZH_TEXT, win: "通关啦！", lose: "再试一次！", score: "得分" },
        ar: { cta: "حمّل الآن", tutorial: AR_TEXT, win: "فوز!", lose: "حاول مرة أخرى", score: "النقاط" },
      },
      rtl: ["ar"],
    },
    channels: { targets: ["applovin"], orientation: "portrait", overrides: {} },
    qc: { maxLoadSec: 3.0, autoplayTimeoutSec: 45 },
  };
  const p = join(tmp, "selftest-spec.json");
  writeFileSync(p, `${JSON.stringify(spec, null, 2)}\n`, "utf8");
  return p;
}

function assert(name, ok, detail = "") {
  console.log(`  ${ok ? "ok " : "FAIL"} ${name}${detail ? `（${detail}）` : ""}`);
  return ok;
}

export function runSelftest() {
  return runSelftestAsync();
}

// 直接执行入口（node packages/assetkit/selftest.mjs）；被 CLI/测试 import 时走 runSelftest()。
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  runSelftestAsync().then((code) => {
    process.exitCode = code;
  }, (err) => {
    process.stderr.write(`assetkit selftest: 未捕获异常：${err?.stack || err}\n`);
    process.exitCode = 1;
  });
}

async function runSelftestAsync() {
  const { runAssetkit } = await import("./src/pipeline.ts");

  if (existsSync(TMP_ROOT)) rmSync(TMP_ROOT, { recursive: true, force: true });
  mkdirSync(TMP_ROOT, { recursive: true });
  console.log(`[assetkit] selftest 工作目录：${TMP_ROOT}`);

  await synthGem(join(TMP_ROOT, "selftest-gem.png"));
  await synthPhoto(join(TMP_ROOT, "selftest-photo.png"));
  synthWav(join(TMP_ROOT, "selftest-sfx.wav"));
  const specPath = writeSpec(TMP_ROOT);

  const gemBytes = sizeOf(join(TMP_ROOT, "selftest-gem.png"));
  const photoBytes = sizeOf(join(TMP_ROOT, "selftest-photo.png"));
  const wavBytes = sizeOf(join(TMP_ROOT, "selftest-sfx.wav"));
  console.log(`  合成素材：gem ${gemBytes}B / photo ${photoBytes}B / wav ${wavBytes}B`);

  const zhFont = pickFont(ZH_FONT_CANDIDATES, ZH_TEXT);
  const arFont = pickFont(AR_FONT_CANDIDATES, AR_TEXT);
  let fontsAvailable = zhFont !== null && arFont !== null;
  if (!fontsAvailable) {
    console.log(`  SKIP 系统字体候选不足（zh=${zhFont}, ar=${arFont}），字体子集项本机无法验证`);
  } else {
    console.log(`  字体样本（只读输入，不入库）：zh=${zhFont.split("/").pop()}, ar=${arFont.split("/").pop()}`);
  }

  const report = await runAssetkit({
    inputs: [join(TMP_ROOT, "selftest-photo.png"),
      ...(fontsAvailable ? [zhFont, arFont] : [])],
    out: join(TMP_ROOT, "opt"),
    spec: specPath,
    minReductionPct: 30.0,
  });

  let ok = true;
  const totals = report.totals;
  ok = assert("汇总降幅 ≥30%", totals.minReductionMet === true,
    `${totals.originalBytes.toLocaleString("en-US")}B → ${totals.optimizedBytes.toLocaleString("en-US")}B（降 ${totals.reductionPct}%）`) && ok;

  const mat = report.materials;
  const gemE = mat.image.find((e) => e.key === "selftest-gem.png") ?? null;
  const photoE = mat.image.find((e) => e.key.endsWith("selftest-photo.png")) ?? null;
  ok = assert("游戏件压图生效（量化/近无损竞标，永不增大）",
    gemE !== null && gemE.status === "optimized" && gemE.optimizedBytes < gemE.originalBytes,
    gemE ? `${gemE.encoding} ${gemE.originalBytes}→${gemE.optimizedBytes}B` : "缺条目") && ok;
  ok = assert("照片类走有损 WebP 且大幅下降",
    photoE !== null && photoE.status === "optimized"
    && photoE.encoding === "webp-lossy" && photoE.reductionPct >= 30,
    photoE ? `${photoE.reductionPct}%` : "缺条目") && ok;

  const wavE = mat.audio.find((e) => e.key === "selftest-sfx.wav") ?? null;
  ok = assert("WAV → 低码率 AAC 生效且明显变小",
    wavE !== null && wavE.status === "optimized"
    && String(wavE.out ?? "").endsWith(".m4a") && wavE.reductionPct >= 50,
    wavE ? `${wavE.originalBytes}→${wavE.optimizedBytes}B` : "缺条目") && ok;

  if (fontsAvailable) {
    const zhE = mat.font.find((e) => e.src === resolve(zhFont)) ?? null;
    const arE = mat.font.find((e) => e.src === resolve(arFont)) ?? null;
    const subsetCovers = (entry, text) => {
      const f = openFont(join(TMP_ROOT, "opt", entry.out));
      return [...text].filter((ch) => !/\s/.test(ch))
        .every((ch) => f.hasGlyphForCodePoint(ch.codePointAt(0)));
    };
    ok = assert("中文字体子集含全部请求中文字形且 ≤40KB",
      zhE !== null && zhE.status === "optimized"
      && subsetCovers(zhE, ZH_TEXT) && zhE.optimizedBytes <= 40_960,
      zhE ? `${zhE.optimizedBytes}B，${zhE.note}` : "缺条目") && ok;
    ok = assert("阿拉伯字体子集含全部请求阿拉伯字形且 ≤40KB",
      arE !== null && arE.status === "optimized"
      && subsetCovers(arE, AR_TEXT) && arE.optimizedBytes <= 40_960,
      arE ? `${arE.optimizedBytes}B，${arE.note}` : "缺条目") && ok;
  }

  const atlas = report.atlas ?? {};
  const nImages = mat.image.filter((e) => e.status === "optimized").length;
  const atlasJsonPath = join(TMP_ROOT, "opt", "atlas.json");
  const frames = existsSync(atlasJsonPath)
    ? JSON.parse(readFileSync(atlasJsonPath, "utf8")) : {};
  const fr = frames.frames ?? {};
  let noOverlap = true;
  const keys = Object.keys(fr);
  for (let i = 0; i < keys.length; i++) {
    for (let j = i + 1; j < keys.length; j++) {
      const a = fr[keys[i]];
      const b = fr[keys[j]];
      if (a.x < b.x + b.width && b.x < a.x + a.width
        && a.y < b.y + b.height && b.y < a.y + a.height) noOverlap = false;
    }
  }
  const inBounds = Object.values(fr).every((f) => f.x + f.width <= (frames.width ?? 0)
    && f.y + f.height <= (frames.height ?? 0));
  let atlasImgOk = false;
  if (frames.image) {
    const meta = await sharp(join(TMP_ROOT, "opt", frames.image)).metadata();
    atlasImgOk = meta.width === frames.width && meta.height === frames.height;
  }
  ok = assert("图集帧数=优化图数、两两不重叠、全部在界内",
    atlas.packed === nImages && keys.length === nImages && noOverlap && inBounds,
    `packed=${atlas.packed}/${nImages} frames=${keys.length}`) && ok;
  ok = assert("图集图可解码且尺寸与 atlas.json 一致", atlasImgOk,
    `${frames.image} ${frames.width}x${frames.height}`) && ok;

  const optmapPath = join(TMP_ROOT, "opt", "asset-optmap.json");
  const optmap = existsSync(optmapPath) ? JSON.parse(readFileSync(optmapPath, "utf8")) : {};
  const optKeys = new Set((optmap.entries ?? []).map((e) => e.key));
  const expected = new Set([...mat.image, ...mat.audio, ...mat.font]
    .filter((e) => e.out).map((e) => e.key));
  const sameSet = optKeys.size === expected.size && [...expected].every((k) => optKeys.has(k));
  ok = assert("asset-optmap.json 键与产出素材一一对应（spec 声明串为键）",
    sameSet && optKeys.size > 0, `${optKeys.size} 键`) && ok;

  console.log(`[assetkit] selftest ${ok ? "PASS" : "FAIL"}`);
  if (!ok) console.log(`  工作目录保留于 ${TMP_ROOT}（供排查）`);
  return ok ? 0 : 1;
}

#!/usr/bin/env node
// tmpl-merge 构建脚本（templates.md §3 同一构建形态）：TS 源码（含字节复用的
// 中性名引擎 bundle）esbuild 打包为单 IIFE，与 PlayableSpec JSON 一起内联进
// 单个 HTML（零外链、零相对资源引用）。
//
// 用法：
//   node build.mjs [--spec <path>] [--out <path>] [--locale <tag>] [--no-minify]
//
// 默认：--spec specs-eval/golden-merge.json --out artifacts/preview/merge.html
// 产物自包含：未替换的贴图由引擎运行时程序化生成，音效为代码内置的 WAV data URI。
//
// 最小素材路径（与 tmpl-match3 同一管线）：spec.assets.sprites 里文件真实存在的
// 键，其 PNG/JPG/WebP/GIF 在构建期读出并以 data URI 内联进 window.PF_ASSETS
//（运行期替换同键 tier 的程序化贴图）；缺失/格式不支持的键打警告并继续（运行期
// 回退程序化贴图）。真实嵌入清单同步写旁车 `<out>.assets.json`（零嵌入也写出
// 空清单；make 据此给 CHK10 传 --require-sprite）。

import { readFileSync, writeFileSync, mkdirSync, existsSync } from "node:fs";
import { createHash } from "node:crypto";
import path from "node:path";
import { fileURLToPath } from "node:url";
import process from "node:process";
import { build } from "esbuild";

const PKG_DIR = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(PKG_DIR, "../../..");

// 引擎 vendor 件（决策 §2.1 M3 行 / templates README 契约）：构建前从
// packages/templates/vendor/engine.js 母本**字节复制**到 src/vendor/engine.js
//（sha256 锚定校验，漂移即失败——母本唯一入库，包内副本不入库见根 .gitignore）。
const ENGINE_SHA256 = "660aa854f150fdc8aac45f08114f644e1569e5ed9cfbfed09fc1b0f24de8a686";
const ENGINE_MASTER = path.join(PKG_DIR, "..", "vendor", "engine.js");
const ENGINE_COPY = path.join(PKG_DIR, "src", "vendor", "engine.js");

function copyVendorEngine() {
  const bytes = readFileSync(ENGINE_MASTER);
  const sha = createHash("sha256").update(bytes).digest("hex");
  if (sha !== ENGINE_SHA256) {
    throw new Error(`引擎母本 sha256 漂移：${sha} ≠ 冻结锚 ${ENGINE_SHA256}`);
  }
  if (existsSync(ENGINE_COPY)) {
    const cur = createHash("sha256").update(readFileSync(ENGINE_COPY)).digest("hex");
    if (cur === ENGINE_SHA256) return false; // 已是同字节，免复制
  }
  mkdirSync(path.dirname(ENGINE_COPY), { recursive: true });
  writeFileSync(ENGINE_COPY, bytes);
  return true;
}

const ASSET_MIME = {
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".webp": "image/webp",
  ".gif": "image/gif",
};

/** 解析 spec.assets.sprites 的相对路径：先相对 spec 文件目录，再相对仓库根。 */
function resolveAssetPath(rel, specDir) {
  for (const base of [specDir, REPO_ROOT]) {
    const abs = path.resolve(base, rel);
    if (existsSync(abs)) return abs;
  }
  return null;
}

/** 构建期内联素材：返回 (内联 data URI 表, 真实嵌入清单)。 */
function buildAssetMap(spec, specDir) {
  const sprites = (spec.assets && spec.assets.sprites) || {};
  const map = {};
  const manifest = [];
  for (const [key, rel] of Object.entries(sprites)) {
    if (typeof rel !== "string" || !rel) continue;
    const abs = resolveAssetPath(rel, specDir);
    if (!abs) {
      console.warn(`[tmpl-merge] 警告: 素材文件缺失，跳过嵌入（运行期回退程序化贴图）: ${key}=${rel}`);
      continue;
    }
    const mime = ASSET_MIME[path.extname(abs).toLowerCase()];
    if (!mime) {
      console.warn(`[tmpl-merge] 警告: 不支持的素材格式（仅 png/jpg/webp/gif）: ${key}=${rel}`);
      continue;
    }
    const bytes = readFileSync(abs);
    map[key] = `data:${mime};base64,${bytes.toString("base64")}`;
    manifest.push({ spriteKey: key, path: rel, bytes: bytes.length });
  }
  return { map, manifest };
}

function parseArgs(argv) {
  const o = { spec: path.join(REPO_ROOT, "specs-eval", "golden-merge.json"),
              out: path.join(REPO_ROOT, "artifacts", "preview", "merge.html"),
              locale: "", minify: true };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--spec") o.spec = path.resolve(argv[++i]);
    else if (a === "--out") o.out = path.resolve(argv[++i]);
    else if (a === "--locale") o.locale = argv[++i];
    else if (a === "--no-minify") o.minify = false;
    else throw new Error(`未知参数：${a}`);
  }
  return o;
}

/** 防 </script> 提前闭合与 HTML 注释边界（坑 7）：`<`/`>`/U+2028/U+2029 转义。 */
function escapeForInlineScript(json) {
  return json.replace(/</g, "\\u003c").replace(/>/g, "\\u003e").replace(/\u2028/g, "\\u2028").replace(/\u2029/g, "\\u2029");
}

async function main() {
  const o = parseArgs(process.argv.slice(2));
  const specRaw = readFileSync(o.spec, "utf8");
  const spec = JSON.parse(specRaw);

  if (copyVendorEngine()) {
    console.log("[tmpl-merge] 引擎母本已字节复制 → src/vendor/engine.js（sha256 锚定一致）");
  }

  const result = await build({
    entryPoints: [path.join(PKG_DIR, "src", "main.ts")],
    bundle: true,
    format: "iife",
    target: ["es2019"],
    minify: o.minify,
    legalComments: "none",
    write: false,
    logLevel: "warning",
  });
  const js = result.outputFiles[0].text;

  const localeTag = o.locale || (spec.i18n && spec.i18n.defaultLocale) || "en";
  const title = (spec.meta && spec.meta.title) || "Playable";
  const { map: assetMap, manifest } = buildAssetMap(spec, path.dirname(path.resolve(o.spec)));
  const html = `<!doctype html>
<html lang="${localeTag}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
<title>${title}</title>
<style>
  html, body { margin: 0; padding: 0; width: 100%; height: 100%; overflow: hidden; background: #172038; }
  #app { position: fixed; inset: 0; }
  canvas { display: block; }
</style>
</head>
<body>
<div id="app"></div>
<script>window.PF_SPEC=${escapeForInlineScript(JSON.stringify(spec))};window.PF_LOCALE=${JSON.stringify(localeTag)};window.PF_ASSETS=${escapeForInlineScript(JSON.stringify(assetMap))};</script>
<script>${js}</script>
</body>
</html>
`;

  mkdirSync(path.dirname(o.out), { recursive: true });
  writeFileSync(o.out, html, "utf8");
  // 旁车清单：本次构建真实嵌入的素材（零嵌入也写出空清单——"没嵌"本身就是事实）。
  writeFileSync(
    `${o.out}.assets.json`,
    JSON.stringify({ spec: path.basename(o.spec), locale: localeTag, sprites: manifest }, null, 2) + "\n",
    "utf8",
  );
  const kb = (Buffer.byteLength(html, "utf8") / 1024).toFixed(1);
  const embedded = manifest.map((m) => `${m.spriteKey}=${m.path}(${m.bytes}B)`).join(", ") || "无（程序化贴图）";
  console.log(`[tmpl-merge] 素材嵌入: ${embedded}`);
  console.log(`[tmpl-merge] 构建完成: ${o.out} (${kb}KB, spec=${path.basename(o.spec)}, locale=${localeTag})`);
}

main().catch((err) => {
  console.error("[tmpl-merge] 构建失败:", err.message);
  process.exit(1);
});

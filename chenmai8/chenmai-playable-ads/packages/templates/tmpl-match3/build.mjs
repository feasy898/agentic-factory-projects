#!/usr/bin/env node
// tmpl-match3 构建脚本：TS 源码（含中性名引擎 bundle）esbuild 打包为单 IIFE，
// 与 PlayableSpec JSON 一起内联进单个 HTML（零外链、零相对资源引用）。
//
// 用法：
//   node build.mjs [--spec <path>] [--out <path>] [--locale <tag>] [--no-minify]
//
// 默认：--spec specs-eval/golden-match3.json --out artifacts/preview/match3.html
// 产物自包含：贴图由引擎运行时程序化生成，音效为代码内置的 WAV data URI。

import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import process from "node:process";
import { build } from "esbuild";

const PKG_DIR = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(PKG_DIR, "../../..");

function parseArgs(argv) {
  const o = { spec: path.join(REPO_ROOT, "specs-eval", "golden-match3.json"),
              out: path.join(REPO_ROOT, "artifacts", "preview", "match3.html"),
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

function escapeForInlineScript(json) {
  // 防 </script> 提前闭合与 HTML 注释边界
  return json.replace(/</g, "\\u003c").replace(/>/g, "\\u003e").replace(/\u2028/g, "\\u2028").replace(/\u2029/g, "\\u2029");
}

async function main() {
  const o = parseArgs(process.argv.slice(2));
  const specRaw = readFileSync(o.spec, "utf8");
  const spec = JSON.parse(specRaw);

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
  const html = `<!doctype html>
<html lang="${localeTag}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
<title>${title}</title>
<style>
  html, body { margin: 0; padding: 0; width: 100%; height: 100%; overflow: hidden; background: #141b34; }
  #app { position: fixed; inset: 0; }
  canvas { display: block; }
</style>
</head>
<body>
<div id="app"></div>
<script>window.PF_SPEC=${escapeForInlineScript(JSON.stringify(spec))};window.PF_LOCALE=${JSON.stringify(localeTag)};</script>
<script>${js}</script>
</body>
</html>
`;

  mkdirSync(path.dirname(o.out), { recursive: true });
  writeFileSync(o.out, html, "utf8");
  const kb = (Buffer.byteLength(html, "utf8") / 1024).toFixed(1);
  console.log(`[tmpl-match3] 构建完成: ${o.out} (${kb}KB, spec=${path.basename(o.spec)}, locale=${localeTag})`);
}

main().catch((err) => {
  console.error("[tmpl-match3] 构建失败:", err.message);
  process.exit(1);
});

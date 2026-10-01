/**
 * HTML 内联引擎：把模板构建产物（dist/index.html）处理成"全内联"文档。
 *
 * - <script src>  → 内联 <script>（JS 经 esbuild minify）；或按 zip 模式抽取为独立 bundle
 * - <link rel=stylesheet> → 内联 <style>（CSS 经 esbuild minify）
 * - <img>/<audio>/<video>/<source>/<track> 的 src、<link rel=icon> 的 href → data URI
 * - <link rel=stylesheet> 的 CSS 与 <style> 块中的 url(...) → data URI（相对 CSS 文件解析）
 * - 渠道声明的相对运行时脚本（如 mraid.js）注入 <head>（无 scheme，不算外链）
 *
 * 不使用 DOM 库：模板构建产物由我们控制，用严格正则解析并在异常时快速失败。
 */
import { transform } from "esbuild";
import path from "node:path";

import { readText, resolveDistRef, toDataUri } from "./assets.mjs";

const EXTERNAL_URL_RE = /\bhttps?:\/\/[^\s"'<>\\)\]}]+/gi;

function parseAttrs(tagText) {
  const attrs = {};
  const re = /([:@\w.-]+)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+))/g;
  let m;
  while ((m = re.exec(tagText))) {
    attrs[m[1].toLowerCase()] = m[2] ?? m[3] ?? m[4] ?? "";
  }
  return attrs;
}

function escapeRe(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function replaceAttrValue(tagText, attrName, oldValue, newValue) {
  const needle = new RegExp(`(${attrName}\\s*=\\s*)(["'])${escapeRe(oldValue)}\\2`);
  if (!needle.test(tagText)) {
    throw new Error(`内联失败：标签中找不到 ${attrName}="${oldValue}"`);
  }
  return tagText.replace(needle, (_m, head, q) => `${head}${q}${newValue}${q}`);
}

async function minifyJs(code, fromLabel) {
  const r = await transform(code, {
    minify: true,
    target: ["es2017"],
    legalComments: "none",
    sourcefile: fromLabel,
    loader: "js",
  });
  return r.code;
}

async function minifyCss(code, fromLabel) {
  const r = await transform(code, {
    minify: true,
    target: ["es2017"],
    legalComments: "none",
    sourcefile: fromLabel,
    loader: "css",
  });
  return r.code;
}

/** CSS 中的 url(...) 引用 → data URI；相对 baseDir（CSS 文件所在目录）解析，包含于 distRoot。 */
function inlineCssUrls(css, baseDir, distRoot) {
  return css.replace(/url\(\s*(["']?)([^"')]+)\1\s*\)/g, (whole, _q, ref) => {
    const trimmed = ref.trim();
    if (/^(data:|blob:|#)/i.test(trimmed)) return whole;
    const abs = resolveDistRef(distRoot, trimmed, baseDir);
    return `url("${toDataUri(abs, trimmed)}")`;
  });
}

async function replaceAsync(str, re, fn) {
  const jobs = [];
  str.replace(re, (...args) => {
    jobs.push(fn(...args));
    return "";
  });
  const done = await Promise.all(jobs);
  let i = 0;
  return str.replace(re, () => done[i++]);
}

/**
 * @param {string} htmlPath dist 入口 HTML 绝对路径
 * @param {string} distRoot dist 根目录（HTML 内相对引用的基准）
 * @param {object} opts
 *   - mode: "inline-script"（单 HTML 渠道）| "extract-script"（zip 渠道）
 *   - bundleName: extract 模式下的合并脚本名（默认 build.js）
 *   - minify: 是否用 esbuild 压缩（默认 true）
 *   - injectScripts: 渠道声明注入的相对运行时脚本（如 ["mraid.js"]）
 *   - entryLabel: 报错时显示的入口名
 *
 * 返回 { html, scripts, warnings }：
 *   scripts = 文档顺序的外链脚本 [{ ref, code }]（extract 模式用于合并成 bundle）。
 */
export async function processHtml(htmlPath, distRoot, opts = {}) {
  const mode = opts.mode || "inline-script";
  const bundleName = opts.bundleName || "build.js";
  const minify = opts.minify !== false;
  const warnings = [];
  const entryLabel = opts.entryLabel || "index.html";
  let html = readText(htmlPath, entryLabel);

  // 1) <link>：样式表内联为 <style>，图标 href 转 data URI
  html = await replaceAsync(html, /<link\b[^>]*>/gi, async (tag) => {
    const attrs = parseAttrs(tag);
    const rel = (attrs.rel || "").toLowerCase();
    if (rel === "stylesheet" && attrs.href) {
      const abs = resolveDistRef(distRoot, attrs.href);
      let css = readText(abs, attrs.href);
      css = inlineCssUrls(css, path.dirname(abs), distRoot);
      if (minify) css = await minifyCss(css, attrs.href);
      return `<style data-pf="${attrs.href}">${css}</style>`;
    }
    if (attrs.href && /^(icon|shortcut icon|apple-touch-icon)$/.test(rel) && !/^(data:|blob:)/i.test(attrs.href)) {
      const abs = resolveDistRef(distRoot, attrs.href);
      return replaceAttrValue(tag, "href", attrs.href, toDataUri(abs, attrs.href));
    }
    return tag;
  });

  // 2) 媒体元素 src → data URI
  html = await replaceAsync(html, /<(img|source|audio|video|track)\b[^>]*>/gi, async (tag) => {
    const attrs = parseAttrs(tag);
    if (attrs.src && !/^(data:|blob:)/i.test(attrs.src)) {
      const abs = resolveDistRef(distRoot, attrs.src);
      tag = replaceAttrValue(tag, "src", attrs.src, toDataUri(abs, attrs.src));
    }
    if (attrs.srcset) {
      warnings.push(`srcset 暂不支持内联（${attrs.srcset.slice(0, 60)}），请改用单 src`);
    }
    return tag;
  });

  // 3) <style> 块内的 url(...)（相对 dist 根解析）+ 压缩
  html = await replaceAsync(html, /(<style\b[^>]*>)([\s\S]*?)(<\/style>)/gi, async (_m, open, css, close) => {
    let done = inlineCssUrls(css, distRoot);
    if (minify) done = await minifyCss(done, "inline-style");
    return open + done + close;
  });

  // 4) 收集文档顺序的脚本标签（外链 + 内联）
  const scriptTags = [];
  html.replace(/<script\b([^>]*)>([\s\S]*?)<\/script>/gi, (tag, attrPart) => {
    scriptTags.push({ tag, attrs: parseAttrs(`<x ${attrPart}>`) });
    return tag;
  });
  const externalTags = scriptTags.filter((s) => s.attrs.src);
  const hasModule = externalTags.some((s) => (s.attrs.type || "").toLowerCase() === "module");
  if (hasModule) {
    warnings.push("存在 type=module 的外链脚本：合并/内联为经典脚本后 import/export 不可用，请确认 dist 产物是自包含 bundle");
  }

  // 收集外链脚本内容（文档顺序；两种模式都要）
  const scripts = [];
  for (const s of externalTags) {
    const abs = resolveDistRef(distRoot, s.attrs.src);
    let code = readText(abs, s.attrs.src);
    if (minify) code = await minifyJs(code, s.attrs.src);
    scripts.push({ ref: s.attrs.src, code });
  }

  if (mode === "extract-script") {
    const merged = scripts.map((s) => s.code).join("\n;\n");
    const bundleCode = merged || "/* pf-packager: dist 内无外链脚本，生成空 bundle 以保持渠道包结构 */";
    if (scripts.length === 0) warnings.push("dist 内没有外链 <script>，build.js 为空占位");
    let seen = 0;
    html = html.replace(/<script\b([^>]*)>([\s\S]*?)<\/script>/gi, (tag, attrPart) => {
      const attrs = parseAttrs(`<x ${attrPart}>`);
      if (!attrs.src) return tag; // HTML 内联脚本保持原位
      seen += 1;
      if (seen === 1) {
        const typeAttr = attrs.type ? ` type="${attrs.type}"` : "";
        return `<script${typeAttr} src="${bundleName}"></script>`;
      }
      return `<!-- pf-packager: ${attrs.src} merged into ${bundleName} -->`;
    });
  } else {
    // inline-script：外链脚本就地内联
    let i = 0;
    html = html.replace(/<script\b([^>]*)>([\s\S]*?)<\/script>/gi, (tag, attrPart) => {
      const attrs = parseAttrs(`<x ${attrPart}>`);
      if (!attrs.src) return tag;
      const code = scripts[i++]?.code;
      if (code === undefined) throw new Error("脚本收集与替换数量不一致（内部错误）");
      const typeAttr = attrs.type ? ` type="${attrs.type}"` : "";
      return `<script${typeAttr} data-pf="${attrs.src}">${code}</script>`;
    });
    if (i !== scripts.length) throw new Error("脚本收集与替换数量不一致（内部错误）");
  }

  // 5) 渠道声明的相对运行时脚本注入（如 mraid.js，由渠道容器在投放时提供，非外链）
  for (const name of opts.injectScripts || []) {
    if (!new RegExp(`src\\s*=\\s*["']${escapeRe(name)}`).test(html)) {
      html = html.replace(/<head(\s[^>]*)?>/i, (m) => `${m}\n<script src="${name}"></script>`);
    }
  }

  // 6) 保证 <meta charset>（多语言文案与内联内容需要 UTF-8）
  if (!/<meta[^>]+charset/i.test(html)) {
    html = html.replace(/<head(\s[^>]*)?>/i, (m) => `${m}\n<meta charset="utf-8">`);
  }

  return { html, scripts, warnings };
}

/**
 * MRAID 禁用渠道（如 meta）的启发式检测（按调用形态，不按全词出现）。
 *
 * 含运行时桥的模板产物必然携带 mraid 的"探测代码"（`typeof x.mraid`、`x.mraid?"
 * applovin":"preview"` 之类）——那是为避免在无 mraid 环境误调用而存在的，文本上
 * 无法与依赖分开，却会让任何真实游戏都打不出 meta 包。因此只把两类"真使用"视作
 * 违规：① 对 mraid.js 脚本的引用（src/字符串）；② `mraid.<方法>` 形态的 API 调用。
 * 已知局限（启发式即不完备）：经别名转手后调用（`var m=window.mraid;m.open()`)
 * 不落在 ② 的形态上，声明为启发式的固有盲区。
 */
export function findMraidReferences(text) {
  const hits = [];
  const re = /\bmraid(?:\s*\.\s*[A-Za-z_$][\w$]*|(?:\.js)\b)/gi;
  for (const m of text.matchAll(re)) hits.push(m[0].trim());
  return hits;
}

/**
 * 外链扫描：找出文本中所有 http(s) URL。
 * allowedWhitelist: 允许出现的 URL 前缀（如 spec 的 landingUrl）。
 * 返回违规清单 [{ url, context }]；空数组 = 通过。
 */
export function scanExternalUrls(text, allowedWhitelist = []) {
  const violations = [];
  for (const m of text.matchAll(EXTERNAL_URL_RE)) {
    const url = m[0];
    const allowed = allowedWhitelist.some((w) => url === w || url.startsWith(w));
    if (!allowed) {
      const start = Math.max(0, m.index - 40);
      violations.push({ url, context: text.slice(start, m.index + url.length + 20).replace(/\s+/g, " ") });
    }
  }
  return violations;
}

/**
 * HTML 内联引擎（spec §3.3 识别写法精确清单，冻结；严格正则、异常即失败）。
 *
 * 基准：HTML 内相对引用以所在目录解析（CSS 内 url() 相对 CSS 文件、<style> 块内相对
 * dist 根）；包含性检查针对 dist 根。带 scheme / 协议相对 / 根相对 / 逃逸出 dist 根
 * 的引用一律快速失败（宁失败不出超规包）。
 */
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";
import { realpathSync } from "node:fs";

// esbuild 为工作区提供（钉版 0.28.2）；经 realpath 解析，跨 junction 复制布局也稳定。
const require = createRequire(realpathSync(fileURLToPath(import.meta.url)));
const esbuild = require("esbuild");

const MIME_BY_EXT = new Map([
  ["png", "image/png"], ["jpg", "image/jpeg"], ["jpeg", "image/jpeg"], ["gif", "image/gif"],
  ["webp", "image/webp"], ["svg", "image/svg+xml"], ["ico", "image/x-icon"], ["bmp", "image/bmp"],
  ["mp3", "audio/mpeg"], ["ogg", "audio/ogg"], ["wav", "audio/wav"], ["m4a", "audio/mp4"], ["aac", "audio/aac"],
  ["mp4", "video/mp4"], ["webm", "video/webm"], ["mov", "video/quicktime"],
  ["ttf", "font/ttf"], ["otf", "font/otf"], ["woff", "font/woff"], ["woff2", "font/woff2"],
]);

const SCHEME_RE = /^[A-Za-z][A-Za-z0-9+.-]*:/;

export function isSkippableRef(ref) {
  return /^(data:|blob:|#)/i.test(ref);
}

/** 解析 dist 内相对引用 → 绝对路径；违规写法快速失败。 */
export function resolveDistRef(ref, baseDir, distRoot) {
  if (typeof ref !== "string" || ref.trim() === "") throw new Error(`空引用（来源基准 ${baseDir}）`);
  if (SCHEME_RE.test(ref)) throw new Error(`不允许带 scheme 的引用: "${ref}"`);
  if (ref.startsWith("//")) throw new Error(`不允许协议相对引用: "${ref}"`);
  if (ref.startsWith("/")) throw new Error(`不允许根相对引用: "${ref}"`);
  const abs = path.resolve(baseDir, ref);
  const rel = path.relative(distRoot, abs);
  if (rel === "" || rel.startsWith("..") || path.isAbsolute(rel)) {
    throw new Error(`引用逃逸出 dist 根: "${ref}"`);
  }
  return abs;
}

export function toDataUri(absPath) {
  const ext = path.extname(absPath).slice(1).toLowerCase();
  const mime = MIME_BY_EXT.get(ext);
  if (!mime) throw new Error(`未知资源类型，拒绝内联: ${absPath}`);
  return `data:${mime};base64,${readFileSync(absPath).toString("base64")}`;
}

export function inlineCssUrls(cssText, cssDir, distRoot) {
  return cssText.replace(/url\(\s*(['"]?)([^'")]*)\1\s*\)/gi, (m, q, ref) => {
    const t = ref.trim();
    if (t === "" || isSkippableRef(t)) return m;
    return `url(${q}${toDataUri(resolveDistRef(t, cssDir, distRoot))}${q})`;
  });
}

export async function minifyCss(css) {
  return (await esbuild.transform(css, { minify: true, loader: "css", legalComments: "none" })).code;
}

export async function minifyJs(code) {
  return (await esbuild.transform(code, { minify: true, target: "es2017", legalComments: "none" })).code;
}

function getAttr(s, name) {
  const m = new RegExp(`\\b${name}\\s*=\\s*(?:"([^"]*)"|'([^']*)'|([^\\s>]+))`, "i").exec(s);
  if (!m) return null;
  const v = m[1] !== undefined ? m[1] : m[2] !== undefined ? m[2] : m[3];
  return v;
}

function setAttr(tag, name, value) {
  const re = new RegExp(`\\b${name}\\s*=\\s*(?:"[^"]*"|'[^']*'|[^\\s>]+)`, "i");
  if (re.test(tag)) return tag.replace(re, `${name}="${value}"`);
  return tag.replace(/^<([A-Za-z][A-Za-z0-9]*)/, (_m, t) => `<${t} ${name}="${value}"`);
}

function escapeRegExp(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

async function replaceAsync(str, re, fn) {
  const parts = [];
  let last = 0;
  re.lastIndex = 0;
  for (let m; (m = re.exec(str)); ) {
    parts.push(str.slice(last, m.index));
    parts.push(await fn(...m));
    last = m.index + m[0].length;
    if (m[0].length === 0) re.lastIndex++;
  }
  parts.push(str.slice(last));
  return parts.join("");
}

/**
 * 处理入口 HTML。
 * @param {object} o
 * @param {string} o.html            原始 HTML 文本
 * @param {string} o.distRoot        基准 dist 根（含性检查与 <style> 块 url() 基准）
 * @param {string} o.baseDir         HTML 所在目录（相对引用基准）
 * @param {"inline"|"extract"} o.mode single-html → inline；zip 渠道 → extract
 * @param {string} [o.bundleName]    extract 模式的 bundle 文件名（structure[0]）
 * @param {string[]} o.injectScripts 渠道 runtime.injectRelativeScripts
 * @param {boolean} o.minify         false = --no-minify
 * @param {string[]} o.warnings      告警收集器（mutate）
 * @returns {Promise<{html: string, scripts: {src: string, code: string}[]}>}
 *          scripts = 外链脚本按文档顺序（已压缩）；extract 模式调用方负责合并成 bundle。
 */
export async function processHtml({ html, distRoot, baseDir, mode, bundleName, injectScripts, minify, warnings }) {
  if (mode === "extract" && !bundleName) throw new Error("extract 模式缺 bundleName");

  // <head> 缺 charset → 自动补（须有 <head> 才动刀）。
  if (!/<meta[^>]*charset/i.test(html)) {
    if (!/<head\b[^>]*>/i.test(html)) throw new Error("HTML 缺少 <head>，无法补 charset");
    html = html.replace(/<head\b[^>]*>/i, (m) => `${m}\n  <meta charset="utf-8">`);
  }

  // <style> 块：url() 相对 dist 根 → data URI，整块压缩。
  html = await replaceAsync(html, /(<style\b[^>]*>)([\s\S]*?)(<\/style>)/gi, async (_m, open, body, close) => {
    const withUris = inlineCssUrls(body, distRoot, distRoot);
    return open + (minify ? await minifyCss(withUris) : withUris) + close;
  });

  // <link rel="stylesheet"> → <style data-pf>；icon 类 href → data URI。
  html = await replaceAsync(html, /<link\b[^>]*>/gi, async (tag) => {
    const rel = getAttr(tag, "rel");
    const href = getAttr(tag, "href");
    if (rel === null || href === null) return tag;
    const relL = rel.trim().toLowerCase();
    if (relL === "stylesheet") {
      const abs = resolveDistRef(href, baseDir, distRoot);
      let css = readFileSync(abs, "utf8");
      css = inlineCssUrls(css, path.dirname(abs), distRoot); // CSS 内 url() 相对 CSS 文件
      if (minify) css = await minifyCss(css);
      return `<style data-pf="${href}">${css}</style>`;
    }
    if (relL === "icon" || relL === "shortcut icon" || relL === "apple-touch-icon") {
      if (isSkippableRef(href)) return tag;
      return setAttr(tag, "href", toDataUri(resolveDistRef(href, baseDir, distRoot)));
    }
    return tag;
  });

  // <img|source|audio|video|track src> → data URI；srcset 不支持内联（告警）。
  html = await replaceAsync(html, /<(img|source|audio|video|track)\b[^>]*>/gi, (tag) => {
    if (/\bsrcset\s*=/i.test(tag)) {
      warnings.push(`srcset 不支持内联，要求改单 src（标签: ${tag.slice(0, 80)}）`);
    }
    const src = getAttr(tag, "src");
    if (src === null || isSkippableRef(src)) return tag;
    return setAttr(tag, "src", toDataUri(resolveDistRef(src, baseDir, distRoot)));
  });

  // <script src>：inline 模式就地内联；extract 模式首 → bundle 引用、余 → 注释。
  const scripts = [];
  let firstExternal = true;
  html = await replaceAsync(html, /<script\b([^>]*)>([\s\S]*?)<\/script>/gi, async (_m, attrs, body) => {
    const src = getAttr(attrs, "src");
    if (src === null) return _m; // 已内联脚本原样保留
    if (isSkippableRef(src)) return _m;
    if (injectScripts.includes(src)) return _m; // 渠道相对注入脚本（如 mraid.js），保留原样
    if (body.trim() !== "") throw new Error(`<script> 同时含 src 与内联内容，拒绝: ${src}`);
    const type = getAttr(attrs, "type");
    if (type && type.trim().toLowerCase() === "module") {
      warnings.push(`type=module 外链脚本合并为经典脚本后 import/export 不可用: ${src}`);
    }
    const abs = resolveDistRef(src, baseDir, distRoot);
    let code = readFileSync(abs, "utf8");
    if (minify) code = await minifyJs(code);
    scripts.push({ src, code });
    if (mode === "inline") {
      const typeAttr = type ? ` type="${type}"` : "";
      return `<script${typeAttr} data-pf="${src}">${code}</script>`;
    }
    if (firstExternal) {
      firstExternal = false;
      return `<script src="${bundleName}"></script>`;
    }
    return `<!-- pf-packager: ${src} merged into ${bundleName} -->`;
  });
  if (mode === "extract" && scripts.length === 0) {
    throw new Error("extract 模式（zip 渠道）要求 dist 至少含一个外链 <script src>");
  }

  // 渠道 injectRelativeScripts：<head> 后注入（无 scheme，外链扫描不算外链；已存在不重复）。
  for (const s of injectScripts) {
    const present = new RegExp(`<script\\b[^>]*\\bsrc\\s*=\\s*["']${escapeRegExp(s)}["']`, "i").test(html);
    if (!present) {
      if (!/<head\b[^>]*>/i.test(html)) throw new Error("HTML 缺少 <head>，无法注入渠道脚本");
      html = html.replace(/<head\b[^>]*>/i, (m) => `${m}<script src="${s}"></script>`);
    }
  }

  // 残留守卫：除渠道注入脚本与 extract 模式自身插入的 bundle 引用外，不得有未处理的外链脚本。
  const allowedLeftovers = new Set([...injectScripts, ...(mode === "extract" ? [bundleName] : [])]);
  for (const m of html.matchAll(/<script\b[^>]*\bsrc\s*=\s*["']([^"']+)["'][^>]*>/gi)) {
    const src = m[1];
    if (!allowedLeftovers.has(src) && !isSkippableRef(src)) {
      throw new Error(`未内联的外链脚本残留: ${src}`);
    }
  }

  return { html, scripts };
}

/**
 * 外链扫描（spec §3.3）：正则大小写不敏感，白名单 = spec landingUrl + 规则 allowedUrlWhitelist，
 * 前缀匹配。命中（白名单外）返回 URL 列表，调用方构建失败。
 */
export function scanExternalUrls(text, whitelist) {
  const found = [...text.matchAll(/\bhttps?:\/\/[^\s"'<>\\)\]}]+/gi)].map((m) => m[0]);
  return found.filter((u) => !whitelist.some((w) => u === w || u.startsWith(w)));
}

/** MRAID 禁用扫描（spec §3.3 启发式；大小写不敏感比冻结断言更严，只严不松）。 */
export function scanMraid(text) {
  const m = /\bmraid\b[^;]{0,40}/i.exec(text);
  return m ? m[0] : null;
}

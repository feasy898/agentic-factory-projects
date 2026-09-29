/**
 * HTML 内联引擎（spec packager.md §3.3"识别写法精确清单"，冻结）。
 *
 * - <link rel=stylesheet> → <style data-pf="<原href>">，CSS 内 url(...) 先转 data URI 再压缩
 * - <link rel=icon|shortcut icon|apple-touch-icon> href → data URI（已是 data:/blob: 则跳过）
 * - <img|source|audio|video|track src> → data URI；srcset 不支持内联（告警）
 * - <style> 块内 url(...) 相对 dist 根解析转 data URI，整块压缩
 * - <script src>：inline 模式就地内联为 <script type?> data-pf="<原src>">；
 *   extract 模式（zip 渠道）第一个外链脚本位置替换为 <script src="<bundleName>">，
 *   其余替换为 <!-- pf-packager: x merged into y -->，脚本按文档顺序 "\n;\n" 合并
 * - <head> 缺 charset 自动补 <meta charset="utf-8">
 * - 渠道 injectRelativeScripts（如 mraid.js）注入 <head> 开标签之后（已存在则不重复注入）
 *
 * 不用 DOM 库：严格正则解析，异常即失败是设计行为（dist 产物标签写法须规整）。
 * 压缩：esbuild transform（minify、target es2017、legalComments none）；--no-minify 跳过。
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

/** CSS 中的 url(...) → data URI；相对 baseDir 解析，包含于 distRoot。 */
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
 * @param {string} distRoot dist 根目录（HTML 内相对引用的基准；HTML 相对引用基准 =
 *   所在目录，包含性检查针对 dist 根）
 * @param {object} opts
 *   - mode: "inline-script"（单 HTML 渠道）| "extract-script"（zip 渠道）
 *   - bundleName: extract 模式下的合并脚本名（默认 build.js）
 *   - minify: 是否 esbuild 压缩（默认 true）
 *   - injectScripts: 渠道声明注入的相对运行时脚本（如 ["mraid.js"]）
 *   - entryLabel: 报错时显示的入口名
 * 返回 { html, scripts, warnings }；scripts = 文档顺序外链脚本 [{ ref, code }]。
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

  // 2) 媒体元素 src → data URI（srcset 不支持内联，告警要求改单 src）
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

  // 3) <style> 块内的 url(...)（相对 dist 根解析）+ 整块压缩
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
  if (externalTags.some((s) => (s.attrs.type || "").toLowerCase() === "module")) {
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

  // 5) 渠道声明的相对运行时脚本注入（如 mraid.js）：插到 <head…> 开标签之后；
  //    已引用（src\s*=\s*["']mraid.js）则不重复注入。相对引用无 scheme，不算外链。
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
 * MRAID 禁用渠道（meta）的检测：实现真实调用形态正则（spec §3.3，gi）——
 * `mraid.<方法>` 的 API 调用形态、或对 mraid.js 脚本的引用。命中即失败。
 * 有意收窄不按全词出现判定：含运行时桥的模板产物必然携带 mraid 探测代码
 * （typeof x.mraid 之类），按全词判定一切真实游戏都打不出 meta 包。
 * 已知盲区（启发式固有）：别名转手后调用（var m=window.mraid;m.open()）不落
 * 调用形态；本检查只拦"文本可辨的真使用"。
 */
export function findMraidReferences(text) {
  const hits = [];
  const re = /\bmraid(?:\s*\.\s*[A-Za-z_$][\w$]*|(?:\.js)\b)/gi;
  for (const m of text.matchAll(re)) hits.push(m[0].trim());
  return hits;
}

/**
 * 外链扫描：找出文本中所有 http(s) URL（大小写不敏感）。
 * allowedWhitelist: 允许出现的 URL 前缀（spec flow.endScreen.landingUrl +
 * 规则 allowedTextUrls + 渠道 allowedUrlWhitelist，由调用方合并传入）。
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

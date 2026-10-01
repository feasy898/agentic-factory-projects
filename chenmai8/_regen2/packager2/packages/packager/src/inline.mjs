/**
 * HTML 内联引擎（spec packager.md §3.3，冻结）。
 * 严格正则、不用 DOM 库：dist 产物标签写法须规整；异常即失败是设计行为。
 *
 * 识别写法精确清单：
 * - <link rel="stylesheet" href>          → <style data-pf="<原href>">；CSS 内 url() 先转 data URI 再压缩
 * - <link rel="icon|shortcut icon|apple-touch-icon" href> → href → data URI（data:/blob: 跳过）
 * - <img|source|audio|video|track src>    → src → data URI；srcset 不支持内联（告警）
 * - <style> 块内 url(...)                  → 相对 dist 根解析；整块压缩
 * - <script src>                          → inline 模式就地内联为 <script type? data-pf="<原src>">；
 *                                           extract 模式首个外链脚本位置换 <script src="<bundleName>"></script>，
 *                                           其余换 <!-- pf-packager: x merged into y -->，
 *                                           全部脚本按文档顺序 "\n;\n" 合并成 bundle（原文交调用方压缩）
 * - <head> 缺 charset                      → 补 <meta charset="utf-8">
 * - injectRelativeScripts（如 mraid.js）   → <head> 开标签之后注入 <script src="mraid.js"></script>；
 *                                           已存在（src="mraid.js"）不重复；相对引用无 scheme 不算外链
 *
 * resolveDistRef 拒绝（快速失败）：带 scheme（http(s)://…）、协议相对 //、根相对 /、逃逸出 dist 根。
 */

import { readFileSync } from "node:fs";
import path from "node:path";

const MIME = {
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".gif": "image/gif",
  ".svg": "image/svg+xml",
  ".webp": "image/webp",
  ".ico": "image/x-icon",
  ".bmp": "image/bmp",
  ".avif": "image/avif",
  ".mp3": "audio/mpeg",
  ".ogg": "audio/ogg",
  ".wav": "audio/wav",
  ".m4a": "audio/mp4",
  ".mp4": "video/mp4",
  ".webm": "video/webm",
  ".woff": "font/woff",
  ".woff2": "font/woff2",
  ".ttf": "font/ttf",
  ".otf": "font/otf",
};

export function escapeRegExp(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** 属性解析：name=value（双引号/单引号/裸值）→ Map（键小写，值保留原文）。 */
export function parseAttrs(tagBody) {
  const attrs = new Map();
  const re = /([^\s"'>/=]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'`=<>]+)))?/g;
  let m;
  while ((m = re.exec(tagBody)) !== null) {
    const name = m[1].toLowerCase();
    const value = m[2] !== undefined ? m[2] : m[3] !== undefined ? m[3] : m[4] !== undefined ? m[4] : "";
    if (!attrs.has(name)) attrs.set(name, value);
  }
  return attrs;
}

/**
 * 解析 dist 内相对引用（快速失败）。
 * fromRel: 引用方所在目录（相对 distRoot 的 posix 相对路径，根为 ""）。
 * 返回 { abs, rel }：dist 内绝对路径与相对路径（posix）。
 */
export function resolveDistRef(ref, fromRel, distRoot) {
  if (typeof ref !== "string" || ref.length === 0) {
    throw new Error(`空的 dist 引用（来自 ${fromRel || "."}）`);
  }
  if (/^[A-Za-z][A-Za-z0-9+.-]*:/.test(ref)) {
    throw new Error(`拒绝带 scheme 的引用 "${ref}"（来自 ${fromRel || "."}）——dist 必须自包含`);
  }
  if (ref.startsWith("//")) {
    throw new Error(`拒绝协议相对引用 "${ref}"（来自 ${fromRel || "."}）`);
  }
  if (ref.startsWith("/")) {
    throw new Error(`拒绝根相对引用 "${ref}"（来自 ${fromRel || "."}）`);
  }
  const relPosix = path.posix.normalize(
    path.posix.join(fromRel.replaceAll(path.sep, "/"), ref.replaceAll(path.sep, "/")),
  );
  if (relPosix === ".." || relPosix.startsWith("../")) {
    throw new Error(`引用 "${ref}" 逃逸出 dist 根（来自 ${fromRel || "."}）`);
  }
  const abs = path.join(distRoot, ...relPosix.split("/"));
  return { abs, rel: relPosix };
}

/** 读 dist 内文件并转 data URI。 */
export function toDataUri(absPath) {
  const ext = path.extname(absPath).toLowerCase();
  const mime = MIME[ext] || "application/octet-stream";
  const buf = readFileSync(absPath);
  return `data:${mime};base64,${buf.toString("base64")}`;
}

/** CSS 文本内 url(...) 相对 baseRel 解析转 data URI（data:/blob: 跳过）。 */
export function inlineCssUrls(css, baseRel, distRoot) {
  return css.replace(/url\(\s*('([^']*)'|"([^"]*)"|([^)'"]*))\s*\)/gi, (whole, _g1, sq, dq, bare) => {
    const raw = (sq !== undefined ? sq : dq !== undefined ? dq : bare !== undefined ? bare : "").trim();
    if (raw.length === 0) return whole;
    if (/^(data:|blob:)/i.test(raw)) return whole;
    const quote = sq !== undefined ? "'" : dq !== undefined ? '"' : "";
    const { abs } = resolveDistRef(raw, baseRel, distRoot);
    return `url(${quote}${toDataUri(abs)}${quote})`;
  });
}

function headOpenRe() {
  return /<head\b[^>]*>/i;
}

/** <head> 开标签之后：补 charset（缺时）+ 注入 injectRelativeScripts（已存在不重复）。 */
export function injectIntoHead(html, injectList, warnings) {
  const m = html.match(headOpenRe());
  if (!m) throw new Error("HTML 缺 <head> 开标签（严格正则引擎要求产物写法规整）");
  let insert = "";
  if (!/<meta[^>]*charset/i.test(html)) {
    insert += '<meta charset="utf-8">';
  }
  for (const name of injectList || []) {
    const exists = new RegExp(`src\\s*=\\s*["']${escapeRegExp(name)}`).test(html);
    if (!exists) {
      insert += `<script src="${name}"></script>`;
    } else {
      warnings.push(`${name} 已被引用，不重复注入`);
    }
  }
  if (insert.length === 0) return html;
  const at = m.index + m[0].length;
  return html.slice(0, at) + insert + html.slice(at);
}

/** <link rel="stylesheet" href> → <style data-pf="<原href>">（CSS url() 转 data URI 后整块压缩）。 */
async function inlineStylesheetLinks(html, ctx) {
  const linkRe = /<link\b[^>]*>/gi;
  const tasks = [];
  let m;
  while ((m = linkRe.exec(html)) !== null) {
    const tag = m[0];
    const attrs = parseAttrs(tag.slice(5, -1));
    const rel = (attrs.get("rel") || "").trim().toLowerCase();
    const href = attrs.get("href");
    if (rel === "stylesheet" && href !== undefined) {
      tasks.push({ tag, href });
    }
  }
  for (const t of tasks) {
    const { abs } = resolveDistRef(t.href, ctx.baseRel, ctx.distRoot);
    let css = readFileSync(abs, "utf8");
    // CSS 内 url() 相对 CSS 文件所在目录（locale 基准切换时 = <baseRel>/<cssDir>）
    const cssDir = path.posix.dirname(t.href.replaceAll(path.sep, "/"));
    const cssBase = path.posix.join(ctx.baseRel, cssDir === "." ? "" : cssDir);
    css = inlineCssUrls(css, cssBase, ctx.distRoot);
    css = await ctx.minifyCss(css);
    const replacement = `<style data-pf="${t.href}">${css}</style>`;
    if (!html.includes(t.tag)) throw new Error(`内联时标签丢失: ${t.tag}`);
    html = html.replace(t.tag, () => replacement);
  }
  return html;
}

/** <link rel="icon|shortcut icon|apple-touch-icon" href> → href 换 data URI（data:/blob: 跳过）。 */
function inlineIconLinks(html, ctx) {
  return html.replace(/<link\b[^>]*>/gi, (tag) => {
    const attrs = parseAttrs(tag.slice(5, -1));
    const rel = (attrs.get("rel") || "").trim().toLowerCase();
    if (!["icon", "shortcut icon", "apple-touch-icon"].includes(rel)) return tag;
    const href = attrs.get("href");
    if (href === undefined || /^(data:|blob:)/i.test(href)) return tag;
    const { abs } = resolveDistRef(href, ctx.baseRel, ctx.distRoot);
    return tag.replace(/href\s*=\s*("([^"]*)"|'([^']*)')/i, () => `href="${toDataUri(abs)}"`);
  });
}

/** <img|source|audio|video|track src> → data URI；srcset 告警跳过。 */
function inlineMediaSrc(html, ctx) {
  return html.replace(/<(img|source|audio|video|track)\b[^>]*>/gi, (tag) => {
    if (/\bsrcset\s*=/i.test(tag)) {
      ctx.warnings.push(`srcset 不支持内联，要求改单 src: ${tag.slice(0, 60)}`);
      return tag;
    }
    const m = tag.match(/\bsrc\s*=\s*("([^"]*)"|'([^']*)')/i);
    if (!m) return tag;
    const src = m[2] !== undefined ? m[2] : m[3];
    if (/^(data:|blob:)/i.test(src)) return tag;
    const { abs } = resolveDistRef(src, ctx.baseRel, ctx.distRoot);
    return tag.replace(m[0], () => `src="${toDataUri(abs)}"`);
  });
}

/** <style> 块内 url(...) 相对 dist 根；整块压缩。 */
async function inlineStyleBlocks(html, ctx) {
  const styleRe = /<style\b[^>]*>([\s\S]*?)<\/style>/gi;
  const tasks = [];
  let m;
  while ((m = styleRe.exec(html)) !== null) {
    tasks.push({ whole: m[0], body: m[1] });
  }
  for (const t of tasks) {
    const processed = inlineCssUrls(t.body, ctx.baseRel, ctx.distRoot);
    const replacement = t.whole.replace(t.body, () => processed);
    html = html.replace(t.whole, () => replacement);
  }
  return html;
}

/**
 * 外链 <script src> 收集与替换。
 * - injectList 中的运行时相对脚本（如 mraid.js）跳过（保持相对外链——允许，且不算外链）。
 * - inline 模式：逐个读盘压缩后就地内联为 <script type? data-pf="<原src>">。
 * - extract 模式：全部按文档顺序 "\n;\n" 合并为 bundle 原文（调用方压缩）；
 *   首个位置换 <script src="<bundleName>"></script>，其余换 <!-- pf-packager: x merged into y -->。
 */
async function processScripts(html, ctx) {
  const scriptRe = /<script\b([^>]*)>([\s\S]*?)<\/script>/gi;
  const found = [];
  let m;
  while ((m = scriptRe.exec(html)) !== null) {
    const attrs = parseAttrs(m[1]);
    const src = attrs.get("src");
    if (src === undefined) continue; // 内联脚本块，不动
    if ((ctx.injectList || []).includes(src)) continue; // 渠道运行时脚本：保持原样
    if (m[2].trim() !== "") {
      throw new Error(`外链 script 标签含内联体（${src}）——产物写法规整性破坏`);
    }
    if ((attrs.get("type") || "").trim().toLowerCase() === "module") {
      ctx.warnings.push(`type=module 外链脚本（${src}）合并为经典脚本后 import/export 不可用`);
    }
    found.push({ whole: m[0], src, type: attrs.get("type") });
  }
  if (found.length === 0) return { html, bundle: null };

  const readScript = (srcRef) => {
    const { abs } = resolveDistRef(srcRef, ctx.baseRel, ctx.distRoot);
    return readFileSync(abs, "utf8");
  };

  if (ctx.mode === "extract") {
    const bundleName = ctx.bundleName;
    const merged = found.map((s) => readScript(s.src)).join("\n;\n");
    let first = true;
    for (const s of found) {
      const replacement = first
        ? `<script src="${bundleName}"></script>`
        : `<!-- pf-packager: ${s.src} merged into ${bundleName} -->`;
      first = false;
      if (!html.includes(s.whole)) throw new Error(`替换时脚本标签丢失: ${s.src}`);
      html = html.replace(s.whole, () => replacement);
    }
    return { html, bundle: merged };
  }

  // inline 模式
  for (const s of found) {
    const code = await ctx.minifyJs(readScript(s.src));
    const typeAttr = s.type !== undefined && s.type.trim() !== "" ? ` type="${s.type}"` : "";
    const replacement = `<script${typeAttr} data-pf="${s.src}">${code}</script>`;
    if (!html.includes(s.whole)) throw new Error(`内联时脚本标签丢失: ${s.src}`);
    html = html.replace(s.whole, () => replacement);
  }
  return { html, bundle: null };
}

/**
 * dist 入口 HTML → 渠道产物文本。
 * 返回 { html, bundle }：bundle 仅 extract 模式非 null（"\n;\n" 合并的脚本原文）。
 */
export async function renderHtml({
  distRoot,
  baseRel,
  channelRule,
  mode,
  bundleName,
  warnings,
  minifyJs,
  minifyCss,
}) {
  const entryRel = path.posix.join(baseRel, "index.html");
  const entryAbs = path.join(distRoot, ...entryRel.split("/"));
  let html;
  try {
    html = readFileSync(entryAbs, "utf8");
  } catch (err) {
    throw new Error(`dist 缺入口 index.html（查找 ${entryAbs}）`);
  }

  const ctx = {
    distRoot,
    baseRel,
    mode,
    bundleName,
    injectList: channelRule.runtime?.injectRelativeScripts || [],
    warnings,
    minifyJs,
    minifyCss,
  };

  html = injectIntoHead(html, ctx.injectList, warnings);
  html = await inlineStylesheetLinks(html, ctx);
  html = inlineIconLinks(html, ctx);
  html = inlineMediaSrc(html, ctx);
  html = await inlineStyleBlocks(html, ctx);
  const r = await processScripts(html, ctx);
  return { html: r.html, bundle: r.bundle };
}

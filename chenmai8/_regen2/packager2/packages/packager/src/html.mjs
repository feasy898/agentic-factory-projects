/**
 * 渲染管线 + 压缩 + 产物扫描（spec packager.md §3.3，冻结）。
 * - 压缩：esbuild transform（minify、target es2017、legalComments: "none"）；--no-minify 时恒等。
 * - 外链扫描：正则 \bhttps?://[^\s"'<>\\)\]}]+（大小写不敏感）；白名单 = landingUrl 前缀 + 规则白名单。
 * - MRAID 禁用：\bmraid\b[^;]{0,40}，gi 标志（大小写不敏感）；\b 词边界以 [A-Za-z0-9_] 为词字符，
 *   故 MRAID_TEST 这类下划线接续标识符不命中，window.mraid 命中。
 */
import { transform } from "esbuild";

import { renderHtml } from "./inline.mjs";

export function makeMinifiers(noMinify) {
  if (noMinify) {
    return {
      minifyJs: async (code) => code,
      minifyCss: async (code) => code,
    };
  }
  const opts = { minify: true, target: "es2017", legalComments: "none" };
  return {
    minifyJs: async (code) => (await transform(code, { ...opts, loader: "js" })).code,
    minifyCss: async (code) => (await transform(code, { ...opts, loader: "css" })).code,
  };
}

export { renderHtml };

/** 提取文本中全部 http(s) 外链（与冻结自验收 externalUrls() 同一正则）。 */
export function scanExternalUrls(text) {
  return [...text.matchAll(/\bhttps?:\/\/[^\s"'<>\\)\]}]+/gi)].map((m) => m[0]);
}

/** 白名单判定：landingUrl / allowedUrlWhitelist 均按前缀匹配。 */
export function isWhitelisted(url, whitelist) {
  return (whitelist || []).some((w) => typeof w === "string" && w.length > 0 && (url === w || url.startsWith(w)));
}

/** MRAID 全词命中（启发式，gi）。 */
export function findMraid(text) {
  return text.match(/\bmraid\b[^;]{0,40}/gi) || [];
}

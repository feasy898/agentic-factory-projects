/**
 * 规则库（channel-rules.json）加载与结构校验（spec §3.1：结构由 validateRules 强制，
 * 违规直接抛错——打包器不改渠道知识，规则库是唯一规则来源）。
 */
import { readFileSync } from "node:fs";

export function loadRules(rulesPath) {
  let raw;
  try {
    raw = readFileSync(rulesPath, "utf8");
  } catch (err) {
    throw new Error(`规则库不可读: ${rulesPath}（${err.message.replace(/\n/g, " ")}）`);
  }
  let rules;
  try {
    rules = JSON.parse(raw);
  } catch (err) {
    throw new Error(`规则库不是合法 JSON: ${rulesPath}（${err.message}）`);
  }
  validateRules(rules, rulesPath);
  return rules;
}

function fail(msg) {
  throw new Error(`规则库结构违规: ${msg}`);
}

const FORMAT_VALUES = new Set(["single-html", "zip"]);
const RELATIVE_RE = /^[A-Za-z][A-Za-z0-9+.-]*:/; // 带 scheme
const SCHEMELESS_ABS_RE = /^\/|^\/\//; // 根相对 / 协议相对

export function validateRules(rules, _from = "rules") {
  if (!rules || typeof rules !== "object" || Array.isArray(rules)) fail("顶层必须是对象");
  if (typeof rules.rulesVersion !== "string" || rules.rulesVersion.length === 0) fail("缺 rulesVersion 字符串");
  const channels = rules.channels;
  if (!channels || typeof channels !== "object" || Array.isArray(channels)) fail("缺 channels 对象");
  const ids = Object.keys(channels);
  if (ids.length === 0) fail("channels 为空");
  for (const id of ids) {
    const where = `channels.${id}`;
    const ch = channels[id];
    if (!ch || typeof ch !== "object" || Array.isArray(ch)) fail(`${where} 必须是对象`);

    const pkg = ch.package;
    if (!pkg || typeof pkg !== "object" || Array.isArray(pkg)) fail(`${where}.package 必须是对象`);
    if (!FORMAT_VALUES.has(pkg.format)) fail(`${where}.package.format 须为 "single-html" 或 "zip"，得到 ${JSON.stringify(pkg.format)}`);
    if (pkg.format === "zip") {
      if (typeof pkg.entry !== "string" || pkg.entry.length === 0) fail(`${where}.package.entry（zip 渠道必填）`);
      if (!Array.isArray(pkg.structure) || pkg.structure.length !== 2 ||
          !pkg.structure.every((s) => typeof s === "string" && s.length > 0)) {
        fail(`${where}.package.structure 须恰为 [bundleName, entryName] 两个字符串`);
      }
      if (pkg.structure[1] !== pkg.entry) fail(`${where}.package.structure[1] 必须等于 entry`);
      if (!pkg.structure[0].endsWith(".js")) fail(`${where}.package.structure[0]（bundle 名）须以 .js 结尾`);
      if (pkg.structure.some((s) => s.includes("\\") || s.includes("/"))) {
        fail(`${where}.package.structure 条目名不允许含路径分隔符`);
      }
    } else if (pkg.entry !== undefined && typeof pkg.entry !== "string") {
      fail(`${where}.package.entry 须为字符串`);
    }

    if (typeof ch.maxBytes !== "number" || !Number.isFinite(ch.maxBytes) || ch.maxBytes <= 0) fail(`${where}.maxBytes 须为 >0 数值`);
    if (typeof ch.maxFiles !== "number" || !Number.isFinite(ch.maxFiles) || ch.maxFiles <= 0) fail(`${where}.maxFiles 须为 >0 数值`);

    const exit = ch.exit;
    if (!exit || typeof exit !== "object" || Array.isArray(exit)) fail(`${where}.exit 必须是对象`);
    if (typeof exit.protocol !== "string" || exit.protocol.length === 0) fail(`${where}.exit.protocol 须为非空字符串`);
    if (typeof exit.call !== "string" || exit.call.length === 0) fail(`${where}.exit.call 须为非空字符串`);

    const rt = ch.runtime;
    if (!rt || typeof rt !== "object" || Array.isArray(rt)) fail(`${where}.runtime 必须是对象`);
    if (typeof rt.muteBeforeFirstInteraction !== "boolean") fail(`${where}.runtime.muteBeforeFirstInteraction 须为 boolean`);
    if (rt.forbidMraid !== undefined && typeof rt.forbidMraid !== "boolean") fail(`${where}.runtime.forbidMraid 须为 boolean`);
    if (rt.injectRelativeScripts !== undefined) {
      if (!Array.isArray(rt.injectRelativeScripts) || rt.injectRelativeScripts.length === 0 ||
          !rt.injectRelativeScripts.every((s) => typeof s === "string" && s.length > 0)) {
        fail(`${where}.runtime.injectRelativeScripts 须为非空字符串数组`);
      }
      for (const s of rt.injectRelativeScripts) {
        if (RELATIVE_RE.test(s) || SCHEMELESS_ABS_RE.test(s)) {
          fail(`${where}.runtime.injectRelativeScripts 须为相对文件名，得到 "${s}"`);
        }
      }
    }

    if (ch.allowedUrlWhitelist !== undefined) {
      if (!Array.isArray(ch.allowedUrlWhitelist) || !ch.allowedUrlWhitelist.every((s) => typeof s === "string" && s.length > 0)) {
        fail(`${where}.allowedUrlWhitelist 须为非空字符串数组`);
      }
    }
  }
}

/**
 * channel-rules 加载与结构校验（配置驱动的知识资产，结构对应开发指令 §7 表列：
 * 包形态/包内结构、maxBytes、maxFiles、退出接口、协议、静音要求）。
 */
import { readFileSync } from "node:fs";
import path from "node:path";

const PACKAGE_FORMATS = new Set(["single-html", "zip"]);

/**
 * 校验规则库结构。返回 { ok, errors }。
 * 只做结构级校验（字段齐全/类型正确/取值合法），业务数值（如大小线）由使用方按需执行。
 */
export function validateRules(rules) {
  const errors = [];
  if (typeof rules !== "object" || rules === null || Array.isArray(rules)) {
    return { ok: false, errors: ["rules 必须是 JSON 对象"] };
  }
  if (typeof rules.rulesVersion !== "string" || !rules.rulesVersion) {
    errors.push("rulesVersion: 缺少或非字符串");
  }
  if (typeof rules.channels !== "object" || rules.channels === null || Array.isArray(rules.channels)) {
    errors.push("channels: 缺少或非对象");
    return { ok: false, errors };
  }
  if (Object.keys(rules.channels).length === 0) {
    errors.push("channels: 至少需要一条渠道规则");
  }
  for (const [id, ch] of Object.entries(rules.channels)) {
    if (typeof ch !== "object" || ch === null) {
      errors.push(`channels.${id}: 必须是对象`);
      continue;
    }
    const pkg = ch.package;
    if (typeof pkg !== "object" || pkg === null) {
      errors.push(`channels.${id}.package: 缺少（包形态声明）`);
    } else {
      if (!PACKAGE_FORMATS.has(pkg.format)) {
        errors.push(`channels.${id}.package.format: 非法值 "${pkg.format}"（允许 ${[...PACKAGE_FORMATS].join("/")}）`);
      }
      if (pkg.format === "single-html" && typeof pkg.entry !== "string") {
        errors.push(`channels.${id}.package.entry: single-html 需要入口文件名`);
      }
      if (pkg.format === "zip") {
        if (!Array.isArray(pkg.structure) || pkg.structure.length === 0) {
          errors.push(`channels.${id}.package.structure: zip 需要声明包内结构（文件名清单）`);
        } else if (typeof pkg.entry !== "string" || !pkg.structure.includes(pkg.entry)) {
          errors.push(`channels.${id}.package.entry: 必须是 structure 清单中的入口文件`);
        }
      }
    }
    if (!Number.isFinite(ch.maxBytes) || ch.maxBytes <= 0) {
      errors.push(`channels.${id}.maxBytes: 必须是正数`);
    }
    if (!Number.isFinite(ch.maxFiles) || ch.maxFiles <= 0) {
      errors.push(`channels.${id}.maxFiles: 必须是正数`);
    }
    if (typeof ch.exit !== "object" || ch.exit === null || typeof ch.exit.protocol !== "string" || typeof ch.exit.call !== "string") {
      errors.push(`channels.${id}.exit: 需要 { protocol, call }（退出接口契约）`);
    }
    if (typeof ch.runtime !== "object" || ch.runtime === null) {
      errors.push(`channels.${id}.runtime: 缺少（静音/注入/禁用声明）`);
    } else {
      if (typeof ch.runtime.muteBeforeFirstInteraction !== "boolean") {
        errors.push(`channels.${id}.runtime.muteBeforeFirstInteraction: 需要 boolean（静音要求）`);
      }
      if (ch.runtime.injectRelativeScripts !== undefined && !Array.isArray(ch.runtime.injectRelativeScripts)) {
        errors.push(`channels.${id}.runtime.injectRelativeScripts: 需要 string 数组`);
      }
    }
  }
  return { ok: errors.length === 0, errors };
}

/**
 * 从磁盘加载规则库并校验。
 */
export function loadRules(rulesPath) {
  const abs = path.resolve(rulesPath);
  let raw;
  try {
    raw = readFileSync(abs, "utf8");
  } catch (err) {
    throw new Error(`规则库读取失败: ${abs}（${err.message}）`);
  }
  let rules;
  try {
    rules = JSON.parse(raw);
  } catch (err) {
    throw new Error(`规则库不是合法 JSON: ${abs}（${err.message}）`);
  }
  const { ok, errors } = validateRules(rules);
  if (!ok) {
    throw new Error(`规则库结构校验失败: ${abs}\n  - ${errors.join("\n  - ")}`);
  }
  return { rules, path: abs };
}

/**
 * 取单渠道规则；未知渠道直接抛错（拼错渠道名不应静默通过）。
 */
export function channelRule(rules, channelId) {
  const ch = rules.channels[channelId];
  if (!ch) {
    const known = Object.keys(rules.channels).join(", ");
    throw new Error(`规则库中没有渠道 "${channelId}"（现有: ${known}）`);
  }
  return ch;
}

/**
 * 有效大小上限 = min(渠道规则上限, spec.channels.overrides.<channel>.maxBytes)。
 * spec 覆盖只允许收紧不允许放宽（防止项目配置意外突破渠道红线）。
 */
export function effectiveMaxBytes(rule, spec, channelId) {
  let max = rule.maxBytes;
  const override = spec?.channels?.overrides?.[channelId];
  if (override && Number.isFinite(override.maxBytes) && override.maxBytes > 0) {
    max = Math.min(max, override.maxBytes);
  }
  return max;
}

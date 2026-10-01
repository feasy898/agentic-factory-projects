/**
 * channel-rules 规则库：加载、结构校验、单渠道取用、有效上限。
 * 配置驱动——打包器不携带渠道知识，规则库说了算（spec packager.md §1/§3.1）。
 * 结构违规直接抛错（宁失败不出超规包）。
 */
import { readFileSync } from "node:fs";
import path from "node:path";

const PACKAGE_FORMATS = new Set(["single-html", "zip"]);

/**
 * 校验规则库结构，返回 { ok, errors }。只做结构级校验（字段齐全/类型/取值合法）；
 * 业务数值（大小线等）由使用方按需执行。
 */
export function validateRules(rules) {
  const errors = [];
  if (typeof rules !== "object" || rules === null || Array.isArray(rules)) {
    return { ok: false, errors: ["rules 必须是 JSON 对象"] };
  }
  if (typeof rules.rulesVersion !== "string" || !rules.rulesVersion) {
    errors.push("rulesVersion: 缺少或非字符串");
  }
  if (rules.defaults !== undefined) {
    if (typeof rules.defaults !== "object" || rules.defaults === null || Array.isArray(rules.defaults)) {
      errors.push("defaults: 必须是对象");
    } else if (rules.defaults.allowedTextUrls !== undefined
      && (!Array.isArray(rules.defaults.allowedTextUrls)
        || rules.defaults.allowedTextUrls.some((u) => typeof u !== "string"))) {
      errors.push("defaults.allowedTextUrls: 需要 string 数组（外链文本扫描的全局白名单）");
    }
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
        } else {
          const names = new Set(pkg.structure);
          if (names.size !== pkg.structure.length) {
            errors.push(`channels.${id}.package.structure: 条目重名（${pkg.structure.join(", ")}）`);
          }
          // package.generated（可选）：文件名 → 生成器名。声明由打包器按 spec
          // 现生成的附加文件（如 config.json / js-sdk 桩）；不得覆盖入口。
          if (pkg.generated !== undefined) {
            const gen = pkg.generated;
            if (typeof gen !== "object" || gen === null || Array.isArray(gen)) {
              errors.push(`channels.${id}.package.generated: 必须是对象（文件名 → 生成器名）`);
            } else {
              for (const [name, kind] of Object.entries(gen)) {
                if (!names.has(name)) {
                  errors.push(`channels.${id}.package.generated.${name}: 不在 structure 清单中`);
                }
                if (typeof kind !== "string" || !kind) {
                  errors.push(`channels.${id}.package.generated.${name}: 生成器名须为非空字符串`);
                }
                if (name === pkg.entry) {
                  errors.push(`channels.${id}.package.generated.${name}: 不能覆盖入口文件`);
                }
              }
            }
          }
          // 非入口且非 generated 的条目至多 1 个：它承载 dist 外链脚本的合并产物
          // （如 build.js）；没有则入口全内联。structure 项数随渠道面变。
          const others = pkg.structure.filter(
            (n) => n !== pkg.entry && !(pkg.generated && n in pkg.generated));
          if (others.length > 1) {
            errors.push(
              `channels.${id}.package.structure: 非入口且非 generated 的合并脚本至多 1 个（当前 ${others.length}：${others.join(", ")}）`);
          }
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

/** 从磁盘加载规则库并校验；非法即抛错。 */
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

/** 取单渠道规则；未知渠道（拼错或未冻结）直接抛错并列出现有渠道，不静默通过。 */
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
 * override 只许收紧不许放宽（防项目配置意外突破渠道红线）。
 */
export function effectiveMaxBytes(rule, spec, channelId) {
  let max = rule.maxBytes;
  const override = spec?.channels?.overrides?.[channelId];
  if (override && Number.isFinite(override.maxBytes) && override.maxBytes > 0) {
    max = Math.min(max, override.maxBytes);
  }
  return max;
}

/**
 * 规则库加载与结构校验（spec packager.md §3.1，冻结）：
 * 规则库是渠道知识唯一来源，打包器不改渠道知识；结构违规直接抛错。
 *
 * 结构：rulesVersion; channels.<id>{ package{format: "single-html"|"zip", entry, structure?},
 * maxBytes>0, maxFiles>0, exit{protocol, call}, runtime{muteBeforeFirstInteraction,
 * injectRelativeScripts?, forbidMraid?}, allowedUrlWhitelist? }。
 * zip 的 structure 必须含 entry，且恰为 [bundle, entry] 两项（否则抛错）。
 */
import { readFileSync } from "node:fs";

export function validateRules(rules) {
  const errs = [];
  const need = (ok, msg) => {
    if (!ok) errs.push(msg);
  };

  need(rules !== null && typeof rules === "object", "规则库必须是 JSON 对象");
  if (errs.length === 0) {
    need(typeof rules.rulesVersion === "string" && rules.rulesVersion.length > 0, "缺 rulesVersion（string）");
    need(rules.channels !== null && typeof rules.channels === "object", "缺 channels 对象");
  }
  if (errs.length === 0) {
    for (const [id, ch] of Object.entries(rules.channels)) {
      const pre = `channels.${id}`;
      need(ch !== null && typeof ch === "object", `${pre} 必须是对象`);
      if (ch === null || typeof ch !== "object") continue;

      const pkg = ch.package;
      need(pkg !== null && typeof pkg === "object", `${pre}.package 缺失`);
      if (pkg !== null && typeof pkg === "object") {
        need(
          pkg.format === "single-html" || pkg.format === "zip",
          `${pre}.package.format 非法（${JSON.stringify(pkg.format)}）`,
        );
        need(typeof pkg.entry === "string" && pkg.entry.length > 0, `${pre}.package.entry 缺失`);
        if (pkg.format === "zip") {
          need(Array.isArray(pkg.structure), `${pre}（zip）必须声明 package.structure`);
          if (Array.isArray(pkg.structure)) {
            need(
              pkg.structure.includes(pkg.entry),
              `${pre}.package.structure 必须含 entry（${pkg.entry}）`,
            );
            // 实现约束：zip 恰为 [bundle, entry] 两项
            need(
              pkg.structure.length === 2 && pkg.structure[1] === pkg.entry,
              `${pre}.package.structure 必须恰为 [bundle, entry] 两项`,
            );
          }
        }
      }

      need(typeof ch.maxBytes === "number" && Number.isFinite(ch.maxBytes) && ch.maxBytes > 0, `${pre}.maxBytes 必须 >0`);
      need(typeof ch.maxFiles === "number" && Number.isFinite(ch.maxFiles) && ch.maxFiles > 0, `${pre}.maxFiles 必须 >0`);
      need(
        ch.exit !== null && typeof ch.exit === "object" &&
          typeof ch.exit.protocol === "string" && typeof ch.exit.call === "string",
        `${pre}.exit{protocol, call} 缺失`,
      );
      const rt = ch.runtime;
      need(rt !== null && typeof rt === "object", `${pre}.runtime 缺失`);
      if (rt !== null && typeof rt === "object") {
        need(typeof rt.muteBeforeFirstInteraction === "boolean", `${pre}.runtime.muteBeforeFirstInteraction 缺失`);
        if (rt.injectRelativeScripts !== undefined) {
          need(
            Array.isArray(rt.injectRelativeScripts) && rt.injectRelativeScripts.every((s) => typeof s === "string"),
            `${pre}.runtime.injectRelativeScripts 必须是 string 数组`,
          );
        }
        if (rt.forbidMraid !== undefined) {
          need(typeof rt.forbidMraid === "boolean", `${pre}.runtime.forbidMraid 必须是 boolean`);
        }
      }
      if (ch.allowedUrlWhitelist !== undefined) {
        need(
          Array.isArray(ch.allowedUrlWhitelist) && ch.allowedUrlWhitelist.every((s) => typeof s === "string"),
          `${pre}.allowedUrlWhitelist 必须是 string 数组`,
        );
      }
    }
  }

  if (errs.length > 0) throw new Error(`规则库结构违规: ${errs.join("; ")}`);
  return rules;
}

export function loadRules(path) {
  let raw;
  try {
    raw = readFileSync(path, "utf8");
  } catch (err) {
    throw new Error(`规则库读取失败（${path}）: ${err.message}`);
  }
  let json;
  try {
    json = JSON.parse(raw);
  } catch (err) {
    throw new Error(`规则库不是合法 JSON（${path}）: ${err.message}`);
  }
  return validateRules(json);
}

/**
 * 打包编排：dist + spec + channel-rules → 渠道产物（spec packager.md §3.2/§4）。
 *
 * - single-html（applovin/meta/preview）：单 HTML 全内联（base64 资源、零外链），输出 <entry>
 * - zip：包内结构与条目序由规则库 package.structure 声明——
 *   - 声明合并脚本（mintegral 的 build.js）：Template.html（壳，资源内联）+ build.js
 *   - 仅入口（google/unity）：入口 index.html 全内联
 *   - 入口 + package.generated（tiktok）：index.html + config.json + js-sdk.js 桩
 *
 * 输出目录契约：<out>/<projectId>/<channel>/<locale>/<files> + pack-manifest.json 旁车。
 * 强制项（全部构建失败而非告警——宁失败不出超规包）：maxBytes（含 spec override 收紧）、
 * maxFiles（仅 zip 通道、按包内条目数）、零外链、forbidMraid、包内结构。
 */
import { createHash } from "node:crypto";
import { mkdirSync, statSync, writeFileSync } from "node:fs";
import path from "node:path";

import { generateExtra } from "./extras.mjs";
import { findMraidReferences, processHtml, scanExternalUrls } from "./html.mjs";
import { channelRule, effectiveMaxBytes, loadRules } from "./rules.mjs";
import { createZip } from "./zip.mjs";

const PROJECT_ID_RE = /^[A-Za-z0-9][A-Za-z0-9._-]*$/;
const LOCALE_RE = /^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*$/;
const MANIFEST_NAME = "pack-manifest.json";
const EMPTY_BUNDLE_PLACEHOLDER = "/* pf-packager: 空 bundle（dist 无外链脚本） */";

function sha256(buf) {
  return createHash("sha256").update(buf).digest("hex");
}

function checkId(value, label, re) {
  if (typeof value !== "string" || !re.test(value)) {
    throw new Error(`${label} 非法: "${value}"（需匹配 ${re}，且用于路径拼接，禁止路径符号）`);
  }
  return value;
}

/** 轻量 spec 检查（完整校验属 M1 validator；这里只取 meta.projectId 与顶格 specVersion）。 */
function loadSpecFields(spec) {
  if (typeof spec !== "object" || spec === null) throw new Error("spec 不是 JSON 对象");
  const projectId = checkId(spec?.meta?.projectId, "meta.projectId", PROJECT_ID_RE);
  if (typeof spec.specVersion !== "string") throw new Error("spec.specVersion 缺失");
  return { projectId, spec };
}

/**
 * @param {object} o
 *   spec: 解析后的 PlayableSpec 对象（必填）
 *   specPath: spec 文件路径（用于 manifest 记录）
 *   dist: 模板构建产物目录（必填；若存在 <dist>/<locale>/index.html 则整目录基准
 *         切换到该子目录——语言产物优先）
 *   channel: 渠道 id（必填，须在规则库中）
 *   locale: 输出语言（默认 en）
 *   rulesPath: 规则库路径
 *   out: 输出根目录（默认 artifacts）
 *   minify: 是否压缩（默认 true）
 * 返回 { artifact, dir, files, totalBytes, maxBytes, warnings, manifest }。
 */
export async function pack(o) {
  const locale = checkId(o.locale || "en", "locale", LOCALE_RE);
  if (!o.spec) throw new Error("缺少 spec（--spec）");
  const { projectId, spec } = loadSpecFields(o.spec);
  if (!o.dist) throw new Error("缺少模板构建产物目录（--dist）");
  if (!o.channel) throw new Error("缺少目标渠道（--channel）");

  const { rules } = loadRules(o.rulesPath);
  const rule = channelRule(rules, o.channel);
  const maxBytes = effectiveMaxBytes(rule, spec, o.channel);

  // dist 解析：优先 <dist>/<locale>/index.html（按语言构建的产物），否则 <dist>/index.html
  const distRoot = path.resolve(o.dist);
  const entryLabel = "index.html";
  const localeEntry = path.join(distRoot, locale, entryLabel);
  let htmlDir = distRoot;
  let entryAbs = localeEntry;
  if (!statSync(localeEntry, { throwIfNoEntry: false })?.isFile()) {
    entryAbs = path.join(distRoot, entryLabel);
  } else {
    htmlDir = path.join(distRoot, locale);
  }
  if (!statSync(entryAbs, { throwIfNoEntry: false })?.isFile()) {
    throw new Error(`模板构建产物缺少入口: ${entryAbs}（--dist 需指向含 index.html 的目录，或 <dist>/<locale>/index.html）`);
  }

  const isZip = rule.package.format === "zip";
  const entryOutName = rule.package.entry || "index.html";
  // 生成文件（package.generated，可选）：文件名 → 生成器名，按 spec 现生成。
  const generatedSpec = (isZip && rule.package.generated) || {};
  // 合并脚本 = structure 中既非入口也非生成文件的那个唯一文件（如 build.js），
  // 承载 dist 外链脚本合并产物；没有 → 入口全内联（inline-script 模式）。
  const bundleCandidates = (rule.package.structure || []).filter(
    (n) => n !== entryOutName && !(n in generatedSpec),
  );
  if (bundleCandidates.length > 1) {
    throw new Error(
      `渠道 ${o.channel} 的 package.structure 中非入口且非 generated 的合并脚本至多 1 个，当前: [${rule.package.structure.join(", ")}]`,
    );
  }
  const bundleName = bundleCandidates[0] || null;

  const mode = bundleName ? "extract-script" : "inline-script";
  const { html, scripts, warnings } = await processHtml(entryAbs, htmlDir, {
    mode,
    bundleName: bundleName || "build.js",
    minify: o.minify !== false,
    injectScripts: rule.runtime?.injectRelativeScripts || [],
    entryLabel,
  });

  // 外链白名单 = spec 落地页 URL（前缀匹配；CTA 参数允许出现在 JS 里）
  //             + 规则库 defaults.allowedTextUrls（惰性字符串：品牌串与命名空间标识符）
  //             + 渠道规则 allowedUrlWhitelist
  const whitelist = [
    spec?.flow?.endScreen?.landingUrl,
    ...(rules.defaults?.allowedTextUrls || []),
    ...(rule.allowedUrlWhitelist || []),
  ].filter(Boolean);

  const outRoot = path.resolve(o.out || "artifacts");
  const outDir = path.join(outRoot, projectId, o.channel, locale);
  mkdirSync(outDir, { recursive: true });

  /** 通道公共后置检查：外链 / MRAID 禁用。违规即抛错（红线）。 */
  function enforceText(text, label) {
    const violations = scanExternalUrls(text, whitelist);
    if (violations.length > 0) {
      const lines = violations.slice(0, 8).map((v) => `  - ${v.url}（…${v.context}…）`);
      throw new Error(`${label} 存在白名单外链接（零外链红线）:\n${lines.join("\n")}\n白名单: ${whitelist.join(", ") || "(空)"}`);
    }
    if (rule.runtime?.forbidMraid) {
      const hits = findMraidReferences(text);
      if (hits.length > 0) {
        throw new Error(`${label} 引用了 MRAID，而渠道 ${o.channel} 禁用 MRAID: ${hits.slice(0, 3).join(" | ")}`);
      }
    }
  }

  const files = [];
  let artifact;
  if (isZip) {
    enforceText(html, entryOutName);
    const parts = new Map([[entryOutName, Buffer.from(html, "utf8")]]);
    const entryBytes = parts.get(entryOutName).length;
    if (bundleName) {
      const bundleCode = scripts.map((s) => s.code).join("\n;\n");
      const bundleText = bundleCode || EMPTY_BUNDLE_PLACEHOLDER;
      enforceText(bundleText, bundleName);
      parts.set(bundleName, Buffer.from(bundleText, "utf8"));
    }
    // 生成文件（config.json / js-sdk 桩等）按规则库声明的生成器现生成，同过零外链关。
    for (const [name, kind] of Object.entries(generatedSpec)) {
      const text = generateExtra(kind, { spec });
      enforceText(text, name);
      parts.set(name, Buffer.from(text, "utf8"));
    }

    // zip 条目 = 规则 structure 顺序（冻结形状）
    const entries = rule.package.structure.map((name) => {
      const data = parts.get(name);
      if (data === undefined) throw new Error(`包内结构声明了未知文件 "${name}"`);
      return { name, data };
    });
    // maxFiles：仅 zip 通道强制，按包内条目数计数
    if (entries.length > rule.maxFiles) {
      throw new Error(`zip 条目数 ${entries.length} 超过 maxFiles=${rule.maxFiles}`);
    }
    const zipBuf = createZip(entries);
    if (zipBuf.length > maxBytes) {
      throw new Error(`zip ${zipBuf.length} 字节超过上限 ${maxBytes}（渠道 ${o.channel}）`);
    }
    artifact = path.join(outDir, `${projectId}-${locale}.zip`);
    writeFileSync(artifact, zipBuf);
    files.push(
      { path: path.basename(artifact), bytes: zipBuf.length, sha256: sha256(zipBuf), role: "package" },
      { path: entryOutName, bytes: entryBytes, sha256: sha256(parts.get(entryOutName)), role: "entry-in-zip" },
    );
    if (bundleName) {
      files.push({ path: bundleName, bytes: parts.get(bundleName).length, sha256: sha256(parts.get(bundleName)), role: "bundle-in-zip" });
    }
    for (const name of Object.keys(generatedSpec)) {
      files.push({ path: name, bytes: parts.get(name).length, sha256: sha256(parts.get(name)), role: "generated-in-zip" });
    }
  } else {
    enforceText(html, entryOutName);
    const htmlBuf = Buffer.from(html, "utf8");
    if (htmlBuf.length > maxBytes) {
      throw new Error(`单 HTML ${htmlBuf.length} 字节超过上限 ${maxBytes}（渠道 ${o.channel}，含 spec override 收紧）`);
    }
    artifact = path.join(outDir, entryOutName);
    writeFileSync(artifact, htmlBuf);
    files.push({ path: entryOutName, bytes: htmlBuf.length, sha256: sha256(htmlBuf), role: "package" });
  }

  // totalBytes 只累计 role=package
  const totalBytes = files.filter((f) => f.role === "package").reduce((n, f) => n + f.bytes, 0);
  const manifest = {
    packager: "@pf/packager",
    rulesVersion: rules.rulesVersion,
    channel: o.channel,
    locale,
    project: projectId,
    specPath: o.specPath ? path.resolve(o.specPath) : null,
    dist: distRoot,
    maxBytes,
    packageFiles: files.filter((f) => f.role === "package").map((f) => f.path),
    files,
    warnings,
  };
  writeFileSync(path.join(outDir, MANIFEST_NAME), JSON.stringify(manifest, null, 2) + "\n");

  return { artifact, dir: outDir, files, totalBytes, maxBytes, warnings, manifest };
}

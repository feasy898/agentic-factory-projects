#!/usr/bin/env node
/**
 * M4 打包器 CLI（spec packager.md §2，冻结）：
 *
 *   node bin.mjs build --spec <spec.json> --dist <dir> --channel <id>
 *        [--locale en] [--out artifacts] [--rules channel-rules/channel-rules.json] [--no-minify]
 *   node bin.mjs channels [--rules <path>]
 *
 * - Node ≥22；--out 缺省 = <cwd>/artifacts；rules 缺省 = 仓库根 channel-rules/channel-rules.json
 *   （从 bin.mjs 自身位置反推：packages/packager/bin.mjs → 上两级 = 仓库根，与冻结测试同一 <root>）。
 * - 退出码：0 成功；1 构建失败——含超规/外链/结构违规/未知或未冻结渠道（channelRule 抛错、
 *   被 main 的 catch 统一接住，stderr 输出 `[packager] 失败: <原因>`，未知渠道列出现有渠道）；
 *   2 仅限 CLI 用法层：未知子命令、多余位置参数、参数解析错误。渠道拼写错误不是 exit 2。
 * - 成功时 stdout 末行输出 JSON：{ok:true, artifact, totalBytes, maxBytes}。
 */
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { writeZip } from "./src/zip.mjs";
import { loadRules } from "./src/rules.mjs";
import { renderHtml, makeMinifiers, scanExternalUrls, isWhitelisted, findMraid } from "./src/html.mjs";

const BIN_DIR = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(BIN_DIR, "..", ".."); // packages/packager → 仓库根
const DEFAULT_RULES = path.join(REPO_ROOT, "channel-rules", "channel-rules.json");
const PACKAGER_ID = "@pf/packager";

const PROJECT_ID_RE = /^[A-Za-z0-9][A-Za-z0-9._-]*$/;
const LOCALE_RE = /^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*$/;

const USAGE = `用法:
  pf-packager build --spec <spec.json> --dist <dir> --channel <id>
        [--locale en] [--out artifacts] [--rules channel-rules/channel-rules.json] [--no-minify]
  pf-packager channels [--rules <path>]
退出码: 0 成功; 1 构建失败(超规/外链/结构违规/未知渠道); 2 CLI 用法错误`;

class UsageError extends Error {}

function sha256(buf) {
  return createHash("sha256").update(buf).digest("hex");
}

function fail(message) {
  throw new Error(message);
}

// ---------------- 参数解析（2 = 用法层错误） ----------------

function parseArgs(argv, cmd) {
  const opts = { _: [] };
  const valueFlags = new Set(["--spec", "--dist", "--channel", "--locale", "--out", "--rules"]);
  const boolFlags = new Set(["--no-minify"]);
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a.startsWith("--")) {
      if (!valueFlags.has(a) && !boolFlags.has(a)) {
        throw new UsageError(`未知选项: ${a}`);
      }
      if (boolFlags.has(a)) {
        opts[a.slice(2)] = true;
        continue;
      }
      const val = argv[i + 1];
      if (val === undefined || val.startsWith("--")) {
        throw new UsageError(`选项 ${a} 缺少值`);
      }
      opts[a.slice(2)] = val;
      i++;
    } else {
      opts._.push(a);
    }
  }
  if (opts._.length > 0) {
    throw new UsageError(`${cmd}: 多余位置参数: ${opts._.join(" ")}`);
  }
  return opts;
}

// ---------------- spec 字段（§3.2：顶格 specVersion + meta.projectId 是仅取的结构字段） ----------------

function loadSpecFields(specPath) {
  let raw;
  try {
    raw = readFileSync(specPath, "utf8");
  } catch (err) {
    return fail(`spec 读取失败（${specPath}）: ${err.message}`);
  }
  let spec;
  try {
    spec = JSON.parse(raw);
  } catch (err) {
    return fail(`spec 不是合法 JSON（${specPath}）: ${err.message}`);
  }
  const specVersion = spec.specVersion;
  if (typeof specVersion !== "string" || specVersion.length === 0) {
    return fail("spec 缺 specVersion（顶格 string）");
  }
  const projectId = spec.meta?.projectId;
  if (typeof projectId !== "string" || !PROJECT_ID_RE.test(projectId)) {
    return fail(`spec 缺合法 meta.projectId（须匹配 ${PROJECT_ID_RE}）`);
  }
  const landingUrl = spec.flow?.endScreen?.landingUrl;
  const overrides = spec.channels?.overrides || {};
  return { spec, specVersion, projectId, landingUrl, overrides };
}

// ---------------- 渠道解析 ----------------

function resolveChannel(rules, channelId) {
  const ch = rules.channels[channelId];
  if (!ch) {
    return fail(`未知或未冻结渠道 "${channelId}"（现有渠道: ${Object.keys(rules.channels).join(", ")}）`);
  }
  return ch;
}

/** 有效大小上限 = min(渠道 maxBytes, spec.channels.overrides.<channel>.maxBytes)——override 只许收紧不许放宽。 */
function effectiveMaxBytes(channelRule, overrides, channelId) {
  let max = channelRule.maxBytes;
  const ov = overrides[channelId];
  if (ov && ov.maxBytes !== undefined) {
    if (typeof ov.maxBytes !== "number" || !Number.isFinite(ov.maxBytes) || ov.maxBytes <= 0) {
      return fail(`spec.channels.overrides.${channelId}.maxBytes 非法（须为正数）`);
    }
    max = Math.min(max, ov.maxBytes);
  }
  return max;
}

// ---------------- build ----------------

async function cmdBuild(opts) {
  for (const key of ["spec", "dist", "channel"]) {
    if (!opts[key]) throw new UsageError(`build 缺必需选项 --${key}`);
  }
  const locale = opts.locale || "en";
  if (!LOCALE_RE.test(locale)) {
    return fail(`locale 非法 "${locale}"（须匹配 ${LOCALE_RE}，禁路径符号）`);
  }
  const specPath = path.resolve(opts.spec);
  const rulesPath = opts.rules ? path.resolve(opts.rules) : DEFAULT_RULES;
  const outDir = path.resolve(opts.out || path.join(process.cwd(), "artifacts"));

  const { projectId, landingUrl, overrides } = loadSpecFields(specPath);
  const rules = loadRules(rulesPath);
  const channelRule = resolveChannel(rules, opts.channel);
  const maxBytes = effectiveMaxBytes(channelRule, overrides, opts.channel);

  // dist 基准：<dist>/<locale>/index.html 优先（整目录基准切换）
  const distRoot = path.resolve(opts.dist);
  if (!existsSync(distRoot) || !statSync(distRoot).isDirectory()) {
    return fail(`dist 目录不存在（${distRoot}）`);
  }
  const localeEntry = path.join(distRoot, locale, "index.html");
  const baseRel = existsSync(localeEntry) ? locale : "";

  // 渲染（inline=单 HTML 全内联 / extract=zip 渠道脚本抽取）
  const mode = channelRule.package.format === "zip" ? "extract" : "inline";
  const structure = channelRule.package.structure;
  const bundleName = mode === "extract" ? structure[0] : null;
  const warnings = [];
  const { minifyJs, minifyCss } = makeMinifiers(Boolean(opts["no-minify"]));
  const { html, bundle } = await renderHtml({
    distRoot,
    baseRel,
    channelRule,
    mode,
    bundleName,
    warnings,
    minifyJs,
    minifyCss,
  });

  // 白名单 = spec flow.endScreen.landingUrl（前缀匹配）+ 规则 allowedUrlWhitelist（前缀匹配）
  const whitelist = [
    ...(landingUrl ? [landingUrl] : []),
    ...(channelRule.allowedUrlWhitelist || []),
  ];

  // 外链扫描：HTML 与 bundle 文本分别扫描，命中即构建失败（不许降级为告警）
  const texts = bundle === null ? [html] : [html, bundle];
  const offenders = [];
  for (const text of texts) {
    for (const url of scanExternalUrls(text)) {
      if (!isWhitelisted(url, whitelist) && !offenders.includes(url)) offenders.push(url);
    }
  }
  if (offenders.length > 0) {
    return fail(`白名单外外链 ${offenders.length} 处: ${offenders.join(", ")}`);
  }

  // MRAID 禁用（forbidMraid 渠道，产物任一文本全词命中即失败）
  if (channelRule.runtime?.forbidMraid) {
    const hits = texts.flatMap((t) => findMraid(t));
    if (hits.length > 0) {
      return fail(`渠道禁用 MRAID，产物命中 ${hits.length} 处（如 ${hits[0].slice(0, 40)}）`);
    }
  }

  // 产物组装：<out>/<projectId>/<channel>/<locale>/
  const artifactDir = path.join(outDir, projectId, opts.channel, locale);
  mkdirSync(artifactDir, { recursive: true });
  const files = [];
  let artifactAbs;
  let totalBytes;

  if (mode === "inline") {
    const buf = Buffer.from(html, "utf8");
    if (buf.length > maxBytes) {
      return fail(`产物 ${buf.length} B 超过有效上限 ${maxBytes} B（渠道 ${opts.channel}）`);
    }
    artifactAbs = path.join(artifactDir, "index.html");
    writeFileSync(artifactAbs, buf);
    files.push({ path: "index.html", bytes: buf.length, sha256: sha256(buf), role: "package" });
    totalBytes = buf.length;
  } else {
    // zip：条目 = 规则 structure 顺序（恰 [bundle, entry]）
    const entryName = channelRule.package.entry;
    const minifiedBundle = (await minifyJs(bundle ?? "")).toString();
    const entryContents = structure.map((name) =>
      name === entryName ? Buffer.from(html, "utf8") : Buffer.from(minifiedBundle, "utf8"),
    );
    if (structure.length > channelRule.maxFiles) {
      return fail(`zip 条目数 ${structure.length} 超过 maxFiles ${channelRule.maxFiles}（渠道 ${opts.channel}）`);
    }
    const zipBuf = writeZip(structure.map((name, i) => [name, entryContents[i]]));
    if (zipBuf.length > maxBytes) {
      return fail(`zip 产物 ${zipBuf.length} B 超过有效上限 ${maxBytes} B（渠道 ${opts.channel}）`);
    }
    const zipName = `${projectId}-${locale}.zip`;
    artifactAbs = path.join(artifactDir, zipName);
    writeFileSync(artifactAbs, zipBuf);
    files.push({ path: zipName, bytes: zipBuf.length, sha256: sha256(zipBuf), role: "package" });
    // files[] 顺序按 §3.2 冻结形状：package → entry-in-zip → bundle-in-zip
    const contentItems = structure.map((name, i) => ({
      path: name,
      bytes: entryContents[i].length,
      sha256: sha256(entryContents[i]),
      role: name === entryName ? "entry-in-zip" : "bundle-in-zip",
    }));
    contentItems.sort((a, b) => (a.role === "entry-in-zip" ? -1 : 0) - (b.role === "entry-in-zip" ? -1 : 0));
    files.push(...contentItems);
    totalBytes = zipBuf.length;
  }

  // pack-manifest.json 台账（旁车，不随包投放）
  const packageFiles = files.filter((f) => f.role === "package").map((f) => f.path);
  const manifest = {
    packager: PACKAGER_ID,
    rulesVersion: rules.rulesVersion,
    channel: opts.channel,
    locale,
    project: projectId,
    specPath,
    dist: distRoot,
    maxBytes,
    packageFiles,
    files,
    warnings,
  };
  writeFileSync(path.join(artifactDir, "pack-manifest.json"), JSON.stringify(manifest, null, 2) + "\n");

  // 成功时 stdout 末行 JSON
  process.stdout.write(JSON.stringify({ ok: true, artifact: artifactAbs, totalBytes, maxBytes }) + "\n");
}

// ---------------- channels ----------------

function cmdChannels(opts) {
  const rulesPath = opts.rules ? path.resolve(opts.rules) : DEFAULT_RULES;
  const rules = loadRules(rulesPath);
  for (const id of Object.keys(rules.channels)) {
    process.stdout.write(id + "\n");
  }
}

// ---------------- main ----------------

async function main() {
  const argv = process.argv.slice(2);
  const cmd = argv[0];
  const rest = argv.slice(1);
  if (cmd === "build") {
    const opts = parseArgs(rest, cmd);
    await cmdBuild(opts);
    return;
  }
  if (cmd === "channels") {
    const opts = parseArgs(rest, cmd);
    cmdChannels(opts);
    return;
  }
  process.stderr.write(`[packager] ${cmd ? `未知子命令: ${cmd}` : "缺子命令"}\n${USAGE}\n`);
  process.exitCode = 2;
}

main().catch((err) => {
  if (err instanceof UsageError) {
    process.stderr.write(`[packager] 参数错误: ${err.message}\n${USAGE}\n`);
    process.exitCode = 2;
  } else {
    process.stderr.write(`[packager] 失败: ${err && err.message ? err.message : String(err)}\n`);
    process.exitCode = 1;
  }
});

#!/usr/bin/env node
/**
 * M4 打包器 CLI（spec §2 冻结契约）。
 *
 *   pf-packager build --spec <spec.json> --dist <dir> --channel <id>
 *        [--locale en] [--out artifacts] [--rules channel-rules/channel-rules.json] [--no-minify]
 *   pf-packager channels [--rules <path>]
 *
 * 退出码：0 成功；1 构建失败（超规/外链/结构/缺失，stderr 一行人读原因）；
 * 2 参数错误/未知命令。成功时 stdout 末行输出 {ok:true, artifact, totalBytes, maxBytes}。
 */
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, realpathSync, statSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { loadRules, validateRules } from "./src/rules.mjs";
import { writeZip } from "./src/zip.mjs";
import { processHtml, scanExternalUrls, scanMraid } from "./src/inline.mjs";

const PKG_NAME = "@pf/packager";
const LOCALE_RE = /^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*$/;
const PROJECT_ID_RE = /^[A-Za-z0-9][A-Za-z0-9._-]*$/;

const selfRealDir = path.dirname(realpathSync(fileURLToPath(import.meta.url)));

class ParamError extends Error {}

function usage() {
  return [
    "用法:",
    "  pf-packager build --spec <spec.json> --dist <dir> --channel <id> [--locale en] [--out artifacts] [--rules <path>] [--no-minify]",
    "  pf-packager channels [--rules <path>]",
  ].join("\n");
}

/** 规则库缺省：仓库根 channel-rules/channel-rules.json。兼容两种布局：
 *  本包位于 <仓库根>/channel-rules 旁（当前 pilot 布局），或 <仓库根>/packages/packager 下（原仓库布局）。 */
function defaultRulesPath() {
  const candidates = [
    path.join(selfRealDir, "channel-rules", "channel-rules.json"),
    path.resolve(selfRealDir, "../../channel-rules/channel-rules.json"),
  ];
  for (const c of candidates) if (existsSync(c)) return c;
  throw new Error(`找不到默认规则库，尝试过: ${candidates.join(" ; ")}`);
}

function parseArgs(argv) {
  const flagsWithValues = new Set(["--spec", "--dist", "--channel", "--locale", "--out", "--rules"]);
  const knownBoolean = new Set(["--no-minify"]);
  const out = { _: [] };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (flagsWithValues.has(a)) {
      const v = argv[++i];
      if (v === undefined) throw new ParamError(`参数 ${a} 缺少值`);
      out[a.slice(2)] = v;
    } else if (knownBoolean.has(a)) {
      out[a.slice(2)] = true;
    } else if (a.startsWith("--")) {
      throw new ParamError(`未知参数: ${a}`);
    } else {
      out._.push(a);
    }
  }
  return out;
}

function sha256(buf) {
  return createHash("sha256").update(buf).digest("hex");
}

function specText(v) {
  return typeof v === "string" ? v : undefined;
}

async function cmdBuild(f) {
  for (const k of ["spec", "dist", "channel"]) {
    if (!f[k]) throw new ParamError(`build 缺少必需参数 --${k}\n${usage()}`);
  }
  const rulesPath = f.rules ? path.resolve(f.rules) : defaultRulesPath();
  const rules = loadRules(rulesPath);

  const channel = f.channel;
  const ch = rules.channels[channel];
  if (!ch) {
    throw new Error(`未知渠道 "${channel}"（规则库 ${rulesPath} 现有: ${Object.keys(rules.channels).sort().join(", ")}）`);
  }

  // 轻量 spec 校验（完整校验属 M1）：只取 meta.projectId 与 specVersion。
  const specAbs = path.resolve(f.spec);
  let spec;
  try {
    spec = JSON.parse(readFileSync(specAbs, "utf8"));
  } catch (err) {
    throw new Error(`spec 不可读或非 JSON: ${specAbs}（${err.message}）`);
  }
  const projectId = specText(spec?.meta?.projectId);
  if (!projectId || !PROJECT_ID_RE.test(projectId)) {
    throw new Error(`spec 缺合法 meta.projectId（须匹配 ${PROJECT_ID_RE}）: ${JSON.stringify(spec?.meta?.projectId)}`);
  }
  const specVersion = spec?.specVersion;
  if (!(typeof specVersion === "string" || typeof specVersion === "number") || String(specVersion).length === 0) {
    throw new Error("spec 缺 specVersion");
  }

  const locale = f.locale ?? "en";
  if (!LOCALE_RE.test(locale)) throw new Error(`locale 不合法（须匹配 ${LOCALE_RE}）: "${locale}"`);

  // dist 基准：存在 <dist>/<locale>/index.html 则整目录基准切换到该子目录。
  const distArg = path.resolve(f.dist);
  if (!existsSync(distArg) || !statSync(distArg).isDirectory()) throw new Error(`dist 目录不存在: ${distArg}`);
  let distRoot = distArg;
  if (existsSync(path.join(distArg, locale, "index.html"))) distRoot = path.join(distArg, locale);
  const entryHtmlPath = path.join(distRoot, "index.html");
  if (!existsSync(entryHtmlPath) || !statSync(entryHtmlPath).isFile()) {
    throw new Error(`dist 缺少入口 index.html: ${entryHtmlPath}`);
  }

  // 有效上限 = min(渠道 maxBytes, spec override)；override 只许收紧不许放宽。
  let maxBytes = ch.maxBytes;
  const override = spec?.channels?.overrides?.[channel]?.maxBytes;
  if (override !== undefined && override !== null) {
    if (typeof override !== "number" || !Number.isFinite(override) || override <= 0) {
      throw new Error(`spec.channels.overrides.${channel}.maxBytes 须为 >0 数值，得到 ${JSON.stringify(override)}`);
    }
    if (override > ch.maxBytes) {
      throw new Error(`spec override（${override} B）不得放宽渠道上限（${ch.maxBytes} B）`);
    }
    maxBytes = override;
  }

  const minify = !f["no-minify"];
  const mode = ch.package.format === "zip" ? "extract" : "inline";
  const bundleName = mode === "extract" ? ch.package.structure[0] : undefined;
  const injectScripts = ch.runtime?.injectRelativeScripts ?? [];
  const warnings = [];

  const html0 = readFileSync(entryHtmlPath, "utf8");
  const { html, scripts } = await processHtml({
    html: html0, distRoot, baseDir: distRoot, mode, bundleName, injectScripts, minify, warnings,
  });

  // 外链扫描：HTML 与 bundle 文本分别扫，白名单外命中即失败。
  const whitelist = [specText(spec?.flow?.endScreen?.landingUrl), ...(ch.allowedUrlWhitelist ?? [])].filter(Boolean);
  const texts = [html];
  let bundleBuf = null;
  if (mode === "extract") {
    const bundle = scripts.map((s) => s.code).join("\n;\n");
    bundleBuf = Buffer.from(bundle, "utf8");
    texts.push(bundle);
  }
  const leaks = [];
  for (const t of texts) leaks.push(...scanExternalUrls(t, whitelist));
  if (leaks.length > 0) {
    throw new Error(`发现白名单外外链 ${leaks.length} 处: ${leaks.slice(0, 3).join(" ; ")}`);
  }

  // MRAID 禁用（forbidMraid 渠道产物全词命中即失败）。
  if (ch.runtime?.forbidMraid) {
    for (const t of texts) {
      const hit = scanMraid(t);
      if (hit) throw new Error(`forbidMraid 渠道产物含 MRAID 引用: "${hit}"`);
    }
  }

  // 组包（全部在内存中完成检查后再落盘——失败不出半成品）。
  const outDir = path.resolve(f.out ?? path.join(process.cwd(), "artifacts"), projectId, channel, locale);
  mkdirSync(outDir, { recursive: true });

  const files = [];
  let artifactPath;
  let totalBytes = 0;
  let zipBuf = null;
  let zipEntries = null;

  if (mode === "inline") {
    const buf = Buffer.from(html, "utf8");
    artifactPath = path.join(outDir, "index.html");
    files.push({ path: "index.html", bytes: buf.length, sha256: sha256(buf), role: "package" });
    totalBytes = buf.length;
  } else {
    const tplBuf = Buffer.from(html, "utf8");
    // 条目 = 规则 structure 顺序（恰 [bundle, entry]）。
    zipEntries = [[bundleName, bundleBuf], [ch.package.structure[1], tplBuf]];
    zipBuf = writeZip(zipEntries);
    const zipName = `${projectId}-${locale}.zip`;
    artifactPath = path.join(outDir, zipName);
    files.push({ path: zipName, bytes: zipBuf.length, sha256: sha256(zipBuf), role: "package" });
    files.push({ path: ch.package.structure[1], bytes: tplBuf.length, sha256: sha256(tplBuf), role: "entry-in-zip" });
    files.push({ path: bundleName, bytes: bundleBuf.length, sha256: sha256(bundleBuf), role: "bundle-in-zip" });
    totalBytes = zipBuf.length;
    if (zipEntries.length > ch.maxFiles) {
      throw new Error(`包内条目数 ${zipEntries.length} 超过 maxFiles=${ch.maxFiles}（渠道 ${channel}）`);
    }
  }

  if (totalBytes > maxBytes) {
    throw new Error(`产物 ${totalBytes} B 超过有效上限 ${maxBytes} B（渠道 ${channel}${maxBytes !== ch.maxBytes ? "，spec override 生效" : ""}）`);
  }
  const packageFiles = files.filter((x) => x.role === "package").map((x) => x.path);
  if (packageFiles.length > ch.maxFiles) {
    throw new Error(`包文件数 ${packageFiles.length} 超过 maxFiles=${ch.maxFiles}（渠道 ${channel}）`);
  }

  writeFileSync(artifactPath, mode === "inline" ? Buffer.from(html, "utf8") : zipBuf);

  const manifest = {
    packager: PKG_NAME,
    rulesVersion: rules.rulesVersion,
    channel,
    locale,
    project: projectId,
    specPath: specAbs,
    dist: distArg,
    maxBytes,
    packageFiles,
    files,
    warnings,
    totalBytes,
  };
  writeFileSync(path.join(outDir, "pack-manifest.json"), `${JSON.stringify(manifest, null, 2)}\n`);

  process.stdout.write(`${JSON.stringify({ ok: true, artifact: artifactPath, totalBytes, maxBytes })}\n`);
}

function cmdChannels(f) {
  const rulesPath = f.rules ? path.resolve(f.rules) : defaultRulesPath();
  const rules = loadRules(rulesPath); // validateRules 内部强制
  validateRules(rules, rulesPath);
  for (const id of Object.keys(rules.channels).sort()) {
    process.stdout.write(`${id}\t${rules.channels[id].package.format}\n`);
  }
}

function main() {
  const argv = process.argv.slice(2);
  const command = argv[0];
  if (command === undefined || command === "-h" || command === "--help") {
    process.stderr.write(`${usage()}\n`);
    process.exitCode = command === undefined ? 2 : 0;
    return;
  }
  let f;
  try {
    f = parseArgs(argv.slice(1));
  } catch (err) {
    if (err instanceof ParamError) {
      process.stderr.write(`pf-packager: ${err.message}\n`);
      process.exitCode = 2;
    } else {
      process.stderr.write(`pf-packager: ${String(err.message || err).split("\n")[0]}\n`);
      process.exitCode = 1;
    }
    return;
  }
  if (command === "build") {
    cmdBuild(f).catch((err) => {
      process.stderr.write(`pf-packager: ${String(err && err.message || err).split("\n")[0]}\n`);
      process.exitCode = 1;
    });
  } else if (command === "channels") {
    try {
      cmdChannels(f);
    } catch (err) {
      process.stderr.write(`pf-packager: ${String(err && err.message || err).split("\n")[0]}\n`);
      process.exitCode = 1;
    }
  } else {
    process.stderr.write(`pf-packager: 未知命令 "${command}"\n${usage()}\n`);
    process.exitCode = 2;
  }
}

main();

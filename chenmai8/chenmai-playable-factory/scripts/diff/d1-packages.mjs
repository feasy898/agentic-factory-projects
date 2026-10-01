#!/usr/bin/env node
// scripts/diff/d1-packages.mjs — 差分维度 F2：48 包双实现出包结构等价比对（决策 §3.2 F2 / §3.5 D 硬线辅助）。
//
// 对齐点（字节不等 ≠ FAIL，按硬线比对结构等价）：
//   - 包文件集/目录形状相等（排除质检侧车产物 report.json/report-*.png）
//   - pack-manifest.json：键集全等 + 语义字段全等（rulesVersion/channel/locale/project/
//     maxBytes/packageFiles/warnings/files[].path）；files[].bytes ±5%；sha256 预期不等（重写）
//   - 单 HTML：零外链、mraid 注入与渠道规则一致（meta 禁 mraid）、入口脚本形态
//     （PF_SPEC/PF_LOCALE/PF_ASSETS 标记、script/style 计数）、资源清单（data: URI 计数）、大小 ±5%
//   - zip：条目名+顺序精确相等（自研 central directory 顺序读取）、逐条目解压大小 ±5%、
//     系统 tar.exe 独立解包复核（独立读取器 + CRC 校验）
//   - 实现内两次构建字节一致：抽查 match3×en×applovin（双方各自 build+pack 两遍逐字节比对）
//
// 用法：node scripts/diff/d1-packages.mjs <oracleMatrixDir> <factoryMatrixDir> <outJson>
// 退出码：0 全部结构等价；1 有回归级差异；2 用法/环境错误。

import { spawnSync } from "node:child_process";
import { copyFileSync, existsSync, mkdirSync, readFileSync, readdirSync, rmSync, statSync, writeFileSync } from "node:fs";
import { basename, dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import process from "node:process";

const [, , oracleMatrix, factoryMatrix, outJson] = process.argv;
if (!oracleMatrix || !factoryMatrix || !outJson) {
  console.error("用法：node scripts/diff/d1-packages.mjs <oracleMatrixDir> <factoryMatrixDir> <outJson>");
  process.exit(2);
}
if (!existsSync(oracleMatrix) || !existsSync(join(factoryMatrix, "summary.json"))) {
  console.error("d1-packages: 输入矩阵目录不完整（oracle:", existsSync(oracleMatrix), " factory summary:", existsSync(join(factoryMatrix, "summary.json")), "）");
  process.exit(2);
}

const BSDTAR = process.env.PF_BSDTAR || "C:\\Windows\\System32\\tar.exe";
const FACTORY_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
const summary = JSON.parse(readFileSync(join(factoryMatrix, "summary.json"), "utf8"));
const cells = summary.cells;

// ---------------------------------------------------------------- 差异登记
const findings = []; // {cell, item, severity: equal|diff|regression, detail}
function reg(cell, item, severity, detail) {
  findings.push({ cell, item, severity, detail });
}

// ---------------------------------------------------------------- zip 读取器（central directory，零依赖）
export function zipEntries(buf) {
  // EOCD 从尾部扫描
  let eocd = -1;
  for (let i = buf.length - 22; i >= Math.max(0, buf.length - 22 - 65536); i--) {
    if (buf.readUInt32LE(i) === 0x06054b50) { eocd = i; break; }
  }
  if (eocd < 0) throw new Error("EOCD not found");
  const count = buf.readUInt16LE(eocd + 10);
  let off = buf.readUInt32LE(eocd + 16);
  const entries = [];
  for (let n = 0; n < count; n++) {
    if (buf.readUInt32LE(off) !== 0x02014b50) throw new Error(`bad central header @${off}`);
    const crc = buf.readUInt32LE(off + 16);
    const csize = buf.readUInt32LE(off + 20);
    const usize = buf.readUInt32LE(off + 24);
    const nameLen = buf.readUInt16LE(off + 28);
    const extraLen = buf.readUInt16LE(off + 30);
    const commentLen = buf.readUInt16LE(off + 32);
    const name = buf.toString("utf8", off + 46, off + 46 + nameLen);
    entries.push({ name, crc, csize, usize });
    off += 46 + nameLen + extraLen + commentLen;
  }
  return entries;
}

// ---------------------------------------------------------------- HTML 结构特征
function htmlFeatures(p) {
  const s = readFileSync(p, "utf8");
  const extRefs = [...s.matchAll(/(?:src|href)=["'](https?:\/\/[^"']+)["']/g)].map((m) => m[1]);
  return {
    bytes: statSync(p).size,
    scripts: (s.match(/<script/g) || []).length,
    styles: (s.match(/<style/g) || []).length,
    externalRefs: extRefs,
    mraid: /mraid/i.test(s),
    // mraid 判定用 script 标签注入（非运行时代码引用）：meta 渠道 forbidMraid，双方都只允许桥内引用
    mraidScriptTags: (s.match(/<script[^>]*mraid[^>]*>/gi) || []).length,
    pfSpec: s.includes("PF_SPEC"),
    pfLocale: s.includes("PF_LOCALE"),
    pfAssets: s.includes("PF_ASSETS"),
    viewport: /name=["']viewport["']/.test(s),
    canvas: s.includes("<canvas"),
    dataUri: (s.match(/src=["']data:/g) || []).length,
    pfReady: (s.match(/pf:ready/g) || []).length,
  };
}

function sizeOk(a, b, pct = 0.05) {
  if (a === 0 && b === 0) return true;
  return Math.abs(a - b) / Math.max(a, b) <= pct;
}

// ---------------------------------------------------------------- tar.exe 独立解包
function tarExtract(zipPath, destDir) {
  rmSync(destDir, { recursive: true, force: true });
  mkdirSync(destDir, { recursive: true });
  const r = spawnSync(BSDTAR, ["-xf", zipPath, "-C", destDir], { encoding: "utf8" });
  if (r.status !== 0) throw new Error(`tar 解包失败 exit=${r.status}: ${(r.stderr || "").trim()}`);
  const files = [];
  (function walk(d) {
    for (const e of readdirSync(d, { withFileTypes: true })) {
      const p = join(d, e.name);
      if (e.isDirectory()) walk(p);
      else files.push(relative(destDir, p).replaceAll("\\", "/"));
    }
  })(destDir);
  return files.sort();
}

// ---------------------------------------------------------------- 逐格比对
const perCell = [];
for (const cell of cells) {
  const id = `${cell.project}/${cell.locale}/${cell.channel}`;
  const oDir = join(oracleMatrix, cell.project, cell.channel, cell.locale);
  const nDir = join(factoryMatrix, cell.project, cell.channel, cell.locale);
  const rec = { cell: id, format: cell.format, items: [], equal: true, regression: false };
  const item = (name, ok, detail, hardFail = true) => {
    const severity = ok ? "equal" : (hardFail ? "regression" : "diff");
    rec.items.push({ item: name, severity, detail });
    if (!ok) { rec.equal = false; if (hardFail) rec.regression = true; }
  };

  if (!existsSync(oDir) || !existsSync(nDir)) {
    item("cell-dir-exists", false, `oracle=${existsSync(oDir)} factory=${existsSync(nDir)}`);
    perCell.push(rec); continue;
  }

  // 1) 包文件集（排除质检侧车）
  const pkgFiles = (d) => readdirSync(d).filter((f) => !/index\.report/.test(f)).sort();
  const oFiles = pkgFiles(oDir), nFiles = pkgFiles(nDir);
  item("package-file-set", JSON.stringify(oFiles) === JSON.stringify(nFiles), `oracle=[${oFiles}] factory=[${nFiles}]`);

  // 2) pack-manifest 字段语义
  const om = JSON.parse(readFileSync(join(oDir, "pack-manifest.json"), "utf8"));
  const nm = JSON.parse(readFileSync(join(nDir, "pack-manifest.json"), "utf8"));
  const keysO = Object.keys(om).sort(), keysN = Object.keys(nm).sort();
  item("manifest-key-set", JSON.stringify(keysO) === JSON.stringify(keysN), `oracle=[${keysO}] factory=[${keysN}]`);
  for (const k of ["packager", "rulesVersion", "channel", "locale", "project", "maxBytes", "packageFiles", "warnings"]) {
    item(`manifest.${k}`, JSON.stringify(om[k]) === JSON.stringify(nm[k]),
      `oracle=${JSON.stringify(om[k])} factory=${JSON.stringify(nm[k])}`);
  }
  item("manifest.files.length", om.files?.length === nm.files?.length, `oracle=${om.files?.length} factory=${nm.files?.length}`);
  const len = Math.min(om.files?.length ?? 0, nm.files?.length ?? 0);
  for (let i = 0; i < len; i++) {
    const fo = om.files[i], fn = nm.files[i];
    item(`manifest.files[${i}].path`, fo.path === fn.path, `oracle=${fo.path} factory=${fn.path}`);
    item(`manifest.files[${i}].bytes±5%`, sizeOk(fo.bytes, fn.bytes), `oracle=${fo.bytes} factory=${fn.bytes} delta=${(100 * Math.abs(fo.bytes - fn.bytes) / Math.max(fo.bytes, fn.bytes, 1)).toFixed(3)}%`);
    item(`manifest.files[${i}].role`, fo.role === fn.role, `oracle=${fo.role} factory=${fn.role}`);
  }
  // specPath/dist 绝对路径随仓根迁移（预期环境差异，不判回归，登记）
  if (om.specPath !== nm.specPath) reg(id, "manifest.specPath", "diff", `仓根迁移：oracle=${basename(om.specPath)}@repo factory=${basename(nm.specPath)}@factory（basename 相等=${basename(om.specPath) === basename(nm.specPath)}）`);

  // 3) 产物本体
  const entryName = cell.format === "zip" ? `${cell.project}-${cell.locale}.zip` : "index.html";
  const oArtifact = join(oDir, entryName), nArtifact = join(nDir, entryName);
  if (!existsSync(oArtifact) || !existsSync(nArtifact)) {
    item("artifact-exists", false, `oracle=${existsSync(oArtifact)} factory=${existsSync(nArtifact)}`);
    perCell.push(rec); continue;
  }
  const oBytes = statSync(oArtifact).size, nBytes = statSync(nArtifact).size;
  item("artifact-bytes±5%", sizeOk(oBytes, nBytes),
    `oracle=${oBytes} factory=${nBytes} delta=${(100 * Math.abs(oBytes - nBytes) / Math.max(oBytes, nBytes)).toFixed(3)}%`);
  const sha = (p) => import("node:crypto").then((c) => c.createHash("sha256").update(readFileSync(p)).digest("hex"));
  const oSha = await sha(oArtifact), nSha = await sha(nArtifact);
  rec.sha256 = { oracle: oSha, factory: nSha, byteEqual: oSha === nSha };
  if (oSha !== nSha) reg(id, "artifact-bytes", "diff", `字节不等（预期内：模板重写；结构等价见以下各项）`);

  let oEntryHtml = oArtifact, nEntryHtml = nArtifact;
  if (cell.format === "zip") {
    // 条目名+顺序精确相等
    const oz = zipEntries(readFileSync(oArtifact)), nz = zipEntries(readFileSync(nArtifact));
    const oSeq = oz.map((e) => e.name), nSeq = nz.map((e) => e.name);
    item("zip-entry-sequence", JSON.stringify(oSeq) === JSON.stringify(nSeq), `oracle=[${oSeq.join(",")}] factory=[${nSeq.join(",")}]`);
    const m = Math.min(oz.length, nz.length);
    for (let i = 0; i < m; i++) {
      item(`zip-entry[${i}].usize±5%`, sizeOk(oz[i].usize, nz[i].usize),
        `${oz[i].name}: oracle=${oz[i].usize} factory=${nz[i].usize}`);
    }
    // tar.exe 独立解包复核（CRC/完整性）
    try {
      const oEx = tarExtract(oArtifact, join(oDir, "_difftmp"));
      const nEx = tarExtract(nArtifact, join(nDir, "_difftmp"));
      item("tar-extract-ok", true, `oracle files=[${oEx}] factory files=[${nEx}]`);
      item("tar-extract-file-set", JSON.stringify(oEx) === JSON.stringify(nEx), `oracle=[${oEx}] factory=[${nEx}]`);
      const rules = JSON.parse(readFileSync(join(FACTORY_ROOT, "channel-rules", "channel-rules.json"), "utf8"));
      const entryHtml = rules.channels[cell.channel]?.package?.entry || "index.html";
      oEntryHtml = join(oDir, "_difftmp", entryHtml);
      nEntryHtml = join(nDir, "_difftmp", entryHtml);
      if (!existsSync(oEntryHtml) || !existsSync(nEntryHtml)) {
        item("zip-entry-html-exists", false, `entry=${entryHtml} oracle=${existsSync(oEntryHtml)} factory=${existsSync(nEntryHtml)}`);
      }
    } catch (e) {
      item("tar-extract-ok", false, String(e));
    }
  }

  // 4) 入口 HTML 结构等价（单 HTML 或 zip 入口）
  if (existsSync(oEntryHtml) && existsSync(nEntryHtml)) {
    const fo = htmlFeatures(oEntryHtml), fn = htmlFeatures(nEntryHtml);
    item("html.zero-external-refs", fo.externalRefs.length === 0 && fn.externalRefs.length === 0,
      `oracle=${JSON.stringify(fo.externalRefs)} factory=${JSON.stringify(fn.externalRefs)}`);
    item("html.mraid-consistent", fo.mraid === fn.mraid, `oracle=${fo.mraid} factory=${fn.mraid}`);
    if (cell.channel === "meta") item("html.meta-forbid-mraid(stub-inject)", fo.mraidScriptTags === 0 && fn.mraidScriptTags === 0, `oracle mraid<script>=${fo.mraidScriptTags} factory mraid<script>=${fn.mraidScriptTags}（桥内引用两侧一致：${fo.mraid === fn.mraid}）`);
    if (cell.channel === "applovin") item("html.applovin-mraid-stub", fo.mraidScriptTags === 1 && fn.mraidScriptTags === 1, `oracle=${fo.mraidScriptTags} factory=${fn.mraidScriptTags}`);
    item("html.entry-script-markers", fo.pfSpec && fo.pfLocale && fo.pfAssets && fn.pfSpec && fn.pfLocale && fn.pfAssets,
      `oracle=(spec:${fo.pfSpec},locale:${fo.pfLocale},assets:${fo.pfAssets}) factory=(spec:${fn.pfSpec},locale:${fn.pfLocale},assets:${fn.pfAssets})`);
    item("html.script-count", fo.scripts === fn.scripts, `oracle=${fo.scripts} factory=${fn.scripts}`);
    item("html.style-count", fo.styles === fn.styles, `oracle=${fo.styles} factory=${fn.styles}`);
    item("html.resource-manifest(data-uri,canvas,pfReady)", fo.dataUri === fn.dataUri && fo.canvas === fn.canvas && fo.pfReady === fn.pfReady,
      `oracle=(data:${fo.dataUri},canvas:${fo.canvas},ready:${fo.pfReady}) factory=(data:${fn.dataUri},canvas:${fn.canvas},ready:${fn.pfReady})`);
    item("html.viewport", fo.viewport === fn.viewport, `oracle=${fo.viewport} factory=${fn.viewport}`);
    rec.html = { oracle: fo, factory: fn };
  }

  perCell.push(rec);
  for (const it of rec.items) if (it.severity !== "equal") reg(id, it.item, it.severity, it.detail);
  rmSync(join(oDir, "_difftmp"), { recursive: true, force: true });
  rmSync(join(nDir, "_difftmp"), { recursive: true, force: true });
}

// ---------------------------------------------------------------- 实现内两次构建字节一致（抽查 match3×en×applovin）
const repro = [];
const REPRO_BASE = join(FACTORY_ROOT, "tmp", "diff", "repro");
async function reproCheck(label, root, specRel) {
  const build = join(root, "packages", "templates", "tmpl-match3", "build.mjs");
  const packager = join(root, "packages", "packager", "bin.mjs");
  const specAbs = join(root, "specs-eval", specRel);
  const mk = (i) => join(REPRO_BASE, `${label}-${i}`);
  const runs = [];
  const outDir = mk(0); // 两次同路径：pack-manifest 记录 dist/specPath 绝对路径，实现内字节一致性须同路径对比
  for (const i of [1, 2]) {
    rmSync(outDir, { recursive: true, force: true });
    mkdirSync(join(outDir, "dist", "en"), { recursive: true });
    const prev = join(outDir, "preview.html");
    const b = spawnSync(process.execPath, [build, "--spec", specAbs, "--locale", "en", "--out", prev], { cwd: root, encoding: "utf8", windowsHide: true });
    if (b.status !== 0) { runs.push({ i, error: `build exit ${b.status}: ${(b.stderr || b.stdout || "").slice(-200)}` }); break; }
    copyFileSync(prev, join(outDir, "dist", "en", "index.html"));
    const p = spawnSync(process.execPath, [packager, "build", "--spec", specAbs, "--dist", join(outDir, "dist"), "--channel", "applovin", "--locale", "en", "--out", outDir], { cwd: root, encoding: "utf8", windowsHide: true });
    if (p.status !== 0) { runs.push({ i, error: `pack exit ${p.status}: ${(p.stderr || p.stdout || "").slice(-200)}` }); break; }
    const c = await import("node:crypto");
    const html = c.createHash("sha256").update(readFileSync(join(outDir, "golden-match3", "applovin", "en", "index.html"))).digest("hex");
    const man = c.createHash("sha256").update(readFileSync(join(outDir, "golden-match3", "applovin", "en", "pack-manifest.json"))).digest("hex");
    runs.push({ i, htmlSha: html, manifestSha: man });
  }
  const ok = runs.length === 2 && runs[0].htmlSha && runs[0].htmlSha === runs[1].htmlSha && runs[0].manifestSha === runs[1].manifestSha;
  repro.push({ impl: label, ok, runs });
  return ok;
}
const reproOk = (await reproCheck("oracle", join(FACTORY_ROOT, "..", "repo"), "golden-match3.json"))
  & (await reproCheck("factory", FACTORY_ROOT, "golden-match3.json"));
if (!reproOk) reg("repro-check", "intra-impl-byte-reproducibility", "regression", "实现内两次构建字节不一致（见 evidence.repro）");

// ---------------------------------------------------------------- 汇总
const regressions = findings.filter((f) => f.severity === "regression");
const diffs = findings.filter((f) => f.severity === "diff");
const evidence = {
  capturedAt: new Date().toISOString(),
  inputs: { oracleMatrix, factoryMatrix, cells: cells.length },
  perCell, repro,
  findings, regressions, diffs,
  verdict: regressions.length === 0 ? "PASS（零回归）" : "FAIL（存在回归）",
};
mkdirSync(join(FACTORY_ROOT, "tmp", "diff"), { recursive: true });
writeFileSync(outJson, JSON.stringify(evidence, null, 2) + "\n", "utf8");
console.log(`d1-packages: cells=${perCell.length} byteEqual=${perCell.filter((r) => r.sha256?.byteEqual).length} regressions=${regressions.length} diffs=${diffs.length}`);
for (const r of regressions) console.error(`  回归 ${r.cell} ${r.item}: ${r.detail}`);
for (const d of diffs) console.log(`  登记差异 ${d.cell} ${d.item}: ${d.detail}`);
console.log(`d1-packages: ${evidence.verdict} → ${outJson}`);
process.exit(regressions.length === 0 ? 0 : 1);

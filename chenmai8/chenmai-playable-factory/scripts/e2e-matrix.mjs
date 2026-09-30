#!/usr/bin/env node
// e2e-matrix.mjs — 端到端矩阵门（oracle scripts/e2e_matrix.py 语义移植；宿主 = node）。
//
// golden spec × 语言 × 冻结投放渠道的「构建→打包→逐包质检」全矩阵真实执行，0 FAIL 才放行。
// 用法：node scripts/e2e-matrix.mjs [--quick] [--budget-sec N] [--locales en,zh] [--channels ...]
//        [--out artifacts/matrix] [--jobs 0]
//
//   --quick：仅 golden-match3 × en × 规则库冻结投放渠道（六渠道，随规则库扩缩自动跟随），
//            每日冒烟门，硬预算 ≤90 秒（超预算即 exit 1）；不启用抖动重跑。
//   全量（缺省）：specs-eval 全部 golden-*.json × {en,zh} × 冻结投放渠道。
//            四模板齐后 = 4 模板 × 2 语言 × 6 渠道 = 48 包，0 FAIL 为验收线；
//            决策硬预算 ≤1200s（gate-m2 以 --budget-sec 1200 断言；裸跑不设限只打印）。
//   抖动单重试（仅全量）：首检 FAIL 的格用同一判官（同一冻结检查链）至多重跑一次，
//            以重跑结果为最终判定——只吸收瞬态负载抖动；两跑皆 FAIL 仍判 FAIL
//            （质检是唯一裁判不变）。重跑计入总墙钟；summary 逐格 retried/firstAttemptFails 留痕。
//   --jobs（宿主注记，2026-09-30 实测登记）：缺省 4 沿用 oracle；本机为多代理共享
//            （多核常驻 100%），jobs=4 时 4 路 chromium 并发把冻结的 CHK09 加载墙钟
//            顶破（load_ms 3.4-8.4s vs 2.0s，readyMs 同步膨胀——单格 canary 777ms 证明
//            非产物缺陷）。共享机上建议 --jobs 2：48 包 921.8s ≤1200s 全绿
//            （20 格单重试后过，summary retried 留痕）；断言面不随 jobs 变化。
//
// 与 pf make 同一条真实链路：模板构建器（tmpl-*/build.mjs）→ 打包器（packager/bin.mjs）→
// 判官（qacore/cli.mjs run --autoplay，质检是唯一裁判）。zip 渠道产物先经系统 bsdtar
// 解包到 extract/，对规则库声明的入口 HTML 跑质检——判官只收单 HTML。
// 产物布局（--out 缺省 artifacts/matrix）：preview/ · <project>/dist/<locale>/ ·
// <project>/<channel>/<locale>/（含 index.report.json）· extract/ · summary.json。
// 退出码：0 全部通过（含预算内）；1 有 fail/error 或超预算；2 用法/环境错误。

import { spawn, spawnSync } from "node:child_process";
import { copyFileSync, existsSync, mkdirSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import process from "node:process";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const RULES_PATH = join(ROOT, "channel-rules", "channel-rules.json");
const PACKAGER_BIN = join(ROOT, "packages", "packager", "bin.mjs");
const QACORE_CLI = join(ROOT, "qacore", "cli.mjs");
const PF_CLI = join(ROOT, "pf", "pf.mjs");
const SPECS_DIR = join(ROOT, "specs-eval");
const PREVIEW_CHANNEL = "preview"; // 规则库中的本地渠道，不进投放矩阵
const BSDTAR = process.env.PF_BSDTAR || "C:\\Windows\\System32\\tar.exe";

// spec.game.template → 模板构建脚本（与 pf make 同表；无构建器的模板其格记 skip 并如实
// 给原因，绝不算通过）。四模板齐后全量矩阵不再有 skip 格。
const TEMPLATE_BUILDERS = {
  match3: join(ROOT, "packages", "templates", "tmpl-match3", "build.mjs"),
  merge: join(ROOT, "packages", "templates", "tmpl-merge", "build.mjs"),
  pullpin: join(ROOT, "packages", "templates", "tmpl-pullpin", "build.mjs"),
  sort: join(ROOT, "packages", "templates", "tmpl-sort", "build.mjs"),
};

class MatrixError extends Error {
  constructor(message, exitCode = 1) {
    super(message);
    this.exitCode = exitCode;
  }
}

function log(msg) {
  console.log(`[matrix] ${msg}`);
}

function runSync(cmd, label, { timeoutSec = 300 } = {}) {
  const proc = spawnSync(cmd[0], cmd.slice(1), {
    cwd: ROOT, encoding: "utf8", timeout: timeoutSec * 1000, windowsHide: true,
    maxBuffer: 64 * 1024 * 1024,
  });
  if (proc.error) throw new MatrixError(`${label} 启动失败：${String(proc.error)}`, 1);
  if (proc.status !== 0) {
    const tail = ((proc.stderr ?? "") || (proc.stdout ?? "")).trim().split(/\r?\n/).slice(-10).join("\n");
    throw new MatrixError(`${label} 失败（exit ${proc.status}）\n${tail || "(无输出)"}`, 1);
  }
  return proc.stdout ?? "";
}

// ---------------------------------------------------------------- 矩阵展开

function loadRules() {
  try {
    return JSON.parse(readFileSync(RULES_PATH, "utf8"));
  } catch (err) {
    throw new MatrixError(`规则库不可读：${RULES_PATH}（${String(err)}）`, 2);
  }
}

function discoverChannels(rules) {
  const channels = Object.keys(rules.channels ?? {}).filter((c) => c !== PREVIEW_CHANNEL);
  if (channels.length === 0) throw new MatrixError("规则库没有任何投放渠道", 2);
  return channels;
}

function discoverSpecs(quick) {
  if (quick) {
    const spec = join(SPECS_DIR, "golden-match3.json");
    if (!existsSync(spec)) throw new MatrixError(`--quick 缺指定 spec：${spec}`, 2);
    return [spec];
  }
  const specs = readdirSync(SPECS_DIR).filter((n) => n.startsWith("golden-") && n.endsWith(".json"))
    .sort().map((n) => join(SPECS_DIR, n));
  if (specs.length === 0) throw new MatrixError(`${SPECS_DIR} 下无 golden-*.json`, 2);
  return specs;
}

function specLocales(spec) {
  return ((spec.i18n ?? {}).locales ?? []).map(String);
}

function matrixCells(specs, locales, channels) {
  const cells = [];
  for (const specPath of specs) {
    let spec;
    try {
      spec = JSON.parse(readFileSync(specPath, "utf8"));
    } catch (err) {
      throw new MatrixError(`spec 不可读：${specPath}（${String(err)}）`, 2);
    }
    const project = String((spec.meta ?? {}).projectId ?? specPath.split(/[\\/]/).pop().replace(/\.json$/, ""));
    const template = String((spec.game ?? {}).template ?? "");
    const builder = TEMPLATE_BUILDERS[template];
    if (builder === undefined || !existsSync(builder)) {
      log(`SKIP ${specPath.split(/[\\/]/).pop()}：模板 '${template}' 无真实构建器（现有：${Object.keys(TEMPLATE_BUILDERS).sort().join(", ")}）`);
      cells.push({ spec: specPath, project, template, locale: "-", channel: "-", skip: `模板 '${template}' 无真实构建器` });
      continue;
    }
    const declared = new Set(specLocales(spec));
    for (const locale of locales) {
      if (!declared.has(locale)) {
        log(`SKIP ${specPath.split(/[\\/]/).pop()}×${locale}：spec 未声明该语言（${[...declared].sort()}）`);
        cells.push({ spec: specPath, project, template, locale, channel: "-", skip: `spec 未声明语言 ${locale}` });
        continue;
      }
      for (const channel of channels) {
        cells.push({ spec: specPath, project, template, locale, channel, skip: null });
      }
    }
  }
  return cells;
}

// ---------------------------------------------------------------- 阶段 A-C：构建与打包

function phaseBuild(cells, outRoot) {
  const builds = new Map(); // "spec\u0000locale" → {preview, dist, sprites}
  for (const cell of cells) {
    if (cell.skip) continue;
    const key = `${cell.spec}\u0000${cell.locale}`;
    if (builds.has(key)) continue;
    const previewHtml = join(outRoot, "preview", `${cell.project}-${cell.locale}.html`);
    mkdirSync(dirname(previewHtml), { recursive: true });
    runSync(["node", TEMPLATE_BUILDERS[cell.template],
      "--spec", cell.spec, "--locale", cell.locale, "--out", previewHtml],
      `模板构建 ${cell.spec.split(/[\\/]/).pop()}×${cell.locale}`);
    const distLocale = join(outRoot, cell.project, "dist", cell.locale);
    mkdirSync(distLocale, { recursive: true });
    copyFileSync(previewHtml, join(distLocale, "index.html"));
    builds.set(key, {
      preview: previewHtml,
      dist: dirname(distLocale),
      sprites: requiredSpritesFor(previewHtml),
    });
    log(`构建 OK：${cell.project}×${cell.locale}（${statSync(previewHtml).size.toLocaleString("en-US")}B）`);
  }
  return builds;
}

function phasePack(cells, builds, outRoot) {
  const rules = loadRules();
  const rulesChannels = rules.channels ?? {};
  const packed = new Map(); // "spec\u0000locale\u0000channel" → {artifact, qaTarget, format, bytes, maxBytes, cellDir}
  for (const cell of cells) {
    if (cell.skip) continue;
    const b = builds.get(`${cell.spec}\u0000${cell.locale}`);
    const entryRules = rulesChannels[cell.channel]?.package ?? {};
    const fmt = String(entryRules.format ?? "single-html");
    runSync(["node", PACKAGER_BIN, "build",
      "--spec", cell.spec, "--dist", b.dist,
      "--channel", cell.channel, "--locale", cell.locale, "--out", outRoot],
      `打包 ${cell.channel}/${cell.locale}`);
    const cellDir = join(outRoot, cell.project, cell.channel, cell.locale);
    let artifact;
    if (fmt === "zip") {
      artifact = readdirSync(cellDir).map((n) => join(cellDir, n))
        .filter((p) => p.endsWith(".zip") && statSync(p).isFile())[0] ?? null;
    } else {
      artifact = join(cellDir, "index.html");
    }
    if (artifact === null || !existsSync(artifact)) {
      throw new MatrixError(`打包 ${cell.channel}/${cell.locale} 后未找到产物（${cellDir}）`, 1);
    }
    let qaTarget = artifact;
    if (fmt === "zip") {
      const entry = String(entryRules.entry ?? "Template.html");
      const extractDir = join(outRoot, "extract", `${cell.project}-${cell.locale}-${cell.channel}`);
      rmSync(extractDir, { recursive: true, force: true });
      mkdirSync(extractDir, { recursive: true });
      // 独立读取器 = 系统 bsdtar（P5 同款；Git GNU tar 不能读 zip，按绝对路径定位）
      runSync([BSDTAR, "-xf", artifact, "-C", extractDir], `zip 解包 ${cell.channel}/${cell.locale}`);
      qaTarget = join(extractDir, entry);
      if (!existsSync(qaTarget)) {
        const hits = findHtmls(extractDir).sort();
        if (hits.length === 0) throw new MatrixError(`zip ${artifact.split(/[\\/]/).pop()} 内无 HTML 可质检`, 1);
        qaTarget = hits[0];
      }
    }
    packed.set(`${cell.spec}\u0000${cell.locale}\u0000${cell.channel}`, {
      artifact, qaTarget, format: fmt,
      bytes: statSync(artifact).size,
      maxBytes: rulesChannels[cell.channel]?.maxBytes ?? null,
      cellDir,
    });
    log(`打包 OK：${cell.channel}/${cell.locale} ${artifact.split(/[\\/]/).pop()} ${statSync(artifact).size.toLocaleString("en-US")}B（${fmt}）`);
  }
  return packed;
}

function findHtmls(dir) {
  const out = [];
  const walk = (d) => {
    let entries;
    try {
      entries = readdirSync(d, { withFileTypes: true });
    } catch {
      return;
    }
    for (const e of entries) {
      const p = join(d, e.name);
      if (e.isDirectory()) walk(p);
      else if (e.isFile() && e.name.endsWith(".html")) out.push(p);
    }
  };
  walk(dir);
  return out;
}

// ---------------------------------------------------------------- CHK10 判定输入（与 pf make 同源）

function requiredTextsFor(spec, locale) {
  const loc = (key) => {
    const v = spec.i18n?.strings?.[locale]?.[key];
    return typeof v === "string" ? v : "";
  };
  const flow = spec.flow ?? {};
  const endScreen = flow.endScreen ?? {};
  const texts = [String(spec.meta?.title ?? "")];
  if ((flow.tutorial ?? { enabled: true }).enabled !== false) texts.push(loc("tutorial"));
  texts.push(loc("win"));
  texts.push(loc(String(endScreen.ctaKey ?? "cta")));
  if ((endScreen.showScore ?? true) !== false) texts.push(loc("score"));
  return texts.filter((t) => t.length > 0);
}

function requiredSpritesFor(previewHtml) {
  try {
    const mf = JSON.parse(readFileSync(`${previewHtml}.assets.json`, "utf8"));
    return (mf.sprites ?? []).map((s) => String(s.spriteKey ?? "")).filter((k) => k.length > 0);
  } catch {
    return []; // 旁车缺失/不可读 → 不提要求（构建日志已对缺失素材告警）
  }
}

// ---------------------------------------------------------------- 阶段 D：逐包质检（可并行）

/** 异步子进程（并行质检用——spawnSync 会阻塞事件循环使并行退化为串行）。 */
function runAsync(cmd, timeoutMs = 600_000) {
  return new Promise((res) => {
    const child = spawn(cmd[0], cmd.slice(1), {
      cwd: ROOT, timeout: timeoutMs, windowsHide: true,
    });
    let out = "";
    let err = "";
    child.stdout.on("data", (d) => { out += d; });
    child.stderr.on("data", (d) => { err += d; });
    child.on("error", (e) => res({ status: null, stdout: out, stderr: String(e) }));
    child.on("close", (code) => res({ status: code, stdout: out, stderr: err }));
  });
}

async function qaOne(cell, packed, builds, outRoot) {
  const spec = JSON.parse(readFileSync(cell.spec, "utf8"));
  const qc = spec.qc ?? {};
  const locale = cell.locale;
  const channel = cell.channel;
  const info = packed.get(`${cell.spec}\u0000${locale}\u0000${channel}`);
  const reportPath = join(info.cellDir, "index.report.json");
  const cmd = [process.execPath, QACORE_CLI, "run", info.qaTarget,
    "--channel", channel, "--autoplay",
    "--max-load-sec", String(qc.maxLoadSec ?? 2.0),
    "--autoplay-timeout", String(qc.autoplayTimeoutSec ?? 45.0),
    "--out", reportPath];
  for (const t of requiredTextsFor(spec, locale)) cmd.push("--require-text", t);
  for (const k of builds.get(`${cell.spec}\u0000${locale}`).sprites) cmd.push("--require-sprite", k);

  const t0 = performance.now();
  const proc = await runAsync(cmd);
  const wall = (performance.now() - t0) / 1000;
  const rel = (p) => p.slice(outRoot.length + 1).replaceAll("\\", "/");
  const rec = {
    spec: cell.spec.split(/[\\/]/).pop(), project: cell.project,
    locale, channel, format: info.format,
    artifact: rel(info.artifact),
    bytes: info.bytes, maxBytes: info.maxBytes,
    report: rel(reportPath), wallSec: Math.round(wall * 10) / 10,
    status: "fail", fails: [], pfEnd: null, endWin: null,
  };
  if (proc.error || proc.status !== 0) {
    const tail = ((proc.stderr ?? "") || (proc.stdout ?? "")).trim().split(/\r?\n/).slice(-6).join("\n");
    rec.fails = [`qacore exit ${proc.status}：${tail}`];
    return rec;
  }
  let report;
  try {
    report = JSON.parse(readFileSync(reportPath, "utf8"));
  } catch (err) {
    rec.fails = [`质检报告不可读：${String(err)}`];
    return rec;
  }
  const checks = report.checks ?? [];
  rec.fails = checks.filter((c) => c.status === "fail").map((c) => `${c.id}: ${c.detail ?? ""}`);
  rec.checks = {
    pass: checks.filter((c) => c.status === "pass").length,
    fail: rec.fails.length,
    skip: checks.filter((c) => c.status === "skip").length,
  };
  rec.pfEnd = (report.pf ?? {}).endMs ?? null;
  rec.endWin = (report.pf ?? {}).endWin ?? null;
  rec.status = rec.fails.length === 0 ? "pass" : "fail";
  return rec;
}

async function runPool(items, jobs, worker) {
  const results = new Array(items.length);
  let next = 0;
  const lanes = Array.from({ length: Math.max(1, Math.min(jobs, items.length)) }, async () => {
    for (;;) {
      const i = next++;
      if (i >= items.length) return;
      results[i] = await worker(items[i]);
    }
  });
  await Promise.all(lanes);
  return results;
}

async function phaseQa(cells, packed, builds, outRoot, jobs, allowRetry) {
  const work = cells.filter((c) => !c.skip);
  const t0 = performance.now();
  let results = await runPool(work, Math.max(1, jobs), (c) => qaOne(c, packed, builds, outRoot));
  if (allowRetry) {
    const failedIdx = results.map((r, i) => (r.status === "fail" ? i : -1)).filter((i) => i >= 0);
    if (failedIdx.length > 0) {
      const names = failedIdx.map((i) => `${results[i].spec}×${results[i].locale}×${results[i].channel}`).join("、");
      log(`首检 ${failedIdx.length} 格 FAIL，抖动单重试：重跑同一判官 → ${names}`);
      const retryRecs = await runPool(failedIdx.map((i) => work[i]), Math.max(1, jobs),
        (c) => qaOne(c, packed, builds, outRoot));
      for (let k = 0; k < failedIdx.length; k++) {
        const r2 = retryRecs[k];
        r2.retried = true;
        r2.firstAttemptFails = results[failedIdx[k]].fails;
        results[failedIdx[k]] = r2;
      }
    }
  }
  results = results.filter(Boolean);
  const nRetried = results.filter((r) => r.retried).length;
  log(`质检完成：${results.length} 包并行度 ${jobs}（含单重试 ${nRetried} 格），阶段墙钟 ${((performance.now() - t0) / 1000).toFixed(1)}s`);
  return results;
}

// ---------------------------------------------------------------- 汇总

function writeSummary(outRoot, mode, results, skips, wallSec, budgetSec) {
  const summary = {
    generatedAt: new Date().toISOString().slice(0, 19),
    mode,
    wallSec: Math.round(wallSec * 10) / 10,
    budgetSec,
    totals: {
      cells: results.length + skips.length,
      pass: results.filter((r) => r.status === "pass").length,
      fail: results.filter((r) => r.status === "fail").length,
      skip: skips.length,
      retried: results.filter((r) => r.retried).length,
    },
    cells: [...results, ...skips],
  };
  const path = join(outRoot, "summary.json");
  writeFileSync(path, `${JSON.stringify(summary, null, 2)}\n`, "utf8");
  return path;
}

function printTable(results, skips) {
  console.log("-".repeat(78));
  console.log(`${"spec".padEnd(22)}${"locale".padEnd(7)}${"channel".padEnd(11)}${"bytes".padStart(10)}${"上限".padStart(10)}  ${"结果".padEnd(6)}${"质检墙钟".padStart(8)}`);
  for (const r of [...results].sort((a, b) =>
    a.spec.localeCompare(b.spec) || a.locale.localeCompare(b.locale) || a.channel.localeCompare(b.channel))) {
    const limit = typeof r.maxBytes === "number" ? r.maxBytes.toLocaleString("en-US") : "-";
    const verdict = r.status + (r.retried ? "*" : ""); // * = 单重试后过
    console.log(`${r.spec.padEnd(22)}${r.locale.padEnd(7)}${r.channel.padEnd(11)}`
      + `${r.bytes.toLocaleString("en-US").padStart(10)}${limit.padStart(10)}  ${verdict.padEnd(6)}${r.wallSec.toFixed(1).padStart(7)}s`);
  }
  for (const s of skips) {
    console.log(`${s.spec.split(/[\\/]/).pop().padEnd(22)}${s.locale.padEnd(7)}${s.channel.padEnd(11)}${"-".padStart(10)}${"-".padStart(10)}  SKIP   （${s.skip}）`);
  }
  console.log("-".repeat(78));
}

// ---------------------------------------------------------------- 主流程

function parseArgs(argv) {
  const o = { quick: false, locales: null, channels: null, out: "artifacts/matrix", budgetSec: null, jobs: 0 };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--quick") o.quick = true;
    else if (a === "--locales") o.locales = argv[++i];
    else if (a === "--channels") o.channels = argv[++i];
    else if (a === "--out") o.out = argv[++i];
    else if (a === "--budget-sec") o.budgetSec = Number(argv[++i]);
    else if (a === "--jobs") o.jobs = Number.parseInt(argv[++i], 10);
    else throw new MatrixError(`未知参数：${a}`, 2);
  }
  return o;
}

async function runMatrix(args) {
  const t0 = performance.now();
  const quick = Boolean(args.quick);
  const locales = (args.locales ? args.locales.split(",").map((x) => x.trim()).filter(Boolean) : null)
    ?? (quick ? ["en"] : ["en", "zh"]);
  const rules = loadRules();
  const channels = (args.channels ? args.channels.split(",").map((x) => x.trim()).filter(Boolean) : null)
    ?? discoverChannels(rules);
  const specs = discoverSpecs(quick);
  const budget = args.budgetSec ?? (quick ? 90.0 : 0.0);
  const jobs = args.jobs > 0 ? args.jobs : 4;

  const outRoot = /^([A-Za-z]:[\\/]|\/)/.test(args.out) ? resolve(args.out) : join(ROOT, args.out);
  mkdirSync(outRoot, { recursive: true });

  console.log("=".repeat(78));
  log(`端到端矩阵门 mode=${quick ? "quick" : "full"} specs=[${specs.map((s) => s.split(/[\\/]/).pop()).join(", ")}] `
    + `locales=[${locales.join(",")}] channels=[${channels.join(",")}] `
    + `budget=${quick ? "<=90s" : budget > 0 ? `<=${budget}s` : "不限"}`);
  if (quick && (specs.length !== 1 || specs[0] !== join(SPECS_DIR, "golden-match3.json") || locales.join(",") !== "en")) {
    throw new MatrixError("--quick 语义冻结为 match3×en×冻结渠道，不得与 --locales/--channels 混用", 2);
  }

  const cells = matrixCells(specs, locales, channels);
  const buildable = cells.filter((c) => !c.skip);
  if (quick && buildable.length !== cells.length) {
    throw new MatrixError("--quick 出现 skip 格（golden-match3 必须可构建）", 1);
  }

  // 阶段 A：spec 校验（pf validate 同源——校验是流水线第一道闸）
  for (const specPath of [...new Set(buildable.map((c) => c.spec))]) {
    runSync(["node", PF_CLI, "validate", specPath], `校验 ${specPath.split(/[\\/]/).pop()}`);
  }

  const builds = phaseBuild(cells, outRoot);
  const packed = phasePack(cells, builds, outRoot);
  const results = await phaseQa(cells, packed, builds, outRoot, jobs, !quick);
  const skips = cells.filter((c) => c.skip);

  const wall = (performance.now() - t0) / 1000;
  printTable(results, skips);
  const summaryPath = writeSummary(outRoot, quick ? "quick" : "full", results, skips, wall, budget || null);

  const nFail = results.filter((r) => r.status === "fail").length;
  const nRetried = results.filter((r) => r.retried).length;
  const over = budget > 0 && wall > budget;
  log(`总墙钟 ${wall.toFixed(1)}s（预算 ${budget > 0 ? `≤${budget}s` : "不限"}），`
    + `包 ${results.length}：pass ${results.length - nFail} / fail ${nFail}，skip ${skips.length}`
    + (nRetried > 0 ? `（其中 ${nRetried} 格为单重试后过，见表内 * 号与 summary retried 字段）` : ""));
  log(`summary.json：${summaryPath.slice(ROOT.length + 1).replaceAll("\\", "/")}`);

  if (nFail > 0) {
    for (const r of results) {
      for (const f of r.fails) {
        console.error(`[matrix] FAIL ${r.spec}×${r.locale}×${r.channel}：${f}`);
      }
    }
    console.error(`[matrix] FAIL：矩阵 ${nFail} 包质检未过（质检是唯一裁判）`);
    return 1;
  }
  if (over) {
    console.error(`[matrix] FAIL：总墙钟 ${wall.toFixed(1)}s 超预算 ${budget}s`);
    return 1;
  }
  log(`PASS：${quick ? "冒烟门" : "全矩阵"}全绿${quick ? "且在预算内" : ""}（exit 0）`);
  return 0;
}

// main
try {
  process.exitCode = await runMatrix(parseArgs(process.argv.slice(2)));
} catch (err) {
  if (err instanceof MatrixError) {
    console.error(`[matrix] FAIL：${err.message}`);
    process.exitCode = err.exitCode;
  } else {
    console.error(`[matrix] FAIL：${err?.stack || err}`);
    process.exitCode = 1;
  }
}

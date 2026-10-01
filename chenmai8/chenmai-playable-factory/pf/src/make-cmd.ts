// pf/src/make-cmd.ts — pf make 全流水线编排（oracle pfcore/make.py cmd_make 语义移植）。
//
// 流程（pipeline-contract §1 冻结名 `make`；墙钟口径 §5）：
//   validate → 模板构建（真实可玩单 HTML）→ 按规则库打渠道包 →
//   对首个 single-html 渠道跑判官 --autoplay（质检是裁判）→
//   summary.html + 二维码 + 预览链接 + 墙钟计时 → artifacts/demo-prebuilt/ 兜底目录
//
// 设计约束（照抄 oracle）：
// - 质检不过就没有二维码、没有兜底目录（演示红线：宁可失败不可假绿）。
// - 二维码内容 = LAN 可达的预览 HTML http URL（127.0.0.1 手机扫不出，契约 §5）。
// - 本模块不发起任何对 loopback/私网地址的 HTTP 请求（防 SSRF 纪律）。
// - 计时打印两个口径：make 墙钟（编排入口→二维码可扫）与 spec 修改完成→二维码可扫
//   （以 spec 文件 mtime 为"改完 spec"的客观代理）。

import { copyFileSync, existsSync, mkdirSync, readFileSync, rmSync, statSync, writeFileSync } from "node:fs";
import { basename, dirname, join, relative, resolve } from "node:path";
import process from "node:process";

import { validateSpecFile } from "./validate-cmd.ts";
import { buildSummaryHtml } from "./summary.ts";
import { printQrAscii, writeQrPng } from "./qr.ts";
import { DEFAULT_SERVE_PORT, ensureServer } from "./server-util.ts";
import { loadRules, readSpecJson, requiredSpritesFor, requiredTextsFor } from "./shared.ts";
import { AssetkitError, OPTMAP_NAME, REPORT_NAME } from "../../packages/assetkit/src/index.ts";
import { runAssetkit } from "../../packages/assetkit/src/pipeline.ts";
import {
  MakeError,
  PACKAGER_BIN,
  QACORE_CLI,
  REPO_ROOT,
  RULES_PATH,
  TEMPLATE_BUILDERS,
  copyDirRecursive,
  lanIp,
  log,
  run,
} from "./util.ts";

export interface MakeArgs {
  spec: string;
  locales?: string;
  channels: string;
  out: string;
  servePort: number;
  serveHost?: string;
  noServe: boolean;
  noAssetkit: boolean;
}

interface PkgInfo {
  channel: string;
  locale: string;
  format: string;
  artifact: string;
  rel: string;
  bytes: number;
  maxBytes: number;
  warnings: string[];
}

interface QaInfo {
  channel: string;
  locale: string;
  report: string;
  reportRel: string;
  shotRel: string;
  shotLsRel: string;
  pf: Record<string, unknown>;
  loadMs: number;
  checks: Array<Record<string, unknown>>;
}

const ASSETKIT_RUNNER = resolve(REPO_ROOT, "packages", "assetkit", "src", "pipeline.ts");

interface AssetkitInfo {
  dir: string;
  optmap: string;
  report: string;
  totals: Record<string, unknown>;
}

/**
 * 素材管线步骤（M5 assetkit；--no-assetkit 跳过）——oracle pfcore/make.py _run_assetkit
 * 语义移植：对 spec 声明且真实存在的素材（sprites/background/audio/fontSubset）跑
 * assetkit（压图/转音频/字体子集/图集），产物落 <out_root>/assetkit/，optmap 路径
 * 返回给模板构建接线（PF_ASSET_OPTMAP）。spec 无声明素材时零开销空跑（进程内直跑，
 * 无子进程）。素材管线失败按流水线失败处理（exit 1）：质检是裁判，宁可失败不可带病出包。
 */
async function runAssetkitStep(
  specPath: string,
  outRoot: string,
  noAssetkit: boolean,
): Promise<AssetkitInfo | null> {
  if (noAssetkit) return null;
  void ASSETKIT_RUNNER; // runner 已就位（packages/assetkit/src/pipeline.ts），保留路径常量供追溯
  const akDir = join(outRoot, "assetkit");
  try {
    const report = await runAssetkit({ inputs: [], out: akDir, spec: specPath });
    const totals = report.totals as unknown as Record<string, unknown>;
    log(`素材管线：${totals.count} 个素材，`
      + `${Number(totals.originalBytes ?? 0).toLocaleString("en-US")}B → `
      + `${Number(totals.optimizedBytes ?? 0).toLocaleString("en-US")}B`
      + `（降 ${totals.reductionPct}%）`);
    return {
      dir: akDir,
      optmap: join(akDir, OPTMAP_NAME),
      report: join(akDir, REPORT_NAME),
      totals,
    };
  } catch (err) {
    if (err instanceof AssetkitError) {
      throw new MakeError(`素材管线（assetkit）失败：${err.message}`, err.exitCode || 1);
    }
    throw err;
  }
}

function nodeVersion(): string {
  // oracle _node_version 的子进程探测为跨解释器需要；本实现自身就是 node，直接取。
  return process.version;
}

export async function cmdMake(args: MakeArgs): Promise<number> {
  const startedEpoch = Date.now();
  const t0 = performance.now();
  try {
    return await makeImpl(args, startedEpoch, t0);
  } catch (err) {
    if (err instanceof MakeError) {
      process.stderr.write(`[make] FAIL：${err.message}\n`);
      return err.exitCode;
    }
    throw err;
  }
}

async function makeImpl(args: MakeArgs, startedEpoch: number, t0: number): Promise<number> {
  // ---- 0) 定位 spec / 模板 / 渠道集合 ------------------------------------------------
  const specPath = resolve(args.spec);
  let specMtime = 0;
  try {
    specMtime = statSync(specPath).mtimeMs;
  } catch {
    throw new MakeError(`spec 不存在：${specPath}`, 2);
  }

  const issues = validateSpecFile(specPath);
  if (issues.length > 0) {
    console.log(`[make] validate FAIL ${basename(specPath)}`);
    for (const issue of issues) {
      console.log(`  ${issue.path}: ${issue.message} [${issue.code}]`);
    }
    throw new MakeError("spec 校验未通过（校验是流水线第一道闸）", 1);
  }
  log(`validate OK：${basename(specPath)}`);

  const spec = readSpecJson(specPath);
  const meta = (spec.meta ?? {}) as Record<string, unknown>;
  const game = (spec.game ?? {}) as Record<string, unknown>;
  const i18n = (spec.i18n ?? {}) as Record<string, unknown>;
  const project = String(meta.projectId ?? "playable").trim();
  const template = String(game.template ?? "").trim();
  const builder = TEMPLATE_BUILDERS[template];
  if (builder === undefined || !existsSync(builder)) {
    throw new MakeError(
      `模板 '${template}' 没有可用的真实构建器（支持：${Object.keys(TEMPLATE_BUILDERS).join(", ")}）`, 2);
  }

  const locales = (args.locales ?? "")
    .split(",").map((x) => x.trim()).filter((x) => x.length > 0);
  if (locales.length === 0) {
    locales.push(String((i18n as { defaultLocale?: unknown }).defaultLocale ?? "en"));
  }

  const rules = loadRules(RULES_PATH);
  const rulesChannels = (rules.channels ?? {}) as Record<string, Record<string, unknown>>;
  const known = Object.keys(rulesChannels);
  let channels: string[];
  if (args.channels === "all") {
    channels = known.filter((c) => c !== "preview"); // preview 是本地渠道，不打包
  } else {
    channels = args.channels.split(",").map((x) => x.trim()).filter((x) => x.length > 0);
  }
  const unknownCh = channels.filter((c) => !known.includes(c));
  if (unknownCh.length > 0) {
    throw new MakeError(`渠道不在规则库：${unknownCh.join(", ")}（现有：${known.join(", ")}）`, 2);
  }
  if (channels.length === 0) throw new MakeError("渠道列表为空", 2);

  const outRoot = resolve(args.out);
  const previewDir = join(outRoot, "preview");
  const distDir = join(outRoot, project, "dist");
  const demoDir = join(outRoot, "demo-prebuilt");
  mkdirSync(outRoot, { recursive: true });

  const qc = (spec.qc ?? {}) as Record<string, unknown>;

  // ---- 0.5) 素材管线（assetkit；--no-assetkit 跳过） --------------------------------
  const assetkitInfo = await runAssetkitStep(specPath, outRoot, args.noAssetkit);
  // 模板构建经 PF_ASSET_OPTMAP 接线内联优化产物（仅消费方模板读它；未命中回退原素材）。
  const builderEnv = assetkitInfo
    ? { ...process.env, PF_ASSET_OPTMAP: assetkitInfo.optmap }
    : undefined;

  // ---- 1) 模板构建（真实可玩 HTML）+ 组装打包器输入 dist -----------------------------
  const previews = new Map<string, string>();
  for (const locale of locales) {
    const outHtml = join(previewDir, `${project}-${locale}.html`);
    mkdirSync(dirname(outHtml), { recursive: true });
    run(["node", builder, "--spec", specPath, "--locale", locale, "--out", outHtml],
      `模板构建（${locale}）`, { env: builderEnv });
    previews.set(locale, outHtml);
    const locDir = join(distDir, locale);
    mkdirSync(locDir, { recursive: true });
    copyFileSync(outHtml, join(locDir, "index.html")); // 打包器输入形态（契约 §3.1 路径 B）
  }
  log(`构建完成：${[...previews.values()].map((p) => basename(p)).join(", ")}（dist=${basename(distDir)}/）`);

  // ---- 2) 渠道打包（同一份 HTML × 每渠道规则） ----------------------------------------
  const packages: PkgInfo[] = [];
  for (const channel of channels) {
    const pkgEntry = (rulesChannels[channel]?.package ?? {}) as { format?: unknown };
    const fmt = String(pkgEntry.format ?? "single-html") || "single-html";
    for (const locale of locales) {
      const stdout = run(
        ["node", PACKAGER_BIN, "build",
          "--spec", specPath, "--dist", distDir,
          "--channel", channel, "--locale", locale, "--out", outRoot],
        `打包 ${channel}/${locale}`);
      const lines = stdout.trim().split(/\r?\n/).filter((l) => l.trim().length > 0);
      let info: { artifact?: string; totalBytes?: unknown; maxBytes?: unknown };
      try {
        info = JSON.parse(lines[lines.length - 1] ?? "{}");
      } catch {
        throw new MakeError(`打包 ${channel}/${locale}：末行 JSON 摘要解析失败`, 1);
      }
      if (!info.artifact) {
        throw new MakeError(`打包 ${channel}/${locale}：摘要缺 artifact`, 1);
      }
      const artifact = resolve(info.artifact);
      const warnings = stdout.split(/\r?\n/).filter((ln) => ln.includes("警告:"));
      packages.push({
        channel, locale, format: fmt, artifact,
        rel: posixRel(artifact, demoDir),
        bytes: Number(info.totalBytes ?? 0),
        maxBytes: Number(info.maxBytes ?? 0),
        warnings,
      });
      log(`打包 ${channel}/${locale}：${basename(artifact)} ${packages[packages.length - 1]!.bytes.toLocaleString("en-US")}B`
        + ` / 上限 ${packages[packages.length - 1]!.maxBytes.toLocaleString("en-US")}B（警告 ${warnings.length}）`);
    }
  }

  // ---- 3) 质检（首个 single-html 渠道 × 首语言，--autoplay） --------------------------
  const qaPkg = packages.find((p) => p.locale === locales[0] && p.format === "single-html");
  if (qaPkg === undefined) {
    throw new MakeError("渠道列表中没有 single-html 渠道，判官当前仅支持单 HTML 产物", 2);
  }
  const qaReport = join(dirname(qaPkg.artifact), "index.report.json");

  // CHK10 判定输入（反馈行动 3）：首语言的 标题/教程/胜/CTA/分 文案必须真实上屏；
  // 构建真实嵌入的用户替换素材（旁车清单）必须像素对账通过。lose 不要求。
  const requiredTexts = requiredTextsFor(spec, locales[0]!);
  const previewHtml = previews.get(locales[0]!)!;
  const requiredSprites = requiredSpritesFor(previewHtml);

  const chk10Args: string[] = [];
  for (const t of requiredTexts) chk10Args.push("--require-text", t);
  for (const k of requiredSprites) chk10Args.push("--require-sprite", k);

  run([process.execPath, QACORE_CLI, "run", qaPkg.artifact,
    "--channel", qaPkg.channel, "--autoplay",
    "--max-load-sec", String(qc.maxLoadSec ?? 2.0),
    "--autoplay-timeout", String(qc.autoplayTimeoutSec ?? 45.0),
    ...chk10Args,
    "--out", qaReport],
    `判官质检（${qaPkg.channel}）`, { timeoutSec: 300 });

  const qaRaw = JSON.parse(readFileSync(qaReport, "utf8")) as Record<string, unknown>;
  const qa: QaInfo = {
    channel: qaPkg.channel, locale: qaPkg.locale,
    report: qaReport,
    reportRel: posixRel(qaReport, demoDir),
    shotRel: posixRel(join(dirname(qaReport), "index.report.png"), demoDir),
    shotLsRel: posixRel(join(dirname(qaReport), "index.report-landscape.png"), demoDir),
    pf: (qaRaw.pf ?? {}) as Record<string, unknown>,
    loadMs: Math.round(Number((qaRaw.facts as Record<string, unknown> | undefined)?.load_ms ?? 0)),
    checks: (qaRaw.checks ?? []) as Array<Record<string, unknown>>,
  };
  const nFail = qa.checks.filter((c) => c.status === "fail").length;
  log(`判官 ${qaPkg.channel}：${qa.checks.length} 项（fail ${nFail}，`
    + `pf:end ${String(qa.pf.endMs)}ms win=${String(qa.pf.endWin)}）`);
  if (nFail > 0) {
    throw new MakeError(`质检存在 ${nFail} 项 fail：不产出二维码与兜底目录（质检是裁判）`, 1);
  }

  // ---- 4) demo-prebuilt 兜底目录（静态可伺服） ----------------------------------------
  rmSync(demoDir, { recursive: true, force: true });
  mkdirSync(join(demoDir, "preview"), { recursive: true });
  for (const [, htmlPath] of previews) {
    copyFileSync(htmlPath, join(demoDir, "preview", basename(htmlPath)));
  }
  for (const p of packages) {
    const srcDir = dirname(p.artifact);
    const dst = join(demoDir, "channels", p.channel, p.locale);
    copyDirRecursive(srcDir, dst);
    p.rel = posixRel(join(dst, basename(p.artifact)), demoDir);
    if (p === qaPkg) {
      qa.reportRel = posixRel(join(dst, basename(qaReport)), demoDir);
      qa.shotRel = posixRel(join(dst, "index.report.png"), demoDir);
      qa.shotLsRel = posixRel(join(dst, "index.report-landscape.png"), demoDir);
    }
  }

  // ---- 5) 二维码 + 静态伺服 + 计时 ----------------------------------------------------
  const previewFile = previews.get(locales[0]!)!;
  const previewRel = `preview/${basename(previewFile)}`;
  const host = args.serveHost ?? (await lanIp());
  let serve: { port: number; reused: boolean } = { port: args.servePort, reused: false };
  if (!args.noServe) {
    const [port, reused] = await ensureServer(outRoot, demoDir, args.servePort || DEFAULT_SERVE_PORT);
    serve = { port, reused };
  } else {
    log("--no-serve：不启动伺服器；二维码指向默认端口，请自行伺服 demo-prebuilt 目录");
  }
  const previewUrl = serve.port !== 80
    ? `http://${host}:${serve.port}/${previewRel}`
    : `http://${host}/${previewRel}`;

  await writeQrPng(previewUrl, join(demoDir, "qr.png"));

  const tQr = performance.now();
  const makeWallSec = (tQr - t0) / 1000;
  const specToQrSec = Math.max(0, (Date.now() - specMtime) / 1000);

  const finishedAt = new Date().toISOString().slice(0, 19);
  const summaryHtml = buildSummaryHtml({
    project,
    specRel: posixRel(specPath, REPO_ROOT),
    specArg: args.spec,
    finishedAt,
    makeWallSec,
    specToQrSec,
    previewRel,
    previewUrl,
    demoRel: posixRel(demoDir, REPO_ROOT),
    packages,
    qa,
    serve,
    rulesVersion: rules.rulesVersion,
    nodeVersion: nodeVersion(),
  });
  // 同一份汇总页落双名：index.html 是伺服根落地页；summary.html 是冻结名产物（契约 §3.4）。
  // 二者内容一致、同为相对链接，伺服根相同即可同源打开。
  writeFileSync(join(demoDir, "index.html"), summaryHtml, "utf8");
  writeFileSync(join(demoDir, "summary.html"), summaryHtml, "utf8");

  const report = {
    command: "pf make",
    spec: specPath,
    specMtime,
    startedAt: new Date(startedEpoch).toISOString().slice(0, 19),
    finishedAt,
    timings: {
      makeWallSec: Math.round(makeWallSec * 100) / 100,
      specModifiedToQrScannableSec: Math.round(specToQrSec * 100) / 100,
      note: "二维码可扫 = qr.png 落盘且静态伺服端口 TCP 监听实测通过",
    },
    locales,
    channels,
    assetkit: assetkitInfo,
    preview: { html: previewFile, url: previewUrl },
    serve: { host, ...serve, root: demoDir, stateFile: join(outRoot, ".demo-serve.json") },
    packages: packages.map((p) => ({ ...p, artifact: p.artifact })),
    qa,
    demoPrebuilt: {
      root: demoDir,
      index: join(demoDir, "index.html"),
      summary: join(demoDir, "summary.html"),
      qr: join(demoDir, "qr.png"),
    },
  };
  writeFileSync(join(demoDir, "pipeline-report.json"),
    `${JSON.stringify(report, null, 2)}\n`, "utf8");

  // ---- 6) 收尾输出 --------------------------------------------------------------------
  log(`预览链接（手机同一局域网可开）：${previewUrl}`);
  log(`汇总页：${join(demoDir, "index.html")}`);
  log(`兜底目录：${demoDir}（静态可伺服；渠道包/报告/二维码/汇总页已整体复制）`);
  log(`计时：make 墙钟 ${makeWallSec.toFixed(1)}s；spec 修改完成→二维码可扫 ${specToQrSec.toFixed(1)}s`
    + `（spec mtime 口径，目标 ≤90s）`);
  if (serve.reused) {
    log(`静态伺服：复用端口 ${serve.port} 的上次会话伺服器（.demo-serve.json，PID+映像名+伺服根三重核实）`);
  } else {
    log(`静态伺服：已在 0.0.0.0:${serve.port} 启动（本进程退出后仍存活；`
      + `手机打不开时放行防火墙或改用手机热点）`);
  }
  await printQrAscii(previewUrl);
  console.log(`[make] PASS：${packages.length} 个渠道包 + 质检报告 + 二维码 + demo-prebuilt 兜底，exit 0`);
  return 0;
}

/** os.path.relpath 的 posix 形态（报告/页面引用统一 / 分隔）。 */
export function posixRel(path: string, from: string): string {
  return relative(from, path).replaceAll("\\", "/");
}

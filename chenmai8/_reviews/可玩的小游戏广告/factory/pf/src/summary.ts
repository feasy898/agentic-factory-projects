// pf/src/summary.ts — 演示汇总页构建（oracle pfcore make.build_summary_html / serve.build_page 移植）。
// 两页同规：自包含、仅相对引用、零外链（与二维码同源伺服）；HTML 结构与 oracle 同形，
// 人读文案不锁字节（宿主行改为 Node 栈表述）。

function esc(s: string): string {
  return s
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function badge(status: string): string {
  const color = status === "pass" ? "#1a7f37" : status === "fail" ? "#cf222e" : status === "skip" ? "#9a6700" : "#57606a";
  return `<span style="color:${color};font-weight:600">${esc(status)}</span>`;
}

function fmtInt(v: number | null): string {
  return typeof v === "number" && Number.isFinite(v)
    ? v.toLocaleString("en-US") : "—";
}

const STYLE = `
  body { font-family: system-ui, "Segoe UI", "Microsoft YaHei", sans-serif;
         margin: 24px auto; max-width: 960px; color: #1f2328; line-height: 1.55; }
  h1 { font-size: 22px; } h2 { font-size: 17px; margin-top: 28px; }
  table { border-collapse: collapse; width: 100%; font-size: 13px; }
  th, td { border: 1px solid #d0d7de; padding: 5px 9px; text-align: left; }
  th { background: #f6f8fa; }
  .card { border: 1px solid #d0d7de; border-radius: 8px; padding: 14px 18px; margin: 14px 0; }
  .kv { display: flex; gap: 28px; flex-wrap: wrap; }
  .kv b { font-size: 21px; }
  .dim { color: #57606a; font-size: 12.5px; }
  img.qr { width: 180px; height: 180px; image-rendering: pixelated; }
  a { color: #0969da; }`;

// ---------------------------------------------------------------- make 汇总页

export interface MakeSummaryCtx {
  project: string;
  specRel: string;
  specArg: string;
  finishedAt: string;
  makeWallSec: number;
  specToQrSec: number;
  previewRel: string;
  previewUrl: string;
  demoRel: string;
  packages: Array<{
    channel: string; locale: string; format: string; bytes: number;
    maxBytes: number; warnings: string[]; rel: string;
  }>;
  qa: {
    channel?: string; reportRel?: string; shotRel?: string; shotLsRel?: string;
    pf?: Record<string, unknown>; loadMs?: number;
    checks?: Array<Record<string, unknown>>;
  };
  serve: { port: number; reused: boolean };
  rulesVersion: unknown;
  nodeVersion: string;
}

export function buildSummaryHtml(ctx: MakeSummaryCtx): string {
  const checksRows = (ctx.qa.checks ?? []).map((c) =>
    `<tr><td>${esc(String(c.id ?? ""))}</td><td>${esc(String(c.name ?? ""))}</td>`
    + `<td>${badge(String(c.status ?? ""))}</td>`
    + `<td>${esc(String(c.detail ?? ""))}</td></tr>`).join("");
  const chanRows = ctx.packages.map((p) =>
    `<tr><td>${esc(p.channel)}</td><td>${esc(p.locale)}</td><td>${esc(p.format)}</td>`
    + `<td>${p.bytes.toLocaleString("en-US")}</td><td>${p.maxBytes.toLocaleString("en-US")}</td>`
    + `<td>${p.warnings.length} 条</td>`
    + `<td><a href="${esc(p.rel)}">${esc(p.rel.split("/").pop() ?? p.rel)}</a></td></tr>`).join("");
  const formats = [...new Set(ctx.packages.map((p) => p.format))].sort();
  const fmtNote = formats.map((fmt) =>
    `${fmt} ${ctx.packages.filter((p) => p.format === fmt).length} 包`).join("、");
  const pf = ctx.qa.pf ?? {};
  const serve = ctx.serve;
  return `<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>演示兜底 · ${esc(ctx.project)}</title>
<style>${STYLE}</style>
</head>
<body>
<h1>演示兜底 · ${esc(ctx.project)}（规格驱动试玩广告工厂）</h1>
<p class="dim">生成于 ${esc(ctx.finishedAt)} · spec <code>${esc(ctx.specRel)}</code> ·
命令 <code>node pf/pf.mjs make --spec ${esc(ctx.specArg)}</code></p>

<div class="card">
<h2 style="margin-top:0">墙钟计时</h2>
<div class="kv">
  <div><b>${ctx.makeWallSec.toFixed(1)}s</b><br><span class="dim">make 编排墙钟（入口 → 二维码可扫）</span></div>
  <div><b>${ctx.specToQrSec.toFixed(1)}s</b><br><span class="dim">spec 修改完成 → 二维码可扫（spec mtime 口径）</span></div>
</div>
<p class="dim">"可扫" = 二维码落盘且本机静态伺服端口 ${serve.port} 已在监听（TCP 实测）。目标 ≤90s。</p>
</div>

<div class="card">
<h2 style="margin-top:0">手机预览（扫码即玩）</h2>
<img class="qr" src="qr.png" alt="预览二维码">
<p>预览链接：<a href="${esc(ctx.previewRel)}">${esc(ctx.previewUrl)}</a></p>
<p class="dim">伺服根目录 <code>${esc(ctx.demoRel)}</code>（本机 ${serve.reused ? "复用上次会话" : "本次启动"}的静态伺服器，0.0.0.0:${serve.port}）。
手机须与本机同一局域网；打不开时放行防火墙或改用手机热点，兜底本页即静态件。</p>
</div>

<div class="card">
<h2 style="margin-top:0">渠道包（${esc(ctx.specRel)} → ${ctx.packages.length} 包）</h2>
<table><tr><th>渠道</th><th>语言</th><th>形态</th><th>字节</th><th>上限</th><th>警告</th><th>产物</th></tr>
${chanRows}</table>
<p class="dim">来源：同一份真实可玩 HTML（${esc(ctx.previewRel)}）经打包器按渠道规则库出包
（${esc(fmtNote)}）；zip 渠道包内结构由规则库 package.structure 声明，单 HTML 渠道全内联零外链。</p>
</div>

<div class="card">
<h2 style="margin-top:0">质检（--autoplay · 渠道 ${esc(String(ctx.qa.channel ?? ""))}）</h2>
<p class="dim">自动试玩以真实指针事件驱动到结束页：pf:ready ${esc(String(pf.readyMs ?? ""))}ms ·
pf:end ${esc(String(pf.endMs ?? ""))}ms（win=${esc(String(pf.endWin ?? ""))}）· 本地加载 ${esc(String(ctx.qa.loadMs ?? ""))}ms ·
报告 <a href="${esc(ctx.qa.reportRel ?? "")}">${esc(ctx.qa.reportRel ?? "")}</a>
（截图 <a href="${esc(ctx.qa.shotRel ?? "")}">竖屏</a> /
<a href="${esc(ctx.qa.shotLsRel ?? "")}">横屏</a>）</p>
<table><tr><th>检查</th><th>名称</th><th>状态</th><th>说明</th></tr>
${checksRows}</table>
<p class="dim">skip = 未实装/无判定前提，不算通过。质检不过时 make 不产出二维码与兜底目录。</p>
</div>

<p class="dim">pf make（编排 CLI）· Node ${esc(ctx.nodeVersion)} ·
规则库 rulesVersion=${esc(String(ctx.rulesVersion ?? ""))} ·
本页与二维码同源（demo-prebuilt 静态目录），零外链</p>
</body>
</html>
`;
}

// ---------------------------------------------------------------- serve 汇总页

export interface ServePageCtx {
  project: string;
  generatedAt: string;
  rootDisplay: string;
  rootArg: string;
  port: number;
  previewRel: string;
  previewUrl: string;
  packages: Array<{
    channel: string; locale: string; format: string; rel: string; manifestRel: string;
    bytes: number; maxBytes: number | null; warnings: number;
  }>;
  qas: Array<{
    rel: string; shotRel: string | null; shotLsRel: string | null; channel: string;
    pf: Record<string, unknown>; loadMs: number; checks: Array<Record<string, unknown>>;
  }>;
  pipeline: Record<string, unknown> | null;
  nodeVersion: string;
}

export function buildServePage(ctx: ServePageCtx): string {
  const pkgRows = ctx.packages.map((p) =>
    `<tr><td>${esc(p.channel)}</td><td>${esc(p.locale)}</td><td>${esc(p.format)}</td>`
    + `<td>${p.bytes.toLocaleString("en-US")}</td><td>${fmtInt(p.maxBytes)}</td>`
    + `<td>${p.warnings} 条</td>`
    + `<td><a href="${esc(p.rel)}">${esc(p.rel.split("/").pop() ?? p.rel)}</a></td>`
    + `<td><a href="${esc(p.manifestRel)}">manifest</a></td></tr>`).join("");
  const pkgTable = pkgRows
    || '<tr><td colspan="8" class="dim">（本目录无渠道包——可伺服裸预览目录，或先跑 make）</td></tr>';

  const qaSections = ctx.qas.map((qa) => {
    const pf = qa.pf ?? {};
    const checkRows = qa.checks.map((c) =>
      `<tr><td>${esc(String(c.id ?? ""))}</td><td>${esc(String(c.name ?? ""))}</td>`
      + `<td>${badge(String(c.status ?? ""))}</td>`
      + `<td>${esc(String(c.detail ?? ""))}</td></tr>`).join("");
    let links = `报告 <a href="${esc(qa.rel)}">${esc(qa.rel.split("/").pop() ?? qa.rel)}</a>`;
    if (qa.shotRel) links += ` · 截图 <a href="${esc(qa.shotRel)}">竖屏</a>`;
    if (qa.shotLsRel) links += ` / <a href="${esc(qa.shotLsRel)}">横屏</a>`;
    return `
<div class="card">
<h2 style="margin-top:0">质检报告 · 渠道 ${esc(qa.channel)}</h2>
<p class="dim">pf:ready ${esc(String(pf.readyMs ?? ""))}ms · pf:end ${esc(String(pf.endMs ?? ""))}ms（win=${esc(String(pf.endWin ?? ""))}）·
本地加载 ${esc(String(qa.loadMs))}ms · ${links}</p>
<table><tr><th>检查</th><th>名称</th><th>状态</th><th>说明</th></tr>
${checkRows || '<tr><td colspan="4" class="dim">（报告无 checks 字段）</td></tr>'}</table>
<p class="dim">skip = 未实装/无判定前提，不算通过。报告由判官生成，本页只做现场解析展示。</p>
</div>`;
  }).join("");

  let pipelineHtml = "";
  if (ctx.pipeline) {
    const timings = (ctx.pipeline.timings ?? {}) as Record<string, unknown>;
    pipelineHtml = `
<div class="card">
<h2 style="margin-top:0">make 流水线计时（本目录由 make 产出）</h2>
<div class="kv">
  <div><b>${esc(String(timings.makeWallSec ?? "—"))}s</b><br><span class="dim">make 编排墙钟</span></div>
  <div><b>${esc(String(timings.specModifiedToQrScannableSec ?? "—"))}s</b><br><span class="dim">spec 修改完成 → 二维码可扫</span></div>
</div>
<p class="dim">运行 ${esc(String(ctx.pipeline.startedAt ?? ""))} ·
完整运行报告 <a href="pipeline-report.json">pipeline-report.json</a></p>
</div>`;
  }

  const previewHtml = ctx.previewRel
    ? `<p>预览链接（手机扫码即玩）：<a href="${esc(ctx.previewRel)}">${esc(ctx.previewUrl)}</a></p>`
    : '<p class="dim">本目录没有预览 HTML——二维码退化指向本汇总页。</p>';

  return `<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>演示伺服 · ${esc(ctx.project)}</title>
<style>${STYLE}</style>
</head>
<body>
<h1>演示伺服 · ${esc(ctx.project)}（规格驱动试玩广告工厂）</h1>
<p class="dim">生成于 ${esc(ctx.generatedAt)} · 伺服根目录 <code>${esc(ctx.rootDisplay)}</code> ·
命令 <code>node pf/pf.mjs serve --root ${esc(ctx.rootArg)}</code></p>

<div class="card">
<h2 style="margin-top:0">手机预览（扫码即玩）</h2>
<img class="qr" src="qr.png" alt="预览二维码">
${previewHtml}
<p class="dim">手机须与本机同一局域网（伺服 0.0.0.0:${ctx.port}）；打不开时放行防火墙或改用手机热点。
本页与二维码同源，仅相对引用本目录文件，零外链。</p>
</div>

<div class="card">
<h2 style="margin-top:0">渠道包下载</h2>
<table><tr><th>渠道</th><th>语言</th><th>形态</th><th>字节</th><th>上限</th><th>警告</th><th>产物</th><th>清单</th></tr>
${pkgTable}</table>
<p class="dim">包体由打包器按渠道规则库出包；mintegral 为 zip（Template.html + build.js）。</p>
</div>
${qaSections}${pipelineHtml}
<p class="dim">pf serve · Node ${esc(ctx.nodeVersion)} ·
本页零外链：全部链接为相对路径，资源均在被伺服目录内。</p>
</body>
</html>
`;
}

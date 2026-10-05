// pf/src/serve-cmd.ts — pf serve（oracle pfcore/serve.py 语义移植）。
//
// 对**已经生成好的**产物目录（artifacts/demo-prebuilt/ 或裸预览目录）起一个
// **前台**局域网静态伺服器；每次启动重建两件东西（都落在被伺服目录内，零外链）：
//   - index.html 汇总页：手机预览链接 + 各渠道包下载链接 + 质检报告链接
//     （*.report.json/双视口截图/检查项明细现场解析）；
//   - qr.png 二维码：内容 = LAN 可达的预览 HTML 的 http URL（契约 §5，与 make 同规；
//     无 preview/*.html 时退化为汇总页地址并打印警告）。
//
// 与 make 伺服的差异（照抄 oracle）：serve 是前台进程（Ctrl+C 停止、端口即释放），
// 不做分离子进程、不写 .demo-serve.json 复用状态；端口被占时同样向后顺延（上限 20 个）。
// 退出码：0 = 被正常停止；2 = 用法/环境错误（契约 §2）。

import { readdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import http from "node:http";
import { join, resolve } from "node:path";

import { buildServePage } from "./summary.ts";
import { writeQrPng } from "./qr.ts";
import { startForegroundServer } from "./server-util.ts";
import { MakeError, lanIp, portListening } from "./util.ts";

export const DEFAULT_ROOT = "artifacts/demo-prebuilt";
export const DEFAULT_PORT = 8618;

function log(msg: string): void {
  console.log(`[serve] ${msg}`);
}

export interface ServeArgs {
  root: string;
  port: number;
  host?: string;
}

function posixRel(path: string, root: string): string {
  return resolve(path).slice(resolve(root).length + 1).replaceAll("\\", "/");
}

/** 预览 HTML：优先 preview/*.html；没有则退化为根目录散置 *.html（排除 index.html）。 */
function scanPreviews(root: string): string[] {
  const previewDir = join(root, "preview");
  try {
    if (statSync(previewDir).isDirectory()) {
      return readdirSync(previewDir)
        .filter((n) => n.endsWith(".html") && statSync(join(previewDir, n)).isFile())
        .sort().map((n) => join(previewDir, n));
    }
  } catch { /* 无 preview 目录 */ }
  return readdirSync(root)
    .filter((n) => n.endsWith(".html") && n !== "index.html"
      && statSync(join(root, n)).isFile())
    .sort().map((n) => join(root, n));
}

/** 扫描 channels/<channel>/<locale>/ 渠道包目录（契约 §3.2 形态）。
 *  产物 = index.html（single-html）或目录内唯一 *.zip（zip 渠道）；字节与上限读
 *  pack-manifest.json（缺失/损坏时上限记 null、警告数记 0——清单不阻塞伺服）。 */
function scanChannelPackages(root: string): Array<{
  channel: string; locale: string; format: string; rel: string; manifestRel: string;
  bytes: number; maxBytes: number | null; warnings: number;
}> {
  const channelsDir = join(root, "channels");
  if (!isDir(channelsDir)) return [];
  const packages: Array<{
    channel: string; locale: string; format: string; rel: string; manifestRel: string;
    bytes: number; maxBytes: number | null; warnings: number;
  }> = [];
  for (const channelDir of readdirSync(channelsDir).sort()) {
    const chPath = join(channelsDir, channelDir);
    if (!isDir(chPath)) continue;
    for (const localeDir of readdirSync(chPath).sort()) {
      const locPath = join(chPath, localeDir);
      if (!isDir(locPath)) continue;
      let artifact = join(locPath, "index.html");
      let fmt = "single-html";
      if (!isFile(artifact)) {
        const zips = readdirSync(locPath).filter((n) => n.endsWith(".zip")).sort();
        if (zips.length === 0) continue;
        artifact = join(locPath, zips[0]!);
        fmt = "zip";
      }
      let maxBytes: number | null = null;
      let warnings = 0;
      const manifestPath = join(locPath, "pack-manifest.json");
      if (isFile(manifestPath)) {
        try {
          const manifest = JSON.parse(readFileSync(manifestPath, "utf8")) as Record<string, unknown>;
          maxBytes = manifest.maxBytes ? Number(manifest.maxBytes) : null;
          warnings = Array.isArray(manifest.warnings) ? manifest.warnings.length : 0;
        } catch { /* 清单损坏不阻塞伺服 */ }
      }
      packages.push({
        channel: channelDir, locale: localeDir, format: fmt,
        rel: posixRel(artifact, root), manifestRel: posixRel(manifestPath, root),
        bytes: statSync(artifact).size, maxBytes, warnings,
      });
    }
  }
  return packages;
}

/** 解析目录内全部 *.report.json（判官报告，契约 §4 字段）+ 双视口截图；损坏只跳过。 */
function scanQaReports(root: string): Array<{
  rel: string; shotRel: string | null; shotLsRel: string | null; channel: string;
  pf: Record<string, unknown>; loadMs: number; checks: Array<Record<string, unknown>>;
}> {
  const reports: Array<{
    rel: string; shotRel: string | null; shotLsRel: string | null; channel: string;
    pf: Record<string, unknown>; loadMs: number; checks: Array<Record<string, unknown>>;
  }> = [];
  const walk = (dir: string): void => {
    let entries;
    try {
      entries = readdirSync(dir, { withFileTypes: true });
    } catch {
      return;
    }
    for (const e of entries) {
      const p = join(dir, e.name);
      if (e.isDirectory()) walk(p);
      else if (e.isFile() && e.name.endsWith(".report.json")) collect(p);
    }
  };
  const collect = (reportPath: string): void => {
    let raw: Record<string, unknown>;
    try {
      raw = JSON.parse(readFileSync(reportPath, "utf8")) as Record<string, unknown>;
    } catch {
      return;
    }
    const base = reportPath.slice(0, -".json".length); // "<名>.report"
    const shotPng = `${base}.png`;
    const shotLsPng = `${base}-landscape.png`;
    const facts = (raw.facts ?? {}) as Record<string, unknown>;
    reports.push({
      rel: posixRel(reportPath, root),
      shotRel: isFile(shotPng) ? posixRel(shotPng, root) : null,
      shotLsRel: isFile(shotLsPng) ? posixRel(shotLsPng, root) : null,
      channel: String(raw.channel ?? basenameOf(reportPath)),
      pf: (raw.pf ?? {}) as Record<string, unknown>,
      loadMs: Math.round(Number(facts.load_ms ?? 0)),
      checks: (raw.checks ?? []) as Array<Record<string, unknown>>,
    });
  };
  walk(root);
  reports.sort((a, b) => (a.rel < b.rel ? -1 : a.rel > b.rel ? 1 : 0));
  return reports;
}

function isDir(p: string): boolean {
  try {
    return statSync(p).isDirectory();
  } catch {
    return false;
  }
}

function isFile(p: string): boolean {
  try {
    return statSync(p).isFile();
  } catch {
    return false;
  }
}

function basenameOf(p: string): string {
  return p.replaceAll("\\", "/").split("/").pop() ?? p;
}

/** 展示用项目名（oracle _project_name 同义）：make 目录取 spec projectId（artifact
 *  路径倒数第 4 段）；裸预览目录取文件名前缀（<projectId>-<locale>.html）；再不行用目录名。 */
function projectName(root: string, previews: string[], pipeline: Record<string, unknown> | null): string {
  if (pipeline) {
    const pkgs = (pipeline.packages ?? []) as Array<Record<string, unknown>>;
    if (pkgs.length > 0) {
      const parts = String(pkgs[0]?.artifact ?? "").replaceAll("\\", "/").split("/").filter(Boolean);
      if (parts.length >= 4) return parts[parts.length - 4]!;
    }
  }
  if (previews.length > 0) {
    const stem = basenameOf(previews[0]!).replace(/\.html$/, "");
    if (stem.includes("-")) return stem.slice(0, stem.lastIndexOf("-"));
  }
  return basenameOf(root.replace(/[\\/]$/, "")) || root;
}

export async function cmdServe(args: ServeArgs): Promise<number> {
  try {
    return await serveImpl(args);
  } catch (err) {
    if (err instanceof MakeError) {
      process.stderr.write(`[serve] FAIL：${err.message}\n`);
      return err.exitCode;
    }
    process.stderr.write(`[serve] FAIL：${String(err)}\n`);
    return 2;
  }
}

async function serveImpl(args: ServeArgs): Promise<number> {
  const root = resolve(args.root);
  if (!isDir(root)) {
    process.stderr.write(`[serve] FAIL：目录不存在：${root}（先跑 pf make 产出 demo-prebuilt，`
      + `或用 --root 指向预览产物目录）\n`);
    return 2;
  }

  const previews = scanPreviews(root);
  const packages = scanChannelPackages(root);
  const qas = scanQaReports(root);
  let pipeline: Record<string, unknown> | null = null;
  const pipelinePath = join(root, "pipeline-report.json");
  if (isFile(pipelinePath)) {
    try {
      pipeline = JSON.parse(readFileSync(pipelinePath, "utf8")) as Record<string, unknown>;
    } catch {
      pipeline = null;
    }
  }
  log(`根目录：${root}（渠道包 ${packages.length} · 质检报告 ${qas.length} · 预览 ${previews.length}）`);

  // ---- 端口：被占向后顺延（与 make 同策略，上限 20 个） ------------------------------
  let port = args.port;
  let bound = false;
  for (let i = 0; i < 20; i++) {
    if (!(await portListening(port))) {
      bound = true;
      break;
    }
    port += 1;
  }
  if (!bound) {
    process.stderr.write(`[serve] FAIL：端口 ${args.port}~${port} 均被占用（--port 换口）\n`);
    return 2;
  }
  if (port !== args.port) log(`端口 ${args.port} 被占用，顺延到 ${port}`);

  const host = args.host ?? (await lanIp());

  // ---- 二维码（本地生成 PNG；契约 §5 内容规则与 make 相同） --------------------------
  const previewRel = previews.length > 0 ? posixRel(previews[0]!, root) : "";
  const pathPart = previewRel ? `/${previewRel}` : "/";
  const previewUrl = port !== 80 ? `http://${host}:${port}${pathPart}` : `http://${host}${pathPart}`;
  if (previews.length === 0) {
    log("警告：目录内无 preview/*.html，二维码退化指向汇总页（手机扫码只会看到本页）");
  }
  await writeQrPng(previewUrl, join(root, "qr.png"));

  // ---- 汇总页（覆盖写 index.html；每次 serve 现场重建，链接永远有效） ----------------
  const ctx = {
    project: projectName(root, previews, pipeline),
    generatedAt: new Date().toISOString().slice(0, 19),
    rootDisplay: root,
    rootArg: args.root,
    port,
    previewRel,
    previewUrl,
    packages,
    qas,
    pipeline,
    nodeVersion: process.version,
  };
  writeFileSync(join(root, "index.html"), buildServePage(ctx), "utf8");

  // ---- 前台伺服（0.0.0.0；Ctrl+C 停止） ----------------------------------------------
  let server: http.Server;
  try {
    server = await startForegroundServer(root, port);
  } catch (err) {
    process.stderr.write(`[serve] FAIL：端口 ${port} 绑定失败（${String(err)}）\n`);
    return 2;
  }
  if (!(await portListening(port))) { // TCP 实测（"可扫"纪律：不做 HTTP fetch）
    process.stderr.write(`[serve] FAIL：伺服器已绑定但端口 ${port} 未进入监听\n`);
    return 2;
  }

  const landingUrl = port !== 80 ? `http://${host}:${port}/` : `http://${host}/`;
  log(`汇总页（本页）：${landingUrl}（本机 http://127.0.0.1:${port}/）`);
  log(`LAN 预览：${previewUrl}`);
  log(`二维码：${join(root, "qr.png")} → ${previewUrl}`);
  log(`SERVE port=${port} landing_url=${landingUrl} preview_url=${previewUrl} qr=${join(root, "qr.png")}`);
  log(`伺服中 0.0.0.0:${port}（Ctrl+C 停止）…`);
  const started = Date.now();
  await new Promise<void>((res) => {
    let stopped = false;
    const stop = (): void => {
      if (stopped) return;
      stopped = true;
      server.close(() => res());
      // 兜底：有 keep-alive 连接挂住时 1s 内强制退出（前台伺服，端口必须即释放）。
      setTimeout(() => {
        server.closeAllConnections?.();
        res();
      }, 1000).unref();
    };
    process.once("SIGINT", stop);
    process.once("SIGTERM", stop);
    // 宿主适配（登记）：Windows 无法跨进程投递 SIGINT/SIGTERM（TerminateProcess 硬杀），
    // 管道化 stdin 的 EOF（编排方/终端退出关闭管道）作为等价"被正常停止"钩子——
    // 真实控制台 Ctrl+C 路径（SIGINT）保持不变；TTY 交互时 stdin 不挂钩子。
    if (!process.stdin.isTTY) {
      try {
        process.stdin.resume();
        process.stdin.once("end", stop);
        process.stdin.once("close", stop);
      } catch { /* stdin 不可用时忽略（Ctrl+C 仍在） */ }
    }
    server.on("error", stop);
  });
  log(`已停止（伺服 ${Math.round((Date.now() - started) / 1000)}s）`);
  return 0;
}

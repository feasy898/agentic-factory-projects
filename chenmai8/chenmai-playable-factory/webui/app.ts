// webui/app.ts — 最小操作界面服务（M10；oracle webui/app.py 语义移植，FastAPI→node:http）。
//
// 流程：浏览器单页（webui/static/index.html，无任何外部资源引用）→
// 选模板 / 传 PNG 素材 / 填文案（或直接传 spec JSON）→ POST /api/build 组装
// PlayableSpec（specgen）→ 后台子进程跑 `node pf/pf.mjs make`（真实流水线：
// 校验→模板构建→打包→qacore 自动试玩质检）→ 状态轮询 → 二维码 + 质检报告链接。
//
// 设计纪律（与 pf make 同一套，照抄 oracle）：
// - 零外链：页面自包含；产物链接全部指向本伺服的 /artifacts/... 相对路径。
// - 防 SSRF：本服务不发起任何 HTTP 请求（landingUrl 只做 http/https 格式校验，
//   从不访问；二维码为 qrcode 包本地生成；LAN 地址探测复用 pf.make 的 lanIp）。
// - 质检是裁判：qacore 有 fail 时 pf make 不产出 demo-prebuilt，任务如实记失败。
// - 无登录、仅 LAN（默认绑 0.0.0.0）；任务串行（promise 链信号量）避免质检资源互踩。
//
// 用法：node webui/app.ts [--port 8788] [--host 0.0.0.0]
// 自验收：node webui/selftest.mjs

import { createReadStream, existsSync, mkdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import http from "node:http";
import { basename, extname, join, resolve, sep } from "node:path";
import { randomBytes } from "node:crypto";
import process from "node:process";
import { fileURLToPath } from "node:url";
import { dirname } from "node:path";

import { validateSpec } from "../packages/spec/src/validate.ts";
import { writeQrPng } from "../pf/src/qr.ts";
import { lanIp } from "../pf/src/util.ts";
import { MultipartError, parseMultipart } from "./multipart.ts";
import {
  DEFAULT_CHANNELS,
  DEFAULT_LANDING_URL,
  LOCALES,
  SPRITE_SLOTS,
  SpecBuildError,
  TEMPLATES,
  TEMPLATE_LABELS,
  assembleSpec,
  defaultsTable,
} from "./specgen.ts";

const HERE = dirname(fileURLToPath(import.meta.url));
export const REPO_ROOT = resolve(HERE, "..");
const JOBS_ROOT = join(REPO_ROOT, "artifacts", "webui");
const STATIC_DIR = join(HERE, "static");
const PF_MJS = join(REPO_ROOT, "pf", "pf.mjs");

const PNG_MAGIC = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
const MAX_SPEC_BYTES = 256 * 1024;
const MAX_PNG_BYTES = 5 * 1024 * 1024;
const MAX_PNG_FILES = 12;
const JOB_TIMEOUT_SEC = 900;
const LOG_TAIL_LINES = 40;
const MAX_BODY_BYTES = 64 * 1024 * 1024; // multipart 整体上限（12×5MB + 表单余量）

const STATE = { host: "127.0.0.1", port: 8788 };

interface Job {
  id: string;
  status: "queued" | "running" | "done" | "failed";
  mode: "spec" | "form";
  template: string;
  channels: string[];
  createdAt: string;
  notes: string[];
  error: string | null;
  logTail: string;
  links: Record<string, string> | null;
  packages: Array<Record<string, unknown>>;
  qa: Record<string, unknown> | null;
  wallSec?: number;
  scanUrl?: string;
  projectId: string;
  locale: string;
  seed: number | null;
  startedAt?: string;
  finishedAt?: string;
}

const JOBS = new Map<string, Job>();
// make 含无头浏览器质检，串行防资源互踩（oracle threading.Semaphore(1) → promise 链）。
let makeQueue: Promise<void> = Promise.resolve();

mkdirSync(JOBS_ROOT, { recursive: true });

function now(): string {
  return new Date().toISOString().slice(0, 19);
}

function jobRoot(jobId: string): string {
  return join(JOBS_ROOT, jobId);
}

function persist(job: Job): void {
  try {
    writeFileSync(join(jobRoot(job.id), "job.json"), `${JSON.stringify(job, null, 2)}\n`, "utf8");
  } catch { /* 落盘失败不阻塞任务（oracle 同语义） */ }
}

function tail(text: string): string {
  const lines = (text ?? "").split(/\r?\n/).filter((ln) => ln.trim().length > 0);
  return lines.slice(-LOG_TAIL_LINES).join("\n");
}

// ---------------------------------------------------------------- HTTP 基件

class HttpError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, detail: unknown) {
    super(typeof detail === "string" ? detail : JSON.stringify(detail));
    this.status = status;
    this.detail = detail;
  }
}

function sendJson(res: http.ServerResponse, status: number, obj: unknown): void {
  const body = `${JSON.stringify(obj, null, 2)}\n`;
  res.writeHead(status, { "Content-Type": "application/json; charset=utf-8" });
  res.end(body);
}

function sendError(res: http.ServerResponse, err: unknown): void {
  if (err instanceof HttpError) {
    sendJson(res, err.status, { detail: err.detail });
    return;
  }
  sendJson(res, 500, { detail: `服务内部错误：${String(err)}` });
}

const MIME: Record<string, string> = {
  ".html": "text/html; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".svg": "image/svg+xml",
  ".css": "text/css; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".txt": "text/plain; charset=utf-8",
  ".webp": "image/webp",
  ".woff2": "font/woff2",
  ".m4a": "audio/mp4",
};

/** 任务产物静态伺服：/artifacts/webui/<id>/... → JOBS_ROOT/<id>/...（防目录穿越）。 */
function serveArtifact(res: http.ServerResponse, pathname: string): void {
  let rel: string;
  try {
    rel = decodeURIComponent(pathname);
  } catch {
    throw new HttpError(400, "路径不可解码");
  }
  if (rel.includes("\0") || rel.split("/").includes("..")) {
    throw new HttpError(404, "路径非法");
  }
  const abs = resolve(join(JOBS_ROOT, rel));
  if (abs !== JOBS_ROOT && !abs.startsWith(JOBS_ROOT + sep)) {
    throw new HttpError(404, "路径非法");
  }
  let st;
  try {
    st = statSync(abs);
  } catch {
    throw new HttpError(404, "产物不存在或任务未完成");
  }
  if (st.isDirectory()) {
    throw new HttpError(404, "目录不直接伺服（请用汇总页/具体产物链接）");
  }
  res.writeHead(200, { "Content-Type": MIME[extname(abs).toLowerCase()] ?? "application/octet-stream" });
  createReadStream(abs).pipe(res);
}

function readBody(req: http.IncomingMessage): Promise<Buffer> {
  return new Promise((resolveP, rejectP) => {
    const chunks: Buffer[] = [];
    let size = 0;
    req.on("data", (c: Buffer) => {
      size += c.length;
      if (size > MAX_BODY_BYTES) {
        rejectP(new HttpError(400, `请求体超 ${MAX_BODY_BYTES / 1024 / 1024}MB 上限`));
        req.destroy();
        return;
      }
      chunks.push(c);
    });
    req.on("end", () => resolveP(Buffer.concat(chunks)));
    req.on("error", (e) => rejectP(e));
  });
}

// ---------------------------------------------------------------- 素材落盘

interface WrittenSlot { slot: string; rel: string }

/** 校验并把上传 PNG 写入 dstDir/<槽位>.png；返回写入槽位清单（oracle _save_uploads 同语义）。 */
function saveUploads(
  files: Array<{ filename: string; data: Buffer }>,
  dstDir: string,
  slotOrder: string[],
  notes: string[],
  knownKeys: Set<string> | null = null,
): Record<string, string> {
  if (files.length > MAX_PNG_FILES) {
    throw new HttpError(400, `素材文件最多 ${MAX_PNG_FILES} 个`);
  }
  const written: Record<string, string> = {};
  const used = new Set<string>(knownKeys ?? []);
  for (const f of files) {
    const rawName = basename(f.filename ?? "");
    const stem = [...rawName.replace(/\.[^.]*$/, "").toLowerCase()]
      .map((c) => (/[a-z0-9_-]/.test(c) ? c : "-")).join("");
    const ext = extname(rawName).toLowerCase();
    if (f.data.length > MAX_PNG_BYTES) {
      throw new HttpError(400, `素材超 5MB 上限：${rawName}`);
    }
    if (ext !== ".png") {
      throw new HttpError(400, `仅接受 PNG 素材，得到 ${ext || "(无扩展名)"}：${rawName}`);
    }
    if (!f.data.subarray(0, 8).equals(PNG_MAGIC)) {
      throw new HttpError(400, `不是合法 PNG（魔数不符）：${rawName}`);
    }
    const slot = stem && slotOrder.includes(stem) && !used.has(stem)
      ? stem
      : slotOrder.find((s) => !used.has(s)) ?? null;
    if (slot === null) {
      if (knownKeys !== null && !knownKeys.has(stem)) {
        notes.push(`素材 ${rawName} 的键 ${JSON.stringify(stem)} 不在 spec.sprites 中，已忽略`);
        continue;
      }
      notes.push(`素材 ${rawName} 无可用槽位，已忽略（模板槽位：${slotOrder.join(", ")}）`);
      continue;
    }
    used.add(slot);
    writeFileSync(join(dstDir, `${slot}.png`), f.data);
    written[slot] = `assets/${slot}.png`;
    if (stem !== slot) notes.push(`素材 ${rawName} → 槽位 ${slot}`);
  }
  return written;
}

// ---------------------------------------------------------------- 任务执行

function startMake(job: Job): void {
  const specPath = join(jobRoot(job.id), "spec.json");
  const cmd = [process.execPath, PF_MJS, "make",
    "--spec", specPath,
    "--locales", job.locale,
    "--channels", job.channels.join(","),
    "--out", join(jobRoot(job.id), "out"),
    "--no-serve"]; // 不另起静态伺服：产物统一由本服务 /artifacts 挂载伺服
  job.status = "running";
  job.startedAt = now();
  persist(job);
  // 串行信号量：前一个 make 落定后才起下一个（防质检资源互踩）。
  makeQueue = makeQueue.then(async () => {
    await runMakeJob(job, cmd);
  });
}

async function runMakeJob(job: Job, cmd: string[]): Promise<void> {
  try {
    const { spawn } = await import("node:child_process");
    const child = spawn(cmd[0]!, cmd.slice(1), {
      cwd: REPO_ROOT, windowsHide: true,
    });
    let out = "";
    const grab = (d: Buffer) => {
      out += d.toString("utf8");
      if (out.length > 1_000_000) out = out.slice(-500_000);
    };
    child.stdout.on("data", grab);
    child.stderr.on("data", grab);
    let timedOut = false;
    const timer = setTimeout(() => {
      timedOut = true;
      child.kill();
    }, JOB_TIMEOUT_SEC * 1000);
    const code: number | null = await new Promise((resolveP) => {
      child.on("error", () => resolveP(-1));
      child.on("close", (c) => resolveP(c));
    });
    clearTimeout(timer);
    if (timedOut) {
      job.status = "failed";
      job.error = `pf make 超时（>${JOB_TIMEOUT_SEC}s）`;
      return;
    }
    job.logTail = tail(out);
    if (code !== 0) {
      job.status = "failed";
      job.error = `pf make exit ${code}（质检是裁判：任何 fail 都不产出产物）`;
      return;
    }
    Object.assign(job, await collectResult(job));
    job.status = "done";
  } catch (exc) {
    // 收集/二维码任何意外：如实失败，不假绿
    job.status = "failed";
    job.error = `任务收尾异常：${String(exc)}`;
  } finally {
    job.finishedAt = now();
    persist(job);
  }
}

/** make 成功后解析 pipeline-report，重出二维码（指向本服务的 LAN URL），组链接。 */
async function collectResult(job: Job): Promise<Partial<Job>> {
  const demo = join(jobRoot(job.id), "out", "demo-prebuilt");
  const pipeline = JSON.parse(readFileSync(join(demo, "pipeline-report.json"), "utf8")) as {
    preview?: { html?: string };
    qa?: {
      checks?: Array<{ status?: string }>;
      pf?: Record<string, unknown>;
      channel?: string; loadMs?: number; reportRel?: string;
    };
    timings?: { makeWallSec?: number };
    packages?: Array<{ channel: string; locale: string; format: string; bytes: number; maxBytes: number; rel: string }>;
  };
  const previewRel = `preview/${basename(pipeline.preview?.html ?? "")}`;
  const qa = pipeline.qa ?? {};

  const basePath = `/artifacts/webui/${job.id}/out/demo-prebuilt`;
  const port = STATE.port;
  const host = await lanIp();
  const scanUrl = port !== 80
    ? `http://${host}:${port}${basePath}/${previewRel}`
    : `http://${host}${basePath}/${previewRel}`;
  // make 以 --no-serve 运行，其 qr.png 指向占位端口；这里以本服务的 LAN 可达
  // URL 覆写（汇总页相对引用同名文件，保持一致）。qrcode 本地生成，零出站。
  await writeQrPng(scanUrl, join(demo, "qr.png"));

  const counts = { pass: 0, fail: 0, skip: 0 };
  for (const c of qa.checks ?? []) {
    const k = String(c.status ?? "");
    if (k === "pass" || k === "fail" || k === "skip") counts[k] += 1;
  }
  const pf = qa.pf ?? {};
  return {
    projectId: job.projectId,
    wallSec: Math.round(Number(pipeline.timings?.makeWallSec ?? 0) * 10) / 10,
    links: {
      summary: `${basePath}/index.html`,
      preview: `${basePath}/${previewRel}`,
      qr: `/api/jobs/${job.id}/qr.png`,
      report: `${basePath}/${qa.reportRel ?? "pipeline-report.json"}`,
      pipeline: `${basePath}/pipeline-report.json`,
    },
    scanUrl,
    packages: (pipeline.packages ?? []).map((p) => ({
      channel: p.channel, locale: p.locale, format: p.format,
      bytes: p.bytes, maxBytes: p.maxBytes, href: `${basePath}/${p.rel}`,
    })),
    qa: {
      channel: qa.channel, loadMs: qa.loadMs,
      pass: counts.pass, fail: counts.fail, skip: counts.skip,
      endMs: pf.endMs, endWin: pf.endWin, readyMs: pf.readyMs,
    },
  };
}

// ---------------------------------------------------------------- /api/build

interface BuildParts {
  fields: Record<string, string>;
  specFile: { filename: string; data: Buffer } | null;
  assets: Array<{ filename: string; data: Buffer }>;
}

async function parseBuildParts(req: http.IncomingMessage): Promise<BuildParts> {
  const body = await readBody(req);
  const ctype = req.headers["content-type"] ?? "";
  // FastAPI Form 对 application/x-www-form-urlencoded 同样受理（oracle 负向测试
  // 的 httpx data= 表单即此形态）；factory 同形双收：urlencoded → 纯字段无文件。
  if (ctype.toLowerCase().startsWith("application/x-www-form-urlencoded")) {
    const fields: Record<string, string> = {};
    for (const [k, v] of new URLSearchParams(body.toString("utf8"))) fields[k] = v;
    return { fields, specFile: null, assets: [] };
  }
  const parsed = parseMultipart(body, ctype);
  const specPart = parsed.files.find((f) => f.name === "spec") ?? null;
  return {
    fields: parsed.fields,
    specFile: specPart && specPart.filename.trim() ? { filename: specPart.filename, data: specPart.data } : null,
    assets: parsed.files.filter((f) => f.name === "assets"),
  };
}

/** 负整数/非整数拒绝（oracle int() + ValueError → 400 同语义；留空 → null）。 */
function parseSeed(raw: string | undefined): number | null {
  const s = (raw ?? "").trim();
  if (!s) return null;
  if (!/^[+-]?\d+$/.test(s)) throw new HttpError(400, `seed 须为非负整数：${JSON.stringify(raw ?? "")}`);
  return Number.parseInt(s, 10);
}

function boolField(raw: string | undefined, dflt: boolean): boolean {
  if (raw === undefined) return dflt;
  const s = raw.trim().toLowerCase();
  if (["true", "1", "yes", "on"].includes(s)) return true;
  if (["false", "0", "no", "off", ""].includes(s)) return false;
  return dflt; // FastAPI bool 解析对未知值宽松回落的同形
}

async function apiBuild(req: http.IncomingMessage, res: http.ServerResponse): Promise<void> {
  const { fields, specFile, assets } = await parseBuildParts(req);
  const notes: string[] = [];
  const jobId = randomBytes(6).toString("hex"); // token_hex(6) 同形（12 hex 字符）
  const root = jobRoot(jobId);
  mkdirSync(join(root, "assets"), { recursive: true });

  let specDict: Record<string, unknown>;
  let mode: Job["mode"];
  let channels: string[];
  let templateId: string;
  let jobCore: { projectId: string; locale: string; seed: number | null };

  if (specFile !== null) {
    // ---- 模式 A：上传 spec JSON ----------------------------------------
    if (specFile.data.length > MAX_SPEC_BYTES) {
      throw new HttpError(400, `spec 文件超 ${MAX_SPEC_BYTES / 1024}KB 上限`);
    }
    try {
      specDict = JSON.parse(specFile.data.toString("utf8")) as Record<string, unknown>;
    } catch (exc) {
      throw new HttpError(400, `spec JSON 解析失败：${String(exc)}`);
    }
    const issues = validateSpec(specDict).errors;
    if (issues.length > 0) {
      throw new HttpError(400, { errors: issues.map((i) => `${i.path}: ${i.message} [${i.code}]`) });
    }
    const assetsRec = (specDict.assets ?? {}) as { sprites?: Record<string, unknown> };
    const spriteKeys = Object.keys(assetsRec.sprites ?? {});
    const written = saveUploads(assets, join(root, "assets"),
      [...spriteKeys].sort(), notes, new Set(spriteKeys));
    assetsRec.sprites = assetsRec.sprites ?? {};
    for (const [slot, rel] of Object.entries(written)) {
      (assetsRec.sprites as Record<string, unknown>)[slot] = rel;
    }
    mode = "spec";
    const targets = ((specDict.channels as { targets?: string[] } | undefined)?.targets ?? [])
      .filter((c) => c !== "preview");
    channels = targets.length > 0 ? targets : [...DEFAULT_CHANNELS];
    templateId = String(((specDict.game as { template?: unknown } | undefined)?.template) ?? "");
    const meta = (specDict.meta ?? {}) as { projectId?: unknown; seed?: unknown };
    jobCore = {
      projectId: String(meta.projectId ?? "playable"),
      locale: String(((specDict.i18n as { defaultLocale?: unknown } | undefined)?.defaultLocale) ?? "en"),
      seed: typeof meta.seed === "number" ? meta.seed : null,
    };
  } else {
    // ---- 模式 B：表单组装 spec -----------------------------------------
    const template = fields["template"] ?? "match3";
    const seedVal = parseSeed(fields["seed"]);
    const slots = saveUploads(assets, join(root, "assets"),
      SPRITE_SLOTS[template] ?? SPRITE_SLOTS["match3"]!, notes);
    try {
      specDict = assembleSpec(template, {
        projectId: fields["project_id"] ?? "",
        title: fields["title"] ?? "",
        locale: fields["locale"] ?? "zh",
        texts: {
          cta: fields["cta"] ?? "", tutorial: fields["tutorial"] ?? "",
          win: fields["win"] ?? "", lose: fields["lose"] ?? "", score: fields["score"] ?? "",
        },
        seed: seedVal,
        landingUrl: fields["landing_url"] ?? "",
        nearWin: boolField(fields["near_win"], true),
        spriteSlots: slots,
      });
    } catch (exc) {
      if (exc instanceof SpecBuildError) {
        throw new HttpError(400, { errors: exc.messages });
      }
      throw exc;
    }
    const issues = validateSpec(specDict).errors; // 组装后仍过一遍权威校验（双保险）
    if (issues.length > 0) {
      throw new HttpError(400, { errors: issues.map((i) => `${i.path}: ${i.message} [${i.code}]`) });
    }
    mode = "form";
    channels = [...DEFAULT_CHANNELS];
    templateId = template;
    const meta = specDict.meta as { projectId: string; seed: number };
    jobCore = { projectId: meta.projectId, locale: fields["locale"] ?? "zh", seed: meta.seed };
  }

  writeFileSync(join(root, "spec.json"), `${JSON.stringify(specDict, null, 2)}\n`, "utf8");

  const job: Job = {
    id: jobId, status: "queued", mode,
    template: templateId, channels,
    createdAt: now(), notes, error: null,
    logTail: "", links: null, packages: [], qa: null,
    ...jobCore,
  };
  JOBS.set(jobId, job);
  persist(job);
  startMake(job);
  sendJson(res, 200, { id: jobId, status: "queued" });
}

// ---------------------------------------------------------------- 路由与服务器

async function route(req: http.IncomingMessage, res: http.ServerResponse): Promise<void> {
  const url = new URL(req.url ?? "/", "http://localhost");
  const pathname = url.pathname;
  const method = (req.method ?? "GET").toUpperCase();

  if (pathname === "/" && method === "GET") {
    const html = readFileSync(join(STATIC_DIR, "index.html"));
    res.writeHead(200, { "Content-Type": MIME[".html"]! });
    res.end(html);
    return;
  }
  if (pathname === "/api/health" && method === "GET") {
    sendJson(res, 200, { status: "ok", time: now() });
    return;
  }
  if (pathname === "/api/meta" && method === "GET") {
    sendJson(res, 200, {
      templates: TEMPLATES.map((t) => ({ id: t, label: TEMPLATE_LABELS[t], spriteSlots: SPRITE_SLOTS[t] })),
      locales: [...LOCALES],
      defaults: defaultsTable(),
      channels: DEFAULT_CHANNELS,
      landingUrlDefault: DEFAULT_LANDING_URL,
    });
    return;
  }
  if (pathname === "/api/jobs" && method === "GET") {
    const items = [...JOBS.values()]
      .sort((a, b) => (a.createdAt < b.createdAt ? 1 : a.createdAt > b.createdAt ? -1 : 0))
      .map((j) => ({
        id: j.id, status: j.status, mode: j.mode,
        projectId: j.projectId, locale: j.locale,
        createdAt: j.createdAt, finishedAt: j.finishedAt ?? null,
      }));
    sendJson(res, 200, items);
    return;
  }
  const jobMatch = /^\/api\/jobs\/([0-9a-f]+)$/.exec(pathname);
  if (jobMatch && method === "GET") {
    const job = JOBS.get(jobMatch[1]!);
    if (!job) throw new HttpError(404, `任务不存在：${jobMatch[1]}`);
    sendJson(res, 200, job);
    return;
  }
  const qrMatch = /^\/api\/jobs\/([0-9a-f]+)\/qr\.png$/.exec(pathname);
  if (qrMatch && method === "GET") {
    const qr = join(jobRoot(qrMatch[1]!), "out", "demo-prebuilt", "qr.png");
    if (!existsSync(qr)) {
      throw new HttpError(404, "二维码尚未产出（任务未完成或质检未过）");
    }
    res.writeHead(200, { "Content-Type": "image/png" });
    createReadStream(qr).pipe(res);
    return;
  }
  if (pathname === "/api/build" && method === "POST") {
    await apiBuild(req, res);
    return;
  }
  if (pathname.startsWith("/artifacts/webui/") && method === "GET") {
    serveArtifact(res, pathname.slice("/artifacts/webui".length));
    return;
  }
  throw new HttpError(404, `不存在：${method} ${pathname}`);
}

const server = http.createServer((req, res) => {
  route(req, res).catch((err) => {
    if (!res.headersSent) sendError(res, err);
    else res.end();
  });
});

function main(): void {
  const argv = process.argv.slice(2);
  let port = 8788;
  let host = "0.0.0.0";
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === "--port") port = Number.parseInt(argv[++i] ?? "", 10) || 8788;
    else if (argv[i] === "--host") host = argv[++i] ?? host;
  }
  STATE.host = host;
  STATE.port = port;
  console.log(`[webui] http://${host}:${port}/ （任务产物 /artifacts/webui/<id>/…）`);
  server.listen(port, host);
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main();
}

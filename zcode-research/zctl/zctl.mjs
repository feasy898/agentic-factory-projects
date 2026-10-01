#!/usr/bin/env node
/**
 * zctl —— ZCode 闲时任务 / 额度重置 协议级 CLI 封装
 *
 * 逆向来源（均经 zai-org/ZCode 开源源码核实，见 ../zcode-闲时任务与额度重置-研究报告.md）：
 *   reset:    packages/services/src/usage-stats/providers/bigmodelUsageQuotaProvider.ts
 *   offpeak:  packages/services/src/session/offPeakServerClient.ts
 *   凭据:     packages/services/src/credential/providers/credentialCipherProvider.ts
 *
 * 安全约定：
 *   - 变更类命令（use/opportunity/take/settle/history-read）默认 dry-run，必须 --yes 才真发。
 *   - 输出与 --record 落盘默认脱敏 token；--record-raw 才存原文（慎用，勿外传）。
 *   - 只读命令（status/availability/status查询）不改动服务端状态，但仍会携带凭据发真实请求。
 */
import { createHash, createDecipheriv, randomUUID } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { homedir, platform, userInfo } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const VERSION = "0.1.0";
const DEFAULT_ORIGIN = "https://zcode.z.ai";
const RESET_TIMEOUT_MS = 15000; // so=15e3（reset 客户端）
const OFFPEAK_TIMEOUT_MS = 10000; // REQUEST_TIMEOUT_MS（off-peak 客户端）

// ----------------------------- 参数解析 -----------------------------
function parseArgs(argv) {
  const pos = [];
  const opt = { _: {} };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--yes") opt.yes = true;
    else if (a === "--record") opt.record = true;
    else if (a === "--record-raw") { opt.record = true; opt.recordRaw = true; }
    else if (a === "--team") opt.team = true;
    else if (a === "--dry-run") opt.dryRun = true;
    else if (a === "--help" || a === "-h") opt.help = true;
    else if (a.startsWith("--")) {
      const key = a.slice(2);
      const val = argv[i + 1] && !argv[i + 1].startsWith("--") ? argv[++i] : true;
      opt[key] = val;
    } else pos.push(a);
  }
  return { pos, opt };
}

const USAGE = `zctl v${VERSION} — ZCode off-peak / coding-plan reset CLI（协议级封装，默认 dry-run）

用法: zctl <command> [options]

只读命令（无副作用，直接执行）:
  reset status                                查询可重置额度（GET /api/v1/coding-plan/reset/status）
  offpeak availability                        查询取号资格（GET /api/v1/off-peak/ticket/availability）
  offpeak status --ids <id1,id2,...>          批量查票状态（POST /api/v1/off-peak/ticket/status）

变更命令（默认 dry-run；加 --yes 才真正发送）:
  reset use --type FIVE_HOUR|WEEK [--key K]   消耗一张重置券执行重置（5 小时 / 周额度）
  reset opportunity [--key K]                 领取重置券
  reset history-read                          标记重置历史已读
  offpeak take --task-id <id|auto>            取号排队（注意：无 GUI 调度执行的裸取号会作废，见报告 §3.1）
  offpeak settle --ticket <id>                上报结算

通用选项:
  --team                使用团队套餐身份（reset 需同时给 --org/--project；offpeak 用 team api-key）
  --org ID --project ID 团队组织/项目 ID（写入 Bigmodel-Organization/Project 头）
  --origin URL          覆盖 API origin（默认 ${DEFAULT_ORIGIN}）
  --key K               幂等键（1-64 字符；默认 randomUUID；重试请沿用同一 key）
  --record              请求+响应落盘 zctl/logs/<ts>-<cmd>.json（token 默认脱敏）
  --record-raw          落盘时不脱敏 token（敏感！文件勿外传）
  --timeout MS          请求超时（默认 reset 15000 / offpeak 10000）
  --yes                 变更命令真正发送
  --dry-run             强制只打印请求
  --help                本帮助

凭据: 自动读取并解密 ~/.zcode/v2/credentials.json（AES-256-GCM，密钥本地推导，与 GUI/CLI 同源）`;

// ----------------------------- 凭据 -----------------------------
function decryptValue(value, key) {
  const PREFIX = "enc:v1:";
  if (typeof value !== "string" || !value.startsWith(PREFIX)) return value;
  const [ivRaw, tagRaw, ctRaw] = value.slice(PREFIX.length).split(".");
  if (!ivRaw || !tagRaw || !ctRaw) throw new Error("credential ciphertext format invalid");
  const b64u = (s) => Buffer.from(s, "base64url");
  const iv = b64u(ivRaw), tag = b64u(tagRaw), ct = b64u(ctRaw);
  if (iv.length !== 12 || tag.length !== 16) throw new Error("credential IV/tag length invalid");
  const d = createDecipheriv("aes-256-gcm", key, iv);
  d.setAuthTag(tag);
  return Buffer.concat([d.update(ct), d.final()]).toString("utf-8");
}

function credentialKey(env = process.env) {
  const secret =
    (env.ZCODE_CREDENTIAL_SECRET && env.ZCODE_CREDENTIAL_SECRET.trim()) ||
    `zcode-credential-fallback:${platform()}:${homedir()}:${(() => { try { return userInfo().username; } catch { return "unknown"; } })()}`;
  return createHash("sha256").update(secret).digest();
}

function loadCredentials(opt = {}) {
  const file = opt["cred-file"] || join(homedir(), ".zcode", "v2", "credentials.json");
  if (!existsSync(file)) throw new Error(`credentials not found: ${file}（请先在 GUI 登录）`);
  const key = credentialKey();
  const raw = JSON.parse(readFileSync(file, "utf-8"));
  const dec = (k) => (raw[k] === undefined ? undefined : decryptValue(raw[k], key));
  const family = (dec("oauth:active_provider") || "bigmodel").trim() || "bigmodel"; // 本机实测 = "bigmodel"
  const planKind = opt.team ? "team" : "individual";
  const apiKeyEntry =
    Object.keys(raw).find(
      (k) =>
        k.startsWith("account-provider:coding-plan:account:") &&
        k.includes(`bigmodel-${planKind}-coding-plan`) &&
        k.endsWith(":api-key"),
    ) || Object.keys(raw).find((k) => k.endsWith(":api-key")); // 兜底取第一条 api-key
  const creds = {
    file,
    family,
    jwt: dec("zcodejwttoken"),
    oauthAccessToken: dec(`oauth:${family}:access_token`),
    codingPlanApiKey: apiKeyEntry ? dec(apiKeyEntry) : undefined,
    apiKeyEntryUsed: apiKeyEntry,
  };
  for (const [name, v] of [["zcodejwttoken", creds.jwt], [`oauth:${family}:access_token`, creds.oauthAccessToken], [apiKeyEntry, creds.codingPlanApiKey]]) {
    if (name && !v) throw new Error(`credential missing/undecryptable: ${name}`);
  }
  return creds;
}

// ----------------------------- 请求构造 -----------------------------
function maskHeaders(headers, recordRaw) {
  const out = {};
  for (const [k, v] of Object.entries(headers)) {
    const lk = k.toLowerCase();
    if (!recordRaw && (lk === "authorization" || lk === "x-bigmodel-authorization" || lk === "x-coding-plan-api-key" || lk === "x-api-key")) {
      out[k] = String(v).length > 18 ? `${String(v).slice(0, 11)}…(${String(v).length} chars, masked)` : "***masked***";
    } else out[k] = v;
  }
  return out;
}

function sourceHeaders() {
  return {
    "User-Agent": "ZCode/3.14.3",
    "HTTP-Referer": DEFAULT_ORIGIN,
    "X-Title": "Z Code@electron",
    "X-ZCode-App-Version": "3.14.3",
    "X-Platform": `${process.platform}-${process.arch}`,
    "X-Os-Category": process.platform === "win32" ? "windows" : process.platform === "darwin" ? "macos" : "linux",
    "X-Client-Language": "unknown",
    "X-Client-Timezone": Intl.DateTimeFormat().resolvedOptions().timeZone || "unknown",
  };
}

function resetHeaders(creds, opt, withScope = true) {
  const h = {
    ...sourceHeaders(),
    "x-request-id": randomUUID(),
    Authorization: creds.jwt.startsWith("Bearer ") ? creds.jwt : `Bearer ${creds.jwt}`,
    "X-Bigmodel-Authorization": creds.oauthAccessToken,
  };
  if (withScope) {
    h["Bigmodel-Target-Type"] = opt.team ? "TEAM" : "PERSONAL";
    if (opt.team) {
      if (!opt.org || !opt.project) throw new Error("--team 需要 --org <id> --project <id>（Bigmodel-Organization/Project 头）");
      h["Bigmodel-Organization"] = opt.org;
      h["Bigmodel-Project"] = opt.project;
    }
  }
  return h;
}

function offpeakHeaders(creds, opt) {
  const h = {
    ...sourceHeaders(),
    "x-request-id": randomUUID(),
    authorization: `Bearer ${creds.jwt}`,
    "x-coding-plan-api-key": creds.codingPlanApiKey,
  };
  if (opt.team) {
    if (!opt.org || !opt.project) throw new Error("--team 需要 --org <id> --project <id>");
    h["bigmodel-organization"] = opt.org;
    h["bigmodel-project"] = opt.project;
  }
  return h;
}

// ----------------------------- 执行器 -----------------------------
async function execute({ name, mutating, url, method, headers, body, opt, timeoutMs }) {
  const display = {
    command: name,
    dryRun: mutating && !opt.yes,
    request: { method, url, headers: maskHeaders(headers, opt.recordRaw), ...(body !== undefined ? { body } : {}) },
  };
  if (display.dryRun) {
    console.log("[dry-run] 未发送任何请求（加 --yes 才真正执行）\n" + JSON.stringify(display, null, 2));
    return { ok: true, dryRun: true };
  }
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  let res, text;
  try {
    res = await fetch(url, { method, headers, ...(body !== undefined ? { body: JSON.stringify(body) } : {}), signal: controller.signal });
    text = await res.text();
  } catch (e) {
    const errRec = { ...display, error: String(e) };
    if (opt.record) record(name, errRec, opt);
    console.error(`[network error] ${String(e)}`);
    process.exitCode = 2;
    return { ok: false };
  } finally {
    clearTimeout(timer);
  }
  let json = null;
  try { json = text ? JSON.parse(text) : null; } catch { /* keep raw */ }
  // 信封语义（与官方客户端一致）：{code!==0} 视为业务失败；off-peak 兼容裸体
  const bizCode = json && typeof json === "object" && "code" in json ? json.code : null;
  const record_ = {
    ...display,
    response: { status: res.status, requestId: res.headers.get("x-request-id"), body: json ?? text },
  };
  console.log(JSON.stringify(record_.response, null, 2));
  if (opt.record) record(name, record_, opt);
  if (!res.ok || bizCode !== null && bizCode !== 0) {
    console.error(`[failed] HTTP ${res.status}${bizCode !== null ? ` code=${bizCode}` : ""}（x-request-id: ${res.headers.get("x-request-id") ?? "n/a"}）`);
    process.exitCode = 1;
  }
  return { ok: process.exitCode !== 1, json };
}

function record(name, data, opt) {
  const dir = join(dirname(fileURLToPath(import.meta.url)), "logs");
  mkdirSync(dir, { recursive: true });
  const ts = new Date().toISOString().replace(/[:.]/g, "-");
  const file = join(dir, `${ts}-${name.replace(/[^a-z0-9-]+/gi, "_")}.json`);
  writeFileSync(file, JSON.stringify({ recordedAt: new Date().toISOString(), recordRaw: !!opt.recordRaw, ...data }, null, 2));
  console.error(`[record] ${file}`);
}

// ----------------------------- 命令 -----------------------------
const RESET_BASE = "/api/v1/coding-plan/reset";
const OFFPEAK_BASE = "/api/v1/off-peak";

function requireValue(opt, key, cmd) {
  const v = opt[key];
  if (v === undefined || v === true || String(v).trim() === "") {
    console.error(`缺少参数 --${key}（${cmd}）\n\n${USAGE}`);
    process.exit(2);
  }
  return String(v).trim();
}

function idemKey(opt) {
  const k = opt.key ? String(opt.key).trim() : randomUUID();
  if (!k || k.length > 64) { console.error("--key 需为 1-64 字符"); process.exit(2); }
  return k;
}

async function main() {
  const { pos, opt } = parseArgs(process.argv.slice(2));
  if (opt.help || pos.length === 0) { console.log(USAGE); return; }
  const origin = (opt.origin || DEFAULT_ORIGIN).replace(/\/$/, "");
  const [group, action] = pos;
  const name = `${group}-${action ?? ""}`.replace(/-$/, "");

  // ---- 只读：reset status ----
  if (group === "reset" && action === "status") {
    const creds = loadCredentials(opt);
    return execute({
      name, mutating: false,
      url: `${origin}${RESET_BASE}/status`, method: "GET",
      headers: resetHeaders(creds, opt), opt, timeoutMs: Number(opt.timeout) || RESET_TIMEOUT_MS,
    });
  }

  // ---- 变更：reset use / opportunity / history-read ----
  if (group === "reset" && (action === "use" || action === "opportunity" || action === "history-read")) {
    const creds = loadCredentials(opt);
    if (action === "use") {
      const type = (opt.type || "").toUpperCase();
      if (type !== "FIVE_HOUR" && type !== "WEEK") { console.error(`--type 必须为 FIVE_HOUR 或 WEEK\n\n${USAGE}`); process.exit(2); }
      return execute({
        name, mutating: true,
        url: `${origin}${RESET_BASE}/use`, method: "POST",
        headers: { ...resetHeaders(creds, opt), "content-type": "application/json" },
        body: { idempotency_key: idemKey(opt), reset_type: type },
        opt, timeoutMs: Number(opt.timeout) || RESET_TIMEOUT_MS,
      });
    }
    if (action === "opportunity") {
      return execute({
        name, mutating: true,
        url: `${origin}${RESET_BASE}/opportunity`, method: "POST",
        headers: { ...resetHeaders(creds, opt), "content-type": "application/json" },
        body: { idempotency_key: idemKey(opt) },
        opt, timeoutMs: Number(opt.timeout) || RESET_TIMEOUT_MS,
      });
    }
    return execute({
      name, mutating: true,
      url: `${origin}${RESET_BASE}/history/read`, method: "POST",
      headers: resetHeaders(creds, opt), opt, timeoutMs: Number(opt.timeout) || RESET_TIMEOUT_MS,
    });
  }

  // ---- offpeak ----
  if (group === "offpeak") {
    const creds = loadCredentials(opt);
    if (action === "availability") {
      return execute({
        name, mutating: false,
        url: `${origin}${OFFPEAK_BASE}/ticket/availability`, method: "GET",
        headers: offpeakHeaders(creds, opt), opt, timeoutMs: Number(opt.timeout) || OFFPEAK_TIMEOUT_MS,
      });
    }
    if (action === "take") {
      let taskId = requireValue(opt, "task-id", "offpeak take");
      if (taskId === "auto") taskId = `offpeak-${randomUUID()}`;
      console.error(`[info] task_id = ${taskId}`);
      return execute({
        name, mutating: true,
        url: `${origin}${OFFPEAK_BASE}/ticket`, method: "POST",
        headers: { ...offpeakHeaders(creds, opt), "content-type": "application/json" },
        body: { task_id: taskId },
        opt, timeoutMs: Number(opt.timeout) || OFFPEAK_TIMEOUT_MS,
      });
    }
    if (action === "status") {
      const ids = requireValue(opt, "ids", "offpeak status").split(",").map((s) => s.trim()).filter(Boolean).slice(0, 100);
      return execute({
        name, mutating: false,
        url: `${origin}${OFFPEAK_BASE}/ticket/status`, method: "POST",
        headers: { ...offpeakHeaders(creds, opt), "content-type": "application/json" },
        body: { ticket_ids: ids },
        opt, timeoutMs: Number(opt.timeout) || OFFPEAK_TIMEOUT_MS,
      });
    }
    if (action === "settle") {
      const ticket = requireValue(opt, "ticket", "offpeak settle");
      return execute({
        name, mutating: true,
        url: `${origin}${OFFPEAK_BASE}/ticket/${encodeURIComponent(ticket)}/settle`, method: "POST",
        headers: offpeakHeaders(creds, opt), opt, timeoutMs: Number(opt.timeout) || OFFPEAK_TIMEOUT_MS,
      });
    }
    if (action === "messages") {
      // CLI 直连闲时会话：Anthropic Messages 协议走 /off-peak/anthropic/v1/messages（GUI 调度器的同款通道）
      const ticket = requireValue(opt, "ticket", "offpeak messages");
      const prompt = requireValue(opt, "prompt", "offpeak messages");
      const model = opt.model || "GLM-5.3-Flash";
      const maxTokens = Number(opt["max-tokens"]) || 64;
      const headers = {
        ...offpeakHeaders(creds, opt),
        "content-type": "application/json",
        "x-api-key": creds.jwt,
        "x-off-peak-ticket-id": ticket,
        "anthropic-version": "2023-06-01",
      };
      const body = { model, max_tokens: maxTokens, stream: true, messages: [{ role: "user", content: prompt }] };
      headers["accept"] = "text/event-stream";
      return execute({
        name, mutating: true,
        url: `${origin}${OFFPEAK_BASE}/anthropic/v1/messages`, method: "POST",
        headers, body,
        opt, timeoutMs: Number(opt.timeout) || 120000,
        rawResponse: true,
      });
    }
  }

  console.error(`未知命令: ${pos.join(" ")}\n\n${USAGE}`);
  process.exit(2);
}

main().catch((e) => {
  console.error(`[error] ${e.message ?? e}`);
  process.exit(2);
});

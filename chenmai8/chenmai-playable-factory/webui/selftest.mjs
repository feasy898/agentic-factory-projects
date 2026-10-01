// webui/selftest.mjs — M10 端到端自验收（node:fetch 全局客户端，oracle webui/selftest.py
// httpx 语义移植）。真实走完整流水线。
//
// 流程（oracle EVAL 同表）：
//   1. 选空闲端口，子进程拉起 `node webui/app.ts --host 127.0.0.1 --port N`；
//   2. /api/health → 200 且 status=ok；
//   3. GET / → 200 且页面零外链（无任何 http(s) 外部引用）；
//   4. 模式 A：multipart 上传 specs-eval/demo-zh.json → 200 → 轮询至 done →
//      产物链接（预览/汇总页/质检报告/流水线）逐个 GET 200，质检 0 fail，
//      自动试玩到结束页（pf:end win），二维码 PNG 魔数，渠道包逐个 200；
//   5. 模式 B：表单（match3 + zh 文案 + 上传 demo PNG）→ done → 链接 GET 200；
//   6. 负向：坏 JSON spec → 400；未知模板 → 400；
//   7. 收尾杀掉服务子进程。全部断言过 → 打印 SELFTEST PASS，exit 0。
//
// 用法：node webui/selftest.mjs [--timeout-sec 480]（工作目录任意；仓库根自定位）

import { spawn } from "node:child_process";
import { openSync } from "node:fs";
import { mkdirSync, readFileSync } from "node:fs";
import net from "node:net";
import { dirname, join, resolve } from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const REPO_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const DEMO_SPEC = join(REPO_ROOT, "specs-eval", "demo-zh.json");
const DEMO_PNG = join(REPO_ROOT, "specs-eval", "assets", "demo-zh", "piece-0.png");
const SERVER_LOG = join(REPO_ROOT, "artifacts", "webui", "_selftest-server.log");
const APP_TS = join(REPO_ROOT, "webui", "app.ts");
const HEALTH_WAIT_SEC = 60.0;

const FAILURES = [];
const t0 = Date.now();

function check(name, ok, detail = "") {
  console.log(`  [${ok ? "PASS" : "FAIL"}] ${name}${detail ? ` —— ${detail}` : ""}`);
  if (!ok) FAILURES.push(`${name}: ${detail}`);
  return ok;
}

function freePort() {
  return new Promise((res, rej) => {
    const srv = net.createServer();
    srv.listen(0, "127.0.0.1", () => {
      const port = srv.address().port;
      srv.close(() => res(port));
    });
    srv.on("error", rej);
  });
}

function argNum(name, dflt) {
  const i = process.argv.indexOf(name);
  return i > 0 ? Number(process.argv[i + 1]) || dflt : dflt;
}

const TIMEOUT_SEC = argNum("--timeout-sec", 480);

function spawnServer(port) {
  mkdirSync(dirname(SERVER_LOG), { recursive: true });
  const log = openSync(SERVER_LOG, "a");
  return spawn(process.execPath, [APP_TS, "--host", "127.0.0.1", "--port", String(port)], {
    cwd: REPO_ROOT, stdio: ["ignore", log, log],
  });
}

async function waitHealth(base, deadline) {
  while (Date.now() < deadline) {
    try {
      const r = await fetch(`${base}/api/health`, { signal: AbortSignal.timeout(3000) });
      if (r.status === 200 && (await r.json()).status === "ok") return true;
    } catch { /* 未就绪继续等 */ }
    await new Promise((r) => setTimeout(r, 500));
  }
  return false;
}

async function awaitJob(base, jobId, timeoutSec) {
  const deadline = Date.now() + timeoutSec * 1000;
  while (Date.now() < deadline) {
    try {
      const r = await fetch(`${base}/api/jobs/${jobId}`, { signal: AbortSignal.timeout(10000) });
      if (r.status === 200) {
        const job = await r.json();
        if (job.status === "done" || job.status === "failed") return job;
      }
    } catch { /* 轮询抖动继续 */ }
    await new Promise((r) => setTimeout(r, 2000));
  }
  return { status: "poll-timeout" };
}

async function runBuild(base, label, timeoutSec, expectProject, { data = {}, files = {} } = {}) {
  console.log(`[step] 构建（${label}）：POST /api/build`);
  const fd = new FormData();
  for (const [k, v] of Object.entries(data)) fd.append(k, v);
  for (const [k, f] of Object.entries(files)) {
    fd.append(k, new Blob([f.bytes], { type: f.type }), f.filename);
  }
  let r;
  try {
    r = await fetch(`${base}/api/build`, { method: "POST", body: fd, signal: AbortSignal.timeout(60000) });
  } catch (e) {
    check(`${label}: POST /api/build → 200`, false, String(e));
    return {};
  }
  const text = await r.text();
  if (!check(`${label}: POST /api/build → 200`, r.status === 200, `exit ${r.status} body=${text.slice(0, 300)}`)) {
    return {};
  }
  const jobId = (JSON.parse(text) || {}).id ?? "";
  const job = await awaitJob(base, jobId, timeoutSec);
  if (!check(`${label}: 任务 done（id=${jobId}）`, job.status === "done",
    `status=${job.status} error=${job.error}`)) {
    console.log("  ---- make 日志尾 ----");
    for (const ln of (job.logTail || "").split(/\r?\n/).slice(-12)) console.log(`      ${ln}`);
    return job;
  }
  check(`${label}: projectId=${expectProject}`, job.projectId === expectProject, String(job.projectId));
  const qa = job.qa ?? {};
  check(`${label}: 质检 0 fail（pass=${qa.pass} skip=${qa.skip}）`, qa.fail === 0, JSON.stringify(qa));
  check(`${label}: 自动试玩到结束页（pf:end win）`, qa.endWin === true, String(qa.endWin));
  const links = job.links ?? {};
  for (const name of ["preview", "summary", "report", "pipeline"]) {
    const url = links[name] ?? "";
    let resp = null;
    try {
      resp = await fetch(`${base}${url}`, { signal: AbortSignal.timeout(30000) });
    } catch { /* 落到断言 */ }
    check(`${label}: 链接 ${name} → 200`, resp !== null && resp.status === 200,
      `${url} exit ${resp ? resp.status : "no-resp"}`);
  }
  const qr = await fetch(`${base}/api/jobs/${jobId}/qr.png`, { signal: AbortSignal.timeout(30000) });
  const qrBytes = Buffer.from(await qr.arrayBuffer());
  check(`${label}: 二维码 /api/jobs/…/qr.png → 200 PNG`,
    qr.status === 200 && qrBytes.subarray(0, 8).equals(Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])),
    `exit ${qr.status} bytes=${qrBytes.length}`);
  const pkgs = job.packages ?? [];
  check(`${label}: 渠道包 ≥3`, pkgs.length >= 3, `${pkgs.length} 包`);
  let badHref = null;
  for (const p of pkgs) {
    let resp = null;
    try {
      resp = await fetch(`${base}${p.href}`, { signal: AbortSignal.timeout(60000) });
    } catch (e) {
      badHref = `${p.channel}/${p.locale} → ${String(e)}`;
      break;
    }
    if (resp.status !== 200) {
      badHref = `${p.channel}/${p.locale} → ${resp.status}`;
      break;
    }
  }
  check(`${label}: 渠道包产物逐个 GET 200`, badHref === null, badHref ?? `${pkgs.length} 包全 200`);
  return job;
}

const port = await freePort();
const base = `http://127.0.0.1:${port}`;
console.log(`[step] 启动服务：node webui/app.ts --host 127.0.0.1 --port ${port}（日志 _selftest-server.log）`);
const proc = spawnServer(port);
try {
  const ok = await waitHealth(base, Date.now() + HEALTH_WAIT_SEC * 1000);
  check("服务 /api/health → status=ok", ok, ok ? "" : `${HEALTH_WAIT_SEC}s 内未就绪（见 artifacts/webui/_selftest-server.log）`);
  if (ok) {
    const r0 = await fetch(`${base}/`);
    const page = await r0.text();
    check("GET / → 200", r0.status === 200, `exit ${r0.status}`);
    const external = [...page.matchAll(/(?:src|href)\s*=\s*["']https?:\/\/[^"']+/g)].map((m) => m[0]);
    check("单页零外链（无 http(s) 引用）", external.length === 0, external.slice(0, 3).join("; "));

    const rm = await fetch(`${base}/api/meta`);
    const meta = rm.status === 200 ? await rm.json() : {};
    check("GET /api/meta → 200 且模板 ≥3", rm.status === 200 && (meta.templates ?? []).length >= 3, String(rm.status));

    // ---- 模式 A：上传 demo spec（demo-zh.json，中文三消） ------------------------
    await runBuild(base, "A·上传spec", TIMEOUT_SEC, "demo-zh", {
      files: { spec: { bytes: readFileSync(DEMO_SPEC), type: "application/json", filename: "demo-zh.json" } },
    });

    // ---- 模式 B：表单（match3 + zh 文案 + 上传 PNG） -----------------------------
    const pngBytes = readFileSync(DEMO_PNG);
    await runBuild(base, "B·表单组装", TIMEOUT_SEC, "webui-match3", {
      data: {
        template: "match3", locale: "zh",
        title: "宝石试玩（webui）", cta: "马上玩",
        tutorial: "拖动宝石连成一线！", win: "赢啦！",
        lose: "再挑战！", score: "分数", near_win: "true",
      },
      files: { assets: { bytes: pngBytes, type: "image/png", filename: "piece-0.png" } },
    });

    // ---- 负向：坏 spec / 未知模板必须 400 ----------------------------------------
    let r = await fetch(`${base}/api/build`, {
      method: "POST",
      body: (() => {
        const fd = new FormData();
        fd.append("spec", new Blob(["{ not json"], { type: "application/json" }), "bad.json");
        return fd;
      })(),
    });
    check("负向·坏 JSON spec → 400", r.status === 400, `exit ${r.status}`);
    r = await fetch(`${base}/api/build`, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({ template: "not-a-template" }).toString(),
    });
    check("负向·未知模板 → 400", r.status === 400, `exit ${r.status}`);
  }
} finally {
  proc.kill();
}
const elapsed = (Date.now() - t0) / 1000;
if (FAILURES.length > 0) {
  console.log(`SELFTEST FAIL（${FAILURES.length} 项断言未过，耗时 ${elapsed.toFixed(1)}s）：`);
  for (const f of FAILURES) console.log(`  - ${f}`);
  process.exitCode = 1;
} else {
  console.log(`SELFTEST PASS（全部断言通过，耗时 ${elapsed.toFixed(1)}s）`);
  process.exitCode = 0;
}

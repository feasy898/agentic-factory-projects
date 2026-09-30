/**
 * CHK04 确定性回归（chk04-determinism 契约修订 2026-09-30，qacore spec §4）——
 * 差分终审 QC-02/CLI-B 同族假阴性根因的回归面。
 *
 * 覆盖分三层，每层只断言该层能**确定性**提供的事实：
 * 1. 探针旗契约（页级，真实 WebAudio + 真实 PROBE_JS，本文件直连 playwright）：
 *    无 AudioContext → 旗 false；首 pointer 事件前出现 running AudioContext →
 *    旗 true（"构造即 running"与 suspend→resume 两路径均记账）；旗置真不复位；
 *    首 pointer 事件之后才出现的 running 不置旗（时序判别语义）；探针缺失读 null。
 *    翻转触发走 CDP evaluate（playwright 页函数求值带 userGesture，本机 2/2 确定性
 *    "构造即 running"；页面脚本自发 resume() 受无手势 autoplay 策略约束，落定与否
 *    随机器/会话状态抖动——tmp/diff/probe-contract/probe_cli_sequence.mjs 实测 3/3
 *    永不落定、probe_oracle_timeline.mjs 对 oracle A 产物 12 采样全程 running=0，
 *    这正是 QC-02 假阴/假阳双向竞态的机器层根源，故阳性向量不在 CLI 层断言，
 *    CLI 层只断言阴性/接线（下两层）。
 * 2. CLI 接线（真实 qacore/cli.mjs 快速质检）：B-like（noAudio）阴性不误报 ×5；
 *    慢桥（PF 桥 ~1200ms 装配）有界等待生效 ×3（桥等待修复 string 页函数表达式
 *    恒真放行的坑，见 run.ts 注释）。
 * 3. 判定向量（checks.evaluate，qacore/tests/unit.test.mjs）：旗驱动值 1 → 恰
 *    CHK04 fail 且文案逐字保持（checks.ts 零改动的证据面）。
 *
 * 夹具只读（sha256 前后不变复核）。
 * 运行：node --test qacore/tests/autoplay-flag.test.mjs（需 chromium）。
 */
import test from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { createServer } from "node:http";
import { readFileSync, rmSync, existsSync, mkdirSync } from "node:fs";
import { createHash } from "node:crypto";
import { chromium } from "playwright";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { PROBE_JS } from "./../src/probe.ts";

const FACTORY_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const QACORE_CLI = join(FACTORY_ROOT, "qacore", "cli.mjs");
const FIXTURES = join(FACTORY_ROOT, "qacore", "tests", "fixtures");
const FIXTURE_B = join(FIXTURES, "audio-b-like.html");
const FIXTURE_SLOW = join(FIXTURES, "audio-slow-bridge.html");
const TMP_DIR = join(FACTORY_ROOT, "tmp", "qacore-eval", "autoplay-flag");

function runQacore(artifact, extraArgs, outPath) {
  const args = ["run", artifact, "--out", outPath, ...extraArgs];
  const proc = spawnSync(process.execPath, [QACORE_CLI, ...args], {
    cwd: FACTORY_ROOT,
    timeout: 300_000,
    encoding: "utf8",
    windowsHide: true,
  });
  return { code: proc.status, stdout: proc.stdout ?? "", stderr: proc.stderr ?? "" };
}

function readReport(outPath) {
  assert.ok(existsSync(outPath), `报告未产出：${outPath}`);
  return JSON.parse(readFileSync(outPath, "utf8"));
}

function sha256(p) {
  return createHash("sha256").update(readFileSync(p)).digest("hex");
}

/** 与 CLI 同款仿真 + 真实 PROBE_JS 的独立页面（页级旗契约用）。 */
async function openProbedPage(browser, url) {
  const context = await browser.newContext({
    viewport: { width: 390, height: 844 }, isMobile: true, deviceScaleFactor: 2,
    serviceWorkers: "block",
  });
  const page = await context.newPage();
  void page.addInitScript(new Function(PROBE_JS));
  await page.goto(url, { waitUntil: "load", timeout: 15000 });
  return { context, page };
}

/** 与 qacore src/ev.ts 同款字符串页函数求值；旗读取表达式与 run.ts 采集侧逐字同源。 */
const ev = (page, src) => page.evaluate(new Function(`return (${src})();`));
const flagRead = (page) => ev(page,
  "() => { const p = window.__pfprobe; return p && p.audio"
  + " ? p.audio.everBeforeFirstGesture === true : null; }");

const BLANK_PAGE = `<!doctype html><html><head><meta charset="utf-8"></head>
<body><canvas id="c" width="64" height="64"></canvas></body></html>`;

function serveOnce(html) {
  const server = createServer((req, res) => {
    res.writeHead(200, { "content-type": "text/html; charset=utf-8" });
    res.end(html);
  });
  return new Promise((res) => server.listen(0, "127.0.0.1", res)).then(() => server);
}

test("探针旗契约：阴性 false；首指针前 running 置真（构造即 running 路径）；置真不复位；首指针后不置旗", async () => {
  const server = await serveOnce(BLANK_PAGE);
  const url = `http://127.0.0.1:${server.address().port}/blank.html`;
  const browser = await chromium.launch({ headless: true });
  try {
    // (a) 阴性：无任何 AudioContext → 旗 false（探针在位）
    {
      const { context, page } = await openProbedPage(browser, url);
      assert.equal(await ev(page, "() => !!window.__pfprobe"), true, "探针应已注入");
      assert.equal(await flagRead(page), false, "无 AudioContext → 旗应为 false");
      await context.close();
    }
    // (b) 阳性·构造即 running（首 pointer 前置真，同步记账，与 GC 无关）
    {
      const { context, page } = await openProbedPage(browser, url);
      const born = await page.evaluate(() => new AudioContext().state);
      assert.equal(born, "running",
        "CDP evaluate（userGesture）内构造应即 running（本机确定性路径）");
      assert.equal(await flagRead(page), true,
        "构造即 running（首 pointer 前）→ 旗应置真");
      // (c) 置真不复位：唯一下下文 suspend 落 suspended，旗必须保持 true；
      //     resume 回 running，旗仍 true（chk04-determinism 置真不复位语义）
      await page.evaluate(() => { window.__ac2 = new AudioContext(); });
      await page.evaluate(() => { void window.__ac2.suspend(); });
      await page.waitForFunction(
        () => window.__ac2.state === "suspended", null, { timeout: 5000 });
      assert.equal(await flagRead(page), true,
        "唯一下下文已 suspended，旗必须保持 true（置真不复位）");
      await page.evaluate(() => { void window.__ac2.resume(); });
      await page.waitForFunction(
        () => window.__ac2.state === "running", null, { timeout: 5000 });
      assert.equal(await flagRead(page), true, "resume 回 running 后旗仍 true");
      await context.close();
    }
    // (d) 时序判别：首 pointer 事件在前，running 在后 → 旗不得置真
    //     （CHK04 只罚首交互前的 running；旗的判别必须与采样时刻无关）
    {
      const { context, page } = await openProbedPage(browser, url);
      await page.mouse.move(20, 20);
      await page.mouse.down();  // 真实 pointer 事件：首手势时刻
      await page.mouse.up();
      await page.evaluate(() => { void new AudioContext().state; });
      assert.equal(await flagRead(page), false,
        "首 pointer 事件之后才出现的 running 不得置旗");
      await context.close();
    }
  } finally {
    await browser.close();
    await new Promise((res) => server.close(res));
  }
});

test("探针缺失时旗读取返回 null（None→fail 语义前提不因旗修订漂移）", async () => {
  const server = await serveOnce(BLANK_PAGE);
  const url = `http://127.0.0.1:${server.address().port}/blank.html`;
  const browser = await chromium.launch({ headless: true });
  try {
    const context = await browser.newContext();
    const page = await context.newPage(); // 不注入 PROBE_JS
    await page.goto(url, { waitUntil: "load", timeout: 15000 });
    assert.equal(await flagRead(page), null, "无探针 → 旗读取应为 null");
    await context.close();
  } finally {
    await browser.close();
    await new Promise((res) => server.close(res));
  }
});

test("B-like（noAudio）5 连跑：快速质检全 pass exit 0（旗阴性不误报，接线回归）", () => {
  mkdirSync(TMP_DIR, { recursive: true });
  const shaBefore = [FIXTURE_B, FIXTURE_SLOW].map(sha256);
  for (let i = 1; i <= 5; i++) {
    const outPath = join(TMP_DIR, `b-like-run${i}.report.json`);
    rmSync(outPath, { force: true }); // 先删旧报告：存在才是本次运行的真事实
    const { code, stdout, stderr } = runQacore(FIXTURE_B, ["--channel", "preview"], outPath);
    assert.equal(code, 0, `第 ${i}/5 跑应 exit 0\nstdout=${stdout}\nstderr=${stderr}`);
    const report = readReport(outPath);
    const fails = report.checks.filter((c) => c.status === "fail").map((c) => c.id);
    assert.deepEqual(fails, [], `第 ${i}/5 跑 FAIL 应为空，实得 [${fails}]`);
    const chk04 = report.checks.find((c) => c.id === "CHK04");
    assert.equal(chk04.status, "pass", `第 ${i}/5 跑 CHK04 应 pass`);
    const mute = report.facts.muteLoadTime;
    assert.equal(mute.audioRunningBeforeInteraction, 0,
      `第 ${i}/5 跑无 AudioContext，旗驱动值应=0，实得 ${mute.audioRunningBeforeInteraction}`);
    assert.equal(mute.firstMutedBeforeInteraction, true,
      `第 ${i}/5 跑 isMuted 应=true，实得 ${mute.firstMutedBeforeInteraction}`);
  }
  assert.deepEqual([FIXTURE_B, FIXTURE_SLOW].map(sha256), shaBefore, "夹具被改动（只读纪律）");
});

test("慢桥（PF 桥 ~1200ms 后装配）3 连跑：快速质检等待桥就绪，CHK04 稳定 pass", () => {
  mkdirSync(TMP_DIR, { recursive: true });
  for (let i = 1; i <= 3; i++) {
    const outPath = join(TMP_DIR, `slow-bridge-run${i}.report.json`);
    rmSync(outPath, { force: true });
    const { code, stdout, stderr } = runQacore(FIXTURE_SLOW, ["--channel", "preview"], outPath);
    assert.equal(code, 0, `第 ${i}/3 跑应 exit 0\nstdout=${stdout}\nstderr=${stderr}`);
    const report = readReport(outPath);
    const fails = report.checks.filter((c) => c.status === "fail").map((c) => c.id);
    assert.deepEqual(fails, [], `第 ${i}/3 跑 FAIL 应为空，实得 [${fails}]`);
    const chk04 = report.checks.find((c) => c.id === "CHK04");
    assert.equal(chk04.status, "pass",
      `第 ${i}/3 跑 CHK04 应 pass（桥就绪等待生效），实得 ${chk04.status}：${chk04.detail}`);
    assert.equal(report.facts.muteLoadTime.firstMutedBeforeInteraction, true,
      `第 ${i}/3 跑应读到桥上真实 isMuted=true（而非等待前的 None），`
      + `实得 ${report.facts.muteLoadTime.firstMutedBeforeInteraction}`);
    assert.equal(report.pf.present, true, `第 ${i}/3 跑 pf.present 应 true`);
  }
});

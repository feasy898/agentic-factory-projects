// pf/test/pf.test.mjs — pf 编排 CLI eval（无浏览器部分）：validate 11 件同判 + 占位
// 退出码 + glob/复用/端口等单元语义。真实执行 exit 0（AGENTS.md 纪律）。
//
// F1 对齐（决策 §3.2）：validate 期望 = oracle 双侧实测基线（packages/spec/test/
// eval-matrix.test.mjs 同表——bad 样本属规格，期望永不改）；本件从 CLI 层复测
// 同一套裁定（exit 码 + OK/INVALID 计数 + {path, code} 集），门禁不锁消息字节。
import test from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..");
const PF = join(ROOT, "pf", "pf.mjs");
const TMP = join(ROOT, "tmp", "pf-eval");

function pf(args, opts = {}) {
  const proc = spawnSync(process.execPath, [PF, ...args], {
    cwd: ROOT, encoding: "utf8", timeout: opts.timeout ?? 120_000, windowsHide: true,
  });
  return { code: proc.status, stdout: proc.stdout ?? "", stderr: proc.stderr ?? "" };
}

// oracle 基线（{path, code} 集，与 packages/spec/test/eval-matrix.test.mjs 同表）。
const GOLDEN_OK = [
  "specs-eval/golden-match3.json",
  "specs-eval/golden-merge.json",
  "specs-eval/golden-pullpin.json",
  "specs-eval/golden-sort.json",
  "specs-eval/demo-zh.json",
];
const BAD_EXPECT = {
  "specs-eval/bad/01-missing-field.json": [["$.flow", "schema-required"]],
  "specs-eval/bad/02-pullpin-unsolvable.json": [["$.game.params.orderSolution[0]", "I1-pullpin-unsolvable"]],
  "specs-eval/bad/03-duration-over-budget.json": [["$.game.durationBudgetSec.max", "schema-maximum"]],
  "specs-eval/bad/04-missing-locale-strings.json": [["$.i18n.strings.ja", "I5-i18n-coverage"]],
  "specs-eval/bad/05-bad-url.json": [["$.flow.endScreen.landingUrl", "schema-pattern"]],
  "specs-eval/bad/06-unknown-template.json": [["$.game.template", "schema-enum"]],
};

test("pf validate：golden×4 + demo-zh 全 OK，exit 0（F1 正向半边）", () => {
  const r = pf(["validate", ...GOLDEN_OK]);
  assert.equal(r.code, 0, `stdout=${r.stdout}\nstderr=${r.stderr}`);
  for (const rel of GOLDEN_OK) assert.match(r.stdout, new RegExp(`^OK\\s+${rel}$`, "m"));
  assert.match(r.stdout, /^validate: 5\/5 通过$/m);
});

test("pf validate：bad×6 glob 展开（Windows shell 不展开由 CLI 自行展开），exit 1 + {path,code} 与 oracle 基线逐件全等", () => {
  const r = pf(["validate", "specs-eval/bad/*.json"]);
  assert.equal(r.code, 1);
  assert.match(r.stdout, /^validate: 0\/6 通过$/m);
  for (const [rel, expect] of Object.entries(BAD_EXPECT)) {
    assert.match(r.stdout, new RegExp(`^INVALID ${rel}$`, "m"), rel);
    // 抽该文件 issue 块（到下一个 INVALID/validate 行为止），比对 {path, code} 集
    const block = r.stdout.split(`INVALID ${rel}`)[1]?.split(/^INVALID |^validate:/m)[0] ?? "";
    const got = [...block.matchAll(/^\s+(\$\S+): .*\[([^\]]+)\]$/gm)].map((m) => [m[1], m[2]]);
    assert.deepEqual(got, expect, `${rel} 的 {path,code} 集`);
  }
});

test("pf validate：无匹配 glob → io-not-found 计败 exit 1；零参数 → argparse 用法错误 exit 2（oracle nargs='+' 同语义）", () => {
  const miss = pf(["validate", "specs-eval/none-such-*.json"]);
  assert.equal(miss.code, 1);
  assert.match(miss.stdout, /INVALID <pattern>: 模式无匹配文件：specs-eval\/none-such-\*\.json \[io-not-found\]/);
  const none = pf(["validate"]);
  assert.equal(none.code, 2, "用法错误属 exit 2（契约 §2）");
});

test("pf 占位子命令 build/pack/rules-check → exit 2（占位语义本身是契约，pipeline-contract §2）", () => {
  assert.equal(pf(["build", "x.json"]).code, 2);
  assert.equal(pf(["pack", "x.json", "--all-channels"]).code, 2);
  assert.equal(pf(["rules-check"]).code, 2);
  assert.match(pf(["build", "x.json"]).stdout, /尚未实现（当前为占位）/);
});

test("pf 用法错误：未知子命令/未知旗标 → exit 2；无参数 → 帮助 exit 0", () => {
  assert.equal(pf(["no-such-cmd"]).code, 2);
  assert.equal(pf([], ).code, 0);
});

test("pf make 用法/环境错误：spec 不存在 → exit 2；坏 spec → exit 1（校验是第一道闸）", () => {
  mkdirSync(TMP, { recursive: true });
  const missing = pf(["make", "--spec", "specs-eval/no-such-spec.json", "--no-serve"]);
  assert.equal(missing.code, 2);
  assert.match(missing.stderr, /spec 不存在/);
  const bad = pf(["make", "--spec", "specs-eval/bad/01-missing-field.json", "--no-serve"]);
  assert.equal(bad.code, 1);
  assert.match(bad.stderr, /spec 校验未通过/);
});

test("pf make 渠道语义：规则库外渠道 → exit 2（渠道拼写错误不是 1）", () => {
  const r = pf(["make", "--spec", "specs-eval/golden-match3.json", "--channels", "no-such-channel", "--no-serve"]);
  assert.equal(r.code, 2);
  assert.match(r.stderr, /渠道不在规则库/);
});

test("pf static-server 子进程：文件 200 / 目录 index 200 / 穿越与缺失 404 / MIME 正确", async () => {
  mkdirSync(join(TMP, "srv", "sub"), { recursive: true });
  writeFileSync(join(TMP, "srv", "a.html"), "<h1>ok</h1>");
  writeFileSync(join(TMP, "srv", "sub", "index.html"), "<h1>idx</h1>");
  const { makeStaticHandler } = await import("../src/static.ts");
  const http = await import("node:http");
  const { portListening } = await import("../src/util.ts");
  const server = http.createServer(makeStaticHandler({ root: join(TMP, "srv") }));
  await new Promise((res) => server.listen(0, "127.0.0.1", res));
  const port = server.address().port;
  try {
    assert.ok(await portListening(port), "TCP 监听实测");
    const get = (path) => fetch(`http://127.0.0.1:${port}${path}`);
    const a = await get("/a.html");
    assert.equal(a.status, 200);
    assert.match(a.headers.get("content-type") ?? "", /text\/html/);
    const idx = await get("/sub/");
    assert.equal(idx.status, 200);
    assert.match(await idx.text(), /idx/);
    assert.equal((await get("/nope.html")).status, 404);
    assert.equal((await get("/../../package.json")).status, 404);
  } finally {
    server.close();
    server.closeAllConnections?.();
  }
});

test("pf 网络探测单元：addrTier 段优先级表逐值 + pidIsOurServer 拒绝非正整数", async () => {
  const { addrTier, pidIsOurServer } = await import("../src/util.ts");
  assert.equal(addrTier("198.51.100.22"), 0);
  assert.equal(addrTier("10.0.0.1"), 1);
  assert.equal(addrTier("172.16.0.1"), 2);
  assert.equal(addrTier("172.32.0.1"), 8);
  assert.equal(addrTier("100.100.0.5"), 3);
  assert.equal(addrTier("100.128.0.1"), 8);
  assert.equal(addrTier("198.18.0.1"), 9);
  assert.equal(addrTier("198.19.255.255"), 9);
  assert.equal(addrTier("8.8.8.8"), 5);
  assert.equal(pidIsOurServer(-1), false);
  assert.equal(pidIsOurServer(0), false);
  assert.equal(pidIsOurServer("123"), false);
});

test("pf 伺服复用三重核实：同根复用 / PID 已死清状态换口（防 PID 复用误判语义）", async () => {
  mkdirSync(join(TMP, "reuse-root-a"), { recursive: true });
  mkdirSync(join(TMP, "reuse-root-b"), { recursive: true });
  const { ensureServer, SERVE_STATE_NAME } = await import("../src/server-util.ts");
  const outRoot = join(TMP, "reuse-out");
  mkdirSync(outRoot, { recursive: true });

  // 1) 陈旧状态（PID 999999 几乎必不存在）→ 清状态、起伺服器 → 新端口。
  writeFileSync(join(outRoot, SERVE_STATE_NAME),
    `${JSON.stringify({ port: 8_699, pid: 999_999, root: join(TMP, "reuse-root-a"), started: "2026-09-30T00:00:00" })}\n`);
  const [port1, reused1] = await ensureServer(outRoot, join(TMP, "reuse-root-a"), 8700);
  assert.equal(reused1, false, "陈旧状态不得复用");
  assert.ok(port1 >= 8700 && port1 < 8720, `端口顺延窗：${port1}`);
  assert.ok(existsSync(join(outRoot, SERVE_STATE_NAME)), "新状态已写");

  // 2) 同根同状态 → 三重核实通过 → 复用。
  const [port2, reused2] = await ensureServer(outRoot, join(TMP, "reuse-root-a"), 8618);
  assert.equal(reused2, true, "同根+端口活+PID 验明 → 复用");
  assert.equal(port2, port1);

  // 3) 伺服根变更 + PID 验明为我方 node → 杀旧、状态清零、起新。
  const state = JSON.parse(readFileSync(join(outRoot, SERVE_STATE_NAME), "utf8"));
  assert.equal(typeof state.pid, "number");
  const [port3, reused3] = await ensureServer(outRoot, join(TMP, "reuse-root-b"), 8618);
  assert.equal(reused3, false, "伺服根变更不得复用");
  assert.ok(port3 >= 8618, "换口或原口重起");

  // 清理：杀掉本次起的伺服器（各自 root 独立，互不误伤）。
  const { killPid } = await import("../src/util.ts");
  for (const st of [join(outRoot, SERVE_STATE_NAME)]) {
    if (existsSync(st)) {
      const s = JSON.parse(readFileSync(st, "utf8"));
      killPid(s.pid);
      rmSync(st, { force: true });
    }
  }
});

test("pf glob 展开：单层与 ** 递归与排序（oracle _expand_spec_paths 同义）", async () => {
  const { expandSpecPaths } = await import("../src/util.ts");
  const { files } = expandSpecPaths(["specs-eval/bad/*.json"]);
  assert.deepEqual(files.map((f) => f.replaceAll("\\", "/")), [
    "specs-eval/bad/01-missing-field.json",
    "specs-eval/bad/02-pullpin-unsolvable.json",
    "specs-eval/bad/03-duration-over-budget.json",
    "specs-eval/bad/04-missing-locale-strings.json",
    "specs-eval/bad/05-bad-url.json",
    "specs-eval/bad/06-unknown-template.json",
  ]);
  const rec = expandSpecPaths(["specs-eval/**/*.json"]);
  assert.ok(rec.files.some((f) => f.replaceAll("\\", "/").endsWith("demo-zh.json")), "** 递归命中子目录上层");
  const plain = expandSpecPaths(["specs-eval/golden-match3.json"]);
  assert.deepEqual(plain.files.map((f) => f.replaceAll("\\", "/")), ["specs-eval/golden-match3.json"]);
  assert.deepEqual(plain.unmatched, []);
});

test("pf CHK10 判定输入推导：requiredTextsFor 与 oracle 同源（标题/教程/胜/CTA/分；lose 不要求）", async () => {
  const { requiredTextsFor } = await import("../src/shared.ts");
  const spec = JSON.parse(readFileSync(join(ROOT, "specs-eval", "golden-match3.json"), "utf8"));
  const en = requiredTextsFor(spec, "en");
  assert.ok(en.includes(String(spec.meta.title)), "标题在内");
  assert.ok(en.includes(String(spec.i18n.strings.en.tutorial)), "教程在内");
  assert.ok(en.includes(String(spec.i18n.strings.en.win)), "胜在内");
  const ctaKey = String(spec.flow.endScreen.ctaKey ?? "cta");
  assert.ok(en.includes(String(spec.i18n.strings.en[ctaKey])), "CTA 在内");
  assert.ok(!en.some((t) => t === String(spec.i18n.strings.en.lose)), "lose 不要求（自动试玩必胜）");
});

test("pf e2e：spec mtime 计时口径与 LAN IP 探测存在（lanIp 返回非 127.* 或退化值）", async () => {
  const { lanIp } = await import("../src/util.ts");
  const ip = await lanIp();
  assert.match(ip, /^\d+\.\d+\.\d+\.\d+$/);
  // 本机 tailnet+局域网双栈，允许 127.0.0.1 退化（无任何非回环 IPv4 时）——但本机必有。
  assert.notEqual(ip, "");
});

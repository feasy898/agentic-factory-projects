#!/usr/bin/env node
// scripts/diff/d3-cli-exitcodes.mjs — 差分维度 F7：CLI 退出码矩阵（决策 §3.2 F7）。
//
// 全家：validate / make / qacore / serve / packager（bin.mjs）。同输入 → 同退出码（0/1/2 语义）。
// 浏览器类探针（qacore 带 --autoplay、serve HTTP 探活）建议在 d2 交叉质检结束后串行执行，
// 避免并发 chromium 扰动 CHK09 加载墙钟（本 harness 不并发浏览器）。
//
// 用法：node scripts/diff/d3-cli-exitcodes.mjs <outJson> [--with-browser]
// 退出码：0 双实现同判；1 有回归级不等；2 用法/环境错误。

import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import process from "node:process";

const outJson = process.argv[2];
const WITH_BROWSER = process.argv.includes("--with-browser");
if (!outJson) { console.error("用法：node scripts/diff/d3-cli-exitcodes.mjs <outJson> [--with-browser]"); process.exit(2); }

const FACTORY = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
const ORACLE = resolve(FACTORY, "..", "repo");
const PY = join(ORACLE, "python", ".venv", "Scripts", "python.exe");
if (!existsSync(PY)) { console.error("d3: oracle venv python 不存在:", PY); process.exit(2); }

const WS = join(FACTORY, "tmp", "diff", "cli");
rmSync(WS, { recursive: true, force: true });
mkdirSync(WS, { recursive: true });

const rows = [];
function probe(id, impl, cmd, opts = {}) {
  const r = spawnSync(cmd[0], cmd.slice(1), {
    encoding: "utf8", windowsHide: true, timeout: (opts.timeoutSec ?? 120) * 1000,
    cwd: opts.cwd, env: opts.env ?? process.env, maxBuffer: 64 * 1024 * 1024,
    input: opts.input,
  });
  const row = {
    id, impl, args: cmd.slice(2).join(" ").slice(0, 160),
    exit: r.status, timedOut: Boolean(r.error && r.error.code === "ABORT_ERR"),
    stdoutTail: (r.stdout ?? "").trim().split(/\r?\n/).slice(-2).join(" | ").slice(0, 200),
    stderrTail: (r.stderr ?? "").trim().split(/\r?\n/).slice(-2).join(" | ").slice(0, 200),
  };
  rows.push(row);
  return row;
}

const N_VALIDATE = [process.execPath, join(FACTORY, "pf", "pf.mjs"), "validate"];
const O_VALIDATE = [PY, "-m", "pfcore", "validate"];
const N_MAKE = [process.execPath, join(FACTORY, "pf", "pf.mjs"), "make"];
const O_MAKE = [PY, "-m", "pfcore", "make"];
const N_QC = [process.execPath, join(FACTORY, "qacore", "cli.mjs"), "run"];
const O_QC = [PY, "-m", "qacore", "run"];
const N_SERVE = [process.execPath, join(FACTORY, "pf", "pf.mjs"), "serve"];
const O_SERVE = [PY, "-m", "pfcore", "serve"];
const N_PACK = [process.execPath, join(FACTORY, "packages", "packager", "bin.mjs"), "build"];
const O_PACK = [process.execPath, join(ORACLE, "packages", "packager", "bin.mjs"), "build"];

// 用法层探针的构造：oracle 子进程命令 = [PY, -m, <module>, <subcommand>...]；
// 「无参数用法错」= 去掉子命令位置参数本身，保留 [PY, -m, <module>, <sub>]。
const O_VALIDATE_NOARGS = [PY, "-m", "pfcore", "validate"];
const O_MAKE_NOARGS = [PY, "-m", "pfcore", "make"];

// ---------------------------------------------------------------- validate：11 件 + glob + 用法错
const evalFiles = [
  "specs-eval/golden-match3.json", "specs-eval/golden-merge.json", "specs-eval/golden-pullpin.json", "specs-eval/golden-sort.json",
  "specs-eval/demo-zh.json",
  "specs-eval/bad/01-missing-field.json", "specs-eval/bad/02-pullpin-unsolvable.json", "specs-eval/bad/03-duration-over-budget.json",
  "specs-eval/bad/04-missing-locale-strings.json", "specs-eval/bad/05-bad-url.json", "specs-eval/bad/06-unknown-template.json",
];
for (const f of evalFiles) {
  const n = probe(`validate:${f.split("/").pop()}`, "N", [...N_VALIDATE, f], { cwd: FACTORY });
  const o = probe(`validate:${f.split("/").pop()}`, "O", [...O_VALIDATE, f], { cwd: ORACLE, env: { ...process.env, PYTHONUTF8: "1" } });
  rows.push({ id: `validate-pair:${f.split("/").pop()}`, pair: true, equal: n.exit === o.exit, n: n.exit, o: o.exit });
}
{
  const n = probe("validate:glob", "N", [...N_VALIDATE, "specs-eval/golden-*.json"], { cwd: FACTORY });
  const o = probe("validate:glob", "O", [...O_VALIDATE, "specs-eval/golden-*.json"], { cwd: ORACLE, env: { ...process.env, PYTHONUTF8: "1" } });
  rows.push({ id: "validate-pair:glob", pair: true, equal: n.exit === o.exit, n: n.exit, o: o.exit });
  const n2 = probe("validate:no-args", "N", [process.execPath, join(FACTORY, "pf", "pf.mjs"), "validate"], { cwd: FACTORY });
  const o2 = probe("validate:no-args", "O", O_VALIDATE_NOARGS, { cwd: ORACLE, env: { ...process.env, PYTHONUTF8: "1" } });
  rows.push({ id: "validate-pair:no-args(用法2)", pair: true, equal: n2.exit === o2.exit, n: n2.exit, o: o2.exit });
}

// ---------------------------------------------------------------- make：用法错 / 坏 spec / 未知渠道
{
  const n = probe("make:no-spec", "N", [process.execPath, join(FACTORY, "pf", "pf.mjs"), "make"], { cwd: FACTORY });
  const o = probe("make:no-spec", "O", O_MAKE_NOARGS, { cwd: ORACLE, env: { ...process.env, PYTHONUTF8: "1" } });
  rows.push({ id: "make-pair:no-spec(用法)", pair: true, equal: n.exit === o.exit, n: n.exit, o: o.exit });
  const bad = "specs-eval/bad/01-missing-field.json";
  const n2 = probe("make:bad-spec", "N", [...N_MAKE, "--spec", bad, "--no-serve", "--no-assetkit", "--out", join(WS, "n-badspec")], { cwd: FACTORY });
  const o2 = probe("make:bad-spec", "O", [...O_MAKE, "--spec", bad, "--no-serve", "--no-assetkit", "--out", join(WS, "o-badspec")], { cwd: ORACLE, env: { ...process.env, PYTHONUTF8: "1" } });
  rows.push({ id: "make-pair:bad-spec(判定1)", pair: true, equal: n2.exit === o2.exit, n: n2.exit, o: o2.exit });
  const n3 = probe("make:unknown-channel", "N", [...N_MAKE, "--spec", "specs-eval/golden-match3.json", "--locales", "en", "--channels", "not-a-channel", "--no-serve", "--no-assetkit", "--out", join(WS, "n-badchan")], { cwd: FACTORY });
  const o3 = probe("make:unknown-channel", "O", [...O_MAKE, "--spec", "specs-eval/golden-match3.json", "--locales", "en", "--channels", "not-a-channel", "--no-serve", "--no-assetkit", "--out", join(WS, "o-badchan")], { cwd: ORACLE, env: { ...process.env, PYTHONUTF8: "1" } });
  rows.push({ id: "make-pair:unknown-channel", pair: true, equal: n3.exit === o3.exit, n: n3.exit, o: o3.exit });
}

// ---------------------------------------------------------------- packager：用法错 / 未知渠道 / 正常 0 + 字节复现
{
  const n = probe("pack:no-args", "N", [N_PACK[0], N_PACK[1]], { cwd: FACTORY });
  const o = probe("pack:no-args", "O", [O_PACK[0], O_PACK[1]], { cwd: ORACLE });
  rows.push({ id: "pack-pair:no-args(用法2)", pair: true, equal: n.exit === o.exit, n: n.exit, o: o.exit });
  const n2 = probe("pack:unknown-channel", "N", [...N_PACK, "--spec", "specs-eval/golden-match3.json", "--dist", "packages/packager/test/fixture/match3-dist", "--channel", "not-a-channel", "--locale", "en", "--out", join(WS, "n-pack-bad")], { cwd: FACTORY });
  const o2 = probe("pack:unknown-channel", "O", [...O_PACK, "--spec", "specs-eval/golden-match3.json", "--dist", "packages/packager/test/fixture/match3-dist", "--channel", "not-a-channel", "--locale", "en", "--out", join(WS, "o-pack-bad")], { cwd: ORACLE });
  rows.push({ id: "pack-pair:unknown-channel", pair: true, equal: n2.exit === o2.exit, n: n2.exit, o: o2.exit });
  // 正常打包（oracle 冻结夹具 match3-dist，两侧同夹具字节复用）+ 双跑字节一致
  const fixture = "packages/packager/test/fixture/match3-dist";
  const sha = (p) => createHash("sha256").update(readFileSync(p)).digest("hex");
  for (const [impl, cmd, cwd, outd] of [
    ["N", N_PACK, FACTORY, join(WS, "n-pack")],
    ["O", O_PACK, ORACLE, join(WS, "o-pack")],
  ]) {
    const shas = [];
    let lastExit = null;
    for (let i = 1; i <= 2; i++) {
      rmSync(outd, { recursive: true, force: true });
      const r = probe(`pack:ok#${i}`, impl, [...cmd, "--spec", "specs-eval/golden-match3.json", "--dist", fixture, "--channel", "tiktok", "--locale", "en", "--out", outd], { cwd });
      lastExit = r.exit;
      const f = join(outd, "golden-match3", "tiktok", "en");
      if (r.exit === 0 && existsSync(join(f, "golden-match3-en.zip"))) shas.push(sha(join(f, "golden-match3-en.zip")));
      else shas.push(null);
    }
    rows.push({ id: `pack-repro:${impl}(同输入两次构建字节一致)`, impl, ok: shas[0] !== null && shas[0] === shas[1], exit: lastExit, shas });
  }
}

// ---------------------------------------------------------------- qacore / serve（浏览器类，默认 --with-browser 才跑）
if (WITH_BROWSER) {
  // 0：金标产物快速通过（不 autoplay，取 factory 现成 applovin en 包）
  const passArtifact = join(FACTORY, "artifacts", "matrix", "golden-match3", "applovin", "en", "index.html");
  const n0 = probe("qc:pass-artifact", "N", [...N_QC, passArtifact, "--channel", "applovin", "--out", join(WS, "n-qc0.json")], { cwd: FACTORY, timeoutSec: 180 });
  const o0 = probe("qc:pass-artifact", "O", [...O_QC, passArtifact, "--channel", "applovin", "--out", join(WS, "o-qc0.json")], { cwd: ORACLE, timeoutSec: 180, env: { ...process.env, PYTHONUTF8: "1" } });
  rows.push({ id: "qc-pair:pass-artifact(0)", pair: true, equal: n0.exit === o0.exit, n: n0.exit, o: o0.exit });
  // 2：产物不存在
  const missing = join(WS, "no-such.html");
  const n2 = probe("qc:missing-artifact", "N", [...N_QC, missing, "--channel", "applovin"], { cwd: FACTORY });
  const o2 = probe("qc:missing-artifact", "O", [...O_QC, missing, "--channel", "applovin"], { cwd: ORACLE, env: { ...process.env, PYTHONUTF8: "1" } });
  rows.push({ id: "qc-pair:missing-artifact(2)", pair: true, equal: n2.exit === o2.exit, n: n2.exit, o: o2.exit });
  const n2b = probe("qc:no-args", "N", [process.execPath, join(FACTORY, "qacore", "cli.mjs"), "run"], { cwd: FACTORY });
  const o2b = probe("qc:no-args", "O", [PY, "-m", "qacore", "run"], { cwd: ORACLE, env: { ...process.env, PYTHONUTF8: "1" } });
  rows.push({ id: "qc-pair:no-args(用法2)", pair: true, equal: n2b.exit === o2b.exit, n: n2b.exit, o: o2b.exit });
  // 1：CHK09 阈值压到 0.001s 强制失败（同产物同判官语义，两侧都应 exit 1）
  const n1 = probe("qc:chk09-forced-fail", "N", [...N_QC, passArtifact, "--channel", "applovin", "--max-load-sec", "0.001", "--out", join(WS, "n-qc1.json")], { cwd: FACTORY, timeoutSec: 180 });
  const o1 = probe("qc:chk09-forced-fail", "O", [...O_QC, passArtifact, "--channel", "applovin", "--max-load-sec", "0.001", "--out", join(WS, "o-qc1.json")], { cwd: ORACLE, timeoutSec: 180, env: { ...process.env, PYTHONUTF8: "1" } });
  rows.push({ id: "qc-pair:chk09-forced-fail(1)", pair: true, equal: n1.exit === o1.exit, n: n1.exit, o: o1.exit });
  // serve：根不存在（不阻塞）
  const nS = probe("serve:missing-root", "N", [...N_SERVE, "--root", join(WS, "no-root"), "--port", "18631"], { cwd: FACTORY });
  const oS = probe("serve:missing-root", "O", [...O_SERVE, "--root", join(WS, "no-root"), "--port", "18631"], { cwd: ORACLE, env: { ...process.env, PYTHONUTF8: "1" } });
  rows.push({ id: "serve-pair:missing-root", pair: true, equal: nS.exit === oS.exit, n: nS.exit, o: oS.exit, nTail: nS.stderrTail || nS.stdoutTail, oTail: oS.stderrTail || oS.stdoutTail });
}

// ---------------------------------------------------------------- 判定
const pairs = rows.filter((r) => r.pair);
const reproRows = rows.filter((r) => r.id.startsWith("pack-repro:"));
const badPairs = pairs.filter((r) => !r.equal);
const badRepro = reproRows.filter((r) => !r.ok);
const evidence = {
  capturedAt: new Date().toISOString(),
  withBrowser: WITH_BROWSER,
  rows, pairs, repro: reproRows,
  regressions: [
    ...badPairs.map((r) => ({ item: r.id, severity: "regression", detail: `exit 不等 N=${r.n} O=${r.o}` })),
    ...badRepro.map((r) => ({ item: r.id, severity: "regression", detail: `字节不一致 ${JSON.stringify(r.shas)}` })),
  ],
  verdict: badPairs.length + badRepro.length === 0 ? "PASS（双实现同判）" : "FAIL（存在回归）",
};
writeFileSync(outJson, JSON.stringify(evidence, null, 2) + "\n", "utf8");
console.log(`d3-cli-exitcodes: probes=${rows.length} pairs=${pairs.length} 不等=${badPairs.length} 复现失败=${badRepro.length}`);
for (const b of badPairs) console.error(`  不等 ${b.id}: N=${b.n} O=${b.o}`);
for (const b of badRepro) console.error(`  复现失败 ${b.id}`);
console.log(`d3-cli-exitcodes: ${evidence.verdict} → ${outJson}`);
process.exit(badPairs.length + badRepro.length === 0 ? 0 : 1);

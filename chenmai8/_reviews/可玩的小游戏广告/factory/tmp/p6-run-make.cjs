// tmp/p6-run-make.cjs — P6 计时壳：驱动任一实现的冻结 make CLI 并输出墙钟。
// 用法：node tmp/p6-run-make.cjs <label> <cwd> <cmd0> <cmd1...> [--out <dir>]
const { performance } = require("node:perf_hooks");
const { spawnSync } = require("node:child_process");
const path = require("path");

const label = process.argv[2];
const cwd = process.argv[3];
const rest = process.argv.slice(4);
const outIdx = rest.indexOf("--out");
const env = { ...process.env, PYTHONUTF8: "1" };
const t0 = performance.now();
const r = spawnSync(rest[0], rest.slice(1), { cwd: path.resolve(cwd), encoding: "utf8", timeout: 600000, windowsHide: true, maxBuffer: 64 * 1024 * 1024, env });
const wall = (performance.now() - t0) / 1000;
const fs = require("fs");
fs.writeFileSync(path.resolve(cwd, "..", "factory", "tmp", "diff", "p6", `wall-${label}.json`),
  JSON.stringify({ label, exit: r.status, wallSec: Math.round(wall * 10) / 10, tail: (r.stdout || "").trim().split(/\r?\n/).slice(-2) }, null, 1));
console.log(`${label} make exit=${r.status} wallSec=${Math.round(wall * 10) / 10}`);
console.log((r.stdout || "").trim().split(/\r?\n/).slice(-2).join("\n"));
if (r.status !== 0) console.log("STDERR:", (r.stderr || "").slice(-300));
process.exit(r.status === 0 ? 0 : 1);

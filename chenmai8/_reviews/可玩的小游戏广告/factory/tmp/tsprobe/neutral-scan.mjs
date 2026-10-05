// 用途：法务红线扫描（不入库的临时脚本）：入库树（git ls-files + 本任务新增待入库名单）
// 对仓外词表 D:/upstream-refs/neutral-words.txt 做 casefold 子串匹配（路径与内容）。
import { execSync } from "node:child_process";
import { readFileSync, statSync } from "node:fs";
import { join } from "node:path";

const root = process.cwd();
const words = readFileSync("D:/upstream-refs/neutral-words.txt", "utf8")
  .split(/\r?\n/)
  .map((l) => l.trim())
  .filter((l) => l && !l.startsWith("#"))
  .map((l) => l.toLowerCase());

const tracked = execSync("git ls-files", { cwd: root, encoding: "utf8" })
  .split(/\r?\n/).filter(Boolean);
// 本任务新增、尚未入库的文件一并纳入扫描（commit 前预检）。
const pending = [
  "packages/spec/index.ts",
  "packages/spec/src/types.ts",
  "packages/spec/src/invariants.ts",
  "packages/spec/src/validate.ts",
  "packages/spec/src/validate.mjs",
  "packages/spec/tsconfig.json",
  "packages/spec/test/ajv-check.mjs",
  "packages/spec/test/eval-matrix.test.mjs",
  "packages/spec/test/invariants.test.mjs",
  "scripts/diff/spec-eval-diff.mjs",
  "docs/specs/spec.md",
  "REUSED-ASSETS.md",
  "docs/specs/README.md",
  "test/assets.test.mjs",
];
const files = [...new Set([...tracked, ...pending])].filter((f) => {
  try { return statSync(join(root, f)).isFile(); } catch { return false; }
});

let hits = 0;
let scanned = 0;
for (const f of files) {
  scanned++;
  const rel = f.toLowerCase();
  for (const w of words) {
    if (rel.includes(w)) { console.log(`PATH-HIT [${w}] ${f}`); hits++; }
  }
  let content;
  try { content = readFileSync(join(root, f), "utf8"); } catch { continue; }
  const lc = content.toLowerCase();
  for (const w of words) {
    if (lc.includes(w)) { console.log(`CONTENT-HIT [${w}] ${f}`); hits++; }
  }
}
console.log(`neutral-scan: ${scanned} 文件 × ${words.length} 词，命中 ${hits}`);
process.exit(hits === 0 ? 0 : 1);

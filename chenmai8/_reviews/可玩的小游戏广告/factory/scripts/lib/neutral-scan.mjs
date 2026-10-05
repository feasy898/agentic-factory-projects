// scripts/lib/neutral-scan.mjs — 中性名扫描共享件（oracle gate_mainpath.check_neutral_names 语义）。
//
// 入库树（git ls-files 的路径与内容）对投放域上游词表大小写不敏感子串匹配，**零命中**才过；
// 词表含上游名、永不入库（AGENTS.md：本机 D:/upstream-refs/neutral-words.txt，仓外）。
// 命中只报告不修改（改名/声明问题不碰——法务裁定）。gate-m1 与 gate-m2 共用本实现，防两份漂移。
import { spawnSync } from "node:child_process";
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

export const NEUTRAL_WORDLIST = process.env.PF_NEUTRAL_WORDS || "D:/upstream-refs/neutral-words.txt";

const FALLBACK_SKIP_DIRS = new Set([
  ".git", "node_modules", ".mimosa", "tmp", "artifacts", "coverage", ".venv", "__pycache__", "_vendor",
]);

function trackedFiles(root) {
  // 入库树以 git ls-files 为准；git 不可用时退化为目录枚举（跳过依赖/产物目录）——同 oracle。
  const g = spawnSync("git", ["ls-files", "-z"], { cwd: root, encoding: "buffer", timeout: 60_000 });
  if (!g.error && g.status === 0) {
    return Buffer.from(g.stdout).toString("utf8").split("\0").filter(Boolean)
      .map((n) => resolve(root, ...n.split("/")));
  }
  const out = [];
  const walk = (dir) => {
    for (const name of readdirSync(dir)) {
      const p = join(dir, name);
      let st;
      try { st = statSync(p); } catch { continue; }
      if (st.isDirectory()) {
        if (!FALLBACK_SKIP_DIRS.has(name)) walk(p);
      } else out.push(p);
    }
  };
  try { walk(root); } catch { return null; }
  return out;
}

/**
 * 执行扫描。返回 { ok, words, fileCount, scanned, hits }：
 * ok=false 时 hits 为命中清单（含路径/行号/词），wordlistMissing 表示词表缺失。
 */
export function scanNeutralNames(root) {
  if (!existsSync(NEUTRAL_WORDLIST)) {
    return { ok: false, wordlistMissing: true, words: 0, fileCount: 0, scanned: 0,
      hits: [`词表不存在：${NEUTRAL_WORDLIST}（含上游名不入库，需在本机仓外补建后重跑本门）`] };
  }
  const words = readFileSync(NEUTRAL_WORDLIST, "utf8").split(/\r?\n/)
    .map((l) => l.trim().toLowerCase())
    .filter((l) => l && !l.startsWith("#"));
  if (words.length === 0) {
    return { ok: false, wordlistMissing: true, words: 0, fileCount: 0, scanned: 0,
      hits: [`词表为空：${NEUTRAL_WORDLIST}`] };
  }

  const files = trackedFiles(root);
  if (!Array.isArray(files) || files.length === 0) {
    return { ok: false, words: words.length, fileCount: 0, scanned: 0,
      hits: ["入库树枚举失败（git ls-files 与目录枚举皆空）"] };
  }

  const hits = [];
  let scanned = 0;
  for (const f of files) {
    const rel = relative(root, f).split("\\").join("/");
    const relLow = rel.toLowerCase();
    const pathHits = words.filter((w) => relLow.includes(w));
    if (pathHits.length > 0) {
      hits.push(`${rel}: 路径命中 ${JSON.stringify(pathHits)}`);
      continue; // 路径已命中，内容不必再扫（同 oracle）
    }
    let text;
    try {
      if (!statSync(f).isFile()) continue;
      text = readFileSync(f, "utf8"); // 非法字节按 U+FFFD 替换（≈errors="replace"）
      scanned += 1;
    } catch { continue; }
    const lines = text.split(/\r?\n/);
    for (let i = 0; i < lines.length; i++) {
      const low = lines[i].toLowerCase();
      const hitWords = words.filter((w) => low.includes(w));
      if (hitWords.length > 0) {
        hits.push(`${rel}:${i + 1}: 命中 ${JSON.stringify(hitWords)}：${lines[i].trim().slice(0, 80)}`);
      }
    }
  }
  return { ok: hits.length === 0, words: words.length, fileCount: files.length, scanned, hits };
}

/** CLI 直跑入口：node scripts/lib/neutral-scan.mjs（门内用 lib，这里给人看）。 */
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const root = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
  const r = scanNeutralNames(root);
  console.log(`词表 ${NEUTRAL_WORDLIST}：${r.words} 词 × 入库 ${r.fileCount} 文件（扫描 ${r.scanned}）`);
  for (const h of r.hits.slice(0, 10)) console.log(`命中：${h}`);
  if (r.hits.length > 10) console.log(`……另有 ${r.hits.length - 10} 处（只报告不修改——法务裁定）`);
  console.log(r.ok ? "NEUTRAL-SCAN: PASS（零命中）" : "NEUTRAL-SCAN: FAIL");
  process.exitCode = r.ok ? 0 : 1;
}

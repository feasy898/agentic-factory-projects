#!/usr/bin/env node
/**
 * M4 packager 自验收（T1.3）：对 match3 占位工程跑三条渠道并逐项断言。
 *
 * 用法：node packages/packager/test/run.mjs
 * 全过 exit 0；任一断言失败 exit 1。
 *
 * 断言：
 *   applovin  单 HTML：存在、≤5MB（rules 上限）、白名单外零 http 外链、含 mraid.js 注入
 *   meta      单 HTML：≤3MB（rules+spec override 上限）、零外链、无 MRAID 引用
 *   mintegral zip：条目结构恰为 [build.js, Template.html]、zip ≤5MB、条目内零外链、
 *              Template.html 引用 build.js；python zipfile 交叉验证（有 venv 时）
 *   负向      dist 混入外链 → 构建失败；meta 混入 MRAID → 构建失败；未知渠道 → 失败
 *   复现性    同输入两次构建字节一致
 */
import { execFileSync, spawnSync } from "node:child_process";
import { mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, statSync, writeFileSync } from "node:fs";
import { cp as cpAsync } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { readZip } from "../src/zip.mjs";

const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");
const BIN = path.join(REPO_ROOT, "packages", "packager", "bin.mjs");
const SPEC = path.join(REPO_ROOT, "specs-eval", "golden-match3.json");
const FIXTURE = path.join(REPO_ROOT, "packages", "packager", "test", "fixture", "match3-dist");
const OUT = path.join(REPO_ROOT, "tmp", "packager-selftest");

const LANDING_URL = "https://example.com/playable-lp";
const MB = 1024 * 1024;

let failures = 0;
function check(label, ok, details = []) {
  console.log(`[${ok ? "PASS" : "FAIL"}] ${label}`);
  for (const d of details) console.log(`       ${d}`);
  if (!ok) failures++;
}

function build(channel, dist, locale = "en") {
  return spawnSync(process.execPath, [
    BIN, "build",
    "--spec", SPEC,
    "--dist", dist,
    "--channel", channel,
    "--locale", locale,
    "--out", OUT,
  ], { encoding: "utf8", cwd: REPO_ROOT });
}

/** 等价于 grep -rEo "https?://..." 的白名单扫描（对文本）。 */
function externalUrls(text) {
  const found = [...text.matchAll(/\bhttps?:\/\/[^\s"'<>\\)\]}]+/g)].map((m) => m[0]);
  return found.filter((u) => u !== LANDING_URL && !u.startsWith(LANDING_URL));
}

function listPackageFiles(dir) {
  return readdirSync(dir).filter((f) => f !== "pack-manifest.json");
}

async function main() {
  rmSync(OUT, { recursive: true, force: true });
  mkdirSync(OUT, { recursive: true });

  // ---------- 1) applovin：单 HTML 全内联 ----------
  {
    const r = build("applovin", FIXTURE);
    const dir = path.join(OUT, "golden-match3", "applovin", "en");
    const files = r.status === 0 ? listPackageFiles(dir) : [];
    const artifact = path.join(dir, "index.html");
    check("applovin: build exit 0", r.status === 0, r.status === 0 ? [] : [r.stderr.trim()]);
    const exists = files.includes("index.html") && statSync(artifact, { throwIfNoEntry: false })?.isFile();
    check("applovin: 产物存在（单文件 index.html）", Boolean(exists), [`目录内容: ${files.join(", ")}`]);
    const bytes = exists ? statSync(artifact).size : Infinity;
    check(`applovin: ≤5MB（实际 ${bytes} B ≤ 5242880）`, bytes <= 5 * MB);
    if (exists) {
      const html = readFileSync(artifact, "utf8");
      const bad = externalUrls(html);
      check("applovin: 白名单外零 http 外链（landingUrl 除外）", bad.length === 0, bad.map((u) => `外链: ${u}`));
      check("applovin: mraid.js 已按规则注入（相对引用，非外链）", html.includes('<script src="mraid.js"></script>'));
      check("applovin: 资源已内联（≥3 处 base64 data URI）", (html.match(/data:(?:image|audio|video)\//g) || []).length >= 3);
    }
  }

  // ---------- 2) meta：≤3MB + 禁 MRAID ----------
  {
    const r = build("meta", FIXTURE);
    const dir = path.join(OUT, "golden-match3", "meta", "en");
    const files = r.status === 0 ? listPackageFiles(dir) : [];
    const artifact = path.join(dir, "index.html");
    check("meta: build exit 0", r.status === 0, r.status === 0 ? [] : [r.stderr.trim()]);
    const exists = files.includes("index.html") && statSync(artifact, { throwIfNoEntry: false })?.isFile();
    const bytes = exists ? statSync(artifact).size : Infinity;
    check(`meta: ≤3MB（实际 ${bytes} B ≤ 3145728）`, bytes <= 3 * MB);
    if (exists) {
      const html = readFileSync(artifact, "utf8");
      const bad = externalUrls(html);
      check("meta: 白名单外零 http 外链", bad.length === 0, bad.map((u) => `外链: ${u}`));
      check("meta: 无 MRAID 引用（渠道禁用）", !/\bmraid\b/i.test(html));
    }
  }

  // ---------- 3) mintegral：zip = build.js + Template.html ----------
  {
    const r = build("mintegral", FIXTURE);
    const dir = path.join(OUT, "golden-match3", "mintegral", "en");
    const files = r.status === 0 ? listPackageFiles(dir) : [];
    check("mintegral: build exit 0", r.status === 0, r.status === 0 ? [] : [r.stderr.trim()]);
    const zipPath = files.find((f) => f.endsWith(".zip"));
    check("mintegral: 产物为 zip", Boolean(zipPath), [`目录内容: ${files.join(", ")}`]);
    if (zipPath) {
      const abs = path.join(dir, zipPath);
      const bytes = statSync(abs).size;
      check(`mintegral: zip ≤5MB（实际 ${bytes} B ≤ 5242880）`, bytes <= 5 * MB);
      const entries = readZip(readFileSync(abs));
      const names = [...entries.keys()];
      check(
        "mintegral: 包内结构恰为 [build.js, Template.html]",
        JSON.stringify(names.sort()) === JSON.stringify(["Template.html", "build.js"]),
        [`实际条目: ${names.join(", ")}`],
      );
      const tpl = entries.get("Template.html").toString("utf8");
      const js = entries.get("build.js").toString("utf8");
      check("mintegral: Template.html 以相对路径引用 build.js", tpl.includes('<script src="build.js"></script>'));
      const badTpl = externalUrls(tpl);
      const badJs = externalUrls(js);
      check("mintegral: 条目内白名单外零外链", badTpl.length === 0 && badJs.length === 0, [
        ...badTpl.map((u) => `Template.html 外链: ${u}`),
        ...badJs.map((u) => `build.js 外链: ${u}`),
      ]);
      check("mintegral: Template.html 资源内联（含 base64 data URI）", tpl.includes("data:image/png;base64,"));

      // 独立实现交叉验证：python zipfile（venv 存在时）
      const py = path.join(REPO_ROOT, "python", ".venv", "Scripts", "python.exe");
      if (statSync(py, { throwIfNoEntry: false })?.isFile()) {
        try {
          const out = execFileSync(py, ["-c", [
            "import zipfile",
            `z = zipfile.ZipFile(r"${abs}")`,
            "names = z.namelist()",
            "assert z.testzip() is None, 'CRC fail'",
            "assert sorted(names) == ['Template.html', 'build.js'], names",
            "assert '<script src=\"build.js\"></script>' in z.read('Template.html').decode('utf-8')",
            "print('python-zipfile-OK')",
          ].join("\n")], { encoding: "utf8" });
          check("mintegral: python zipfile 交叉验证通过", out.includes("python-zipfile-OK"), [out.trim()]);
        } catch (err) {
          check("mintegral: python zipfile 交叉验证通过", false, [String(err.stderr || err)]);
        }
      } else {
        console.log("[SKIP ] mintegral: python zipfile 交叉验证（未找到 venv python）");
      }
    }
  }

  // ---------- 4) 可复现性：同输入两次构建字节一致 ----------
  {
    const a = path.join(OUT, "golden-match3", "applovin", "en", "index.html");
    const first = readFileSync(a);
    const r = build("applovin", FIXTURE);
    const second = readFileSync(a);
    check("applovin: 重复构建字节可复现", r.status === 0 && first.equals(second));
  }

  // ---------- 5) 负向：门必须能拦住违规 ----------
  {
    const badDist = mkdtempSync(path.join(OUT, "neg-"));

    // 5a. dist 混入 http 外链 img：打包器在解析阶段即拒绝
    await cpAsync(FIXTURE, path.join(badDist, "d1"), { recursive: true });
    const i1 = path.join(badDist, "d1", "index.html");
    writeFileSync(i1, readFileSync(i1, "utf8").replace("</head>", '  <img src="https://cdn.example.com/leak.png">\n</head>'));
    const r1 = build("applovin", path.join(badDist, "d1"));
    check("负向: dist 混入 http 外链资源 → 拒绝", r1.status !== 0, (r1.stderr || "").trim().split("\n").slice(0, 2));

    // 5b. meta 产物混入 MRAID 调用：forbidMraid 规则拦截
    await cpAsync(FIXTURE, path.join(badDist, "d2"), { recursive: true });
    const j2 = path.join(badDist, "d2", "js", "game.js");
    writeFileSync(j2, readFileSync(j2, "utf8") + "\nwindow.MRAID_TEST = function(){ if (window.mraid) window.mraid.open(LANDING_URL); };\n");
    const r2 = build("meta", path.join(badDist, "d2"));
    check("负向: meta 产物混入 MRAID → 拒绝", r2.status !== 0, (r2.stderr || "").trim().split("\n").slice(0, 2));

    // 5c. 本阶段未冻结的渠道：拒绝（规则库只有 applovin/meta/mintegral）
    const r3 = build("google", FIXTURE);
    check("负向: 未知/未冻结渠道（google）→ 拒绝", r3.status !== 0, (r3.stderr || "").trim().split("\n").slice(0, 2));

    rmSync(badDist, { recursive: true, force: true });
  }

  console.log(failures === 0 ? "\n全部自验收断言通过（exit 0）" : `\n${failures} 条断言失败（exit 1）`);
  process.exitCode = failures === 0 ? 0 : 1;
}

main().catch((err) => {
  console.error(String(err && err.stack || err));
  process.exitCode = 1;
});

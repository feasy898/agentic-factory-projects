#!/usr/bin/env node
/**
 * M4 packager 自验收（T1.3 起步，T2.4 扩六渠道）：对 match3 占位工程跑六条渠道并逐项断言。
 *
 * 用法：node packages/packager/test/run.mjs
 * 全过 exit 0；任一断言失败 exit 1。
 *
 * 断言：
 *   applovin  单 HTML：存在、≤5MB（rules 上限）、白名单外零 http 外链、含 mraid.js 注入
 *   meta      单 HTML：≤3MB（rules+spec override 上限）、零外链、无 MRAID 引用
 *   mintegral zip：条目结构恰为 [build.js, Template.html]、zip ≤5MB、条目内零外链、
 *              Template.html 引用 build.js；系统 tar 交叉验证（P5 去 venv 化）
 *   google    zip：条目恰为 [index.html]（全内联入口）、≤5MB、零外链、资源内联
 *   unity     zip：条目恰为 [index.html]、≤5MB、含 mraid.js 相对注入、零外链
 *   tiktok    zip：条目恰为 [config.json, index.html, js-sdk.js]、≤5MB、入口引用
 *              js-sdk.js、桩定义 window.openAppStore、config.json 可解析含 spec 字段
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

      // 独立实现交叉验证：系统 bsdtar（P5 去 venv 化；断言语义保持——条目名/入口引用/CRC）。
      // 按绝对路径定位：本机 PATH 首位可能是 GNU tar（不支持 zip），只有 libarchive 系
      // bsdtar 可读 zip；解包（-xf）由 libarchive 校验 CRC，损坏即非零退出（execFileSync 抛错）。
      const TAR = process.platform === "win32"
        ? path.join(process.env.SystemRoot || "C:\\Windows", "System32", "tar.exe")
        : "tar";
      {
        let ok = false;
        const details = [];
        try {
          const ver = execFileSync(TAR, ["--version"], { encoding: "utf8" });
          if (!/bsdtar|libarchive/i.test(ver)) {
            throw new Error(`独立读取器须为 bsdtar/libarchive，实际: ${ver.trim().split("\n")[0]}`);
          }
          const xDir = path.join(path.dirname(abs), "tar-crosscheck");
          rmSync(xDir, { recursive: true, force: true });
          mkdirSync(xDir, { recursive: true });
          const names = execFileSync(TAR, ["-tf", abs], { encoding: "utf8" })
            .split(/\r?\n/).map((s) => s.trim()).filter(Boolean);
          execFileSync(TAR, ["-xf", abs, "-C", xDir], { encoding: "utf8" });
          const tpl = readFileSync(path.join(xDir, "Template.html"), "utf8");
          const refOk = tpl.includes('<script src="build.js"></script>');
          ok = JSON.stringify(names.sort()) === JSON.stringify(["Template.html", "build.js"]) && refOk;
          if (!ok) details.push(`条目: ${names.join(", ")}`, `入口引用命中: ${refOk}`);
          rmSync(xDir, { recursive: true, force: true });
        } catch (err) {
          ok = false;
          details.push(String((err.stderr || "") || err.message || err).split("\n")[0]);
        }
        check("mintegral: 系统 tar 交叉验证通过（条目名/入口引用/CRC）", ok, details);
      }
    }
  }

  // ---------- 3b) google：zip，条目恰为 [index.html]（全内联入口） ----------
  {
    const r = build("google", FIXTURE);
    const dir = path.join(OUT, "golden-match3", "google", "en");
    const files = r.status === 0 ? listPackageFiles(dir) : [];
    check("google: build exit 0", r.status === 0, r.status === 0 ? [] : [r.stderr.trim()]);
    const zipPath = files.find((f) => f.endsWith(".zip"));
    check("google: 产物为 zip", Boolean(zipPath), [`目录内容: ${files.join(", ")}`]);
    if (zipPath) {
      const abs = path.join(dir, zipPath);
      const bytes = statSync(abs).size;
      check(`google: zip ≤5MB（实际 ${bytes} B ≤ 5242880）`, bytes <= 5 * MB);
      const entries = readZip(readFileSync(abs));
      const names = [...entries.keys()];
      check(
        "google: 包内结构恰为 [index.html]",
        JSON.stringify(names.sort()) === JSON.stringify(["index.html"]),
        [`实际条目: ${names.join(", ")}`],
      );
      const html = entries.get("index.html").toString("utf8");
      check("google: 白名单外零外链", externalUrls(html).length === 0,
        externalUrls(html).map((u) => `外链: ${u}`));
      check("google: 资源已内联（含 base64 data URI）", html.includes("data:image/png;base64,"));
      check("google: 无 mraid/js-sdk 运行时注入（规则库声明为空）",
        !html.includes('src="mraid.js"') && !html.includes('src="js-sdk.js"'));
    }
  }

  // ---------- 3c) unity：zip，条目恰为 [index.html]，mraid.js 相对注入 ----------
  {
    const r = build("unity", FIXTURE);
    const dir = path.join(OUT, "golden-match3", "unity", "en");
    const files = r.status === 0 ? listPackageFiles(dir) : [];
    check("unity: build exit 0", r.status === 0, r.status === 0 ? [] : [r.stderr.trim()]);
    const zipPath = files.find((f) => f.endsWith(".zip"));
    check("unity: 产物为 zip", Boolean(zipPath), [`目录内容: ${files.join(", ")}`]);
    if (zipPath) {
      const abs = path.join(dir, zipPath);
      const bytes = statSync(abs).size;
      check(`unity: zip ≤5MB（实际 ${bytes} B ≤ 5242880）`, bytes <= 5 * MB);
      const entries = readZip(readFileSync(abs));
      const names = [...entries.keys()];
      check(
        "unity: 包内结构恰为 [index.html]",
        JSON.stringify(names.sort()) === JSON.stringify(["index.html"]),
        [`实际条目: ${names.join(", ")}`],
      );
      const html = entries.get("index.html").toString("utf8");
      check("unity: mraid.js 已按规则注入（相对引用，容器提供，不占包内条目）",
        html.includes('<script src="mraid.js"></script>'));
      check("unity: 白名单外零外链", externalUrls(html).length === 0,
        externalUrls(html).map((u) => `外链: ${u}`));
      check("unity: 资源已内联（含 base64 data URI）", html.includes("data:image/png;base64,"));
    }
  }

  // ---------- 3d) tiktok：zip = index.html + config.json + js-sdk.js 桩 ----------
  {
    const r = build("tiktok", FIXTURE);
    const dir = path.join(OUT, "golden-match3", "tiktok", "en");
    const files = r.status === 0 ? listPackageFiles(dir) : [];
    check("tiktok: build exit 0", r.status === 0, r.status === 0 ? [] : [r.stderr.trim()]);
    const zipPath = files.find((f) => f.endsWith(".zip"));
    check("tiktok: 产物为 zip", Boolean(zipPath), [`目录内容: ${files.join(", ")}`]);
    if (zipPath) {
      const abs = path.join(dir, zipPath);
      const bytes = statSync(abs).size;
      check(`tiktok: zip ≤5MB（实际 ${bytes} B ≤ 5242880）`, bytes <= 5 * MB);
      const entries = readZip(readFileSync(abs));
      const names = [...entries.keys()];
      check(
        "tiktok: 包内结构恰为 [config.json, index.html, js-sdk.js]",
        JSON.stringify(names.sort()) === JSON.stringify(["config.json", "index.html", "js-sdk.js"]),
        [`实际条目: ${names.join(", ")}`],
      );
      const html = entries.get("index.html").toString("utf8");
      const sdk = entries.get("js-sdk.js").toString("utf8");
      check("tiktok: 入口以相对路径引用 js-sdk.js（规则库注入项）",
        html.includes('<script src="js-sdk.js"></script>'));
      check("tiktok: js-sdk 桩兜底定义 window.openAppStore（容器已实现时让位）",
        sdk.includes("window.openAppStore") && sdk.includes("typeof window.openAppStore"));
      const cfgText = entries.get("config.json").toString("utf8");
      let cfg = null;
      try {
        cfg = JSON.parse(cfgText);
      } catch {
        cfg = null;
      }
      check("tiktok: config.json 可解析", cfg !== null, [cfgText.slice(0, 120)]);
      const spec = JSON.parse(readFileSync(SPEC, "utf8"));
      check("tiktok: config.json 含 spec 派生字段（orientation/gameName）",
        cfg !== null && cfg.orientation === spec.channels.orientation
        && typeof cfg.gameName === "string" && cfg.gameName.length > 0
        && typeof cfg.version === "string",
        cfg ? [`orientation=${cfg.orientation} gameName=${cfg.gameName}`] : []);
      const bad = [...externalUrls(html), ...externalUrls(sdk), ...externalUrls(cfgText)];
      check("tiktok: 条目内白名单外零外链", bad.length === 0, bad.map((u) => `外链: ${u}`));
      check("tiktok: 入口资源已内联（含 base64 data URI）", html.includes("data:image/png;base64,"));
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

    // 5c. 规则库没有的渠道：拒绝（T2.4 起六投放渠道已冻结，改用不存在的渠道名）
    const r3 = build("not-a-channel", FIXTURE);
    check("负向: 未知渠道（not-a-channel）→ 拒绝", r3.status !== 0, (r3.stderr || "").trim().split("\n").slice(0, 2));

    rmSync(badDist, { recursive: true, force: true });
  }

  console.log(failures === 0 ? "\n全部自验收断言通过（exit 0）" : `\n${failures} 条断言失败（exit 1）`);
  process.exitCode = failures === 0 ? 0 : 1;
}

main().catch((err) => {
  console.error(String(err && err.stack || err));
  process.exitCode = 1;
});

/**
 * M4 六渠道产物结构断言（移植 eval，新增——冻结 run.mjs 之外的验收面）。
 *
 * 依据 spec packager.md §3.1.1（rulesVersion 1.1.0 七渠道冻结表）与 §3.2
 * （files[]/packageFiles 形状按通道冻结、zip 条目 = structure 顺序、totalBytes 只累计
 * role=package、manifest 字段集），对 match3 夹具跑全部 7 渠道并逐项断言；
 * 另断言 CLI 退出码契约（§2：未知渠道=1、未知子命令=2）与 channels 列表。
 *
 * 用法：node packages/packager/test/structure.test.mjs（或被根 node --test 发现）
 */
import test from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, readdirSync, rmSync, statSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { readZip } from "../src/zip.mjs";

const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");
const BIN = path.join(REPO_ROOT, "packages", "packager", "bin.mjs");
const SPEC = path.join(REPO_ROOT, "specs-eval", "golden-match3.json");
const FIXTURE = path.join(REPO_ROOT, "packages", "packager", "test", "fixture", "match3-dist");
const OUT = path.join(REPO_ROOT, "tmp", "packager-structure");

const MANIFEST_KEYS = [
  "packager", "rulesVersion", "channel", "locale", "project", "specPath", "dist",
  "maxBytes", "packageFiles", "files", "warnings",
].sort();
const ROLES = new Set(["package", "entry-in-zip", "bundle-in-zip", "generated-in-zip"]);

function build(channel, locale = "en") {
  return spawnSync(process.execPath, [
    BIN, "build",
    "--spec", SPEC,
    "--dist", FIXTURE,
    "--channel", channel,
    "--locale", locale,
    "--out", OUT,
  ], { encoding: "utf8", cwd: REPO_ROOT });
}

function loadManifest(channel, locale = "en") {
  return JSON.parse(readFileSync(path.join(OUT, "golden-match3", channel, locale, "pack-manifest.json"), "utf8"));
}

/** 规则库七渠道的冻结结构期望（spec §3.1.1 表 + §3.2 files[]/packageFiles 形状表）。 */
const EXPECT = {
  applovin: { format: "single-html", maxBytes: 5242880, roles: ["package"],
    pkgFiles: ["index.html"], injectMraid: true, injectSdk: false },
  meta: { format: "single-html", maxBytes: 3145728, roles: ["package"],
    pkgFiles: ["index.html"], injectMraid: false, injectSdk: false },
  preview: { format: "single-html", maxBytes: 5242880, roles: ["package"],
    pkgFiles: ["index.html"], injectMraid: false, injectSdk: false },
  mintegral: { format: "zip", structure: ["build.js", "Template.html"], entry: "Template.html",
    maxBytes: 5242880, roles: ["package", "entry-in-zip", "bundle-in-zip"],
    pkgFiles: ["golden-match3-en.zip"], injectMraid: true },
  google: { format: "zip", structure: ["index.html"], entry: "index.html",
    maxBytes: 5242880, roles: ["package", "entry-in-zip"],
    pkgFiles: ["golden-match3-en.zip"], injectMraid: false, injectSdk: false },
  unity: { format: "zip", structure: ["index.html"], entry: "index.html",
    maxBytes: 5242880, roles: ["package", "entry-in-zip"],
    pkgFiles: ["golden-match3-en.zip"], injectMraid: true, injectSdk: false },
  tiktok: { format: "zip", structure: ["index.html", "config.json", "js-sdk.js"], entry: "index.html",
    maxBytes: 5242880, roles: ["package", "entry-in-zip", "generated-in-zip", "generated-in-zip"],
    pkgFiles: ["golden-match3-en.zip"], injectMraid: false, injectSdk: true },
};
const ALL_CHANNELS = Object.keys(EXPECT);

test("setup: 七渠道全部构建 exit 0", () => {
  rmSync(OUT, { recursive: true, force: true });
  mkdirSync(OUT, { recursive: true });
  for (const ch of ALL_CHANNELS) {
    const r = build(ch);
    assert.equal(r.status, 0, `${ch} build 失败: ${r.stderr}`);
    const last = r.stdout.trim().split("\n").pop();
    const line = JSON.parse(last);
    assert.equal(line.ok, true);
    assert.equal(line.maxBytes, EXPECT[ch].maxBytes, `${ch} maxBytes 应为 min(规则, override)`);
    BUILDS.set(ch, line);
  }
});

for (const ch of ALL_CHANNELS) {
  test(`结构: ${ch}`, () => {
    const e = EXPECT[ch];
    const dir = path.join(OUT, "golden-match3", ch, "en");
    assert.ok(existsSync(dir), `${dir} 应存在（<out>/<project>/<channel>/<locale>/）`);

    // 产物目录内容：single-html 恰 1 个包文件；zip 恰 1 个 zip；pack-manifest.json 为旁车
    const dirFiles = readdirSync(dir).filter((f) => f !== "pack-manifest.json").sort();
    assert.deepEqual(dirFiles, e.pkgFiles, `${ch} 目录内容（不含 manifest）`);

    const manifest = loadManifest(ch);

    // manifest 字段集（决策 §2.2：报告字段零变更）
    assert.deepEqual(Object.keys(manifest).sort(), MANIFEST_KEYS, `${ch} manifest 字段集`);
    assert.equal(manifest.packager, "@pf/packager");
    assert.equal(manifest.rulesVersion, "1.1.0");
    assert.equal(manifest.channel, ch);
    assert.equal(manifest.locale, "en");
    assert.equal(manifest.project, "golden-match3");
    assert.equal(manifest.specPath, path.resolve(SPEC));
    assert.equal(manifest.dist, path.resolve(FIXTURE));
    assert.equal(manifest.maxBytes, e.maxBytes);
    assert.ok(Array.isArray(manifest.warnings));

    // files[] 形状按通道冻结：角色序列 + 路径；sha256 为 64 位 hex；bytes 为正。
    // 落盘面：role=package 是产物目录里的真实文件；zip 通道其余角色的 path 是
    // 包内条目（spec §3.2：zip 内条目不进 packageFiles、不落产物目录）。
    assert.deepEqual(manifest.files.map((f) => f.role), e.roles, `${ch} files[] 角色序列`);
    assert.deepEqual(manifest.packageFiles, e.pkgFiles, `${ch} packageFiles 恒为包文件本身`);
    let zipEntries = null;
    if (e.format === "zip") {
      zipEntries = readZip(readFileSync(path.join(dir, e.pkgFiles[0])));
    }
    for (const f of manifest.files) {
      assert.ok(ROLES.has(f.role));
      assert.ok(f.bytes > 0);
      assert.match(f.sha256, /^[0-9a-f]{64}$/);
      if (f.role === "package") {
        assert.ok(statSync(path.join(dir, f.path), { throwIfNoEntry: false })?.isFile(),
          `${ch}: 包文件 ${f.path} 应真实存在于产物目录`);
      } else {
        assert.ok(zipEntries && zipEntries.has(f.path),
          `${ch}: 包内条目 ${f.path} 应存在于 zip`);
        if (zipEntries && zipEntries.has(f.path)) {
          assert.equal(zipEntries.get(f.path).length, f.bytes, `${ch}: 条目 ${f.path} 字节数与 manifest 对账`);
        }
      }
    }

    const pkgFile = path.join(dir, e.pkgFiles[0]);
    const pkgBytes = statSync(pkgFile).size;
    // totalBytes（CLI 末行）= manifest 中 role=package 字节和 = 包文件实际大小
    assert.equal(sumPackage(manifest), pkgBytes, `${ch} totalBytes 只累计 role=package`);
    assert.equal(BUILDS.get(ch).totalBytes, pkgBytes, `${ch} CLI totalBytes 与包文件对账`);
    assert.ok(pkgBytes <= e.maxBytes, `${ch} 包体积 ${pkgBytes} ≤ ${e.maxBytes}`);

    if (e.format === "single-html") {
      const html = readFileSync(pkgFile, "utf8");
      assert.equal(html.includes('<script src="mraid.js"></script>'), Boolean(e.injectMraid),
        `${ch} mraid.js 注入应为 ${Boolean(e.injectMraid)}`);
      assert.equal(html.includes('src="js-sdk.js"'), Boolean(e.injectSdk), `${ch} js-sdk 引用应为 ${Boolean(e.injectSdk)}`);
      assert.ok(html.includes("data:image/png;base64,"), `${ch} 资源已内联`);
      assert.ok(!/<link\b[^>]*rel="stylesheet"/i.test(html), `${ch} 样式表已内联为 <style>`);
    } else {
      // zip：条目 = 规则 structure 顺序（冻结）；readZip 按 central directory 序返回
      const entries = readZip(readFileSync(pkgFile));
      assert.deepEqual([...entries.keys()], e.structure, `${ch} zip 条目与 structure 同序`);
      const entryHtml = entries.get(e.entry).toString("utf8");
      assert.ok(entryHtml.includes("data:image/png;base64,"), `${ch} 入口资源已内联`);
      assert.equal(entryHtml.includes('<script src="mraid.js"></script>'), Boolean(e.injectMraid),
        `${ch} 入口 mraid.js 注入应为 ${Boolean(e.injectMraid)}`);
      if (ch === "mintegral") {
        assert.ok(entryHtml.includes('<script src="build.js"></script>'), "Template.html 相对引用 build.js");
        assert.ok(entries.get("build.js").length > 0, "build.js 非空（dist 外链脚本合并产物）");
      }
      if (ch === "tiktok") {
        assert.ok(entryHtml.includes('<script src="js-sdk.js"></script>'), "入口引用 js-sdk.js");
        const stub = entries.get("js-sdk.js").toString("utf8");
        assert.ok(stub.includes("window.openAppStore") && stub.includes("typeof window.openAppStore"),
          "js-sdk 桩兜底定义 window.openAppStore");
        const cfg = JSON.parse(entries.get("config.json").toString("utf8"));
        assert.equal(cfg.version, "1.0.0");
        assert.equal(cfg.orientation, "portrait");
        assert.equal(cfg.gameName, "Gem Rush (Playable Demo)");
      }
    }
  });
}

function sumPackage(manifest) {
  return manifest.files.filter((f) => f.role === "package").reduce((n, f) => n + f.bytes, 0);
}

/** CLI 末行 JSON（setup 阶段捕获）：{ok, artifact, totalBytes, maxBytes}，用于对账。 */
const BUILDS = new Map();

test("CLI: channels 列出规则库全部 7 渠道", () => {
  const r = spawnSync(process.execPath, [BIN, "channels"], { encoding: "utf8", cwd: REPO_ROOT });
  assert.equal(r.status, 0, r.stderr);
  assert.match(r.stdout, /rulesVersion=1\.1\.0/);
  for (const ch of ALL_CHANNELS) assert.ok(r.stdout.includes(ch), `channels 输出应含 ${ch}`);
});

test("CLI 退出码: 未知渠道 = 1（不是 2）", () => {
  const r = spawnSync(process.execPath, [
    BIN, "build", "--spec", SPEC, "--dist", FIXTURE, "--channel", "not-a-channel", "--out", OUT,
  ], { encoding: "utf8", cwd: REPO_ROOT });
  assert.equal(r.status, 1);
  assert.match(r.stderr, /\[packager\] 失败:/);
  assert.match(r.stderr, /现有: /, "失败信息应列出现有渠道");
});

test("CLI 退出码: 未知子命令 = 2；多余位置参数 = 2", () => {
  const bad = spawnSync(process.execPath, [BIN, "frobnicate"], { encoding: "utf8", cwd: REPO_ROOT });
  assert.equal(bad.status, 2);
  const extra = spawnSync(process.execPath, [BIN, "channels", "surprise"], { encoding: "utf8", cwd: REPO_ROOT });
  assert.equal(extra.status, 2);
});

test("CLI 退出码: 缺 --spec = 构建失败 1（oracle 同判）", () => {
  const r = spawnSync(process.execPath, [BIN, "build", "--dist", FIXTURE, "--channel", "applovin"], {
    encoding: "utf8", cwd: REPO_ROOT,
  });
  assert.equal(r.status, 1);
  assert.match(r.stderr, /build 缺少 --spec/);
});

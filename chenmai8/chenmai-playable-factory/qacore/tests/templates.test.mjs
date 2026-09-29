/**
 * 四模板 --autoplay 复验（M2.2 验收的"本器复验"）：把 M2.1 模板移植的临时验收
 * （oracle qacore --autoplay 0 FAIL）全部换成**本判官**复验——
 * 对 tmpl-match3 / tmpl-merge / tmpl-pullpin / tmpl-sort 各自的 golden spec
 * 构建产物逐个跑 `node qacore/cli.mjs run --channel preview --autoplay`：
 * exit 0、零 fail、pf:end 已触发且 ≤ 预算（45s）、reachedState=end、结束页可见。
 *
 * 另跑 spec §7 的 CHK10 实装层：demo-zh 构建（piece-0 为用户替换 PNG）+
 * --require-text（标题/教程/胜/CTA/分）+ --require-sprite piece-0 → CHK10 pass。
 *
 * 运行：node --test qacore/tests/templates.test.mjs（需 chromium；
 * 构建产物落 tmp/，先清后跑；不污染 artifacts/）。
 */
import test from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { readFileSync, rmSync, existsSync, mkdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const FACTORY_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const QACORE_CLI = join(FACTORY_ROOT, "qacore", "cli.mjs");
const TMP_DIR = join(FACTORY_ROOT, "tmp", "qacore-eval", "templates");

const TEMPLATES = [
  { name: "match3", pkg: "tmpl-match3", spec: "specs-eval/golden-match3.json" },
  { name: "merge", pkg: "tmpl-merge", spec: "specs-eval/golden-merge.json" },
  { name: "pullpin", pkg: "tmpl-pullpin", spec: "specs-eval/golden-pullpin.json" },
  { name: "sort", pkg: "tmpl-sort", spec: "specs-eval/golden-sort.json" },
];

function run(cmd, args, opts = {}) {
  const proc = spawnSync(process.execPath, [cmd, ...args], {
    cwd: FACTORY_ROOT,
    timeout: opts.timeout ?? 300_000,
    encoding: "utf8",
    windowsHide: true,
  });
  return {
    code: proc.status,
    stdout: proc.stdout ?? "",
    stderr: proc.stderr ?? "",
  };
}

/** 构建单模板产物到 tmp/（spec 相对仓库根；构建脚本在包目录内）。 */
function buildTemplate(pkg, specPath, outPath, locale) {
  const args = [join(FACTORY_ROOT, "packages", "templates", pkg, "build.mjs"),
    "--spec", specPath, "--out", outPath];
  if (locale) args.push("--locale", locale);
  const proc = spawnSync(process.execPath, args, {
    cwd: FACTORY_ROOT,
    timeout: 300_000,
    encoding: "utf8",
    windowsHide: true,
  });
  assert.equal(proc.status, 0,
    `${pkg} build exit=${proc.status}\n${proc.stdout}\n${proc.stderr}`);
  assert.ok(existsSync(outPath), `${pkg} 构建产物未产出：${outPath}`);
}

for (const t of TEMPLATES) {
  test(`本器复验 ${t.pkg}：构建 → --autoplay 全过（pf:end ≤ 预算、结束页可见）`, () => {
    mkdirSync(TMP_DIR, { recursive: true });
    const html = join(TMP_DIR, `${t.name}.html`);
    buildTemplate(t.pkg, t.spec, html);
    const reportPath = join(TMP_DIR, `${t.name}.report.json`);
    rmSync(reportPath, { force: true });

    const { code, stdout, stderr } = run(QACORE_CLI,
      ["run", html, "--channel", "preview", "--autoplay", "--out", reportPath]);
    if (code !== 0) {
      const report = existsSync(reportPath)
        ? JSON.stringify(JSON.parse(readFileSync(reportPath, "utf8")).checks, null, 1)
        : "(无报告)";
      assert.fail(`${t.name}: qacore exit=${code}\n${stdout}\n${stderr}\n${report}`);
    }
    const report = JSON.parse(readFileSync(reportPath, "utf8"));
    const fails = report.checks.filter((c) => c.status === "fail").map((c) => c.id);
    assert.deepEqual(fails, [], `${t.name}: FAIL 项应为空`);
    // F4 行为流（决策 §3.2）：ready→end(win=true)、手势>0、pf:end ≤45s、终态 end、结束页可见
    assert.equal(report.pf.present, true, `${t.name}: window.PF 应在位`);
    assert.equal(report.pf.endWin, true, `${t.name}: pf:end win=true`);
    assert.ok(typeof report.pf.endMs === "number" && report.pf.endMs <= 45000,
      `${t.name}: pf:end ${report.pf.endMs}ms ≤ 45000ms`);
    const auto = report.facts.muteLoadTime;
    assert.ok(auto.gestures > 0, `${t.name}: 试玩手势数 > 0`);
    assert.equal(auto.reachedState, "end", `${t.name}: 最终 state=end`);
    assert.equal(auto.endScreenVisible, true, `${t.name}: 结束页可见`);
  });
}

test("CHK10 实装层：demo-zh 构建 + 标题/教程/胜/CTA/分文案 + piece-0 像素对账 → pass", () => {
  mkdirSync(TMP_DIR, { recursive: true });
  const html = join(TMP_DIR, "demo-zh.html");
  buildTemplate("tmpl-match3", "specs-eval/demo-zh.json", html);
  assert.ok(existsSync(html + ".assets.json"), "构建旁车 .assets.json 未产出");
  const sidecar = JSON.parse(readFileSync(html + ".assets.json", "utf8"));
  assert.ok(sidecar.sprites.some((s) => s.spriteKey === "piece-0"),
    "旁车清单应含真实嵌入素材 piece-0");

  const reportPath = join(TMP_DIR, "demo-zh.report.json");
  rmSync(reportPath, { force: true });
  // make 自动传入口径（pipeline-contract §3.4）：首语言（zh）标题/教程/胜/CTA/分
  // ——lose 不要求（自动试玩必胜，无出场机会）。
  const { code, stdout, stderr } = run(QACORE_CLI, [
    "run", html, "--channel", "preview", "--autoplay", "--out", reportPath,
    "--require-text", "宝石消消乐（试玩演示）",
    "--require-text", "拖动宝石，三个同色连成一线！",
    "--require-text", "通关啦！",
    "--require-text", "立即下载",
    "--require-text", "得分",
    "--require-sprite", "piece-0",
  ]);
  if (code !== 0) {
    const report = existsSync(reportPath)
      ? JSON.stringify(JSON.parse(readFileSync(reportPath, "utf8")).checks, null, 1)
      : "(无报告)";
    assert.fail(`demo-zh: qacore exit=${code}\n${stdout}\n${stderr}\n${report}`);
  }
  const report = JSON.parse(readFileSync(reportPath, "utf8"));
  const byId = new Map(report.checks.map((c) => [c.id, c]));
  assert.equal(byId.get("CHK10").status, "pass",
    `CHK10 应 pass：${byId.get("CHK10").detail}`);
  // 自证证据落报告：text_states 曾见 + asset_audit replaced=true
  assert.equal(report.facts.text_states_hook, true, "textStates 钩子应在位");
  const audit = report.facts.asset_audit.find((a) => a.spriteKey === "piece-0");
  assert.ok(audit && audit.replaced === true, "piece-0 像素对账 replaced=true");
  const fails = report.checks.filter((c) => c.status === "fail").map((c) => c.id);
  assert.deepEqual(fails, [], "demo-zh 全检零 fail");
});

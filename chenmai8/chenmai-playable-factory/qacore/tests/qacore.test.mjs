/**
 * qacore 移植 eval（浏览器层）——oracle gate_phase0 门项 5/6 + spec §7 eval
 * 命令语义按"语义冻结、宿主移植"转 node:test（决策 §2.1 M8 行）：
 *
 * 门项 5（金标层）：mini.html 夹具（装配 PF/__PF_QC__ 桩）经双视口+自动试玩
 *   产出报告：exit 0、checks 非空、零 fail；skip 不算过——已实装检查
 *   （CHK01/03/04/05/07/08/09）零 skip；CHK03/08/09 必须 pass。
 * 门项 6（变异层）：三个 mutant 各自必须且只能击中对应检查项，exit 1：
 *   MUT-01 外链 img → 恰 CHK03 / MUT-02 未静音 audio → 恰 CHK04 /
 *   MUT-04 超体积 → 恰 CHK01（--channel meta，>3MB 上限）。
 *   样本现场构造、先清后跑、夹具只读（sha256 前后不变由测试复核）。
 * 退出码契约：产物不存在 / 非 .html → exit 2。
 *
 * 运行：node --test qacore/tests/qacore.test.mjs（需 chromium，见 npm run test:qacore）。
 */
import test from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { readFileSync, writeFileSync, rmSync, existsSync, mkdirSync } from "node:fs";
import { createHash } from "node:crypto";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const FACTORY_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const QACORE_CLI = join(FACTORY_ROOT, "qacore", "cli.mjs");
const FIXTURE_MINI = join(FACTORY_ROOT, "qacore", "tests", "fixtures", "mini.html");
const RULES_PATH = join(FACTORY_ROOT, "channel-rules", "channel-rules.json");
const TMP_DIR = join(FACTORY_ROOT, "tmp", "qacore-eval");
const MUTATION_DIR = join(TMP_DIR, "mutations");

// 已实装的检查项：门禁口径里这些项出现 skip 即 FAIL（skip 不算过）。
const QACORE_IMPLEMENTED_IDS = ["CHK01", "CHK03", "CHK04", "CHK05", "CHK07", "CHK08", "CHK09"];
// 合规底线三项必须 pass。
const QACORE_MUST_PASS_IDS = ["CHK03", "CHK08", "CHK09"];

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

test("门项5 金标层：mini.html --autoplay 全过、已实装项零 skip、CHK03/08/09 必 pass", () => {
  const outPath = join(TMP_DIR, "qacore-report.json");
  rmSync(outPath, { force: true }); // 先删旧报告再跑："报告存在"才是本次运行的真事实
  const fixtureShaBefore = sha256(FIXTURE_MINI);

  const { code, stdout, stderr } = runQacore(
    FIXTURE_MINI, ["--channel", "preview", "--autoplay"], outPath);
  assert.equal(code, 0, `qacore exit=${code}（应 0）\nstdout=${stdout}\nstderr=${stderr}`);
  assert.ok(existsSync(outPath), "报告未产出");

  const report = readReport(outPath);
  assert.ok(Array.isArray(report.checks) && report.checks.length > 0,
    "报告缺非空 checks 键");
  const byId = new Map(report.checks.map((c) => [c.id, c]));
  const fails = report.checks.filter((c) => c.status === "fail").map((c) => c.id);
  assert.deepEqual(fails, [], "FAIL 项应为空");
  const skippedImpl = QACORE_IMPLEMENTED_IDS.filter(
    (id) => byId.get(id)?.status === "skip");
  assert.deepEqual(skippedImpl, [], `已实装项（${QACORE_IMPLEMENTED_IDS.join("/")}）零 skip`);
  for (const mid of QACORE_MUST_PASS_IDS) {
    assert.equal(byId.get(mid)?.status, "pass", `${mid} status 应为 pass`);
  }
  assert.equal(sha256(FIXTURE_MINI), fixtureShaBefore, "夹具被改动（只读纪律）");
});

test("门项6 变异层：MUT-01/02/04 各自恰好命中对应 CHK 且 exit 1（夹具只读）", async () => {
  const { materializeMutants } = await import("./mutations.mjs");
  const fixtureShaBefore = sha256(FIXTURE_MINI);
  const mutants = await materializeMutants(MUTATION_DIR, RULES_PATH, FIXTURE_MINI);
  assert.equal(mutants.length, 3, "恰三个已实装 mutant（MUT-01/02/04）");

  for (const mutant of mutants) {
    const reportPath = join(MUTATION_DIR, `${mutant.name}.report.json`);
    rmSync(reportPath, { force: true });
    const { code, stdout, stderr } = runQacore(
      mutant.path, ["--channel", mutant.channel, "--autoplay"], reportPath);
    if (!existsSync(reportPath)) {
      assert.fail(`${mutant.name}: 报告未产出（qacore exit=${code}）\n${stdout}\n${stderr}`);
    }
    const report = readReport(reportPath);
    const failedIds = report.checks.filter((c) => c.status === "fail").map((c) => c.id);
    assert.deepEqual(
      failedIds, [mutant.expect],
      `${mutant.name}（${mutant.desc}）: exit=${code}（应 1），恰命中 [${mutant.expect}]`);
    assert.equal(code, 1, `${mutant.name}: exit=${code}（应 1）`);
  }
  assert.equal(sha256(FIXTURE_MINI), fixtureShaBefore, "夹具被改动（只读纪律）");
});

test("退出码契约：产物不存在 → 2；非 .html → 2", () => {
  const missing = join(TMP_DIR, "definitely-missing.html");
  rmSync(missing, { force: true });
  const out1 = join(TMP_DIR, "exit2-missing.json");
  assert.equal(runQacore(missing, [], out1).code, 2, "产物不存在应 exit 2");

  const notHtml = join(TMP_DIR, "not-html.txt");
  mkdirSync(dirname(notHtml), { recursive: true });
  if (!existsSync(notHtml)) writeFileSync(notHtml, "<html>not html suffix</html>");
  const out2 = join(TMP_DIR, "exit2-suffix.json");
  assert.equal(runQacore(notHtml, [], out2).code, 2, "非 .html 后缀应 exit 2");
});

test("CHK10 阴性对照：无嵌入的夹具 + --require-sprite → 恰 CHK10 fail、exit 1（检查非永绿）", () => {
  const outPath = join(TMP_DIR, "negative-sprite.json");
  rmSync(outPath, { force: true });
  const { code } = runQacore(
    FIXTURE_MINI,
    ["--channel", "preview", "--autoplay", "--require-sprite", "piece-0"],
    outPath);
  assert.equal(code, 1, `阴性对照应 exit 1，实得 ${code}`);
  const report = readReport(outPath);
  const failedIds = report.checks.filter((c) => c.status === "fail").map((c) => c.id);
  assert.deepEqual(failedIds, ["CHK10"],
    "阴性对照恰命中 CHK10（替换素材页面未上报像素对账结果）");
});

test("CHK10 阴性对照：--require-text 未上屏 → 恰 CHK10 fail（夹具无 texts 钩子从严）", () => {
  const outPath = join(TMP_DIR, "negative-text.json");
  rmSync(outPath, { force: true });
  const { code } = runQacore(
    FIXTURE_MINI,
    ["--channel", "preview", "--autoplay", "--require-text", "永不存在的文案"],
    outPath);
  assert.equal(code, 1, `阴性对照应 exit 1，实得 ${code}`);
  const report = readReport(outPath);
  const failedIds = report.checks.filter((c) => c.status === "fail").map((c) => c.id);
  assert.deepEqual(failedIds, ["CHK10"]);
});

function sha256(p) {
  return createHash("sha256").update(readFileSync(p)).digest("hex");
}

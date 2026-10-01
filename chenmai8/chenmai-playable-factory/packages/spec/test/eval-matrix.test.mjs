// packages/spec/test/eval-matrix.test.mjs — M1.2a 冻结 eval：specs-eval 11 件裁定矩阵。
//
// 期望值 = oracle 双侧实测基线（2026-09-30，只读运行；Python 权威 pfcore.validate_spec_file
// 与 JS 镜像 packages/spec validateSpec 给出全等判定，diff harness
// scripts/diff/spec-eval-diff.mjs 复核并在 artifacts/diff/ 留档）：
//   golden×4 + demo-zh → OK；bad×6 → INVALID，{path, code} 集逐件如下表。
// 门禁只断言退出语义与 {path,code}（消息人读不锁，spec-contract §2.5/决策 §3.2 F1）。
// bad 样本属规格：期望永不改（AGENTS.md「bad 样本属规格，永不改期望」）。

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { validateSpec } from "../src/validate.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..", "..", ".."); // factory 根

function load(rel) {
  return JSON.parse(readFileSync(join(root, rel), "utf8"));
}

const GOLDEN_OK = [
  "specs-eval/golden-match3.json",
  "specs-eval/golden-merge.json",
  "specs-eval/golden-pullpin.json",
  "specs-eval/golden-sort.json",
  "specs-eval/demo-zh.json",
];

// oracle 基线（{path, code} 集；Python jsonschema 与 ajv 消息措辞不同，不锁）。
const BAD_EXPECT = {
  "specs-eval/bad/01-missing-field.json": [["$.flow", "schema-required"]],
  "specs-eval/bad/02-pullpin-unsolvable.json": [["$.game.params.orderSolution[0]", "I1-pullpin-unsolvable"]],
  "specs-eval/bad/03-duration-over-budget.json": [["$.game.durationBudgetSec.max", "schema-maximum"]],
  "specs-eval/bad/04-missing-locale-strings.json": [["$.i18n.strings.ja", "I5-i18n-coverage"]],
  "specs-eval/bad/05-bad-url.json": [["$.flow.endScreen.landingUrl", "schema-pattern"]],
  "specs-eval/bad/06-unknown-template.json": [["$.game.template", "schema-enum"]],
};

test("golden×4 + demo-zh 全部通过（schema + 四模板不变式）", () => {
  for (const rel of GOLDEN_OK) {
    const r = validateSpec(load(rel));
    assert.equal(r.ok, true, `${rel} 应通过：${JSON.stringify(r.errors)}`);
    assert.deepEqual(r.errors, []);
  }
});

test("bad×6 全拒，{path, code} 集与 oracle 基线逐件全等", () => {
  for (const [rel, expect] of Object.entries(BAD_EXPECT)) {
    const r = validateSpec(load(rel));
    assert.equal(r.ok, false, `${rel} 应被拒绝`);
    const got = r.errors.map((e) => [e.path, e.code]).sort();
    assert.deepEqual(got, expect.sort(), `${rel} 的 {path,code} 集与 oracle 基线不等`);
    for (const e of r.errors) assert.match(e.path, /^\$/, `${rel} 错误缺 json-path：${JSON.stringify(e)}`);
  }
});

test("bad03 双层同守：schema 层先行，报 schema-maximum（I4-duration-max 为兜底，spec-contract §3）", async () => {
  const r = validateSpec(load("specs-eval/bad/03-duration-over-budget.json"));
  assert.equal(r.ok, false);
  assert.equal(r.errors[0].code, "schema-maximum");
  assert.equal(r.errors[0].path, "$.game.durationBudgetSec.max");
  // 兜底层本身有效：绕过 schema 直接调 checkInvariants 时 I4-duration-max 必拦。
  const { checkInvariants } = await import("../src/invariants.ts");
  const spec = load("specs-eval/bad/03-duration-over-budget.json");
  const inv = checkInvariants(spec);
  assert.ok(inv.some((e) => e.code === "I4-duration-max" && e.path === "$.game.durationBudgetSec.max"),
    "I4-duration-max 兜底层应拦 max=35");
});

test("校验次序：schema 失败即止，不合并报告（spec-contract §2.4）", () => {
  // 缺顶层 flow（schema-required）+ pullpin orderSolution 语义违规——只许 schema 层错误。
  const spec = load("specs-eval/bad/01-missing-field.json");
  spec.game.template = "pullpin";
  spec.game.params = { orderSolution: "not-an-array" };
  const r = validateSpec(spec);
  assert.equal(r.ok, false);
  assert.ok(r.errors.length > 0);
  for (const e of r.errors) assert.match(e.code, /^schema-/, "schema 未过时不得出现不变式层错误码");
});

test("io 归一契约形状：非对象输入 → schema-type 单条（$ 路径）", async () => {
  const { checkInvariants } = await import("../src/invariants.ts");
  for (const bad of [null, 42, "x", [], true]) {
    const issues = checkInvariants(bad);
    assert.deepEqual(issues.map((e) => [e.path, e.code]), [["$", "schema-type"]]);
  }
});

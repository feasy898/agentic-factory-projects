#!/usr/bin/env node
// M1 eval：node packages/spec/test/ajv-check.mjs（在仓库根执行）。
//
// 断言：
//   1. specs-eval/golden-match3.json 通过 schema v1（ajv draft 2020-12）+ 语义不变式；
//   2. specs-eval/bad/*.json 全部被拒绝，且每条错误都带 json-path 字段路径。
// 全过 exit 0；任一断言失败 exit 1。

import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

import { validateSpec } from "../src/validate.mjs";

const REPO_ROOT = path.resolve(fileURLToPath(new URL("../../..", import.meta.url)));
const GOLDEN = path.join(REPO_ROOT, "specs-eval", "golden-match3.json");
const BAD_DIR = path.join(REPO_ROOT, "specs-eval", "bad");

let failures = 0;

function report(label, ok, details = []) {
  console.log(`[${ok ? "PASS" : "FAIL"}] ${label}`);
  for (const line of details) console.log(`       ${line}`);
  if (!ok) failures++;
}

// 1) golden 必须通过。
try {
  const golden = JSON.parse(readFileSync(GOLDEN, "utf8"));
  const result = validateSpec(golden);
  report(
    `golden 通过：${path.relative(REPO_ROOT, GOLDEN)}`,
    result.ok,
    result.ok ? [] : result.errors.map((e) => `${e.path}: ${e.message} [${e.code}]`),
  );
} catch (err) {
  report(`golden 读取/解析失败：${GOLDEN}`, false, [String(err)]);
}

// 2) bad 样本必须全拒，且错误带字段路径。
const badFiles = readdirSync(BAD_DIR)
  .filter((f) => f.endsWith(".json"))
  .sort();
if (badFiles.length === 0) {
  report(`bad 样本目录非空：${BAD_DIR}`, false, ["未找到任何 .json 样本"]);
}
for (const f of badFiles) {
  const full = path.join(BAD_DIR, f);
  try {
    const spec = JSON.parse(readFileSync(full, "utf8"));
    const result = validateSpec(spec);
    const details = [`判定：${result.ok ? "被通过（应当拒绝）" : "被拒绝"}`];
    for (const e of result.errors) {
      details.push(`${e.path}: ${e.message} [${e.code}]`);
      if (!e.path || !e.path.startsWith("$")) {
        details.push(`!!! 错误缺字段路径：${JSON.stringify(e)}`);
      }
    }
    const hasPathedError = result.errors.length > 0
      && result.errors.every((e) => e.path && e.path.startsWith("$"));
    report(
      `bad 拒绝：specs-eval/bad/${f}（错误含字段路径）`,
      !result.ok && hasPathedError,
      details,
    );
  } catch (err) {
    report(`bad 读取/解析失败：specs-eval/bad/${f}`, false, [String(err)]);
  }
}

console.log("-".repeat(72));
console.log(
  failures === 0
    ? `AJV-CHECK: PASS（golden 1 通过，bad ${badFiles.length} 全拒）`
    : `AJV-CHECK: FAIL（${failures} 项断言未过）`,
);
process.exit(failures === 0 ? 0 : 1);

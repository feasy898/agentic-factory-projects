// packages/spec/src/validate.ts — PlayableSpec 结构校验（ajv，draft 2020-12）+ 不变式复合入口。
//
// 错误 path 统一为 json-path 风格（"$.game.durationBudgetSec.max"），与 oracle 侧
// 输出对齐（包括"缺字段"错误把缺失字段名补进路径的约定，如 "$.flow"，
// spec-contract §2.4）。校验次序（冻结）：schema 结构 → 语义不变式（src/invariants.ts，
// TS 单源）；任一阶段失败即止，不合并报告。消息为诊断用意串，门禁只断言
// exit 码与 {path, code}（spec-contract §2.5）。
//
// 入口兼容：oracle 冻结测试 test/ajv-check.mjs 原样 import "../src/validate.mjs"，
// 该文件为本模块的 re-export 壳，实现本体在本文件（TS）。

// 兼容性注记（TS 7.0.2 native + Node 22 实测）：ajv/dist/2020.js 为 CJS，default 形态
// 在 tsc 侧不可构造（TS2351），具名导入在 tsc 与 Node cjs-module-lexer 双侧均可用。
import { Ajv2020 } from "ajv/dist/2020.js";
import type { ErrorObject } from "ajv";
import schemaJson from "../playable-spec.schema.json" with { type: "json" };
import { checkInvariants } from "./invariants.ts";
import type { SpecError, ValidateResult } from "./types.ts";

export const schema: Record<string, unknown> = schemaJson as Record<string, unknown>;

const ajv = new Ajv2020({ allErrors: true, strict: false });
const validateFn = ajv.compile(schema);

/** ajv 错误对象 -> { path, message, code }；路径转 json-path 风格。 */
function ajvIssue(err: ErrorObject): SpecError {
  let path = "$";
  if (err.instancePath) {
    path += err.instancePath
      .split("/")
      .filter(Boolean)
      .map((seg) => (/^\d+$/.test(seg) ? `[${seg}]` : `.${seg}`))
      .join("");
  }
  if (err.keyword === "required" && err.params && typeof err.params.missingProperty === "string") {
    path += `.${err.params.missingProperty}`;
  }
  return { path, message: err.message ?? "", code: `schema-${err.keyword}` };
}

/** 仅结构校验（schema）。 */
export function schemaErrors(spec: unknown): SpecError[] {
  const ok = validateFn(spec);
  return ok ? [] : (validateFn.errors ?? []).map(ajvIssue);
}

/**
 * 复合校验：schema 通过后执行语义不变式（校验次序与 oracle 同，§2.4）。
 */
export function validateSpec(spec: unknown): ValidateResult {
  const errors = schemaErrors(spec);
  if (errors.length) return { ok: false, errors };
  const issues = checkInvariants(spec);
  return { ok: issues.length === 0, errors: issues };
}

export { checkInvariants };

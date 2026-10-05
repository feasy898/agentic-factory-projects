// PlayableSpec 结构校验（ajv，draft 2020-12）+ 不变式复合入口。
//
// 错误 path 统一为 json-path 风格（"$.game.durationBudgetSec.max"），与
// python 侧 pfcore.validation 的输出对齐（包括"缺字段"错误把缺失字段名
// 补进路径的约定，如 "$.flow"）。

import Ajv2020 from "ajv/dist/2020.js";
import schemaJson from "../playable-spec.schema.json" with { type: "json" };
import { checkInvariants } from "./invariants.mjs";

export const schema = schemaJson;

const ajv = new Ajv2020({ allErrors: true, strict: false });
const validateFn = ajv.compile(schema);

/** ajv 错误对象 -> { path, message, code }；路径转 json-path 风格。 */
function ajvIssue(err) {
  let path = "$";
  if (err.instancePath) {
    path += err.instancePath
      .split("/")
      .filter(Boolean)
      .map((seg) => (/^\d+$/.test(seg) ? `[${seg}]` : `.${seg}`))
      .join("");
  }
  if (err.keyword === "required" && err.params && err.params.missingProperty) {
    path += `.${err.params.missingProperty}`;
  }
  return { path, message: err.message ?? "", code: `schema-${err.keyword}` };
}

/** 仅结构校验（schema）。 */
export function schemaErrors(spec) {
  const ok = validateFn(spec);
  return ok ? [] : validateFn.errors.map(ajvIssue);
}

/**
 * 复合校验：schema 通过后执行语义不变式（与 python 侧同序）。
 * @returns {{ok: boolean, errors: {path: string, message: string, code: string}[]}}
 */
export function validateSpec(spec) {
  const errors = schemaErrors(spec);
  if (errors.length) return { ok: false, errors };
  const issues = checkInvariants(spec);
  return { ok: issues.length === 0, errors: issues };
}

export { checkInvariants };

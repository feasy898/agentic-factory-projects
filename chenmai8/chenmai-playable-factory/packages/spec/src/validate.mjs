// packages/spec/src/validate.mjs — 冻结测试兼容入口（re-export 壳，零逻辑）。
//
// oracle 冻结测试 test/ajv-check.mjs 原样复用（字节复制），其 import 路径钉死为
// "../src/validate.mjs"（spec-contract §4）；本文件保持该路径可用。
// 实现本体 = TS 单源：./validate.ts（ajv 结构层）与 ./invariants.ts（四模板不变式，
// 可解性单一真源，决策 §0/§2.1 P1）。
export {
  schema,
  schemaErrors,
  validateSpec,
  checkInvariants,
} from "./validate.ts";

// @pf/spec —— PlayableSpec v1 契约入口。
//
// 公开面：schema JSON、复合校验器（ajv + 不变式）、规范生成器与不变式镜像、
// TS 类型。契约（schema v1.0.0 + 五条不变式 + 生成算法）自 M1 起冻结。

export { default as schema } from "./playable-spec.schema.json" with { type: "json" };
export {
  schemaErrors,
  validateSpec,
  checkInvariants,
} from "./src/validate.mjs";
export {
  Lcg,
  match3Board,
  match3FindMove,
  pullpinLevelRoles,
  pullpinSimulate,
  sortSolvedBoard,
  sortLegalMoves,
  sortApplyMove,
  sortInverseLegal,
  sortScramble,
  REQUIRED_STRING_KEYS,
  MATCH3_DEFAULTS,
  MERGE_DEFAULTS,
  PULLPIN_DEFAULTS,
  SORT_DEFAULTS,
  MAX_DURATION_SEC,
} from "./src/invariants.mjs";

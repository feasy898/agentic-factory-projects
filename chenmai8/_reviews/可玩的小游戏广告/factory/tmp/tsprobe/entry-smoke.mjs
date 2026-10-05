// 入口烟测：@pf/spec 公开面（spec-contract §2.5 清单 + 追加项）可加载且行为正确。
import * as pf from "@pf/spec";

const need = [
  "schema", "schemaErrors", "validateSpec", "checkInvariants",
  "Lcg", "match3Board", "match3FindMove", "pullpinLevelRoles", "pullpinSimulate",
  "sortSolvedBoard", "sortLegalMoves", "sortApplyMove", "sortInverseLegal", "sortScramble",
  "REQUIRED_STRING_KEYS", "MATCH3_DEFAULTS", "MERGE_DEFAULTS", "PULLPIN_DEFAULTS",
  "SORT_DEFAULTS", "MAX_DURATION_SEC", "PULLPIN_REROLL_MAX", "LCG_A", "LCG_C", "MASK32",
  "registerTemplateCheck", "listTemplateChecks", "clearTemplateChecks",
];
const missing = need.filter((k) => !(k in pf));
if (missing.length) {
  console.error("MISSING:", missing);
  process.exit(1);
}
const r = pf.validateSpec({ game: { template: "sort", params: { colors: 9 } } });
console.log("ENTRY-SMOKE-OK", r.ok === false, JSON.stringify(r.errors.map((e) => e.code).sort()),
  "schema.$id:", pf.schema.$id);

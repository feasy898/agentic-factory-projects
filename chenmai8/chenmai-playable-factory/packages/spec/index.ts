// @pf/spec — PlayableSpec v1 契约入口。
//
// 公开面（spec-contract §2.5 冻结清单）：schema JSON、复合校验器（ajv + 不变式）、
// 规范生成器与常量、TS 类型（src/types.ts）。契约（schema v1.0.0 + 五条不变式 +
// 生成算法）自 M1 起冻结；实现为 TS 单源（决策 §0/§2.1：oracle 双镜像废除）。
// 追加公开（预declare，不破坏冻结面）：LCG_A/LCG_C/MASK32/PULLPIN_REROLL_MAX 与
// check(spec) 注册制（P1 接缝：registerTemplateCheck/listTemplateChecks/clearTemplateChecks）。

// schema JSON 以 import attribute 导入（Node 22 语法，spec-contract §6）；
// 入口处经 validate.ts 的已加载实例再导出（TS 7.0.2 不支持 export-from 带 attribute）。
export { schema } from "./src/validate.ts";
export {
  schemaErrors,
  validateSpec,
  checkInvariants,
} from "./src/validate.ts";
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
  PULLPIN_REROLL_MAX,
  LCG_A,
  LCG_C,
  MASK32,
  registerTemplateCheck,
  listTemplateChecks,
  clearTemplateChecks,
} from "./src/invariants.ts";
export type {
  SpecVersion,
  Template,
  ChannelId,
  Gesture,
  Orientation,
  Palette,
  Meta,
  Match3Params,
  MergeParams,
  PullpinParams,
  SortParams,
  TemplateParams,
  Difficulty,
  Attract,
  DurationBudgetSec,
  GameSpec,
  Match3Game,
  MergeGame,
  PullpinGame,
  SortGame,
  TypedGame,
  Tutorial,
  EndScreen,
  Flow,
  AudioAssets,
  Assets,
  LocaleStrings,
  I18n,
  ChannelOverride,
  ChannelsSpec,
  Variant,
  QC,
  PlayableSpec,
  SpecError,
  ValidateResult,
  TemplateCheck,
} from "./src/types.ts";

# M1 规格 spec（PlayableSpec schema v1 校验器 · TS 单源）

> 模块：`packages/spec/`（@pf/spec）。任务 M1.2a，2026-09-30。
> 权威规格源：oracle `repo/docs/assets/specs/spec-contract.md`（frozen，只读）+ `match3-rules-card.md`
> §12 算例；实现裁定：`plan/模式M-技术选型决策.md` §0/§2.1（单栈、可解性单源、pydantic→TS 类型）。
> 本页是 factory 侧的模块资产 spec（双交付之一）；另一交付 = 冻结/移植 eval（见 §5）。

---

## 1. 职责与边界（照 spec-contract §1）

**做**：PlayableSpec v1.0.0 结构校验（JSON Schema draft 2020-12，ajv）、五条跨字段语义不变式
（I1–I5）、"由 seed 确定性生成关卡盘面"的规范生成器；错误一律定位到 json-path 字段路径并带
稳定错误码。

**不做**：不构建、不打包、不质检；CLI 面（`node pf.mjs validate`、glob 展开、stdout 人读格式）
属编排模块（pf/，批次 3）；模板参数的宽容归一属模板（规则卡 §1）。

## 2. 与 oracle 的结构差异（全部为决策预declare，非静默变更）

| # | 差异 | 依据 |
|---|---|---|
| 1 | **可解性单源**：oracle 的"Python 权威 `invariants.py` + JS 镜像 `invariants.mjs`"双实现废除，全部生成器与 I1–I5 以 `src/invariants.ts` 为唯一实现 | 决策 §0/§1.2-2/§2.1、spec-contract §5 目标形态（P1 授权） |
| 2 | **pydantic 表示层 → TS 类型**：无运行时 `model` 校验阶段；类型面 = `src/types.ts`（TS 消费方从这里 import，不自行声明） | 决策 §2.1（M1-spec 行）。oracle 冻结 11 件上 model 层零命中（实测），F1 等价不受影响 |
| 3 | **`src/validate.mjs` 为冻结测试兼容壳**：oracle 冻结测试 `ajv-check.mjs` 原样复用，其 import 钉在 `../src/validate.mjs`；壳仅 re-export，零逻辑 | spec-contract §4（eval 命令原样）+ 决策"冻结 JS 测试原样复用" |
| 4 | **注册制接缝（P1）**：`registerTemplateCheck/listTemplateChecks/clearTemplateChecks`——模板包 check(spec) 进程内注册，在 schema + 内建不变式之后追加执行（template 匹配者）。内建四模板不变式仍是当前唯一实现；M3 模板包落地后经此接缝接入，新增玩法"只改模板包一处" | 决策 §2 树注（P1）、spec-contract §5 |
| 5 | ajv 消息措辞与 jsonschema 不同（如 `must be <= 30` vs `35 is greater than...`）；门禁只断言退出语义与 `{path, code}`，消息人读不锁 | spec-contract §2.5、决策 §3.2 F1 |

## 3. 对外契约（锚点冻结）

- **schema**：`packages/spec/playable-spec.schema.json`（字节复用，sha 见 REUSED-ASSETS.md #1，
  `$id: urn:pf:spec:playable-spec:1.0.0`）；`specVersion` 恒 1.0.0、`rulesVersion` 恒 1.1.0（数据契约零变更）。
- **公开面**（`index.ts`，照 spec-contract §2.5 清单）：`schema / schemaErrors / validateSpec /
  checkInvariants` + 生成器与常量（`Lcg, match3Board, match3FindMove, pullpinLevelRoles,
  pullpinSimulate, sortSolvedBoard, sortLegalMoves, sortApplyMove, sortInverseLegal, sortScramble,
  REQUIRED_STRING_KEYS, MATCH3/MERGE/PULLPIN/SORT_DEFAULTS, MAX_DURATION_SEC`）+ 类型入口
  `src/types.ts`。追加公开（预declare）：`LCG_A/LCG_C/MASK32/PULLPIN_REROLL_MAX` 与注册制三函数。
- **校验次序**（冻结）：schema 结构 → 不变式；任一阶段失败即止，不合并报告。
- **错误契约**：`{path, message, code}`；path 为 json-path 风格；缺字段补名（`$.flow`）在 schema 层
  （ajv `required` + `missingProperty`，与 oracle jsonschema 路径约定一致）；稳定错误码全集 =
  `schema-<keyword>`、`I1-pullpin-order|unsolvable`、`I2-sort-colors|scramble|reversible`、
  `I3-sprites-cover-colors|match3-feasible-move`、`I4-duration-max|target`、
  `I5-i18n-coverage|default|rtl`、`I-merge-sprites|spawn|goal`、`schema-type`。
- **确定性随机源**（冻结）：32 位 LCG（`Math.imul + >>>0`），三自由度 = 先推进后取值 / 单流跨关卡 /
  各生成器独立建流；`variants[].seed` 不参与校验器生成器。
- **I2 重放方向钉死**：从 `sort_solved_board` 正向应用 trace，逐步断言合法（`I2-sort-scramble`）+
  逆步合法（`I2-sort-reversible`，该码只用于逆步不合法）；重放完与生成器盘面逐柱比对。
  I2 侧唯一前置域检查 `colors > rods → I2-sort-colors`；其余域约束属 schema 层。
- **bad03 双层同守**：schema `maximum=30` 先行（报 `schema-maximum`），`I4-duration-max` 为第二层兜底。

## 4. 兼容性注记（TS 7.0.2 native + Node 22.23.2 实测）

- Node 22 默认类型剥离可用；TS 源经 `.ts` 扩展直接 import（`erasableSyntaxOnly`，坑 5 纪律照抄）。
- ajv `dist/2020.js` 为 CJS：default 形态在 tsc 下不可构造（TS2351），**具名导入**
  `import { Ajv2020 } from "ajv/dist/2020.js"` 在 tsc 与 Node 运行时双侧可用（cjs-module-lexer
  识别其 defineProperty getter）。
- TS 7.0.2 不支持 `export ... from "....json" with { type: "json" }`（TS2307）；`import` 形态可用，
  入口 schema 经 `src/validate.ts` 已加载实例再导出。

## 5. eval：精确命令与通过线（真实执行，2026-09-30 全部实跑）

```bash
node packages/spec/test/ajv-check.mjs          # 冻结测试原样（字节复制，登记册 #27）→ AJV-CHECK: PASS，exit 0
node --test packages/spec/test/invariants.test.mjs packages/spec/test/eval-matrix.test.mjs packages/spec/test/schema.test.mjs
                                               # 21/21 pass（坑 4：不向 --test 传目录）
npx tsc -p packages/spec --noEmit              # TS 严格类型检查 exit 0
node scripts/diff/spec-eval-diff.mjs           # oracle 差分 harness → PASS（F1 11/11 双侧全等 + F6-M1 14 组向量逐值全等）
node scripts/verify-reused-assets.mjs          # 登记册 33 项 sha 重算全 MATCH，exit 0
```

- **11 件裁定矩阵**（`test/eval-matrix.test.mjs`，期望 = oracle 双侧实测基线，永不改）：
  golden×4 + demo-zh → OK；bad×6 → INVALID，`{path, code}` 逐件：
  `01 → $.flow [schema-required]`；`02 → $.game.params.orderSolution[0] [I1-pullpin-unsolvable]`；
  `03 → $.game.durationBudgetSec.max [schema-maximum]`；`04 → $.i18n.strings.ja [I5-i18n-coverage]`；
  `05 → $.flow.endScreen.landingUrl [schema-pattern]`；`06 → $.game.template [schema-enum]`。
- **算例逐值**（`test/invariants.test.mjs`）：§2.3 LCG 三自由度（bad02 seed=424242 首两抽 %3=[2,0]、
  golden seed=20260930 find_move=(0,2,1,2)）、整盘/整迹向量（Python 权威实测 + diff harness 程序化
  全等后冻结）、规则卡 §12 算例 B（唯一可行步 (0,1)-(1,1)）/C（死局 → null）。
- **oracle 差分证据**：`artifacts/diff/M1.2a-spec-eval.json`（F1 每件 新/oracle-JS/oracle-Python
  三方判定与 issue 集全等；F6-M1 14 组生成器向量 expected/actual 全等）。
- **禁止事项**（照抄）：不许为过 gate 改 bad 样本期望；不许单侧修算法（本仓已单源，改动即跑全量 eval）。

## 6. 已知边界（如实）

- `pullpinLevelRoles` 等生成器对非整数 seed 的行为：`Lcg` 构造做 `Number(seed) >>> 0`（与 oracle
  JS 镜像一致）；schema 层先保证 `meta.seed` 为整数 ≥0，直接调用生成器时由调用方负责。
- I4 层对 `max/target` 的类型判定用 `typeof === "number"`（JS 镜像语义）；Python `isinstance(int)`
  的 bool 兼容差异在 schema 先行的次序下不可达。
- 模板侧向量（mulberry32/deriveRng、FNV 形状调色板、resolve 波形）属 M3 模板包 logic-test
  （决策 §2.1 M3 行、批次 2 F6），不在本模块。

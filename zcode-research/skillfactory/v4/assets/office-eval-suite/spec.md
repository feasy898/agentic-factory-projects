# spec.md — 中文办公评测集 v2（office-eval-suite）

- 资产路径：`skillfactory/v4/assets/office-eval-suite/`
- 版本：1.0（2026-09-30 固化）
- oracle 参照：`oracle/suite.json` + `oracle/validate.py` + `oracle/export_legacy.py`（本 spec 全部规则均锚定其**实跑行为**，验证命令见 §7）
- 接口契约（冻结）：见同目录 `contract.md`
- 评测器：`eval/runner.py`（确定性，规则见 §4.4）

---

## 1. 定位与目标

本资产是「中文办公评测集 v2」：50 道自含材料的中文办公任务题（8 域 × 精确配比），每题带难度档与 3–5 条可判定检查要点（checks），是 v3「中文办公 Prompt 回归黄金集」（25 题/6 域）的扩容版；并附 v1 黄金集兼容导出器。任何按本契约重新生成或改造套件的产物，都必须通过 `oracle/validate.py` 的结构校验与 `eval/runner.py` 的确定性评测。

目标（逐条可判定）：

| # | 目标 | 判定方法 |
|---|---|---|
| G1 | 套件结构合法（schema/唯一性/域配比/难度分布/自含题干/checks 形状） | `oracle/validate.py` 退出码 0（9 项全绿） |
| G2 | 八域精确配比与难度分布和 spec 一致 | runner 检查 `ratio_difficulty_per_spec` |
| G3 | 50 题无内部重复，且与 oracle 套件比对完全相同题 ≤ 10 | runner 检查 `no_dup_vs_reference` |
| G4 | 自套件导出的 v1 黄金集兼容子集能被 v1 校验器通过（向下兼容实证） | runner 检查 `legacy_export_v1_green` |

## 2. 术语与产物结构

- **套件（suite.json）**：顶层 JSON object，键恰为 `version`(非空字符串) + `items`(非空数组)，可选 `description`(字符串)。
- **题（item）**：object，键集**恰为** `id` / `domain` / `difficulty` / `instruction` / `checks` 五键（`difficulty` 为 v2 相对 v1 新增字段）。
- **check**：object，必含 `name`/`desc`，允许 `type`/`value`；`type ∈ {contains, regex, semantic}`，缺省 `semantic`。
- **v1 兼容导出（golden-legacy.json）**：v1 黄金集格式（题目恰四键、无 difficulty、六域、25 题 6/5/3/3/4/4），由 `export_legacy.py` 从 v2 套件抽取生成。
- **被测产物根 / 参照产物根**：目录路径，布局约定见 `contract.md` §1/§5（runner 按 root → package/ 顺序解析；若给的是报告目录——仅含 `validate.json`——且父目录构成完整产物根，则**单层回退**解析到父目录并以 `resolved_via=report-dir-parent` 留痕；普通空目录/随机目录不回退，仍判红）。

## 3. 输入 / 输出

**输入**：`suite.json`（UTF-8）；命令行为 `<被测产物根> <参照产物根>`（runner）、`--suite <path>`（validate.py）、`--suite/--out/--report/--counts/--all`（export_legacy.py）。

**输出**：
- `validate.py`：stdout 逐项 `[PASS]/[FAIL]` + 汇总行；报告 JSON 写入 `--out`（缺省 `<脚本目录>/out/validate.json`）；退出码 0=全过 / 1=任一失败。
- `export_legacy.py`：导出产物写 `--out`（缺省 `out/golden-legacy.json`）、报告写 `--report`（缺省 `out/export-legacy.json`）；退出码 0=成功 / 1=任一域不足或失败。
- `runner.py`：stdout 打印 JSON（含 `ok` 与 `checks` 数组，4 项）；退出码 0=全过 / 1=任一失败。输出**不含时间戳**，同参数重复运行 stdout 逐字节一致。

## 4. 行为规则（逐条可判定）

### 4.1 套件数据规则（源自 `oracle/validate.py`，括号内为代码行号）

- **R1 顶层结构**：顶层为 object；必含 `version`(非空 str) 与 `items`(非空 list)；未知键禁止（允许 `version`/`description`/`items`）（validate.py:60, 93-109）。
- **R2 题 schema**：每题键集恰为 `{id, domain, difficulty, instruction, checks}`；`id` 匹配 `^[a-z0-9][a-z0-9._-]{1,63}$`（validate.py:64）；`domain` ∈ 八域枚举（validate.py:47-56）；`difficulty ∈ {易, 中, 难}`（validate.py:58）；`instruction` 非空字符串；`checks` 为数组（validate.py:112-136）。
- **R3 id 唯一**：50 个 `id` 全局唯一（validate.py:139-145）。
- **R4 域配比**：八域**精确**配比，总题数 = 50（validate.py:148-171）：

  | domain | 标签 | 题数 |
  |---|---|---|
  | doc-writing | 文档写作 | 8 |
  | table-data | 表格数据 | 6 |
  | meeting-minutes | 会议纪要 | 6 |
  | ppt-outline | PPT要点 | 5 |
  | email-comm | 邮件沟通 | 7 |
  | process-spec | 流程规范 | 6 |
  | info-extraction | 信息抽取 | 6 |
  | rewrite-polish | 改写润色 | 6 |

- **R5 难度分布**（v2 新增）：每域 易/中/难 三档齐备（各 ≥1），且**中档占该域多数（>50%）**；全局中档亦须占多数（validate.py:59, 174-211）。
- **R6 题干自含**：每题 `instruction` 长度 ∈ [80, 2000] 字符，且含至少一个材料标记 cue（cue 表 18 词：`如下/材料/背景/原文/要点/数据/记录/笔记/素材/时间线/规则/条文/条款/对话/邮件/说明/简历/议程`，validate.py:66-67, 214-235）。
- **R7 题干互异**：50 题 instruction 去空白归一化后两两互异（validate.py:238-254）。
- **R8 checks 形状**：每题 checks 数量 ∈ [3, 5]（validate.py:69）；每条 check 必含 `name`/`desc`，未知键禁止（允许 `name`/`desc`/`type`/`value`，validate.py:62）；`name` 匹配 `^[a-z0-9][a-z0-9_-]{0,49}$` 且**题内唯一**（validate.py:65）；`desc` 为 1–300 字符字符串；`type ∈ {contains, regex, semantic}`（validate.py:63）；`type=contains/regex` 时必须带非空字符串 `value`；`type=regex` 时 `value` 必须可被 `re.compile` 编译（validate.py:257-304）。
- **R9 每域三档示例基线**：oracle 实测各域难度（易/中/难）：文档写作 2/5/1、表格数据 1/4/1、会议纪要 1/4/1、PPT要点 1/3/1、邮件沟通 2/4/1、流程规范 1/4/1、信息抽取 1/4/1、改写润色 1/4/1；全局 易10/中32/难8（本会话实测，非冻结规则——冻结规则是 R5）。

### 4.2 validate.py 行为规则

- **V1 CLI**：`python validate.py --suite <path> [--out <path>]`；`--suite` 必填；`--out` 缺省 `<脚本目录>/out/validate.json`（validate.py:309-311, 385）。
- **V2 九项检查**：依次执行 `load_json / schema_top / schema_items / ids_unique / domain_ratio / difficulty_distribution / instruction_quality / instructions_distinct / checks_shape`，语义即 R1–R8（validate.py:322-341）。依赖链：`load_json → schema_top` 失败时后续按依赖跳过，跳过项不入 `checks`，仍判失败。
- **V3 报告**：写出 JSON，含 `tool/asset/suite/generated_at/ok/summary{validator_checks,items,domains,difficulty,checks_in_suite}/checks[{name,passed,detail}]`（validate.py:370-384）。
- **V4 退出码**：全部通过（恰 9 项且全过）→ 打印 `ALL GREEN ✓` 且退出码 0；任一失败 → 退出码 1（validate.py:345, 389）。

### 4.3 export_legacy.py 行为规则

- **X1 CLI**：`python export_legacy.py [--suite <path>] [--out <path>] [--report <path>] [--counts k=v,...] [--all]`；`--suite` 缺省 `<脚本目录>/suite.json`，`--out` 缺省 `out/golden-legacy.json`，`--report` 缺省 `out/export-legacy.json`（export_legacy.py:156-167）。
- **X2 导出格式（v1 黄金集契约）**：顶层 `{version, description, items}`，version=`1.0.0-legacy-export`；题目**恰四键** `{id, domain, instruction, checks}`（严格此顺序，**移除 difficulty**）；只含 v1 六域题目，v2 新增域（info-extraction/rewrite-polish）不导出并在报告 `dropped_v2_only_domains` 留痕（export_legacy.py:42-56, 81-87, 101-115）。
- **X3 缺省模式（严格）**：按 v1 六域下限 6/5/3/3/4/4（共 25 题）**按文件顺序取前 N 题**；任一域可导出数不足 → 退出码 1（export_legacy.py:89-99, 148-152）。`--counts 域=整数` 覆盖各域抽取数（域名限 v1 六域）；`--all` 导出全部六域题目（宽松模式，仅保证域合法）。
- **X4 报告**：`{tool, suite, generated_at, ok, mode, exported, total_items, total_checks, per_domain_taken, dropped_v2_only_domains, dropped_field, problems}`（export_legacy.py:124-140）。退出码 0=导出成功且达 v1 规格。

### 4.4 eval/runner.py 行为规则（本 spec 冻结，runner 内同值写死）

- **E1 CLI**：`python skillfactory/v4/assets/office-eval-suite/eval/runner.py <被测产物根> <参照产物根> [--out <path>]`。stdout 打印 JSON：`{tool, asset, candidate, reference, candidate_layout, resolved_via, reference_resolved_via, self_eval, sampled_ids, ok, summary, checks[4]}`；退出码 0=4 项检查全过 / 1=任一失败。失败时同样打印完整 JSON（`ok=false`）。`checks` 数组每项为 `{name, passed, detail[, ...附加审计字段]}`，消费方只应依赖 `name/passed/detail`。
- **E2 四项检查（名称冻结）**：
  1. `validate_all_green` — 在被测产物根解析出三件套后，以子进程执行 `[python, <被测 validate.py>, --suite, <被测 suite.json>, --out, <临时文件>]`（显式 `--out`，不污染产物目录）；通过条件：退出码 0 **且** 报告 `ok==true`。
  2. `ratio_difficulty_per_spec` — 直接解析被测 suite.json（**不信任被测校验器**），逐项核对：八域精确配比（R4 表）、总题数 50、无八域之外 domain；每域三档齐备、中档占该域多数、全局中档占多数（R5）。
  3. `no_dup_vs_reference` — (a) **内部唯一**：被测 50 题 instruction 去空白归一化后两两互异；(b) **跨集查重**：与参照套件比对，归一化后**完全相同**的题数 ≤ 10；同时输出与参照集最大/平均相似度（`difflib.SequenceMatcher`）作审计信息。**自评豁免**：当被测 suite.json 与参照 suite.json 解析后为同一路径（`Path.resolve()` 相等）时，(b) 豁免并标注 `self_eval=true`；但位于不同路径的逐字节拷贝**不豁免**（50 > 10 判红），这正是本检查要拦截的整卷抄袭。(a) 内部唯一性在任何模式下都执行。
  4. `legacy_export_v1_green` — 以子进程执行 `[python, <被测 export_legacy.py>, --suite, <被测 suite.json>, --out, <临时导出>, --report, <临时报告>]`；导出退出码 0 且产物可解析后，再以 v1 校验器（`skillfactory/v3/assets/prompt-regression/package/validate.py`，由 runner 路径上溯 `parents[4]` 定位）执行 `--golden <临时导出>`；通过条件：导出退出码 0 **且** v1 校验退出码 0 **且** v1 报告 `ok==true`。此检查把"向下兼容"从推断变成实证：v1 cue 表含 `「/“` 而 v2 无（R6 cue 表是**不同**集合而非超集），存在 v2 绿、v1 红的理论缝隙，本检查封死该缝隙。
- **E3 确定性**：输出不含时间戳；同参数重复运行 → stdout 逐字节一致、退出码一致。runner 全程无模型调用（`semantic` 判分不在 runner 范围内，天然确定）。
- **E4 短路补位**：被测三件套无法解析/suite.json 无法加载时，依赖数据的检查项置 `passed=false`，detail 注明「前置失败」，4 项检查始终齐全出现在 `checks` 数组中；`export_legacy.py` 缺失只判红第 4 项，其余三项照常执行。

## 5. 质量基线（oracle 实测，2026-09-30 本会话测得）

| 指标 | 实测值 |
|---|---|
| validate.py | 9/9 全绿，exit 0（命令见 §7.1） |
| 题数 / check 总数 | 50 题 / 230 条（每题 3–5 条） |
| 域配比 | 文档写作 8 / 表格数据 6 / 会议纪要 6 / PPT要点 5 / 邮件沟通 7 / 流程规范 6 / 信息抽取 6 / 改写润色 6 |
| 难度分布 | 全局 易10/中32/难8；每域三档齐备且中档占多数（§4.1 R9 表） |
| instruction 长度 | 172–384 字符，全部含材料标记，归一化后两两互异 |
| version / id 样例 | `2.0.0-suite`；id 从 `dw-01` 到 `rp-06` |
| legacy 导出 | 25 题 / 118 条 check，六域 6/5/3/3/4/4，移除 difficulty；v1 校验器 7/7 全绿 exit 0（兼容性实证） |
| 红灯夹具（oracle/out/red/，8 个变异逐一实跑） | red-schema→schema_items+instruction_quality、red-dup-id→ids_unique、red-ratio→domain_ratio、red-diff-tier→difficulty_distribution、red-diff-majority→difficulty_distribution、red-material→instruction_quality、red-checkcount→checks_shape、red-regex→checks_shape；全部 ok=false、exit 1——每项必查校验都被实证能抓错 |

## 6. 边界与非目标

- **不做**被测模型/被测 skill 答案的判分：本资产只管套件产物自身的质量；`semantic` 类 check 的执行交由未来评测流水线的裁判模型，runner 不调用任何模型。
- **不做** instruction 语义正确性评审：runner 只查结构、配比、难度分布、查重与向下兼容；题目内容质量靠出题时人工把关。
- **不做**多语言/非办公域扩展：八域枚举与 cue 表按中文办公场景冻结。
- **不修改 oracle**：oracle 为参照实现，只读；演进套件 = 在新产物根按 contract 重新生成并过 runner。
- **eval 只增不删**：`eval/` 下检查项只允许新增，不允许删除或放松既有检查与阈值（含相同题上限 10 只许收紧）。
- runner 不校验 `export_legacy.py` 的 `--counts/--all` 变体路径（只测缺省严格模式）——变体行为由 oracle 侧自检覆盖。
- 兼容缝隙说明：v2 cue 表与 v1 cue 表是**不同集合**（共享 9 词；v2 独有 9 词如 `条款/议程`；v1 独有 `「/“`）。故"v2 全绿 ⇒ v1 导出必绿"不是逻辑推论，而是靠 runner 第 4 项检查对每次导出产物实跑 v1 校验器来保证。

## 7. 验证方式（本会话实跑记录）

以下命令均于 2026-09-30 在本机 Python 3.12.10（Windows）实际执行；工作目录为资产根 `skillfactory/v4/assets/office-eval-suite/`。

1. **oracle 自检**：`python oracle/validate.py --suite oracle/suite.json` → 9 项全 `[PASS]`、`ALL GREEN ✓（9/9 项校验通过，50 题 / 230 条 check）`、exit 0（报告 `oracle/out/validate.json`，ok=true）。
2. **绿（runner 对 oracle 判绿）**：`python eval/runner.py oracle oracle --out eval/out/runner-green.json` → 4/4 全 `[PASS]`、`ALL GREEN ✓`、**exit 0**：check1 `被测校验器全绿：9/9 项通过，items=50，checks_in_suite=230`；check2 八域精确配比+每域三档齐备中档占多数；check3 `self_eval=true`（同文件豁免跨集查重）；check4 `legacy 兼容导出 → v1 校验器全绿：导出 25 题（六域配比 6/5/3/3/4/4），v1 校验 7/7 项通过`。
3. **红（主案例，空目录）**：`python eval/runner.py <空目录> oracle --out eval/out/runner-red-empty.json` → 4 项全部 `前置失败` 判红（detail 逐条列出已尝试路径）、**exit 1**。
4. **定向负例（验证各项检查"有牙"，报告存档于 `eval/out/`）**：
   - ① `runner-red-ratio-weak.json` — 恒绿 stub 校验器 + 配比变异套件（文档写作 8→7、改写润色 6→7）：check1 通过（stub 恒绿），`ratio_difficulty_per_spec` 精确判红（`文档写作=7/8`、`改写润色=7/6`，exit 1）——证明 check2 不信任被测校验器、独立核对 spec 配比。
   - ② `runner-red-copy.json` — oracle 三件套异地逐字节拷贝：仅 `no_dup_vs_reference` 判红（`完全相同题 50 > 上限 10`、`self_eval=false`，exit 1）——不同路径的整卷拷贝不豁免。
   - ③ `runner-red-legacy-v1.json` — dw-01 instruction 改为仅含 v2 独有 cue（`议程/说明`，无任何 v1 cue；被测自身 validate.py 实跑仍 exit 0 全绿）：仅 `legacy_export_v1_green` 判红（`v1 校验器对导出产物退出码 1——legacy 兼容性不成立`，exit 1）——实证 §6 所述 cue 表缝隙被该检查封死。
5. **确定性**：绿侧同参数连续两次运行，stdout 经 `cmp` 比对**逐字节一致**，退出码均 0。
6. **布局解析（contract §1 行为实证）**：① `runner-green-package.json` — 三件套置于 `<root>/package/`（41 题题干加变体后缀、9 题与 oracle 相同）→ `candidate_layout=package`、4/4 全绿、exit 0，且跨集相同题 9 ≤ 10 正向验证了上限边界（`self_eval=false`）；② `runner-green-reportdir.json` — 对仅含 `validate.json` 的报告目录 `<root>/package/out/` 运行 runner → 单层回退到父目录，`resolved_via=report-dir-parent(<out> -> <package>)`、4/4 全绿、exit 0。

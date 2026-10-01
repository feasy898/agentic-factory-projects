# spec.md — 中文办公 Prompt 回归黄金集（prompt-regression）

- 资产路径：`skillfactory/v3/assets/prompt-regression/`
- 版本：1.0（2026-09-30 固化）
- oracle 参照：`oracle/golden.json` + `oracle/validate.py`（本 spec 全部规则均锚定其**实跑行为**，验证命令见 §7）
- 接口契约（冻结）：见同目录 `contract.md`
- 评测器：`eval/runner.py`（确定性，规则见 §4.3）

---

## 1. 定位与目标

本资产是「中文办公 prompt 回归黄金集」：25 道自含材料的中文办公任务题，每题附 3–5 条可判定检查要点（checks），作为**未来 skill 的回归底座**——任何按本契约重新生成或改造黄金集的产物，都必须通过 `oracle/validate.py` 的结构校验与 `eval/runner.py` 的确定性评测。

目标（逐条可判定）：

| # | 目标 | 判定方法 |
|---|---|---|
| G1 | 黄金集结构合法（schema/唯一性/域配比/自含题干/checks 形状） | `oracle/validate.py` 退出码 0 |
| G2 | 域配比与 spec 一致（六域，总 25 题） | runner 检查 `domain_coverage_per_spec` |
| G3 | 25 题无一重复，且与 oracle 黄金集比对不得整卷雷同 | runner 检查 `no_duplicate_vs_reference` |
| G4 | 抽样题目的 checks 实际可判（非恒真/不可执行） | runner 检查 `sampled_checks_decidable` |

## 2. 术语与产物结构

- **黄金集（golden.json）**：顶层 JSON object，键恰为 `version`(非空字符串) + `items`(非空数组)，可选 `description`(字符串)。
- **题（item）**：object，键集**恰为** `id` / `domain` / `instruction` / `checks` 四键。
- **check**：object，必含 `name`/`desc`，允许 `type`/`value`；`type ∈ {contains, regex, semantic}`，缺省 `semantic`。
- **被测产物根 / 参照产物根**：目录路径，布局约定见 `contract.md` §1（runner 按 root → package/ 顺序解析；若给的是报告目录——仅含 `validate.json`——且父目录构成完整产物根，则**单层回退**解析到父目录并以 `resolved_via=report-dir-parent` 留痕；普通空目录/随机目录不回退，仍判红）。

## 3. 输入 / 输出

**输入**：`golden.json`（UTF-8）；命令行为 `<被测产物根> <参照产物根>`（runner）或 `--golden <path>`（validate.py）。

**输出**：
- `validate.py`：stdout 逐项 `[PASS]/[FAIL]` + 汇总行；报告 JSON 写入 `--out`（缺省 `<脚本目录>/out/validate.json`）；退出码 0=全过 / 1=任一失败。
- `runner.py`：stdout 打印 JSON（含 `ok` 与 `checks` 数组，4 项）；退出码 0=全过 / 1=任一失败。输出**不含时间戳**，同参数重复运行 stdout 逐字节一致。

## 4. 行为规则（逐条可判定）

### 4.1 黄金集数据规则（源自 `oracle/validate.py`，括号内为代码行号）

- **R1 顶层结构**：顶层为 object；必含 `version`(非空 str) 与 `items`(非空 list)；未知键禁止（允许 `version`/`description`/`items`）（validate.py:46-47, 63-81）。
- **R2 题 schema**：每题键集恰为 `{id, domain, instruction, checks}`；`id` 匹配 `^[a-z0-9][a-z0-9._-]{1,63}$`（validate.py:58）；`domain` ∈ 六域枚举（validate.py:36-43）；`instruction` 非空字符串；`checks` 为数组（validate.py:84-117）。
- **R3 id 唯一**：25 个 `id` 全局唯一（validate.py:120-125）。
- **R4 域配比**：六域各域题数 ≥ 下限，且总题数 = 25（validate.py:36-44, 128-143）。下限表（合计恰为 25，故等价于精确配比）：

  | domain | 标签 | 下限 |
  |---|---|---|
  | doc-writing | 文档写作 | 6 |
  | table-data | 表格数据 | 5 |
  | meeting-minutes | 会议纪要 | 3 |
  | ppt-outline | PPT要点 | 3 |
  | email-comm | 邮件沟通 | 4 |
  | process-spec | 流程规范 | 4 |

- **R5 题干自含**：每题 `instruction` 长度 ∈ [80, 2000] 字符，且含至少一个材料标记 cue（cue 表：`如下/材料/背景/原文/要点/数据/记录/笔记/素材/「/“`，validate.py:49-51, 146-159）。
- **R6 checks 形状**：每题 checks 数量 ∈ [3, 5]（validate.py:53）；每条 check 必含 `name`/`desc`，未知键禁止（允许 `name`/`desc`/`type`/`value`）（validate.py:54-55）；`name` 匹配 `^[a-z0-9][a-z0-9_-]{0,49}$` 且**题内唯一**（validate.py:59）；`desc` 为 1–300 字符字符串；`type ∈ {contains, regex, semantic}`（validate.py:56）；`type=contains/regex` 时必须带非空字符串 `value`；`type=regex` 时 `value` 必须可被 `re.compile` 编译（validate.py:162-216）。

### 4.2 validate.py 行为规则

- **V1 CLI**：`python validate.py --golden <path> [--out <path>]`；`--golden` 必填（validate.py:223）；`--out` 缺省 `<脚本目录>/out/validate.json`（validate.py:227）。
- **V2 七项检查**：依次执行 `load_json / schema_top / schema_items / ids_unique / domain_coverage / instruction_quality / checks_shape`，语义即 R1–R6（validate.py:247-262）。
- **V3 报告**：写出 JSON，含 `tool/asset/golden/generated_at/ok/summary{validator_checks,items,domains,checks_in_golden}/checks[{name,passed,detail}]`（validate.py:273-288）。
- **V4 退出码**：全部通过 → 打印 `ALL GREEN ✓` 且退出码 0；任一失败 → 退出码 1（validate.py:290-294）。前序检查失败时后续检查按依赖跳过，跳过项不出现在 `checks` 中，仍判失败。

### 4.3 eval/runner.py 行为规则（本 spec 冻结，runner 内同值写死）

- **E1 CLI**：`python skillfactory/v3/assets/prompt-regression/eval/runner.py <被测产物根> <参照产物根> [--out <path>]`。stdout 打印 JSON：`{tool, asset, candidate, reference, candidate_layout, resolved_via, reference_resolved_via, self_eval, sampled_ids, ok, summary, checks[4]}`；退出码 0=4 项检查全过 / 1=任一失败。失败时同样打印 JSON（`ok=false`）。`checks` 数组每项为 `{name, passed, detail[, ...附加审计字段]}`，消费方只应依赖 `name/passed/detail`。
- **E2 四项检查（名称冻结）**：
  1. `validate_all_green` — 在被测产物根解析出 `validate.py`+`golden.json` 后，以子进程执行 `[python, <validate.py>, --golden, <golden.json>, --out, <临时文件>]`（显式 `--out`，不污染产物目录）；通过条件：退出码 0 **且** 报告 `ok==true`。
  2. `domain_coverage_per_spec` — 直接解析被测 golden.json，按 R4 下限表逐域核对 `count ≥ min`，且总题数 = 25，且无六域之外的 domain 值。
  3. `no_duplicate_vs_reference` — (a) **内部唯一**：被测 25 题 instruction 经归一化（删除全部空白字符）后两两互不相同；(b) **跨集查重**：与参照黄金集比对，归一化后**完全相同**的题数 ≤ 5；同时输出与参照集最大/平均相似度（`difflib.SequenceMatcher`）作审计信息。**自评豁免**：当被测 golden 与参照 golden 解析后为同一路径（`Path.resolve()` 相等）时，(b) 豁免并标注 `self_eval=true`——同一文件与自身比对查重无意义；但位于不同路径的逐字节拷贝**不豁免**（25 > 5 判红），这正是本检查要拦截的整卷抄袭。(a) 内部唯一性在任何模式下都执行。
  4. `sampled_checks_decidable` — 以固定种子 `random.Random(20260930)` 从被测题（按文件顺序）抽 3 题，逐条执行脚本化可判性复核：
     - 题目级：四键 schema 合法；instruction 长度 ∈ [80,2000] 且含材料标记（R5 同判）。
     - `contains`：`value` 长度 ≥ 2（oracle 观测最小值=2）；且不构成「对全部探针恒真」（探针表见下）。
     - `regex`：可编译；pattern 字面字符（`[A-Za-z0-9\u4e00-\u9fff]`）数 ≥ 2（oracle 观测最小值=2，如「回滚」）；若 pattern **不含** `(?!`（正向检查），则不得匹配全部探针（恒真模式不可判）；若**含** `(?!`（否定型/禁止出现某内容），则必须至少禁止一个长度 ≥2 的具体字面 token（否则等于什么都没禁止）。否定型不做匹配式恒真测试——禁止型检查天然匹配空串与无关文本。
     - `semantic`：`desc` 长度 ≥ 8（oracle 观测最小值=9）且汉字数 ≥ 3（oracle 观测最小值=4），保证裁判模型有可执行判据。
     - 探针表（含空串）：`""`、`"今天天气不错，大家出去散步，顺便吃了午饭。"`、`"会议纪要：待办事项、责任人、截止时间。"`、`"ABCDEFG 1234567890 !@#$%^&*()"`、`"的总计合计金额为350000元，占比34.3%，由华东区域上报。"`。
     - 以上阈值已在本会话于 oracle **全部 125 条 check** 上预验证：0 违规（§7）。抽样结果（题 id 与逐条判据结论）写入 runner 输出 `sampled_ids` 与该检查项的 `samples` 字段留档，供人工审计。
- **E3 确定性**：抽样用固定种子；输出不含时间戳；同参数重复运行 → stdout 逐字节一致、退出码一致。`semantic` 判分不在 runner 范围内（无需模型调用，天然确定）。
- **E4 短路补位**：被测 golden 无法加载/题数不足时，依赖数据的检查项置 `passed=false`，detail 注明「前置失败」，4 项检查始终齐全出现在 `checks` 数组中。

## 5. 质量基线（oracle 实测，2026-09-30 本会话测得）

| 指标 | 实测值 |
|---|---|
| validate.py | 7/7 全绿，exit 0（命令见 §7） |
| 题数 / check 总数 | 25 题 / 125 条（每题恰 5 条） |
| check 类型分布 | regex 80 / contains 8 / semantic 37 |
| instruction 长度 | 128–313 字符，全部含材料标记 |
| 归一化后内部最大相似度 | 0.3440（无近似重复） |
| 阈值观测最小值 | contains value 2 字符；regex 字面 2 字符；semantic desc 9 字符/4 汉字 |
| 抽样 3 题人工复核（seed=20260930 → ppt-001 / meeting-002 / email-004） | 15/15 条 check 实际可判；发现 1 处弱点不影响可判性：meeting-002.demand 的 `中旬?` 使 regex 实际只需「10月」即命中（记录不改，eval 只增不删） |
| 表类数字抽算 | table-001：350000=120000+95000+88000+47000 ✓，占比 34.3% ✓；table-003：6950=3200+800+2800+150 ✓，总额 12550 ✓ |

## 6. 边界与非目标

- **不做**被测模型/被测 skill 答案的判分：本资产只管黄金集产物自身的质量；`semantic` 类 check 的执行交由未来回归流水线的裁判模型，runner 不调用任何模型。
- **不做** instruction 语义正确性评审：表类数字正确性靠出题时人工核算（基线见 §5），runner 只查结构与可判性。
- **不做**多语言/非办公域扩展：域枚举与 cue 表按中文办公场景冻结。
- **不修改 oracle**：oracle 为参照实现，只读；演进黄金集 = 在新产物根按 contract 重新生成并过 runner。
- **eval 只增不删**：`eval/` 下检查项只允许新增，不允许删除或放松既有检查与阈值。
- runner 的可判性判据是**人工复核的脚本化近似**（启发式），其局限（如对「禁止 5 位数字」这类无字面 token 的否定型 regex 会误报）已在 §4.3 标注；抽样留档供人工审计兜底。

## 7. 验证方式（本会话实跑记录）

以下命令均于 2026-09-30 在本机实际执行：

1. `cd ...\oracle && python validate.py --golden golden.json` → 7 项全 `[PASS]`，`ALL GREEN ✓（7/7 项校验通过，25 题 / 125 条 check）`，`EXIT=0`。
2. 探针脚本在 oracle 全部 125 条 check 上预验证 §4.3 判据 → `违规数: 0 / 125`（初版判据误伤 3 处：两条否定型 regex、一条 9 字 semantic desc，据此把否定型 regex 改为「禁止具体 token」判据、阈值降到不高于 oracle 观测最小值）。
3. 红绿自校验（报告存档于 `eval/out/`，命令均从工作区根执行）：
   - **绿**：`python eval/runner.py oracle oracle --out eval/out/runner-green.json` → `[PASS]×4`、`ALL GREEN ✓（4/4）`、**exit 0**、`self_eval=true`、抽样 `['ppt-001','meeting-002','email-004']` 与人工复核一致。
   - **红（主案例，空目录）**：`runner.py <空目录> oracle --out eval/out/runner-red-empty.json` → 4 项全部 `前置失败` 判红、**exit 1**。
   - **定向负例（验证各项检查"有牙"）**：① 弱校验器 stub（恒绿）+ 缺 1 题 → check1 通过但 `domain_coverage_per_spec` 精确判红（流程规范 3<4、总数 24≠25，exit 1，同时证明 package/ 布局可解析）；② oracle 异地逐字节拷贝 → 仅 `no_duplicate_vs_reference` 判红（完全相同 25 > 5、`self_eval=false`，exit 1——不同路径的拷贝不豁免）；③ 抽中题 ppt-001.kpi 的 regex 换成 `.*` → 被测校验器仍绿，但 `sampled_checks_decidable` 精确判红（字面字符 0 < 2，恒真不可判，exit 1）。报告：`runner-red-missing-q.json` / `runner-red-copy.json` / `runner-red-trivial-regex.json`。
   - **确定性**：绿侧同参数连续两次运行，stdout 经 `cmp` 比对**逐字节一致**，退出码均 0。

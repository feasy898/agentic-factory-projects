# contract.md — office-eval-suite（中文办公评测集 v2）资产接口契约

> 原则：**接口冻结，实现自由**。本文件约定产物必备文件、脚本命令行与产物格式；
> 满足契约的任何实现（包括重新生成的套件与重写的校验器/导出器）都可直接接入 `eval/runner.py`。
> 数据与行为细则以 `spec.md` §4 为准；本文只冻结"接口面"。
> oracle 参照实现：`oracle/`（suite.json + validate.py + export_legacy.py），只读。

---

## 1. 被测产物必备文件

被测产物根（candidate root）必须能让 runner 解析出三个文件：

| 布局 | 必备文件 | 说明 |
|---|---|---|
| root 布局（与 oracle 同构） | `<root>/suite.json` + `<root>/validate.py` + `<root>/export_legacy.py` | 推荐开发期使用 |
| package 布局（打包形态） | `<root>/package/` 下同上三文件 | 推荐分发形态 |

- 解析顺序：root 布局 → package 布局 →（报告目录回退，见下），取第一个文件齐备的位置。
- `suite.json + validate.py` 不齐备 → 检查 `validate_all_green`、`ratio_difficulty_per_spec`、`no_dup_vs_reference` 全部前置失败判红；`export_legacy.py` 缺失只判红 `legacy_export_v1_green`（其余三项照常执行）。
- 报告目录回退（单层、留痕）：若给定的根只含校验器报告 `validate.json` 而无三件套，且其**父目录**构成完整产物根，则回退解析到父目录，输出以 `resolved_via=report-dir-parent(<报告目录> -> <父目录>)` 留痕。普通空目录/随机目录不满足回退条件，仍判红。
- runner 调用被测脚本时**始终显式传 `--out`/`--report`**（指向临时文件），不依赖也不污染产物目录的 `out/`。

## 2. suite.json 数据契约（冻结）

```jsonc
{
  "version": "<非空字符串>",            // oracle: "2.0.0-suite"
  "description": "<可选字符串>",
  "items": [
    {
      "id": "dw-01",                    // ^[a-z0-9][a-z0-9._-]{1,63}$，全局唯一
      "domain": "doc-writing",          // 八域枚举，见下表
      "difficulty": "易",               // 易 | 中 | 难（v2 相对 v1 新增字段）
      "instruction": "<80-2000字符，自含全部输入材料，含材料标记>",
      "checks": [                        // 每题 3-5 条，name 题内唯一
        { "name": "event-time",          // ^[a-z0-9][a-z0-9_-]{0,49}$
          "desc": "<1-300字符，说明判定什么>",
          "type": "regex",               // contains | regex | semantic（缺省 semantic）
          "value": "<contains/regex 必带：非空字符串，regex 须可编译>" }
      ]
    }
  ]
}
```

八域配比（**精确值**，总计 50）：

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

难度分布（v2 新增维度）：每域 易/中/难 三档齐备（各 ≥1）且**中档占该域多数（>50%）**；全局中档亦须占多数。

内容约束：50 题 instruction 去空白归一化后两两互异；与参照套件（oracle）比对，归一化后完全相同题 ≤ 10（自评模式豁免跨集部分，见 spec §4.4 E3）。

## 3. validate.py 命令行契约（冻结）

```bash
python validate.py --suite <suite.json 路径> [--out <报告输出路径>]
```

| 项 | 冻结约定 |
|---|---|
| `--suite` | 必填 |
| `--out` | 可选；缺省写 `<脚本所在目录>/out/validate.json` |
| stdout | 逐项 `[PASS]/[FAIL] <name>: <detail>` + 汇总行（含 `ALL GREEN ✓` 或 `FAILED ✗`） |
| 报告 JSON | `{tool, asset, suite, generated_at, ok, summary:{validator_checks:{total,passed,failed}, items, domains, difficulty, checks_in_suite}, checks:[{name,passed,detail}]}`（UTF-8） |
| 检查项名称 | `load_json / schema_top / schema_items / ids_unique / domain_ratio / difficulty_distribution / instruction_quality / instructions_distinct / checks_shape`（9 项，语义 = spec §4.1 R1–R9） |
| 退出码 | 0 = 全过（恰 9 项且全过）；1 = 任一失败。前序失败按依赖跳过，跳过项不入 `checks`，仍判失败 |

实现自由：校验逻辑内部写法、报告里 `asset` 字段的取值、`generated_at` 的具体时刻。

## 4. export_legacy.py 命令行契约（冻结）

```bash
python export_legacy.py [--suite <suite.json>] [--out <导出路径>]
                        [--counts doc-writing=6,table-data=5,...] [--all] [--report <json>]
```

| 项 | 冻结约定 |
|---|---|
| `--suite` | 可选；缺省 `<脚本所在目录>/suite.json` |
| `--out` | 可选；缺省 `<脚本所在目录>/out/golden-legacy.json`（导出产物，v1 黄金集格式） |
| `--report` | 可选；缺省 `<脚本所在目录>/out/export-legacy.json`（导出报告） |
| `--counts` | 可选；`域名=整数` 逗号分隔，域名限 v1 六域，覆盖各域抽取数 |
| `--all` | 可选；导出全部 v1 六域题目（宽松模式，不做 25 题裁剪） |
| 导出产物格式 | v1 黄金集契约：顶层 `{version, description, items}`；题目**恰四键** `{id, domain, instruction, checks}`（**移除 difficulty**）；version=`1.0.0-legacy-export`；v2 新增域（info-extraction/rewrite-polish）不导出 |
| 缺省模式 | 严格模式：按 v1 六域下限 6/5/3/3/4/4（共 25 题）从 v2 套件**按文件顺序取前 N 题**；任一域不足 → 退出码 1 |
| stdout | `[PASS] 导出 N 题 / M 条 check → <路径>` + 六域配比行 + 移除字段/未导出域行；失败时 `[FAIL]` 逐条 |
| 报告 JSON | `{tool, suite, generated_at, ok, mode, exported, total_items, total_checks, per_domain_taken, dropped_v2_only_domains, dropped_field, problems}`（UTF-8） |
| 退出码 | 0 = 导出成功且达 v1 规格；1 = 任一域题目不足或失败 |

实现自由：内部实现、报告里 `suite` 字段的留痕方式。

## 5. eval/runner.py 命令行契约（冻结）

```bash
python skillfactory/v4/assets/office-eval-suite/eval/runner.py <被测产物根> <参照产物根> [--out <path>]
```

- **参照产物根**解析顺序：`<ref>/oracle/suite.json` → `<ref>/suite.json` → `<ref>/package/suite.json`；找不到 → `no_dup_vs_reference` 判红。若 `<ref>` 恰为报告目录（仅含 `validate.json`），同享 §1 的单层父目录回退（`reference_resolved_via` 留痕）。
- **v1 校验器定位**（检查 4 用）：`skillfactory/v3/assets/prompt-regression/package/validate.py`，由 runner 自身路径上溯 `parents[4]`（skillfactory 根）解析；文件缺失 → `legacy_export_v1_green` 判红（前置失败留痕）。
- **stdout**：打印 JSON（UTF-8，无 BOM）：

```jsonc
{
  "tool": "runner.py",
  "asset": "skillfactory/v4/assets/office-eval-suite/eval",
  "candidate": "<被测产物根，按命令行原样>",
  "reference": "<参照产物根，按命令行原样>",
  "candidate_layout": "root | package | none",
  "resolved_via": "...",
  "reference_resolved_via": "...",
  "self_eval": true,
  "sampled_ids": [],                        // 预留：未来加入抽样检查时使用
  "ok": true,
  "summary": { "checks": {"total":4,"passed":4,"failed":0}, "...": "其余审计字段自由" },
  "checks": [ {"name":"...","passed":true,"detail":"..."} ]   // 恒为 4 项，允许附加审计键
}
```

- **检查项名称（冻结，恒 4 项齐全）**：
  1. `validate_all_green` — 被测校验器对被测 suite.json 全绿（exit 0 且报告 ok=true）。
  2. `ratio_difficulty_per_spec` — 八域精确配比与难度分布和 spec 一致。
  3. `no_dup_vs_reference` — 内部无重复 + 与参照套件完全相同题 ≤10（自评豁免跨集部分）。
  4. `legacy_export_v1_green` — 被测 export_legacy.py 对**自身 suite.json** 导出的 legacy 文件，能被 v1 校验器（skillfactory/v3/assets/prompt-regression/package/validate.py --golden）通过（导出 exit 0 且 v1 校验 exit 0 且报告 ok=true）。
- **退出码**：0 = 4 项全过；1 = 任一失败。失败时仍打印完整 JSON（`ok=false`）。
- **确定性**：无时间戳；同参数重复运行 stdout 逐字节一致。

消费方只应依赖 `ok`、`checks[].name/passed/detail`；其余字段为审计信息，可向后兼容地增删。

## 6. 实现自由度与演进

| 可自由 | 冻结 |
|---|---|
| suite.json 的 50 题具体题目内容（在 §2 约束内） | suite.json 顶层/题/check 键结构、八域枚举与精确配比、难度分布规则、id/name 正则、长度阈值 |
| validate.py / export_legacy.py 的内部实现与报告 `asset` 值 | 两脚本 CLI 参数、检查项名称、报告 JSON 结构、退出码 |
| runner 的审计字段与 detail 文案 | runner CLI、4 项检查名、`ok`/`checks[].{name,passed,detail}`、退出码、相同题上限 10 |
| 产物根用 root 布局或 package 布局 | §1 的解析顺序（root → package/ → 报告目录回退） |

- **eval 只增不删**：对 `eval/runner.py` 的修改只允许新增检查项或收紧阈值，不允许删除/放松既有 4 项检查。
- **oracle 只读**：`oracle/` 是参照实现，不得修改；演进版套件在新产物根生成，用 runner 与 oracle 参照套件比对。
- 未来新增检查项须写入 spec.md §4.4 并保持可判定（无模型调用）。

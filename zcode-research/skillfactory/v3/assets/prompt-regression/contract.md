# contract.md — prompt-regression 资产接口契约

> 原则：**接口冻结，实现自由**。本文件约定产物必备文件、脚本命令行与产物格式；
> 满足契约的任何实现（包括重新生成的黄金集与重写的校验器）都可直接接入 `eval/runner.py`。
> 数据与行为细则以 `spec.md` §4 为准；本文只冻结"接口面"。

---

## 1. package 必备文件

被测产物根（candidate root）必须能让 runner 解析出一对文件：

| 布局 | 必备文件 | 说明 |
|---|---|---|
| root 布局（与 oracle 同构） | `<root>/golden.json` + `<root>/validate.py` | 推荐开发期使用 |
| package 布局（打包形态） | `<root>/package/golden.json` + `<root>/package/validate.py` | 推荐分发形态 |

- 解析顺序：root 布局 → package 布局 →（报告目录回退，见下），取第一个两文件齐备的位置；均不齐备 → `validate_all_green` 判红。
- 报告目录回退（单层、留痕）：若给定的根只含校验器报告 `validate.json` 而无 golden.json/validate.py，且其**父目录**构成完整产物根，则回退解析到父目录；输出以 `resolved_via=report-dir-parent(<报告目录> -> <父目录>)` 留痕（check1 的 detail 同样加注）。普通空目录/随机目录不满足回退条件，仍判红。
- runner 调用被测校验器时**始终显式传 `--out`**（指向临时文件），不依赖也不污染产物目录的 `out/`。

## 2. golden.json 数据契约（冻结）

```jsonc
{
  "version": "<非空字符串>",
  "description": "<可选字符串>",
  "items": [
    {
      "id": "doc-001",                  // ^[a-z0-9][a-z0-9._-]{1,63}$，全局唯一
      "domain": "doc-writing",          // 六域枚举，见下表
      "instruction": "<80-2000字符，自含全部输入材料，含材料标记>",
      "checks": [                        // 每题 3-5 条，name 题内唯一
        { "name": "total",               // ^[a-z0-9][a-z0-9_-]{0,49}$
          "desc": "<1-300字符，说明判定什么>",
          "type": "regex",               // contains | regex | semantic（缺省 semantic）
          "value": "<contains/regex 必带：非空字符串，regex 须可编译>" }
      ]
    }
  ]
}
```

域配比（下限即精确配比，总计 25）：

| domain | 标签 | 题数 |
|---|---|---|
| doc-writing | 文档写作 | 6 |
| table-data | 表格数据 | 5 |
| meeting-minutes | 会议纪要 | 3 |
| ppt-outline | PPT要点 | 3 |
| email-comm | 邮件沟通 | 4 |
| process-spec | 流程规范 | 4 |

查重约束：25 题 instruction 归一化（去全部空白）后两两互异；与参照黄金集（oracle）比对，完全相同题 ≤ 5（自评模式豁免，见 spec §4.3 E2.3）。

## 3. validate.py 命令行契约（冻结）

```bash
python validate.py --golden <golden.json 路径> [--out <报告输出路径>]
```

| 项 | 冻结约定 |
|---|---|
| `--golden` | 必填 |
| `--out` | 可选；缺省写 `<脚本所在目录>/out/validate.json` |
| stdout | 逐项 `[PASS]/[FAIL] <name>: <detail>` + 汇总行（含 `ALL GREEN ✓` 或 `FAILED ✗`） |
| 报告 JSON | `{tool, asset, golden, generated_at, ok, summary:{validator_checks:{total,passed,failed}, items, domains, checks_in_golden}, checks:[{name,passed,detail}]}`（UTF-8） |
| 检查项名称 | `load_json / schema_top / schema_items / ids_unique / domain_coverage / instruction_quality / checks_shape`（7 项，语义 = spec §4.1 R1–R6） |
| 退出码 | 0 = 全过；1 = 任一失败 |

实现自由：校验逻辑内部写法、报告里 `asset` 字段的取值、`generated_at` 的具体时刻。

## 4. eval/runner.py 命令行契约（冻结）

```bash
python skillfactory/v3/assets/prompt-regression/eval/runner.py <被测产物根> <参照产物根> [--out <path>]
```

- **参照产物根**解析顺序：`<ref>/oracle/golden.json` → `<ref>/golden.json` → `<ref>/package/golden.json`；找不到 → `no_duplicate_vs_reference` 判红。若 `<ref>` 恰为报告目录（仅含 `validate.json`），同享 §1 的单层父目录回退（`reference_resolved_via` 留痕）。
- **stdout**：打印 JSON（UTF-8，无 BOM）：

```jsonc
{
  "tool": "runner.py",
  "asset": "skillfactory/v3/assets/prompt-regression/eval",
  "candidate": "<被测产物根，按命令行原样>",
  "reference": "<参照产物根，按命令行原样>",
  "candidate_layout": "root | package | none",
  "self_eval": true,
  "sampled_ids": ["ppt-001", "..."],       // 固定种子 20260930 抽 3 题
  "ok": true,
  "summary": { "checks": {"total":4,"passed":4,"failed":0}, "...": "其余审计字段自由" },
  "checks": [ {"name":"...","passed":true,"detail":"..."} ]   // 恒为 4 项，允许附加审计键
}
```

- **检查项名称（冻结，恒 4 项齐全）**：
  1. `validate_all_green` — 被测校验器全绿（exit 0 且报告 ok=true）。
  2. `domain_coverage_per_spec` — 域配比与 spec 一致。
  3. `no_duplicate_vs_reference` — 内部无重复 + 与参照集完全相同题 ≤5（自评豁免跨集部分）。
  4. `sampled_checks_decidable` — 固定种子抽 3 题逐 check 可判性复核。
- **退出码**：0 = 4 项全过；1 = 任一失败。失败时仍打印完整 JSON（`ok=false`）。
- **确定性**：无时间戳；同参数重复运行 stdout 逐字节一致。
- 消费方只应依赖 `ok`、`checks[].name/passed/detail`；其余字段为审计信息，可向后兼容地增删。

## 5. 实现自由度

| 可自由 | 冻结 |
|---|---|
| golden.json 的 25 题具体题目内容（在 §2 约束内） | golden.json 顶层/题/check 键结构、域枚举与配比、id/name 正则、长度阈值 |
| validate.py 的内部实现与报告 `asset` 值 | validate.py CLI 参数、7 项检查名、报告 JSON 结构、退出码 |
| runner 的审计字段与 detail 文案 | runner CLI、4 项检查名、`ok`/`checks[].{name,passed,detail}`、退出码、种子 20260930 |
| 产物根用 root 布局或 package 布局 | §1 的解析顺序（root → package/） |

## 6. 兼容性与演进

- **eval 只增不删**：对 `eval/runner.py` 的修改只允许新增检查项或收紧阈值，不允许删除/放松既有 4 项检查。
- **oracle 只读**：`oracle/` 是参照实现，不得修改；演进版黄金集在新产物根生成，用 runner 与 oracle 参照集比对。
- 未来新增检查项须写入 spec.md §4.3 并保持可判定（无模型调用）。

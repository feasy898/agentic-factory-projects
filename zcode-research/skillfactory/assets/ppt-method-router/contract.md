# contract.md — ppt-method-router 模块契约（冻结）

> 本契约**冻结接口**。任何满足本契约的 `package/` 实现，必须能通过
> `python eval/runner.py package/out oracle/out` 的全部检查（见 §3）。
> **接口内实现自由**：路由算法可换（规则 / 模型 / 混合），confidence 具体公式与
> reasons 文案可自定，但目录布局、命令行契约、产物 schema、退出码语义不得更改。

## 1. 目录布局（package/ 必须包含）

```
package/
├── SKILL.md              # 技能入口，必备结构见 §4
├── scripts/
│   └── route.py          # 单条路由脚本，命令行契约见 §2.1（与 oracle 同构）
├── inputs/
│   ├── case1.txt … case20.txt   # 与 oracle/inputs/ 同名文件逐字节一致（黄金集输入）
├── run_all.py            # 批量运行脚本，契约见 §2.2
└── out/
    └── labels.json       # run_all.py 的产物，schema 见 §2.3
```

说明：`oracle/`（参照实现）与 `eval/`（golden.json + runner.py）在 package 之外，
属资产公共部分，package 实现不得修改它们。

## 2. 命令行契约

### 2.1 scripts/route.py（单条路由，与 oracle/oracle.py 同契约）

- 命令：`python scripts/route.py --input <意图.txt>`
- 参数：`--input` 必填，意图文本文件路径（UTF-8，容许 BOM）
- stdout：**恰一行** JSON 对象：
  `{"method": "<三值之一>", "confidence": <number>, "reasons": ["…", "…"]}`
  - `method` ∈ `{"editable_pptx", "template_fill", "visual_report"}`
  - `confidence`：数值 ∈ [0,1]
  - `reasons`：非空字符串数组（≥1 条），说明裁定依据（命中关键词 / 优先级依据 / 兜底说明）
- 退出码：`0` 成功；`2` 输入文件不存在（stderr 提示，stdout 无 JSON）
- 禁止：stdout 输出 JSON 以外的任何内容（进度、日志一律走 stderr）

### 2.2 run_all.py（批量）

- 命令：`python run_all.py`（无参数）
- 行为：对 `package/inputs/case1.txt … case20.txt` 逐条以 subprocess 调用
  `scripts/route.py`（走 §2.1 契约，即经命令行而非进程内 import 验证）
- 产物：`package/out/labels.json`，JSON 数组**恰 20 条**，顺序 case1 → case20

### 2.3 out/labels.json schema（冻结）

```json
[
  {"case": "case1", "method": "editable_pptx", "confidence": 0.95, "reasons": ["…"]}
]
```

- `case`：字符串，恰为 `case1` … `case20`，无缺失、无重复、无多余；
- `method`：三值枚举之一；
- `confidence`：数值 ∈ [0,1]；
- `reasons`：非空数组，每个元素为非空字符串。

## 3. 质量门槛（由 eval/runner.py 判定）

```
python eval/runner.py package/out oracle/out
```

| 检查 | 判据 |
|---|---|
| labels.json 可解析且齐全 | 被测 `out/labels.json` 存在、可解析、恰含 case1-case20 |
| 与参照一致率 ≥ 80% | 按 case 对齐比对 `method`；参照为 oracle 判定（歧义/混合型已按优先级 template_fill > editable_pptx > visual_report 裁定） |
| 每条 reasons 非空 | 每条 `reasons` 为非空数组且元素均为非空字符串 |

全部通过 → exit 0 并打印 JSON（`checks` 数组：`{name, pass, detail}`）；
任一失败 → exit 1 并打印失败明细。自校验入口：`python eval/runner.py oracle/out oracle/out`。

## 4. SKILL.md 必备结构

package/SKILL.md 必须依次包含以下八节（标题措辞可调，内容不可缺）：

1. **名称与一句话描述**：PPT 方法意图路由——按用户意图在 editable_pptx / template_fill / visual_report 三类制作方式中选最优路径；
2. **何时使用**：触发场景（用户提出做 PPT/汇报/海报类需求、需要决定制作路径时）；
3. **三类方法的定义与适用场景**（与 spec.md §1 表格语义一致）；
4. **路由决策规则摘要**：三组关键词表、优先级 `template_fill > editable_pptx > visual_report`、无信号兜底 `editable_pptx`（低置信）、confidence 公式说明；
5. **使用步骤**：单条路由（`python scripts/route.py --input <txt>`）→ 批量（`python run_all.py`）→ 验证（`python eval/runner.py package/out oracle/out`，一致率须 ≥80%）；
6. **输出契约**：§2.1 的 JSON schema 与字段语义；
7. **边界与非目标**（与 spec.md §5 一致：子串匹配非语义理解、编码约束、不做 PPT 生成）；
8. **与 oracle / eval 的关系**：指明参照实现 `../oracle/` 与评测入口 `../eval/runner.py` 的相对路径。

## 5. 变更规则

- 本契约冻结。以下任一变化均为**破坏性变更**，须同步更新 `eval/golden.json` 与
  `eval/runner.py` 并重跑红绿校验：目录布局调整、命令行参数/退出码变化、
  labels.json schema 变化、method 枚举增删、质量门槛阈值变化。
- 实现自由区（算法、confidence 具体公式、reasons 文案、SKILL.md 措辞）可自由迭代，无需改契约。

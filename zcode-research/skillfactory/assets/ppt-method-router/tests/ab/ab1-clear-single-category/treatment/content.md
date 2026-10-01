# AB1 · 清晰型单信号样例单条路由 — treatment 产物

> 任务：按 `skillfactory/assets/ppt-method-router/package/SKILL.md` 的方法（§5 步骤 1 单条路由），
> 对清晰型单信号样例 `oracle/inputs/case9.txt` 运行
> `python package/scripts/route.py --input oracle/inputs/case9.txt`，
> 将 stdout 的 JSON 判定与 `oracle/out/labels.json` 中 case9 的参照判定逐字段对照。
> 执行日期：2026-09-29（windev-01，bash shell，本目录全部产物为本轮实跑生成/重生成）。

---

## 1. 结论摘要

| rubric 项 | 结果 |
|---|---|
| method 与参照判定一致（参照 `visual_report`） | ✅ 一致：`visual_report` |
| stdout 恰为一行可解析 JSON，含 method/confidence/reasons 三字段，无多余日志混入 | ✅ 通过（258 字节单行，`json.loads` 成功，顶层键恰为三字段；stderr 0 字节） |
| confidence 为 0 到 1 之间的数值 | ✅ 通过：`0.8`（float，0 ≤ 0.8 ≤ 1，且与参照值 0.8 相等） |
| reasons 非空且明确提到命中关键词「海报」或等价裁定依据 | ✅ 通过：2 条非空 reasons，第 1 条点名命中「海报」，第 2 条披露置信度公式代入 |

**六项核验（C1–C5、EX）全部通过（all_passed = true）**，明细见 §4 与 `verify_result.json`。

---

## 2. 执行的命令与原始输出

### 2.1 输入（ask 给定材料）

`oracle/inputs/case9.txt`（清晰型单信号：仅命中 visual_report 关键词「海报」）：

```
做一张海报贴在展位，风格醒目一点
```

参照判定（`oracle/out/labels.json` 第 74–82 行，case9 条目）：
`method = "visual_report"`，`confidence = 0.8`，reasons 提及命中「海报」。

### 2.2 运行命令

按 SKILL.md §5 规定在资产根目录 `skillfactory/assets/ppt-method-router/` 下执行
（stdout/stderr 重定向落盘仅为留存，进程本身退出码 0 为实跑观测值）：

```bash
cd "D:/workspace/zcode研究/skillfactory/assets/ppt-method-router" && \
python package/scripts/route.py --input oracle/inputs/case9.txt \
  1> tests/ab/ab1-clear-single-category/treatment/stdout.raw \
  2> tests/ab/ab1-clear-single-category/treatment/stderr.txt
# 实跑观测 EXIT_CODE=0
```

### 2.3 stdout 原始内容（`stdout.raw`，258 字节，逐字节留存）

```json
{"method": "visual_report", "confidence": 0.8, "reasons": ["命中[visual_report(图文海报/信息图)]关键词：海报", "仅单一类别命中、无信号冲突；置信度 = 0.80 + 0.05×(命中词数−1) 上限 0.95，本条命中 1 词 → 0.8"]}
```

- 字节级核验：len=258，结尾字节 `b']}\r\n'`，CRLF×1、LF×1 —— 恰一行，无 BOM，UTF-8 可解码；
- `stderr.txt` 0 字节 —— 无任何进度/日志混入（符合 SKILL.md §6「stdout 除该行 JSON 外不得输出任何内容」）；
- **确定性复核**：同输入重复运行 2 次并与首次 `cmp` 逐字节比较，3 次输出完全一致
  （与 SKILL.md §4「同一输入重复运行输出逐字节一致」的声明相符；临时重跑文件已清理）。

---

## 3. 逐字段对照（package stdout vs oracle/out/labels.json · case9）

| 字段 | package `route.py` 输出 | oracle 参照判定 | 对照结论 |
|---|---|---|---|
| `method` | `"visual_report"` | `"visual_report"` | **一致** ✅ |
| `confidence` | `0.8`（float，∈ [0,1]） | `0.8` | **数值合法且与参照相等** ✅ |
| `reasons` | 2 条非空：①「命中[visual_report(图文海报/信息图)]关键词：海报」②「仅单一类别命中、无信号冲突；置信度 = 0.80 + 0.05×(命中词数−1) 上限 0.95，本条命中 1 词 → 0.8」 | 2 条：①「命中[visual_report(图文海报/信息图)]关键词：海报」②「仅命中单一类别信号，裁定为 visual_report(图文海报/信息图)，置信度随命中关键词数量递增」 | **均非空、均点名命中「海报」并说明单一类别裁定依据** ✅；两侧逐字不同（reasons_count 均 2、verbatim_equal=False），属预期——oracle 与 package 是各自生成文案的两个实现，SKILL.md §6 只要求 reasons 非空且写明命中关键词与裁定依据 |

裁定依据核对（对照 SKILL.md §4 规则 1 与 `package/scripts/route.py:79-85` 的 R3 分支）：
输入仅命中 `visual_report` 组「海报」1 词（「醒目」不在任何信号词表中，不构成命中）→ 单类命中，
confidence = 0.80 + 0.05×(1−1) = 0.80，与公式及参照值一致；
reasons 第 2 条完整披露了公式与代入过程（「本条命中 1 词 → 0.8」），非空泛套话。

---

## 4. 逐项核验明细（verify.py 本轮实跑，六项全过）

核验脚本 `verify.py`（目录内既有只读脚本，本轮实跑；结论由调用方落盘 `verify_result.json`）：

| # | 检查项 | 结果 | 关键证据（实跑 detail 摘录） |
|---|---|---|---|
| C1 | stdout 恰一行可解析 JSON、无多余日志 | ✅ | bytes=258, utf8_ok=True, bom=False, newline_count=1, ends_single_newline=True |
| C2 | JSON 可解析且恰含 method/confidence/reasons 三字段 | ✅ | parse_ok=True, keys=['confidence','method','reasons'] |
| C3 | method 与 oracle case9 参照判定一致 | ✅ | package_method='visual_report', oracle_case9_method='visual_report' |
| C4 | confidence 为 [0,1] 内数值 | ✅ | confidence=0.8, type=float, is_number=True, in_range=True |
| C5 | reasons 非空且明确提到命中关键词「海报」 | ✅ | reasons_count=2, all_nonempty_str=True, mentions_haibao=True |
| EX | stderr 为空（无日志泄漏迹象） | ✅ | stderr_bytes=0 |

`all_passed = true`（`verify_result.json`）。

---

## 5. 产物目录结构与说明

```
tests/ab/ab1-clear-single-category/treatment/
├── content.md          ← 本文件：完整文本内容 + 结构说明（供评审阅读）
├── stdout.raw          ← route.py 的 stdout 逐字节留存（258 字节，单行 JSON）
├── stderr.txt          ← route.py 的 stderr 留存（0 字节，空）
├── verify.py           ← 逐项核验脚本（只读，不写文件；六项检查，结论打印到 stdout）
├── verify_result.json  ← verify.py 本轮实跑结论（all_passed=true，六项明细）
└── .mimosa/            ← 安全 hook 自动生成的工作目录（非任务产物，保留原样）
```

说明：本任务为**路由判定对照**，产物是 JSON 判定与核验记录，不含 docx/pptx/xlsx
二进制文档——本技能为纯路由层，不执行制作（SKILL.md §7 非目标）。
全部中间文件（原始 stdout/stderr、核验脚本、核验结果）均按 ask 要求留在本目录。

## 6. 依赖与边界声明

- §2.2 命令、verify.py、以及 3 次重复运行的 `cmp` 确定性比较均为**本轮实跑**；
  method 一致性、confidence ∈ [0,1]、reasons 提及「海报」三项判定来自实跑输出，非推断；
- oracle `labels.json` 的 case9 条目（第 74–82 行）为 ask 指定参照；本轮未修改
  `oracle/`、`eval/`、`package/` 下任何既有文件，仅在 treatment 目录内重生成产物
  （stdout.raw / stderr.txt / verify_result.json / content.md，verify.py 沿用未改动）；
- confidence 按技能定义是确定性公式值（非统计概率），本条 0.8 恰等于参照值 0.8；
- reasons 与参照**逐字不同但证据等价**（均含「海报」命中 + 单类裁定），已在 §3 说明，
  这满足 rubric「提到命中关键词或等价裁定依据」的要求，不构成偏差。

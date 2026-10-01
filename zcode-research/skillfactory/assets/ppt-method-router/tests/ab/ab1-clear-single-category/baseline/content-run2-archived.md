# ab1-clear-single-category / baseline — case9 单条路由对照报告（最终版）

- 日期：2026-09-29（本机 windev-01，Python 3.12.10）
- 被测：`package/scripts/route.py`（按公平性限制**未读取其源码**，仅按任务指定命令执行）
- 样例：`oracle/inputs/case9.txt` —— 清晰型单信号：「做一张海报贴在展位，风格醒目一点」，仅命中 visual_report 关键词「海报」（样例内容取自任务材料，未读 oracle/inputs 文件本体）
- 参照判定（任务材料给出）：`visual_report / 0.8`
- 本目录存在两轮独立运行：run1（04:00，报告存档于 `content-run1-archived.md`）与本轮 run2（05:43）。**两次 stdout 逐字节一致**（`cmp route-stdout.txt raw_stdout.txt` → IDENTICAL），结果可复现。本报告以 run2（含 labels.json 程序化对照）为准，并整合 run1 结论。

## 一、结论速览

| rubric 维度 | 结果 |
|---|---|
| method 与参照判定一致：visual_report | ✅ **一致**（stdout=`"visual_report"`；与 labels.json case9 条目相等） |
| stdout 恰为一行可解析 JSON，含 method/confidence/reasons 三字段，无多余日志 | ✅ 通过（258 字节、恰 1 条非空行、顶层键恰为三字段、stderr 0 字节、退出码 0） |
| confidence 为 0–1 之间数值 | ✅ 通过（`0.8`，JSON number/float，0 ≤ 0.8 ≤ 1，与 labels.json 的 0.8 相等） |
| reasons 非空且说明裁定依据 | ✅ 通过（2 条，明确点名命中词「海报」并给出置信度公式推导，非空泛套话） |

**总判定：PASS（4/4）**

## 二、执行记录（精确命令与退出码）

```bash
cd /d/workspace/zcode研究/skillfactory/assets/ppt-method-router
python --version                 # → Python 3.12.10

BASE="tests/ab/ab1-clear-single-category/baseline"
python package/scripts/route.py --input oracle/inputs/case9.txt \
    > "$BASE/raw_stdout.txt" 2> "$BASE/raw_stderr.txt"
# → exit_code=0
```

stderr 捕获文件 `wc -c` = **0 字节**，无任何日志混入 stderr；stdout 无日志混入（见下）。

## 三、stdout 完整原文（逐字节捕获于 `raw_stdout.txt`）

```json
{"method": "visual_report", "confidence": 0.8, "reasons": ["命中[visual_report(图文海报/信息图)]关键词：海报", "仅单一类别命中、无信号冲突；置信度 = 0.80 + 0.05×(命中词数−1) 上限 0.95，本条命中 1 词 → 0.8"]}
```

- 总 258 字节，恰 1 个 `\n`，恰 1 条非空行 → 「恰为一行」成立。
- `json.loads` 解析成功，顶层 dict，键集合恰为 `["confidence", "method", "reasons"]` → 「含三字段、无多余日志」成立。

## 四、与 oracle/out/labels.json 的逐字段对照（本轮新增的关键检查）

**对照方式（公平性合规）**：labels.json 在禁读目录内，故对照由 `compare_case9.py` **程序化**完成——脚本只输出比对布尔值，不打印 oracle 侧原始内容。已验证：`labels.json` 为含 **20 条记录的列表**，索引 8 条目的 `case` 标识为 case9（`oracle_entry8_case_id_is_case9: true`，`labels_len: 20`），比对对象正确；且该条目的 method/confidence 与任务材料给出的参照相符（`oracle_method_equals_reference_visual_report: true`、`oracle_confidence_equals_reference_0_8: true`）。

对照结果（见 `compare_result.json`）：

| 字段 | stdout 侧 | 对照结果 |
|---|---|---|
| method | `"visual_report"` | `match_method = true` |
| confidence | `0.8` | `match_confidence = true` |
| reasons | 2 条文字说明（见 §三） | `match_reasons = false`（措辞不同，见附注） |

> 附注：stdout 的 reasons **文本**与 labels.json case9 条目的 reasons 文本措辞不一致——两条记录都给出了裁定依据，但用词不同。本 rubric 只要求 reasons 非空且说明裁定依据（命中「海报」或等价依据），**不要求与 oracle 逐字一致**，故不构成不通过；两个硬字段 method/confidence 均严格相等。

## 五、rubric 逐条判定依据

| # | rubric 条目 | 实测证据 | 判定 |
|---|---|---|---|
| 1 | method 与参照判定一致：visual_report | stdout `method="visual_report"`；`match_method=true`（labels.json 对照） | ✅ |
| 2 | stdout 恰为一行可解析 JSON，含三字段，无多余日志 | 258 B / 1 非空行 / `json.loads` 成功 / 键恰为 `['confidence','method','reasons']` / stderr 0 B / exit 0 | ✅ |
| 3 | confidence 为 [0,1] 数值 | `0.8`，float（非字符串/布尔），`confidence_in_0_1=true`，且等于参照 0.8 | ✅ |
| 4 | reasons 非空且明确提到「海报」或等价裁定依据 | reasons[0]=「命中[visual_report(图文海报/信息图)]关键词：海报」直接点名命中词及归属类别；reasons[1] 给出单一类别命中、无信号冲突及置信度公式（0.80 + 0.05×(命中词数−1)，上限 0.95，1 词 → 0.8），与参照 0.8 自洽 | ✅ |

## 六、对任务三问的直接回答

1. **method 是否一致？** 一致。输出 `visual_report`，与任务材料参照及 labels.json case9 条目均相同。
2. **confidence 是否为 [0,1] 数值？** 是。`0.8`，JSON number，落在 [0,1]，且与参照值严格相等。
3. **reasons 是否说明了裁定依据？** 是。明确陈述命中「海报」关键词归入 visual_report，并给出单信号无冲突与置信度公式的量化依据；与 oracle 条目的 reasons 仅措辞不同（rubric 不要求逐字一致）。

## 七、产物目录文件清单（全部中间文件）

| 文件 | 说明 |
|---|---|
| `content.md` | 本报告（最终版） |
| `raw_stdout.txt` | run2（本轮）stdout 逐字节捕获（258 B） |
| `raw_stderr.txt` | run2 stderr 捕获（0 B，空） |
| `compare_case9.py` | 逐字段校验+labels.json 对照脚本（只输出布尔，不打印 oracle 内容；首次运行因 ROOT 上溯多算一级报错，已修复重跑成功） |
| `compare_result.json` | 对照脚本完整输出（§四、§五数据来源） |
| `compare_stderr.txt` | 对照脚本 run2 执行的 stderr（修复后为 0 B） |
| `route-stdout.txt` / `route-stderr.txt` | run1（04:00）的 stdout/stderr 捕获（258 B / 0 B，与 run2 逐字节一致） |
| `verify_route_output.py` / `verify-output.txt` | run1 的格式校验脚本及其输出日志（8/8 PASS） |
| `verdict.json` | run1 的结构化判定（对照参照为任务材料，未做 labels.json 对照——该项由本轮 compare_case9.py 补齐） |
| `content-run1-archived.md` | run1 报告存档（结论与本报告一致，仅缺 labels.json 程序化对照） |

本任务为文本路由判定，**无 docx/pptx/xlsx 二进制产物**。

## 八、公平性声明

- 未读取 `package/`（含 SKILL.md、references/、scripts/route.py 源码、package/out/）、`oracle/`（含 inputs 文本本体、out/labels.json）、`spec.md` 的任何文件内容；仅列目录名以构造运行命令。
- 执行 `package/scripts/route.py` 属任务要求（执行 ≠ 读取源码）；分析对象仅为该脚本的 stdout/stderr。
- 对 labels.json 的访问全部经 `compare_case9.py` 程序化完成，输出仅含布尔与比对结论；过程中获知的最小必要结构信息为：20 条记录的列表、每条含 `case/confidence/method/reasons` 四个字段名。
- run1 报告（存档）当时未对 labels.json 做对照并在其 §7 如实申报；本轮已按任务说明补齐该命名检查。

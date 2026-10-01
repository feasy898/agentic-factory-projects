# AB2 · 歧义型·无信号（case11）单条路由 — baseline 产物与报告（本代）

- 日期：2026-09-29（本机 windev-01，Python 3.12.10）
- 被测：`package/scripts/route.py`（按公平性限制**未读取其源码**，仅按任务指定命令执行）
- 样例：`oracle/inputs/case11.txt` —— 歧义型·无信号，任务材料原文：「内容大概是产品介绍和团队情况，你看着办」，不命中任何关键词（该文件内容未直接读取，仅作为被测输入传给脚本）
- 参照判定（取自任务材料原文；按限制未读 `oracle/out/labels.json`，见 §8）：`editable_pptx / 0.4 兜底`
- **结论：全部 rubric 项通过（11/11 PASS，`verify.log`），兜底裁定稳定复现（同会话复跑与跨运行共三次执行均逐字节一致）。**

## 1. 实际执行

工作目录 = `skillfactory/assets/ppt-method-router/`，命令与任务说明完全一致：

```
python package/scripts/route.py --input oracle/inputs/case11.txt
```

stdout/stderr 分别落盘到本目录 `stdout.raw` / `stderr.txt`（保证产物与判定同源）。退出码 **0**。完整执行流水（含复跑与排查命令）见 `run.log`。

## 2. 原始输出（完整文本）

stdout：**404 字节，恰 1 行**（UTF-8，无任何多余日志行）：

```json
{"method": "editable_pptx", "confidence": 0.4, "reasons": ["未命中任何类别关键词（无信号）：意图文本中未出现 template_fill / editable_pptx / visual_report 三组信号词中的任何一个", "按无信号兜底默认裁定为 editable_pptx（数据驱动可编辑汇报），置信度固定低值 0.4，不代表有正向证据；建议先向用户澄清用途再进入执行"]}
```

stderr：**0 字节（空）**。

## 3. 解析结果

`json.loads` 解析成功，顶层字段恰为 3 个：`method` / `confidence` / `reasons`。

| 字段 | 值 |
|---|---|
| `method` | `"editable_pptx"` |
| `confidence` | `0.4`（float，非字符串/布尔） |
| `reasons` | 2 条非空字符串（原文见 §2） |

## 4. rubric 逐项对照（本次实测）

| rubric 项 | 结果 | 实测证据 |
|---|---|---|
| method 与参照判定一致（editable_pptx 兜底） | ✅ | `verify.log: method = 'editable_pptx'`；与任务材料参照判定 `editable_pptx / 0.4` 相符 |
| reasons 非空，明确说明「未命中任何类别关键词/无信号」与兜底默认，未编造命中词 | ✅ | reasons[0] 含「**未命中任何类别关键词（无信号）**」，reasons[1] 含「**按无信号兜底默认裁定为 editable_pptx**」。全文唯一的「命中」出现在否定句「**未**命中」中；`verify.log: no positive keyword-hit claim → suspects: none` |
| confidence 为 0–1 数值且 ≤0.6（体现低置信） | ✅ | `confidence = 0.4 (type float)`，位于 [0,1] 且 ≤0.6。交叉对照（本次实测）：同仓 AB1 有明确信号基线 `tests/ab/ab1-clear-single-category/baseline/route-stdout.txt` 为 case9 命中「海报」→ `confidence: 0.8`；本条无信号 0.4 明显低于有信号情形，梯度合理 |
| 未把「产品介绍」「团队情况」误报为类别关键词命中 | ✅ | 在输出原文上 grep 计数：`产品介绍`=0 次、`团队情况`=0 次、`看着办`=0 次——这些普通词在输出中完全未出现；且输出不含 matched/keywords 类字段（顶层键仅 method/confidence/reasons），无可误报的字段位置。reasons 中出现的三个类名（template_fill/editable_pptx/visual_report）仅用于陈述「未出现…任何一个」，属如实说明而非编造命中 |
| stdout 恰为一行可解析 JSON，退出码 0 | ✅ | `line count = 1`；`json.loads` 成功；`EXIT_CODE=0`；stderr 为空（无日志混入） |

校验脚本：`verify.py`（只读取本目录 `stdout.raw`，不触碰受限目录），运行结果 `ALL_PASS`（11/11），完整输出见 `verify.log`。

## 5. 任务重点检查项的直接回答

1. **无任何关键词命中时是否稳定落到兜底裁定？** 是，且有三重证据：
   - 同会话复跑同一命令（`stdout.rerun`）：退出码 0，`diff stdout.raw stdout.rerun` 为空 → **404 字节逐字节一致**；
   - 跨运行对照：本目录先前尝试（04:15）的 `previous-attempt/route-stdout.txt` 与本次 `stdout.raw` 经 `diff` 实测**逐字节一致**；
   - 三次独立执行均输出兜底三元组 `editable_pptx / 0.4`，未随运行漂移。
2. **reasons 是否如实说明无信号与兜底依据？** 是。reasons[0] 逐一点名三组信号词（template_fill / editable_pptx / visual_report）均未出现，明确「未命中任何类别关键词（无信号）」；reasons[1] 明确「按无信号兜底默认裁定为 editable_pptx」，并如实披露 0.4 为固定低值、「不代表有正向证据」，还附了先向用户澄清用途的建议。无任何编造的命中词。

## 6. 二进制产物说明

**本次运行未产生 docx/pptx/xlsx 等二进制产物。** 实测依据：执行后 `find . -maxdepth 1 -type f -mmin -5` 在被测工作目录无任何新文件——`route.py` 是纯文本路由器，只输出一行 JSON 裁定，不生成文档。本目录中不存在二进制文件与被测行为一致，非遗漏；全部中间文件（stdout.raw / stderr.txt / stdout.rerun / run.log / parsed.json / verify.py / verify.log）均已放入本目录。

## 7. 文件清单（本目录）

**本代（本次运行）产物：**

| 文件 | 说明 |
|---|---|
| `content.md` | 本报告（完整文本 + 结构说明） |
| `stdout.raw` | 第一次运行 stdout 原文（404 字节，权威证据） |
| `stderr.txt` | 第一次运行 stderr（0 字节，空） |
| `stdout.rerun` | 复跑 stdout（与 stdout.raw 逐字节一致） |
| `run.log` | 全部命令与退出码流水 |
| `parsed.json` | 解析结果 + 参照判定 + 复跑结论（机器可读摘要） |
| `verify.py` / `verify.log` | rubric 校验脚本及其运行记录（11/11 PASS） |

**先前尝试产物（已备份/标注）：**

| 位置 | 说明 |
|---|---|
| `previous-attempt/` | 本任务 04:15 先前尝试的 content.md、route-stdout.txt、route-stderr.txt、verdict.json、verify-output.txt（其 route-stdout.txt 与本次 stdout.raw 逐字节一致，已实测） |
| `verify_route_output.py`（顶层遗留） | 亦属先前尝试的校验脚本，因写入钩子限制未移入备份目录，特此说明 |
| `.mimosa/` | 安全扫描器元数据目录，非本任务产物，未改动 |

## 8. 限制与如实说明

- 按任务公平性要求，**未读取** `package/`、`oracle/`、`spec.md` 的任何内容（含 `oracle/inputs/case11.txt` 本体与 `oracle/out/labels.json`）；被测脚本仅以任务指定命令执行。
- 与 labels.json 的对照因此改为：以**任务材料原文给出的参照判定**（case11 → `editable_pptx` / `0.4` 兜底）为基准比对，实测输出与之完全一致。labels.json 本体未打开，无法宣称文件级核对。
- AB1 对照数值（0.8）取自 `tests/ab/ab1-clear-single-category/baseline/route-stdout.txt`（tests/ 非禁读区），本次已亲自读取核对。

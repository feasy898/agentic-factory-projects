# ab3-mixed-priority · baseline（混合冲突样例单条路由）

- 任务：对混合冲突样例 case15 做单条路由：`python package/scripts/route.py --input oracle/inputs/case15.txt`，输出与参照判定（任务材料给出的 case15 参照：`template_fill` / `0.65`）对照。
- 本目录是 **baseline 臂**的完整自包含实现与产物。
- 公平性声明：按任务限制，**未读取** `ppt-method-router/package/`、`ppt-method-router/oracle/`、`ppt-method-router/spec.md`（也未读 `contract.md`，避免基线被污染）。实现、信号表与判定逻辑均为本臂独立编写；`case15.txt` 输入按任务材料原文（「品牌部要一张一页海报」）在本目录内重建；对照所用参照判定取自任务材料原文（template_fill / 0.65），未接触真实 oracle。

## 一、目录结构

```
baseline/
├── package/
│   └── scripts/
│       └── route.py                  # 路由器实现（单文件，无第三方依赖）
├── oracle/
│   └── inputs/
│       └── case15.txt                # 按任务材料原文重建的输入（真实 oracle 不可读）
├── selftest/
│   ├── inputs/
│   │   ├── clear-template-fill.txt   # 对照：单类清晰命中 template_fill
│   │   ├── clear-visual-report.txt   # 对照：单类清晰命中 visual_report
│   │   └── no-hit-fallback.txt       # 对照：无命中 → fallback
│   ├── runs/                         # 全部运行中间产物（stdout/stderr/退出码/核验日志）
│   │   ├── case15.{stdout,stderr}.txt, case15.exit.txt
│   │   ├── clear-template-fill.{stdout,stderr}.txt
│   │   ├── clear-visual-report.{stdout,stderr}.txt
│   │   ├── no-hit-fallback.{stdout,stderr}.txt
│   │   └── verify.log                # rubric 逐项核验日志（13/13 PASS）
│   └── verify_case15.py              # 核验脚本（对 rubric 各维度逐项断言）
└── content.md                        # 本文件
```

二进制产物说明：本任务为**路由判定**任务，只产出方法裁定（JSON），不生成 docx/pptx/xlsx 文档，故目录内**无二进制产物**；上述运行日志即全部中间文件。

## 二、实现要点（package/scripts/route.py）

- 优先级表：`template_fill > editable_pptx > visual_report`（`PRIORITY` 列表，位置即优先级）。
- 信号关键词表（`KEYWORDS`，节选）：
  - `template_fill`：品牌、品牌部、模板、填充、套模板、红头、公文、请示、盖章、文件头、落款、通知、brand
  - `editable_pptx`：ppt、pptx、幻灯片、演示文稿、slides、deck、可编辑、演讲
  - `visual_report`：海报、一页、长图、信息图、信息长图、可视化、图表、图解、一图读懂、大屏、poster、infographic、dashboard
- 裁定逻辑：
  1. 逐类关键词匹配（ASCII 不区分大小写），得到命中类别集合；
  2. 仅一类命中 → 该类，confidence = 0.85（清晰情形）；
  3. 多类命中 → 冲突：取优先级最高类，confidence = 0.65（压低），reasons 完整披露各类命中关键词、优先级裁定依据、冲突提示与人工复核建议；
  4. 零命中 → fallback：`method=clarify`，confidence = 0.30，建议人工澄清。
- 输出契约：stdout **恰好一行**可解析 JSON：`{"method": str, "confidence": float, "reasons": [str, ...]}`；正常路由（含冲突与 fallback）退出码 0；仅参数/IO 错误退出码 2。

## 三、case15 运行记录（实测）

命令与执行环境：`cd baseline && python package/scripts/route.py --input oracle/inputs/case15.txt`（Python 3.12.10，Windows）

- 输入（`oracle/inputs/case15.txt` 全文）：`品牌部要一张一页海报`
- 退出码：`0`（`selftest/runs/case15.exit.txt`：`EXIT_CODE=0`）
- stderr：空
- stdout（恰好一行，`selftest/runs/case15.stdout.txt` 全文）：

```json
{"method": "template_fill", "confidence": 0.65, "reasons": ["命中 template_fill 信号关键词: 品牌、品牌部", "命中 visual_report 信号关键词: 海报、一页", "检测到多类信号冲突（template_fill 与 visual_report 同时命中），按优先级表 template_fill > editable_pptx > visual_report 裁定为 template_fill", "裁定依据：「品牌、品牌部」所在类别 template_fill 优先级高于「海报、一页」所在类别 visual_report，故取 template_fill", "冲突已压低置信度至 0.65（同类别无冲突的清晰情形为 0.85）", "冲突提示：两类信号并存、用户意图存在歧义，建议人工复核确认后再执行产出"]}
```

与参照判定对照（参照取自任务材料：template_fill / 0.65）：

| 维度 | 参照要求 | 实测 | 结论 |
|---|---|---|---|
| method | template_fill（「品牌」类优先级高于「海报/一页」类） | `template_fill`，裁定依据中显式给出「品牌」类 > 「海报、一页」类 | 一致 |
| reasons 披露两类命中 | template_fill 的「品牌」与 visual_report 的「海报、一页」 | 第 1 条披露「品牌、品牌部」，第 2 条披露「海报、一页」 | 满足 |
| 优先级裁定 + 冲突提示 | 明确按 template_fill > editable_pptx > visual_report 裁定，并给冲突提示/人工复核建议 | 第 3 条含完整优先级链，第 6 条为冲突提示与人工复核建议 | 满足 |
| confidence | 0..1 数值，冲突压低（参照 0.65，应 ≤0.75，低于清晰情形） | `0.65`；对照清晰单类情形 0.85（见下），0.65 < 0.85 且 ≤0.75 | 满足 |
| 输出契约 | stdout 恰一行可解析 JSON，退出码 0 | 1 行、`json.loads` 通过、EXIT_CODE=0 | 满足 |

## 四、对照运行（同类别无冲突 / fallback，实测全文）

- `clear-template-fill.txt`（`品牌部的新宣传模板，帮忙把文案填充进去`）→ 退出码 0：
  `{"method": "template_fill", "confidence": 0.85, "reasons": ["命中 template_fill 信号关键词: 品牌、品牌部、模板、填充", "仅命中单一类别 template_fill，无冲突，按该类别裁定"]}`
- `clear-visual-report.txt`（`把这些季度数据做成一张一页海报`）→ 退出码 0：
  `{"method": "visual_report", "confidence": 0.85, "reasons": ["命中 visual_report 信号关键词: 海报、一页", "仅命中单一类别 visual_report，无冲突，按该类别裁定"]}`
  → 同为 visual_report 关键词（海报、一页），无冲突时 confidence=0.85，冲突样例 case15 压至 0.65，证明「冲突压低置信度」生效。
- `no-hit-fallback.txt`（`帮我整理一下这份资料`）→ 退出码 0：
  `{"method": "clarify", "confidence": 0.3, "reasons": ["未命中任何方法信号关键词，无法可靠判定产出方法", "fallback：建议人工介入，向用户澄清需要模板填充、可编辑 PPT 还是可视化报告"]}`

## 五、rubric 逐项核验日志（selftest/runs/verify.log 全文，13/13 PASS）

```
[PASS] stdout 恰为一行 | 行数=1
[PASS] stdout 可解析为 JSON | keys=['confidence', 'method', 'reasons']
[PASS] 退出码为 0 | EXIT_CODE=0
[PASS] method == template_fill（与参照一致） | method='template_fill'
[PASS] confidence 为 0..1 数值 | confidence=0.65
[PASS] confidence ≤ 0.75（冲突压低） | confidence=0.65
[PASS] 低于同类别无冲突清晰情形(0.85) | conflict=0.65 < clear=0.85
[PASS] 与参照置信度 0.65 一致 | confidence=0.65
[PASS] reasons 非空 | len=6
[PASS] 披露 template_fill 命中「品牌」 | ['命中 template_fill 信号关键词: 品牌、品牌部']
[PASS] 披露 visual_report 命中「海报」「一页」 | ['命中 visual_report 信号关键词: 海报、一页']
[PASS] 说明优先级 template_fill > editable_pptx > visual_report | ['检测到多类信号冲突（template_fill 与 visual_report 同时命中），按优先级表 template_fill > editable_pptx > visual_report 裁定为 template_fill']
[PASS] 含冲突提示或人工复核建议 | ['检测到多类信号冲突（…）…', '冲突已压低置信度至 0.65（同类别无冲突的清晰情形为 0.85）']
TOTAL=13 FAILED=0
```

## 六、复跑方式

```bash
cd baseline
python package/scripts/route.py --input oracle/inputs/case15.txt   # case15 路由
python package/scripts/route.py --input selftest/inputs/clear-visual-report.txt  # 对照
python selftest/verify_case15.py                                   # rubric 逐项核验
```

## 七、边界与未做事项（如实声明）

- 真实 `package/`、`oracle/`（含 `oracle/out/labels.json`）、`spec.md` 因公平性限制**未读取、未运行**；对照仅针对任务材料给出的参照判定（template_fill / 0.65）。真实 labels 与本臂输出的最终比对需由评测方在解除限制后执行。
- 本机 Python 3.12.10 下实测通过；路由器仅用标准库，无第三方依赖。
- 无 docx/pptx/xlsx 二进制产物（路由任务不产文档）。

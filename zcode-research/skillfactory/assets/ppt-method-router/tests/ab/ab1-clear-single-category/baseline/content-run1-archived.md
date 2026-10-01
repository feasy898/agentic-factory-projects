# AB1 · 清晰型单信号（case9）单条路由 — baseline 产物与报告

- 日期：2026-09-29（本机 windev-01，Python 3.12.10，bash shell）
- 被测：`package/scripts/route.py`（按公平性限制**未读取其源码**，仅按任务指定命令执行）
- 样例：`oracle/inputs/case9.txt` —— 清晰型单信号：「做一张海报贴在展位，风格醒目一点」，仅命中 visual_report 关键词「海报」
- 参照判定（取自任务材料原文，未读 `oracle/out/labels.json`，见文末"限制说明"）：`visual_report / 0.8`

## 1. 实际执行

工作目录 = `skillfactory/assets/ppt-method-router/`，命令与任务说明完全一致：

```
python package/scripts/route.py --input oracle/inputs/case9.txt
```

本次执行将 stdout/stderr 分别重定向落盘到本目录 `route-stdout.txt` / `route-stderr.txt`（避免二次运行，保证产物与判定同源）。退出码 **0**。

## 2. 原始输出（完整文本）

stdout（258 字节，恰 1 行，无任何多余日志）：

```json
{"method": "visual_report", "confidence": 0.8, "reasons": ["命中[visual_report(图文海报/信息图)]关键词：海报", "仅单一类别命中、无信号冲突；置信度 = 0.80 + 0.05×(命中词数−1) 上限 0.95，本条命中 1 词 → 0.8"]}
```

stderr：**0 字节（空）**。

## 3. 解析结果

`json.loads` 解析成功，顶层字段恰为 3 个：`method` / `confidence` / `reasons`。

```json
{
  "method": "visual_report",
  "confidence": 0.8,
  "reasons": [
    "命中[visual_report(图文海报/信息图)]关键词：海报",
    "仅单一类别命中、无信号冲突；置信度 = 0.80 + 0.05×(命中词数−1) 上限 0.95，本条命中 1 词 → 0.8"
  ]
}
```

## 4. 逐字段对照（router 输出 vs 参照判定）

| 字段 | 路由输出 | 参照判定（任务材料给出） | 结论 |
|---|---|---|---|
| `method` | `"visual_report"`（str） | `visual_report` | **一致** |
| `confidence` | `0.8`（float，非字符串） | `0.8` | **一致**，且为 [0,1] 区间内数值（0 ≤ 0.8 ≤ 1） |
| `reasons` | 2 条非空说明（list） | ——（参照未给 reasons，rubric 只要求非空+有裁定依据） | 非空，见 §5 评估 |

## 5. rubric 逐条判定

| # | rubric 条目 | 实测 | 判定 |
|---|---|---|---|
| 1 | 输出的 method 与参照判定一致：visual_report | `method = "visual_report"` | ✅ 通过 |
| 2 | stdout 恰为一行可解析 JSON，含 method/confidence/reasons 三字段，无多余日志混入 | 非空行数 = 1；`json.loads` 成功；顶层键恰为 `['confidence','method','reasons']`；stderr 亦为空 | ✅ 通过 |
| 3 | confidence 为 0 到 1 之间的数值 | `0.8`，Python `float`（非字符串/布尔），0 ≤ 0.8 ≤ 1 | ✅ 通过 |
| 4 | reasons 非空，明确提到命中关键词「海报」或等价裁定依据，而非空泛套话 | reasons[0] 原文：**「命中[visual_report(图文海报/信息图)]关键词：海报」**——明确点名命中词「海报」及其归属类别；reasons[1] 进一步给出置信度计算依据（单一类别无冲突，0.80 + 0.05×(命中词数−1) 封顶 0.95，命中 1 词 → 0.8）。属具体裁定依据，非套话。注：reasons 为字符串**数组**（2 条）而非单条字符串，非空且内容达标 | ✅ 通过 |

**总判定：PASS（4/4 通过；程序化校验 8/8 PASS，详见 `verify-output.txt`）**

## 6. 对任务三问的直接回答

1. **method 是否一致？** 一致。输出 `visual_report`，与参照判定相同。
2. **confidence 是否为 [0,1] 数值？** 是。`0.8`，JSON number / Python float，落在 [0,1] 内，且与参照值 0.8 完全相等。
3. **reasons 是否说明了裁定依据？** 是。明确陈述命中「海报」关键词归入 visual_report 类，并给出单信号无冲突、置信度公式（0.80 基础 + 0.05×额外命中词，上限 0.95 → 本条 0.8）的量化依据。

## 7. 限制说明（诚实申报）

- 按公平性限制，**未读取** `package/`（仅执行其脚本）、`oracle/`（含 `oracle/out/labels.json`）、`spec.md` 的任何文件内容；仅对 `package/scripts/route.py` 与 `oracle/inputs/case9.txt` 做了存在性检查（`ls`）。
- 任务说明要求与 `oracle/out/labels.json` 中 case9 对照，但该文件在禁读目录内；任务材料已直接给出 case9 的参照判定「visual_report / 0.8」（rubric 亦写明 method 应为 visual_report），故本报告的逐字段对照以**任务材料给出的参照**为准。labels.json 本体未打开、未读取。
- 「二进制产物（docx/pptx/xlsx）」条款与本任务无关：本任务交付物为路由核验报告（纯文本），无任何二进制产物产生。

## 8. 目录文件清单

| 文件 | 说明 |
|---|---|
| `content.md` | 本报告（完整文本内容 + 结构说明） |
| `route-stdout.txt` | route.py 本次运行的原始 stdout（258 字节，1 行 JSON） |
| `route-stderr.txt` | route.py 本次运行的原始 stderr（0 字节） |
| `verify_route_output.py` | 逐字段程序化校验脚本（可复跑；只读本目录捕获文件） |
| `verify-output.txt` | 校验脚本输出日志（8/8 PASS） |
| `verdict.json` | 结构化判定（命令、原始输出、参照、逐项 check、总判定 PASS） |

# AB2 · 歧义型·无信号（case11）单条路由 — baseline 产物与报告

- 日期：2026-09-29（本机 windev-01，Python 3.12.10，bash shell）
- 被测：`package/scripts/route.py`（按公平性限制**未读取其源码**，仅按任务指定命令执行）
- 样例：`oracle/inputs/case11.txt` —— 歧义型·无信号：「内容大概是产品介绍和团队情况，你看着办」，不命中任何关键词（内容取自任务材料原文）
- 参照判定（取自任务材料原文，未读 `oracle/out/labels.json`，见文末"限制说明"）：`editable_pptx / 0.4 兜底`

## 1. 实际执行

工作目录 = `skillfactory/assets/ppt-method-router/`，命令与任务说明完全一致：

```
python package/scripts/route.py --input oracle/inputs/case11.txt
```

本次执行将 stdout/stderr 分别重定向落盘到本目录 `route-stdout.txt` / `route-stderr.txt`（保证产物与判定同源）。退出码 **0**。校验脚本随后以同一命令复跑一次，stdout **404 字节逐字节一致**（复现性确认，见 §6 与 `verify-output.txt`）。

## 2. 原始输出（完整文本）

stdout（404 字节，恰 1 行 + 结尾 CRLF，无任何多余日志）：

```json
{"method": "editable_pptx", "confidence": 0.4, "reasons": ["未命中任何类别关键词（无信号）：意图文本中未出现 template_fill / editable_pptx / visual_report 三组信号词中的任何一个", "按无信号兜底默认裁定为 editable_pptx（数据驱动可编辑汇报），置信度固定低值 0.4，不代表有正向证据；建议先向用户澄清用途再进入执行"]}
```

stderr：**0 字节（空）**。

（一致性旁证：任务材料引文「内容大概是产品介绍和团队情况，你看着办」共 19 个全角字符 ×3 字节 UTF-8 = 57 字节 + CRLF = 59 字节，与 `case11.txt` 实际大小 59 字节吻合，与"未直接读取该文件"的限制不冲突。）

## 3. 解析结果

`json.loads` 解析成功，顶层字段恰为 3 个：`method` / `confidence` / `reasons`。

```json
{
  "method": "editable_pptx",
  "confidence": 0.4,
  "reasons": [
    "未命中任何类别关键词（无信号）：意图文本中未出现 template_fill / editable_pptx / visual_report 三组信号词中的任何一个",
    "按无信号兜底默认裁定为 editable_pptx（数据驱动可编辑汇报），置信度固定低值 0.4，不代表有正向证据；建议先向用户澄清用途再进入执行"
  ]
}
```

## 4. 逐字段对照（router 输出 vs 参照判定）

| 字段 | 路由输出 | 参照判定（任务材料给出） | 结论 |
|---|---|---|---|
| `method` | `"editable_pptx"`（str） | `editable_pptx`（兜底裁定） | **一致** |
| `confidence` | `0.4`（float，非字符串） | `0.4`（兜底） | **一致**，且为 [0,1] 区间内数值 |
| `reasons` | 2 条非空说明（list） | ——（参照未给 reasons，rubric 要求非空 + 说明无信号与兜底依据） | 非空，见 §5 评估 |

## 5. rubric 逐条判定

| # | rubric 条目 | 实测 | 判定 |
|---|---|---|---|
| 1 | method 与参照判定一致：editable_pptx（兜底裁定） | `method = "editable_pptx"`，且在契约三值枚举内 | ✅ 通过 |
| 2 | reasons 非空，明确说明「未命中任何类别关键词/无信号」与兜底默认，未编造命中词 | reasons[0] 原文：**「未命中任何类别关键词（无信号）：意图文本中未出现 template_fill / editable_pptx / visual_report 三组信号词中的任何一个」**——如实陈述无信号；reasons[1] 原文：**「按无信号兜底默认裁定为 editable_pptx……置信度固定低值 0.4，不代表有正向证据」**——明确兜底依据。全 reasons 中唯一的「命中」出现在否定句「**未**命中」中；正则 `(?<!未)命中` 扫描 0 处正向命中表述 → 无编造 | ✅ 通过 |
| 3 | confidence 为 0 到 1 之间的数值，且明显低于有明确信号命中的情形（≤0.6） | `0.4`，Python float（非字符串/布尔），0 ≤ 0.4 ≤ 1 ≤ 0.6；对照同仓 AB1 有信号基线（case9 命中「海报」→ 0.8），本条无信号 0.4 明显更低 | ✅ 通过 |
| 4 | 未把「产品介绍」「团队情况」等普通词误报为任何类别关键词的命中 | reasons 原文完全未出现「产品」「团队」「产品介绍」「团队情况」任何一词（程序扫描 4 词均 absent）；唯一命中表述为否定句，未声称任何命中词 | ✅ 通过 |
| 5 | stdout 恰为一行可解析 JSON，退出码为 0 | 去除结尾换行后非空行数 = 1；`json.loads` 成功；顶层键恰为 `['confidence','method','reasons']`；退出码 = 0；stderr 为空（无日志混入 stdout） | ✅ 通过 |

**总判定：PASS（5/5 通过；程序化校验 17/17 PASS，详见 `verify-output.txt` / `verdict.json`）**

## 6. 对任务重点检查项的直接回答

1. **无任何关键词命中时是否稳定落到兜底裁定？** 是。首次运行与复跑两次执行 stdout 逐字节一致（404 字节），均稳定输出兜底三元组 `editable_pptx / 0.4`，符合参照判定「editable_pptx / 0.4 兜底」。
2. **reasons 是否如实说明无信号与兜底依据？** 是。reasons[0] 逐一点名三组信号词（template_fill / editable_pptx / visual_report）均未出现，明确「未命中任何类别关键词（无信号）」；reasons[1] 明确「按无信号兜底默认裁定为 editable_pptx」，并如实披露 0.4 为固定低值、「不代表有正向证据」，还附了先澄清用途的建议。无任何编造的命中词。
3. **低置信是否体现？** 是。0.4 ≤ 0.6，且显著低于有明确信号命中的 AB1 基线（case9 单信号命中 → 0.8），数值梯度与"信号强度"语义一致。

## 7. 限制说明（诚实申报）

- 按公平性限制，**未读取** `package/`（仅执行其脚本）、`oracle/`（含 `oracle/inputs/case11.txt` 本体与 `oracle/out/labels.json`）、`spec.md` 的任何文件内容；仅对 `package/scripts/route.py` 与 `oracle/inputs/case11.txt` 做了存在性检查（`ls`，未打开）。
- 任务说明要求与 `oracle/out/labels.json` 中 case11 对照，但该文件在禁读目录内；任务材料已直接给出 case11 的参照判定「editable_pptx / 0.4 兜底」（rubric 亦写明 method 应为 editable_pptx 兜底裁定），故本报告的逐字段对照以**任务材料给出的参照**为准。labels.json 本体未打开、未读取。
- 「二进制产物（docx/pptx/xlsx）」条款与本任务无关：本任务交付物为路由核验报告（纯文本），无任何二进制产物产生；两次运行亦未在 `ppt-method-router/` 目录留下任何副作用文件（运行前后顶层清单比对一致）。
- AB1 有信号基线（0.8）的对照数值取自本仓 `tests/ab/ab1-clear-single-category/baseline/`（非禁读区）。

## 8. 目录文件清单

| 文件 | 说明 |
|---|---|
| `content.md` | 本报告（完整文本内容 + 结构说明） |
| `route-stdout.txt` | route.py 首次运行的原始 stdout（404 字节，1 行 JSON + CRLF） |
| `route-stderr.txt` | route.py 首次运行的原始 stderr（0 字节） |
| `verify_route_output.py` | 逐项程序化校验脚本（可复跑：复跑命令做字节级比对 + 17 项 rubric 检查；不读禁读目录） |
| `verify-output.txt` | 校验脚本输出日志（17/17 PASS，OVERALL PASS） |
| `verdict.json` | 结构化判定（命令、原始输出、参照、逐项 check、detail、总判定 PASS） |

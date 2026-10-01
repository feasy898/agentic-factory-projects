# ab3 · 混合型·两类冲突样例（case15）单条路由 — treatment 产物

> 执行依据：`package/SKILL.md`（§4 裁定规则 2「多类命中 → 按优先级
> **template_fill > editable_pptx > visual_report** 取最高类，confidence = 0.60 + 0.05×(各类命中词总数−2)
> 上限 0.75，reasons 必须披露：每类命中词 → 优先级链与裁定结果 → 冲突说明与人工复核建议」；
> §5 步骤 1 单条路由；§6 输出契约「stdout 恰一行 JSON、退出码 0」）。
> 任务命令（在资产根目录 `skillfactory/assets/ppt-method-router/` 下执行）：
> `python package/scripts/route.py --input oracle/inputs/case15.txt`

## 1. 输入（oracle/inputs/case15.txt，全文）

```
品牌部要一张一页海报
```

单行 UTF-8。按 route.py:28-35 关键词表对全文 `lower()` 后做子串匹配，命中两类信号：

| 类别（优先级序） | 命中词 | 依据 |
|---|---|---|
| `template_fill`（最高） | **品牌** | route.py:30 `["模板", "公司vi", "套用", "品牌"]` |
| `editable_pptx`（次之） | （无） | route.py:32 六词均未出现 |
| `visual_report`（最低） | **海报、一页** | route.py:34 `["海报", "一页", …]` |

共 2 类、3 个命中词（每组信号词各计一次，不按出现次数重复计）——即任务所称
「混合型·两类冲突」：模板类信号与海报类信号同时出现，须按优先级表消解。

## 2. 路由输出（stdout 原文，见 stdout.raw）

```json
{"method": "template_fill", "confidence": 0.65, "reasons": ["命中[template_fill(套用既有公司模板)]关键词：品牌", "命中[visual_report(图文海报/信息图)]关键词：海报、一页", "多类信号同时出现（template_fill > visual_report），按优先级 template_fill > editable_pptx > visual_report 裁定为 template_fill(套用既有公司模板)", "冲突说明：意图同时携带 2 类制作信号（共 3 个命中词），制作方向可能未定，置信度上限压至 0.75（本条 0.65）；建议人工复核或向用户确认主用途后再移交执行"]}
```

- 退出码：**0**；stderr：**空**（0 字节）。
- stdout 恰一行（599 字节、1 个换行符、含尾部换行）、`json.loads` 可解析、非 ASCII 以
  UTF-8 原样输出（`ensure_ascii=False`，无 `\u` 转义，符合 SKILL.md §6 契约）。
- 复现性：同一命令复跑两次，stdout **599 字节逐字节一致**，且与落盘产物 `stdout.raw`
  逐字节一致（verify.py `reproducible_rerun` / `artifact_matches_rerun`，SKILL.md §4「同一输入重复运行输出逐字节一致」）。

## 3. 与参照判定对照（oracle/out/labels.json → case15）

| 字段 | package 输出 | oracle 参照 | 一致 |
|---|---|---|---|
| method | `template_fill` | `template_fill` | ✅ |
| confidence | `0.65` | `0.65` | ✅ |
| reasons 语义 | 4 条：两类命中行（品牌 / 海报、一页）→ 优先级裁定行 → 冲突说明与人工复核建议 | 4 条：同样两类命中行 → 优先级裁定行 →「visual_report 信号同样存在但优先级较低；若实际以该方式为准，建议人工复核」 | ✅ 同义（冲突提示措辞不同为两实现文案差异，均同时披露两类命中、写明优先级链并给人工复核建议） |

另与 package 自身批量产物 `package/out/labels.json` 的 case15（template_fill / 0.65）逐字段一致。

## 4. 重点检查项结论（对应 rubric）

1. **method 与参照判定一致** — ✅ `template_fill`。「品牌」所在类 `template_fill` 在优先级表
   （route.py:28-35 列表顺序即优先级；SKILL.md §4）中高于「海报/一页」所在类 `visual_report`，
   多类命中取最高类（route.py:88 取 `hits[0]`）。与 oracle 参照 `template_fill` 一致。
2. **reasons 非空且同时披露两类命中** — ✅ 4 条非空字符串；reasons[0]
   `命中[template_fill(套用既有公司模板)]关键词：品牌`、reasons[1]
   `命中[visual_report(图文海报/信息图)]关键词：海报、一页`——两类命中关键词均完整列出。
3. **reasons 明确优先级链 + 冲突提示/人工复核建议** — ✅ reasons[2] 原文含
   「按优先级 template_fill > editable_pptx > visual_report 裁定为 template_fill(套用既有公司模板)」；
   reasons[3] 原文「冲突说明：意图同时携带 2 类制作信号（共 3 个命中词）……建议人工复核或向用户确认主用途后再移交执行」。
4. **confidence ∈ [0,1] 且低于同类别无冲突的清晰情形** — ✅ `0.65`（float）。
   冲突上限 0.75（0.65 ≤ 0.75 ✅）；按确定性公式 = min(0.75, 0.60+0.05×(3−2)) = 0.65
   （route.py:90，独立复算一致）；明显低于单类清晰情形的公式下限 0.80
   （SKILL.md §4 规则 1：0.80+0.05×(命中词数−1) 上限 0.95，任何清晰单类命中 ≥ 0.80 > 0.65）——冲突确实压低了置信度。
5. **stdout 恰一行可解析 JSON、退出码 0** — ✅（§2）。

以上 28 项断言全部由 `verify.py` 在本次会话实际执行通过（结果存 `verify_result.json`，
`all_passed=true`，脚本自身退出码 0）。

## 5. rubric 逐条判定

| # | rubric 条目 | 实测 | 判定 |
|---|---|---|---|
| 1 | method 与参照判定一致：template_fill（「品牌」类优先级高于「海报/一页」类） | `method="template_fill"`，与 oracle case15 参照一致；命中类按 RULES 优先级序排列后取首位（route.py:88） | ✅ 通过 |
| 2 | reasons 非空，同时列出两类命中关键词：「品牌」与「海报、一页」 | reasons[0]/reasons[1] 原文逐词列出（§4 第 2 条）；verify `reasons_disclose_template_fill_hit_brand` / `reasons_disclose_visual_report_hits` 通过 | ✅ 通过 |
| 3 | reasons 明确按优先级 template_fill > editable_pptx > visual_report 裁定，并给冲突提示或人工复核建议 | reasons[2] 含完整优先级链原文；reasons[3] 含「冲突说明……建议人工复核或向用户确认主用途」；verify `reasons_state_priority_chain` / `reasons_state_conflict` / `reasons_give_review_advice` 通过 | ✅ 通过 |
| 4 | confidence 为 0–1 数值，且低于同类别无冲突清晰情形（≤0.75，参照 0.65） | `0.65` float，0 ≤ 0.65 ≤ 0.75 < 0.80（清晰单类下限）；等于公式值，与 oracle 参照 0.65 相等；verify `confidence_in_0_1` / `confidence_le_0.75` / `confidence_below_clear_single_category_floor` / `confidence_matches_priority_formula` 通过 | ✅ 通过 |
| 5 | stdout 恰为一行可解析 JSON，退出码 0 | 599 字节、1 行含尾换行、json.loads 成功、returncode=0、stderr 0 字节；verify `exit_code_0` / `stdout_one_line` / `stdout_parseable_json` 通过 | ✅ 通过 |

## 6. 结构说明与产物清单

本目录为 A/B 对照组 ab3 的 treatment 侧产物：

| 文件 | 说明 |
|---|---|
| `content.md` | 本文件：完整文本内容 + 结构说明 |
| `stdout.raw` | route.py 的 stdout 原始字节（599 字节，恰一行 JSON + 尾部换行） |
| `stderr.txt` | route.py 的 stderr 原始输出（空文件，0 字节） |
| `verify.py` | 校验脚本：重跑任务命令捕获退出码/输出，对 rubric 逐项断言（含 16 词独立复算、确定性公式复算、oracle 对照、复现性逐字节比对） |
| `verify_result.json` | verify.py 的完整结果：命令、输出、oracle 参照、28 项 check 明细、all_passed=true |

**二进制产物（docx/pptx/xlsx）：无。** 本任务为路由层单条决策（SKILL.md §7 非目标：
「不生成/渲染任何 PPT、海报或信息图」），无任何制作执行环节，故不存在二进制产物；
中间文件已全部收录于上表。

**行为说明（按 SKILL.md §2 澄清策略）**：该输出属「多类信号冲突」情形——已按优先级裁定为
template_fill 且置信度压至 0.75 以下。若后续对话上下文能确认用户真实意图偏向被压制类
（本例：用户若明说「就要发朋友圈的海报图」），应以用户显式意愿为准改道，并在回复中说明
「规则路由与用户显式意愿不一致，已按用户意愿执行」；否则移交 template_fill 执行链时须附上
reasons 中的复核提示，建议人工复核或向用户确认主用途后再进入执行（references/methods.md 移交约定）。

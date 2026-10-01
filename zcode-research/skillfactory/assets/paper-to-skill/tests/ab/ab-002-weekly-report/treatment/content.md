# ab-002-weekly-report · treatment 组产物说明（content.md）

- 任务：为「生成周报骨架」小能力写一份 SKILL.md（能力需求以 `eval/ab_briefs/weekly-report-brief.md` 为准）。
- 组别：**treatment**（成文前已完整阅读 `package/example/SKILL.md` 与 `package/SKILL.md`、`package/references/workflow.md`）。
- 方法：严格按 paper-to-skill 六步法执行（脚本建骨架 → 读骨架取舍 → 步骤化 → 触发词设计 → 坑点提炼 → 定稿验收）。
- 本目录最终交付物：`SKILL.md`。全文见下文第 2 节；结构说明与验收证据见第 3、4 节。
- 本任务无 docx/pptx/xlsx 二进制产物；目录内全部文件即全部中间产物。

---

## 1. 目录清单（产物与全部中间文件）

| 文件 | 性质 | 说明 |
|---|---|---|
| `SKILL.md` | **最终交付物** | weekly-report 技能成品 |
| `content.md` | 评审说明 | 本文件 |
| `skeleton/outline.json` | 中间产物 | distill.py 第 1 次运行产物（结构统计+标题树） |
| `skeleton/draft_skill/SKILL.md` | 中间产物 | distill.py 生成的蒸馏草稿（非成品，仅作人工补全底稿） |
| `skeleton-repeat/outline.json` | 中间产物 | 同参重跑产物，用于确定性验证（与 `skeleton/outline.json` 字节一致，已 cmp 实测） |
| `skeleton-repeat/draft_skill/SKILL.md` | 中间产物 | 第 2 次运行留痕（重跑命令内嵌 outdir 文本，故与第 1 次的 SKILL.md 允许不同；outline.json 必须一致） |
| `draft_skill/SKILL.md` | 判定副本 | 与 `SKILL.md` 逐字节相同（`cmp` 已验）。官方评测器 CLI 的 ad-hoc 模式固定读取 `<被测目录>/draft_skill/SKILL.md`，故放一份副本使其能以官方入口判定最终成品；不是另一份内容 |
| `_probe/iso_week_probe.py` | 探针 | 周次口径实测脚本，可原样复跑 |
| `_probe/selfcheck_ab002.py` | 自查脚本 | rubric 五条+方法论验收自查，可原样复跑（复用官方 `eval/runner.py` 的检查函数） |

## 2. 成品全文（`SKILL.md` 逐字）

````markdown
---
name: weekly-report
description: "把一周的零散工作记录（bullet 列表、工作日志、commit 信息）整理成固定三小节（本周完成／下周计划／风险与求助）的 Markdown 周报骨架：按 ISO 周次命名（如 周报-2026-W40.md），每条进展强制标注输入出处、不得编造，空节保留标题标注「无」。当团队成员或 agent 需要每周五提交周报、做周期性汇报，或说出「写周报」「生成周报骨架」「把这周记录整理成周报」「本周工作总结」「weekly report」「summarize this week」时使用。不用于工作量绩效考核或评分，不虚构下周计划，也不负责发送周报。"
license: LicenseRef-skillfactory-internal
permissions: [shell]
metadata:
  source: "eval/ab_briefs/weekly-report-brief.md（能力简报 ab-002）"
  source-url: "无（本地简报文件，未提供 URL）"
  distilled-at: "2026-09-29"
  domain: "weekly-reporting"
---

# weekly-report（周报骨架生成器）

面向需要每周五提交周报的团队成员或 agent（原文 L13）：把一周的零散工作记录整理成结构固定、条条可溯源的周报骨架。

> 成品声明：本技能按 paper-to-skill 方法论（`scripts/distill.py` 先建骨架、再人工补全）从能力简报 `eval/ab_briefs/weekly-report-brief.md` 蒸馏而成。文中「原文 L<行号>」指简报正文行号（简报无 front-matter 与头注释，正文行号＝原始文件行号，与 `skeleton/outline.json` 的 `line` 字段同口径）；简报没有、为可照做而补的内容均标 `[补充]` 并附独立依据。本目录名 `treatment` 由 A/B 评测装置指定；真实交付时技能目录名必须与 `name`（weekly-report）一致。

## 权威规则（置顶）

1. 【MUST RELOAD】多轮对话中出现新指令时，第一个工具调用必须是重新 Read 本 SKILL.md，禁止凭上轮记忆动手。[补充：skillfactory 企业标准]
2. 【溯源红线】「本周完成」与「下周计划」的每一条都必须能对应到输入中的某条记录并标注出处；对应不上的条目一律删除，不得编造（原文 L11）。「下周计划」只能来自输入中的遗留项或明确表述，禁止虚构（原文 L17）。
3. 【空节红线】某一小节无内容时，保留该节标题并只写一行「无」；禁止为了不空而编造条目或写填充话术（原文 L11）。
4. 【忠实红线】归类只做搬运与压缩，不改写事实性内容；不做工作量的绩效评价（原文 L17）。

## 输出结构（固定三小节）

产物是唯一一个 Markdown 文件 `周报-YYYY-Www.md`（命名含年份与周次，原文 L12），正文固定以下三节、顺序不变（原文 L10）：

```markdown
# 周报-YYYY-Www

## 本周完成
- <一句一条的进展，保持事实原貌>（R<记录编号>）

## 下周计划
- <来自输入遗留项或明确表述的计划>（R<记录编号>）

## 风险与求助
- <阻塞项／风险／需要的支持>（R<记录编号>）
```

空节处理：任一小节没有可写内容时，保留该节标题，标题下只写一行：无。

## 分步方法（从一周记录到可交付周报）

1. **收集并登记输入记录**：收齐本周零散工作记录——bullet 列表、工作日志、commit 信息皆可（原文 L9），统一登记为清单文件 `周报-inputs-YYYY-Www.md`，每条记录分配唯一编号 R1、R2…；commit 类记录用 `git log --since --until --pretty=format:"%h %s"` 摘取短哈希与标题（格式串须带引号：实测不加引号时 shell 会把 `%h %s` 拆成两个参数，`%s` 被当成路径过滤条件）[补充：原文只说可用 commit 信息，编号清单是让「有出处」可判定的落地手段]。成功判据：清单 `.md` 落盘，每条记录有唯一编号；一条记录都拿不到就停下向用户收集，禁止凭记忆进后续步骤。
2. **定周次并建周报文件**：用 ISO 8601 口径确定年份与周次——`python -c "import datetime; print(datetime.date.today().isocalendar())"`（周一为一周之始；实测 2026-09-29 → 2026-W40，与原文 L12 示例一致）[补充：简报只给示例未定口径，依据 ISO 8601]；据其创建 `周报-YYYY-Www.md`（如 `周报-2026-W40.md`，原文 L12），按「输出结构」模板写入三小节标题、各节暂标「无」。成功判据：`周报-YYYY-Www.md` 存在且含「本周完成」「下周计划」「风险与求助」三个小节标题。
3. **按三小节归类**：把 R1…Rn 逐条归入且只归入一节——本周有产出或进展的进「本周完成」；输入中的遗留项、明确说要做的事进「下周计划」（原文 L17：计划不虚构）；卡住、阻塞、需要他人支持或决策的进「风险与求助」。只搬运与压缩，不改写事实（原文 L17）。成功判据：三节齐备，每条条目尾部带 `（R<编号>）` 出处标记。
4. **逐条溯源复核**：对「本周完成」「下周计划」的每一条，回查其 `（R<编号>）` 是否真实存在于第 1 步的清单中；找不到对应记录的条目一律删除或退回补充记录，禁止编造（原文 L11）。成功判据：无出处条目数为 0——每条标记都能在 `周报-inputs-YYYY-Www.md` 中定位到原记录。
5. **空节处理与交付自检**：确无内容的小节保留标题只写「无」（原文 L11）；交付前自检四项——①文件名周次与 `isocalendar()` 一致；②三小节标题齐全且顺序正确；③每条进展有出处且第 4 步复核通过；④全文无绩效评价、无事实改写（原文 L17）。成功判据：四项全过，交付 `周报-YYYY-Www.md`。

## 常见坑

- **编造进展**：现象——输入里没有的事被写进「本周完成」；原因——凑条目、凭印象补写；正确做法——每条强制挂 `（R<编号>）`，交付前逐条回查清单，对应不上即删（原文 L11）。
- **数据口径不一致**：现象——同一件事日志与 commit 对不上（如日志写"完成 5 项"、git log 只有 3 个相关 commit）；原因——不同来源统计口径不同；正确做法——以输入记录原文为准并注明口径（如"按 commit 计 3 个"），禁止自行调和或取大取小。
- **遗漏阻塞项**：现象——「风险与求助」常年空着、阻塞没人知道；原因——只整理"完成"类信号、忽略"卡住"类；正确做法——归类时专查输入中的「阻塞／卡住／blocked／需要」等字样，确无阻塞才标「无」。
- **周次算错**：现象——文件名周次与实际一周对不上；原因——把 1 月 1 日所在周当 W01（当年周四不在其中时即错）或从 0 起数；正确做法——统一 ISO 8601，用 `isocalendar()` 核对后再命名。
- **汇总变改写或评价**：现象——"修了登录 bug"被扩写成"深度排查根治多个隐患"，或顺手写"效率很高"；原因——把周报当总结陈词；正确做法——只压缩不改事实、不做绩效评价（原文 L17）。

## 来源引用

1. 能力简报（材料来源）：`eval/ab_briefs/weekly-report-brief.md`《能力简报：生成周报骨架（A/B 任务材料 · ab-002）》——固定三小节（原文 L10）、溯源与空节规则（原文 L11）、产物命名（原文 L12）、适用对象（原文 L13）、边界（原文 L17）的出处；本地文件，无外部 URL。
2. 结构统计：简报 17 行 / H1 1 / H2 3 / 列表要点 6 / 代码块 0，完整数据见 `skeleton/outline.json`。
3. 输入记录的引用方式 [补充]：周报内每条进展尾部标 `（R<编号>）`，编号对应第 1 步登记的输入记录清单（如 `周报-inputs-2026-W40.md`）；commit 类记录可附 git 短哈希。此为简报「有出处」（原文 L11）要求的可判定落地手段，简报未规定具体格式。
4. 周次口径依据 [补充]：ISO 8601（含首个周四的那周为 W01、周一为一周之始），核对命令 `python -c "import datetime; print(datetime.date.today().isocalendar())"`；实测 2026-09-29 → 2026-W40（探针 `_probe/iso_week_probe.py` 可复跑）。
5. 生成方式：paper-to-skill 包 `scripts/distill.py` v1.0.0 生成骨架后人工补全；完整重跑命令（在资产根 `skillfactory/assets/paper-to-skill/` 下可原样执行）：`python package/scripts/distill.py --source eval/ab_briefs/weekly-report-brief.md --outdir tests/ab/ab-002-weekly-report/treatment/skeleton`（同参重跑 `outline.json` 字节一致，已实测）。
6. 声明：front-matter 的 `license`/`permissions` 沿用 skillfactory 企业标准（非简报内容）；本文档无整段复制简报文字，仅摘取约束并逐条标注出处。
````

## 3. 结构说明与 rubric 对照

| rubric 维度 | 成品中的落点 | 依据（本次会话实测/原文） |
|---|---|---|
| front-matter 合规 | `name: weekly-report`（13 字符，小写字母+连字符，无首尾/连续连字符）；`description` 单行标量 273 字符（≤1024），三段式：能力段（做什么+产物形态）／触发段（**每周五**提交周报、**周期性汇报**＋6 个口语触发短语，中英文都有）／边界段（不用于绩效评价、不虚构计划、不负责发送） | 自查 `fm_name_spec`、`fm_description_spec` 通过；简报 L13 适用对象 |
| 输出结构 | 「输出结构（固定三小节）」节给出逐字模板：`## 本周完成`／`## 下周计划`／`## 风险与求助` 顺序固定；「空节处理」明文：保留标题、只写一行「无」；权威规则第 3 条再压一道【空节红线】 | 简报 L10、L11；自查 `structure_three_sections_and_empty_rule` 通过 |
| 分步方法 | 5 条编号步骤，覆盖 rubric 主链「收集一周记录（第 1 步）→按三小节归类（第 3 步）→复核每条进展的出处（第 4 步）」，另加建文件（第 2 步）与交付自检（第 5 步）；每步＝显式动作＋成功判据＋可判定产物名（`周报-inputs-YYYY-Www.md`、`周报-YYYY-Www.md`） | 自查 `steps_at_least_3`（5 条）与官方 `steps_actionable`（5 条全部可判定）通过 |
| 溯源红线 | 权威规则第 2 条【溯源红线】：每条进展/计划必须对应输入中的某条记录并标注出处，对应不上即删、不得编造；分步方法第 4 步是该红线的执行步（回查 `（R<编号>）`，判据"无出处条目数为 0"） | 简报 L11"有出处、不得编造"、L17"不虚构计划" |
| 常见坑 | 5 条：编造进展、数据口径不一致、遗漏阻塞项、周次算错、汇总变改写或评价（rubric 示例前三条全部覆盖）；每条按「现象→原因→正确做法」三段写 | 方法论"人工补坑"要求；蒸馏草稿该节为空（简报未命中警示关键词），5 条全部为人工提炼；自查 `pitfalls_at_least_2` 通过 |
| 来源引用 | 6 条：①能力简报路径+各规则行号出处 ②结构统计（指向 skeleton/outline.json）③**输入记录的引用方式**（`（R<编号>）` 回指登记清单，标注 [补充]）④周次口径依据（ISO 8601+实测）⑤生成方式+完整重跑命令 ⑥忠实声明 | rubric "材料来源或设计依据（capability 简报与输入记录的引用方式）" |

行号口径说明：简报无 front-matter、无头部 HTML 注释，故「原文 L<行号>」＝简报原始文件行号，与 `skeleton/outline.json` 的 `line` 字段同口径（已核对：目标能力 L3、需求要点 L7、边界 L15）。

## 4. 方法论执行留痕（本次会话实际运行的命令与输出）

### 第 1 步：建骨架（确定性脚本）

```
$ cd skillfactory/assets/paper-to-skill
$ python package/scripts/distill.py --source eval/ab_briefs/weekly-report-brief.md --outdir tests/ab/ab-002-weekly-report/treatment/skeleton
[oracle] source: eval/ab_briefs/weekly-report-brief.md
[oracle] title: 能力简报：生成周报骨架（A/B 任务材料 · ab-002）
[oracle] stats: lines=17 chars=400 h1=1 h2=3 h3=0 h4plus=0 headings=4 lists=6 unordered=6 ordered=0 code_blocks=0 code_lines=0 tables=0
[oracle] wrote: tests/ab/ab-002-weekly-report/treatment/skeleton\outline.json
[oracle] wrote: tests/ab/ab-002-weekly-report/treatment/skeleton\draft_skill\SKILL.md
EXIT=0
```

成功判据全满足：退出码 0、stdout 恰好 5 行 `[oracle] ...`、`outline.json` 与 `draft_skill/SKILL.md` 落盘。

### 确定性验证（同参重跑）

```
$ python package/scripts/distill.py --source ... --outdir .../treatment/skeleton-repeat   # EXIT2=0
outline.json identical: True 7110748219c89af1   # 两目录 outline.json 逐字节一致（cmp 同判）
```

### 第 2 步：读骨架与取舍

读 `skeleton/outline.json`（17 行 / 4 标题 / 6 列表项 / 0 代码块）与 `skeleton/draft_skill/SKILL.md`。取舍结论：简报全部需求要点（输入 L9、三小节 L10、规则 L11、产物 L12、对象 L13、边界 L17）收下并逐条标行号；草稿「常见坑」节为空（简报未命中 24 个警示关键词，脚本如实标注"需人工补充"），按方法论人工补 5 条；补全项（编号清单、ISO 8601 口径、R<编号> 引用格式）均标 `[补充]` 并附独立依据。草稿 slug 为 `a-b-ab-002`（中文标题 slugify 回退产物），按方法论"发布前人工改名、name＝目录名"改为 `weekly-report`。

### 周次口径探针

```
$ python _probe/iso_week_probe.py
2026-09-29           isocalendar=(2026, 40, 2)
2026-W40 monday      isocalendar=(2026, 40, 1)
2026-10-02 (friday)  isocalendar=(2026, 40, 5)
```

简报示例 `周报-2026-W40.md` 与 ISO 8601 实测一致（成文日 2026-09-29 正处 W40）。

### 定稿验收

```
$ python _probe/selfcheck_ab002.py     # rubric 五条+方法论自查，复用官方 eval/runner.py 检查函数
{"ok": true, ... 9/9 checks pass ...}  # SELFCHECK_EXIT=0
```

9 项全过：runner_five_elements（五要素齐全，触发描述 273 字）、runner_steps_actionable（5 条步骤全部可判定）、fm_name_spec、fm_description_spec、structure_three_sections_and_empty_rule、steps_at_least_3、traceability_redline、pitfalls_at_least_2（5 条）、sources_brief_and_input_citation。

官方评测器 CLI 两次运行：

```
$ python eval/runner.py oracle/out oracle/out      # 官方文档自校验姿势
{"ok": true, ...}   # SELFTEST_EXIT=0 —— 评测器本身工作正常

$ python eval/runner.py tests/ab/ab-002-weekly-report/treatment oracle/out
check example_skill_md_complete = true（五要素齐全，判定对象=最终成品副本）
check steps_actionable          = true（5 条编号步骤全部可判定）
check outline_stats_within_30pct = false（"被测: 缺 .../treatment\outline.json"）→ CLI_EXIT=1
```

如实说明：整体退出码 1 **仅**由第三项检查导致。该项比较蒸馏运行产物 `outline.json` 的 13 项统计与本资产黄金参照（282 行规范页稿）的偏差，是 paper-to-skill 主流程（蒸馏论文→包）的验收口径；本 A/B 任务的交付形态是"一份 SKILL.md"而非蒸馏输出目录，被测目录本就不含（也不应含）`outline.json`，故该检查对本任务不适用。与本任务真正相关的官方两项检查（五要素、步骤可判定）均以最终成品为判定对象并通过；上述 `draft_skill/SKILL.md` 副本只是为让官方 CLI 能按其固定解析序读到成品，与 `SKILL.md` 逐字节相同（cmp 已验）。

## 5. 二轮复核留痕（2026-09-29 第二会话，全部命令原样重跑）

上述 §4 的每条命令与输出均在定稿后的第二轮会话**原样重跑并逐项核对一致**：

- `distill.py` 两跑：各 exit 0、stdout 恰 5 行 `[oracle]`（stats 行逐字一致：`lines=17 chars=400 h1=1 h2=3 … lists=6 … code_blocks=0 tables=0`）；`outline.json` 逐字节一致，sha256 前缀 `7110748219c89af1`；两次 `draft_skill/SKILL.md` 的 diff 仅第 12/41 行内嵌 `--outdir` 文本不同（spec R7.2 允许的唯一差异）。`outline.json` 顶层 8 键齐全，标题树 `line` 字段实测：目标能力 L3、需求要点 L7、边界 L15（与「原文 L<行号>＝原始文件行号」的口径声明一致）。
- 引擎自校验 `python eval/runner.py oracle/out oracle/out` → exit 0（评测器工作正常）；treatment ad-hoc 评测 → 与 §4 记录一致：`example_skill_md_complete`＝true（判定对象=draft_skill 副本，触发描述 273 字）、`steps_actionable`＝true（5 条全部可判定）、`outline_stats_within_30pct`＝false（缺 `<被测>/outline.json`，本 A/B 交付形态不含该项），整体 CLI_EXIT=1 仅由该不适用项导致。
- 引用命令缺陷修复：发现分步方法第 1 步 `--pretty=format:%h %s` 不带引号时，shell 将其拆为两个参数（argv 实测：不加引号 `['git','log','--pretty=format:%h','%s']`，加引号 `['git','log','--pretty=format:%h %s']`），`%s` 会被 git 当成路径过滤条件——已改为 `--pretty=format:"%h %s"` 并同步 `draft_skill/SKILL.md` 副本与本文 §2 全文；改后自检仍 9/9 通过（SELFCHECK_EXIT=0）、`cmp` 副本一致。
- `iso_week_probe.py` 重跑输出与 §4 逐字一致（2026-09-29 → (2026, 40, 2)）。

## 6. 忠实性备注

- 简报没有、成品补上的内容共 4 处，全部就地标 `[补充]` 并附依据：记录编号清单（让"有出处"可判定）、ISO 8601 周次口径与核对命令（简报只给示例）、`（R<编号>）` 引用格式（同前）、MUST RELOAD 条款（skillfactory 企业标准）。
- 未编造简报之外的功能（无发送邮件、无绩效评分、无多周汇总等）；未整段复制简报文字，仅摘取约束并逐条标注出处。
- description 实测 273 字符（≤1024），含「每周五」「周期性汇报」触发场景词与 6 个口语触发短语（中英文）。
- 本目录名 `treatment` 为评测装置固定；若真实发布为技能包，目录名须改为与 `name` 一致的 `weekly-report`（agentskills.io 规范，成品声明中已注明）。

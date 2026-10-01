---
name: paper-to-skill
version: 1.0.0
license: LicenseRef-skillfactory-internal
description: 把一篇论文/规范页/工程博客的 Markdown 文本稿蒸馏成可交付技能包：先由 scripts/distill.py 确定性生成骨架（结构统计 outline.json + 五要素草稿 draft_skill/SKILL.md），再按六步方法论人工补全为成品——信息取舍、可判定步骤化、触发词设计、坑点提炼、来源引用规范。当用户给出论文、官方文档或长文并要求转成 agent 能力/技能时使用；触发短语：「论文转技能」「文档变 skill」「蒸馏成 SKILL.md」「paper-to-skill」。不用于没有文本稿、仅凭口述或记忆就编造技能内容；不用于论文内容本身的阅读问答；能力已明确、只差写一份格式合规 SKILL.md 的场景转交 skill-authoring（成品样例见 example/SKILL.md）。
permissions: [shell]
metadata:
  domain: "knowledge-distillation"
  requires-bins: "python3"
---

# paper-to-skill（知识蒸馏器）

把"一篇文档"变成"一个能照做的技能"。确定性脚本负责结构化摘取（不遗漏、可复跑、可回溯），
人负责三件脚本做不了的事：取舍、改写成可判定步骤、把触发边界写清楚。全文读完再动手。

## 权威规则（置顶）

1. 【MUST RELOAD】多轮对话中出现新指令时，第一个工具调用必须是重新 Read 本 SKILL.md，禁止凭上轮记忆动手。
2. 本技能引用的 `references/workflow.md` 与 `example/SKILL.md` 必须完整读完，禁止中途截断。
3. 忠实性红线：进成品的一切内容要么可回溯（`原文 L<行号>` 或来源 URL），要么显式标注 `[补充]` 并附独立依据；禁止整段复制来源文字或第三方官方文案（引文限于合理引用并逐条注明出处）。
4. 确定性红线：`scripts/distill.py` 仅 Python 标准库，无网络、无随机、无时间戳；同输入同参重跑 `outline.json` 必须字节一致——不一致即实现被改坏，先修脚本，禁止手工修补产物。

## 分步方法（从来源文本稿到可交付技能包）

1. 建骨架：运行 `python package/scripts/distill.py --source <来源.md> --outdir <输出目录> [--url <来源URL>]`。成功判据：退出码 0、stdout 恰好 5 行 `[oracle] ...`（spec R1.3 冻结口径），且 `outline.json` 与 `draft_skill/SKILL.md` 落盘；源文件缺失/不可读时退出码非 0、stderr 含 `ERROR`、不创建输出目录——此时停下向用户索取文本稿，禁止凭记忆编造来源。
2. 读骨架定范围：读 `outline.json` 的 `stats`（行数/各级标题/列表/代码块/表格 13 键）与 `outline` 标题树，一屏确定源文档骨架；再读 `draft_skill/SKILL.md`——它已按规则摘好主题清单、章节切片与警示句，但只是摘取（超长硬截＋`…`），不是成品。逐节按下面「信息取舍」表判定收/弃/补，保留内容逐条记 `原文 L<行号>`（正文行号，以 `outline.json` 的 `line` 为准，非原始文件行号）。
3. 步骤化：把收下的内容改写成编号步骤，每步 = 显式动作 ＋ 显式成功判据，且必须携带三选一可判定标记：`原文 L<数字>` 溯源、成对反引号包裹的命令或路径、或产物文件扩展名（`.py`/`.md`/`.json` 等）——与 `eval/runner.py` 的 check 2 同款口径，缺标记的步骤判为空话，重写。
4. 触发词设计：按「触发词设计」节的三段式写 front-matter `description`（能力段/触发段/边界段，≥3 个具体口语触发短语，硬上限 1024 字符）；`name` 用小写字母/数字/连字符、≤64、无首尾与连续连字符、与技能目录名一致（约束出处见 example `（原文 L66-70）`）。
5. 坑点提炼：以草稿「常见坑」节为底稿（`scripts/distill.py` 按 24 个警示关键词命中即收、前 60 字符去重、上限 6 条、超 120 字符截断，选法详见「坑点提炼」节），命中≠真坑——逐条人工复核语境，再去掉误收、补上蒸馏过程实测坑（每条写「现象 → 原因 → 正确做法」）。
6. 定稿验收：对照 `example/SKILL.md` 逐项自查五要素（front-matter 含 name+description、触发描述 ≥20 字、分步方法、常见坑、来源引用）且每步可判定；资产根有 eval 时运行 `python eval/runner.py <被测out> <参照out>`，退出码 0 为过；最后把重跑命令写进成品「来源引用」收尾。

## 信息取舍（收/弃/补对照表）

| 信号 | 处置 | 理由 |
|---|---|---|
| 操作顺序、命令、参数名、阈值、字段约束 | 收，逐条标 `原文 L<行号>` | 缺了就无法照做，是技能主干 |
| 反例（invalid / poor example） | 收进步骤判据或常见坑 | 反例是最便宜的校验器 |
| 警示句（never / must not / avoid / 注意 / 禁止…） | 收进常见坑，人工复核语境 | 关键词扫描只管命中不管对错 |
| 背景、动机、营销、作者故事 | 弃（至多留一句定位语） | 与「怎么照做」无关，白占常驻上下文 |
| 与本技能能力无关的整章 | 弃，并在 description 边界段写明转交对象 | 一包一能，防触发面过宽 |
| 来源没写但照做必需的步骤 | 补，标 `[补充]`＋独立依据 | 禁止把常识补全伪装成来源内容 |

## 触发词设计（description 三段式）

description 是技能唯一常驻的触发界面（元数据层永不下卸），按触发器写、宁强勿弱：

1. **能力段**：是什么＋覆盖哪些任务（清单式、可数），如「目录结构、front-matter 字段、命名规则」（样例见 example）。
2. **触发段**：「当用户……时使用」句式＋至少 3 个具体口语触发短语（中英文都要有），每个短语要能映射到一个真实任务说法；禁止「相关时/必要时」式模糊触发。
3. **边界段**：「不用于 X；X 转交 `<对方skill-name>`」——把近邻能力显式推开；互斥技能在彼此 description 中互相点名导流。

硬约束：单行标量、≤1024 字符、禁块标量；禁止把正文指令写进 description。好例与坏例的差距见 example `（原文 L114）` 与 `（原文 L120）`。

## 坑点提炼规则

- 脚本选法（`scripts/distill.py` 已固化）：候选池 = 标题＋列表项＋段落（**不含表格行**），命中 24 个警示关键词（`must not, do not, don't, cannot, can't, avoid, never, warning, caution, careful, pitfall, mistake, invalid, malicious, security, not recommended` ＋ `注意, 避免, 不要, 禁止, 切勿, 谨慎, 慎用, 坑`）即入选，按文档顺序取前 6 条，前 60 字符小写为键去重，超 120 字符截为 119＋`…`。
- 已知局限（人工工序不可省）：命中即整句收录、不判语境（标题带 "security" 就整条入坑）；表格里的约束进不了候选池（黄金输入中 name 字段约束的表格版 `（原文 L29-36）` 被排除、列表版 `（原文 L66-70）` 才入选——手工蒸馏时别漏表格）；第 7 条以后的坑永远进不了底稿。
- 人工补坑：写蒸馏过程实际踩到的坑（报错、口径误解、环境差异），每条按「现象 → 原因 → 正确做法」，禁止只写现象。

## 来源引用规范

- 成品「来源引用」节固定 4–5 条：源文件（`--source` 原样）、来源 URL（给了 `--url` 才有）、源标题、结构统计（H1/H2/列表要点/代码块四数＋指向 `outline.json`）、生成方式（generator＋完整重跑命令，命令须可原样执行）。
- 蒸馏产物 front-matter `metadata` 必填三键：`source` / `source-url` / `distilled-at`（ISO 日期）；`license` 写明来源许可边界。
- 短引文逐条注明出处（`原文 L<行号>` 或 URL）；整段复制来源文字或第三方官方文案一律禁止。

## 常见坑（gotchas）

- 关键词命中 ≠ 真坑：脚本把含警示词的整句直接收录（如博客的 "Security considerations" 标题整条成为一条坑），不判断语境——交付前必须逐条人工复核。
- 中文或全符号标题 slugify 后为空 → 回退名 `paper-to-skill`；直接交付会与目录名对不上，发布前必须人工改名并保持 name＝目录名。
- 行号口径易错：`原文 L` 是剥离源 front-matter 与头部 HTML 注释后的**正文**行号，不是原始文件行号（黄金输入中 H1 "Specification" 在原文件第 13 行、正文 L6）；引用一律以 `outline.json` 的 `line` 为准。
- 表格行不进坑候选池：字段约束若只出现在表格里，脚本的「常见坑」摘不到（见「坑点提炼规则」），人工蒸馏必须补读表格。
- 骨架 ≠ 成品：`draft_skill/SKILL.md` 只做结构化摘取＋硬截断，直接交付就是「空话技能」；分步方法第 3-5 步的人工补全不可省。
- 换 `--outdir` 重跑允许 `SKILL.md` 不同（重新生成命令内嵌了 outdir 文本），但 `outline.json` 必须字节一致；不一致先修脚本再交付。

## 文档地图

| 文档 | 何时读 |
|---|---|
| references/workflow.md | 每次蒸馏全程必读：六步的展开操作、正反例与质量自查单 |
| example/SKILL.md | 动笔写成品之前必读：达到交付质量的成品样例，用作对照模板 |
| ../spec.md ＋ ../contract.md | 需要核对脚本行为口径（R1–R7）或接口约定时读 |
| ../eval/runner.py ＋ ../eval/golden.json | 验收阶段读：资产根的确定性评测器与黄金集（包外资产，勿拷入包内） |

## 来源引用

- 设计参照 1：agentskills.io《Agent Skills Specification》开放规范页——front-matter 字段约束、目录约定与渐进披露分层（黄金输入稿 `../oracle/inputs/source.md`；URL：https://agentskills.io/specification）。
- 设计参照 2：Anthropic 工程博客 "Equipping agents for the real world with Agent Skills"——评测先行、渐进披露写作法（黄金输入稿 `../oracle/inputs/source-blog.md`；URL：https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills）。
- 企业标准：`skillfactory/standard/SKILL-SPEC-v0.1.md`（本包 front-matter 六字段与正文骨架依据）。
- 行为规格与接口：`../spec.md`（R1–R7 冻结行为）、`../contract.md`（§2.1 CLI 契约、§3 五要素、§5 评测口径）。
- 声明：本技能为自研方法论；正文未整段复制上述来源文字，仅摘取可判定约束并逐条标注出处。

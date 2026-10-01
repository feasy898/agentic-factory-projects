# KIT-SPEC v0.1 — 专用 agent 配置包（agentkit）范式

| 项 | 值 |
|---|---|
| 文件 | `skillfactory/v2/agentkit/KIT-SPEC.md` |
| 版本 | v0.1（2026-09-29） |
| 上位文档 | 评测继承 `skillfactory/v2/standard/EVAL-SPEC-v0.2.md`（尤其 §6.3 整包 kit 评测）；形态定义沿用 `skillfactory/v2/TAXONOMY.md` §四「agent配置」与「plugin」 |
| 适用范围 | `skillfactory/v2/agentkit/` 下全部 kit：面向单一任务域的专用 agent 配置包的定义、全量件清单、按任务配置方法与验收门 |
| 首个实例 | `OFFICE-KIT/`（办公文档生产力，v0.1） |
| 证据纪律 | 沿用 EVAL-SPEC v0.2：**【实访】**=本轮亲自访问外部页面；**【盘内】**=本轮实际读取的本地文件；**【清单口径】**=转引 CATALOG/前一采集轮。未核实项一律如实声明 |

---

## 0. 范式来源（含「找不到指定仓库」的如实说明）

### 0.1 指定来源的核实结果

任务指定「GitHub 搜 alibaba/cloud-agent-handbook」。本轮实际执行：

1. WebSearch `alibaba cloud-agent-handbook github`（2026-09-29）：**不存在**名为 `cloud-agent-handbook` 的阿里仓库；搜索命中的最接近官方权威是 **[aliyun/ai-agent-handbook](https://github.com/aliyun/ai-agent-handbook)**（阿里云官方 Agent 构建白皮书仓，Apache-2.0）。
2. WebFetch 实访该仓根页与 `02-build/` 目录页（2026-09-29，两次均成功）。

### 0.2 aliyun/ai-agent-handbook 的组件范式（两次实访所见）

该白皮书 30 章，分六篇：00 前言 / 01 架构篇（第 1–2 章）/ **02 构建篇（第 3–6 章）** / 03 运行篇（第 7–12 章）/ 04 治理篇（第 13–16 章）/ 05 调优篇（第 17–24 章）/ 06 实践篇（第 25–29 章）/ 07 总结篇（第 30 章）。构建篇以 **Harness** 为核心概念，组织三条主线：

| 主线 | 组件（实访所载章节要点） |
|---|---|
| **任务** | Agent Loop、任务状态机、阶段门禁；编排、长程推进与协作流转（第 4 章） |
| **信息** | Context Builder、Session、Task State、Workspace、**Memory**、Knowledge、**Skill**（第 5 章） |
| **行动** | Action Plane、Function Calling、**MCP**、A2A、权限、HITL（第 6 章）；运行时与沙箱（第 7 章） |

评测在调优篇（**黄金数据集**第 21 章、**轨迹评估**、**LLM-as-Judge**）与治理篇（上线前仿真第 16 章、可观测性第 13 章）。

**如实说明的局限**：该白皮书是**企业架构视角**，没有把 hooks、slash commands、插件、系统提示词等 Claude Code 式配置件作为章节主题——它给骨架，不给配置件接口。

### 0.3 兜底条款的执行：骨架 + 落地件

按任务兜底条款「找不到就以实际找到的权威 agent 配置范式替代并注明」，本范式采用：

- **骨架**（组件怎么组织）：aliyun/ai-agent-handbook 的 Harness 三主线【实访，§0.2】；
- **落地件**（每件长什么样、接口是什么）：
  - 入口件 = **AGENTS.md 开放规范**（agents.md："A simple, open format for guiding coding agents…Think of it as a README for agents"，单文件 Markdown、无必填字段、monorepo 嵌套就近生效）【盘内：`TAXONOMY.md` 锚 6，2026-09-29 前轮实访记录】；
  - 技能件 = **Agent Skills 开放标准**（agentskills.io，SKILL.md frontmatter+渐进披露）与 **modelcontextprotocol/ext-skills**（Skills over MCP，SEP-2640 已 Final——skill 与 MCP 两条路线正在合流）【盘内：`TAXONOMY.md` 锚 5；`CATALOG.md:39` A1.3 清单口径】；
  - 护栏件 = **Claude Code Hooks 官方参考**（33 种 hook 事件；三层配置 事件→matcher→handler；5 种 handler：command/http/mcp_tool/prompt/agent）【盘内：`TAXONOMY.md` 锚 7，前轮实访记录，口径以官方 33 事件为准】；
  - 插件件 = **anthropics/knowledge-work-plugins** 的四件套目录结构（`.claude-plugin/plugin.json` 清单 + `.mcp.json` 连接器 + `commands/` 斜杠命令 + `skills/` 技能）【盘内：`v2/evalbench/knowledge-work-plugins/ASSET-DOC.md:60-71`，2026-09-29 抓取轮实访记录，本轮复读】；
  - 工具件 = **MCP 官方生态**（`CATALOG.md` A4 段 24 条：参考实现/任务域 server/网关/注册表）【盘内】；
  - 评测件 = 本厂 **EVAL-SPEC v0.2**（双臂盲评、复合线、§6.3 整包 kit 评测）【盘内】。

> 一句话范式：**kit = 把 Harness 的「信息件（提示/技能/知识/记忆）+ 行动件（MCP/工具/沙箱/权限）+ 护栏件（hooks）+ 入口件（AGENTS.md/commands）+ 评测件」按固定目录结构打成一份可分发、可整包评测的资产。**

---

## 1. 定义与定位

### 1.1 什么是专用 agent 配置包（kit）

**kit 是面向一个任务域的专用 agent 的全部配置件 + 一份「按任务配置」说明书的打包资产。** 判定标准（三条同时满足）：

1. **域集中**：全部件服务于同一任务域（如办公文档生产力），不做跨域大杂烩；
2. **可装配**：拿到 kit 的人按 AGENTS.md 的指引能把专用 agent 在目标 harness（Claude Code / zcode / 兼容 AGENTS.md 的客户端）里装配起来，路径全部 kit 内相对引用；
3. **可整包评测**：存在 EVAL.md 定义的双臂验收方案（treatment=完整 kit，baseline=同 kit 去配置件），对接 EVAL-SPEC v0.2 §6.3。

### 1.2 kit 与单件资产的关系

- 单件资产（skill/MCP/hook/command…）按 `TAXONOMY.md` 单形态验收，各自过五门；
- kit 是**组合资产**：它引用单件而不重复实现单件；kit 的增值在「选件决策 + 件间协作流程 + 域红线」，因此 kit 的验收单位是**整包**（EVAL-SPEC §6.3），不是逐件重复验收；
- kit 引用的单件必须标注**验收状态**（accepted / 确定性门过但盲评未达线 / 返工中…），状态变化时 kit 升版本。

---

## 2. 全量件清单（9 件）

> 每件给出：**作用 / 配置要领 / 选配决策规则**。「必配」指该 kit 声明的任务域下缺件不成立；「选配」按决策规则判定。

### 2.1 系统提示 · AGENTS.md（角色定义）

- **作用**：专用 agent 的入口件与宪法——角色、使命、工作流程、红线、产物规范、件索引。对齐 AGENTS.md 开放规范（单文件 Markdown、就近生效）【盘内：TAXONOMY 锚 6】；对齐 aliyun 手册「信息主线」中上下文装配的顶层件【实访：§0.2】。
- **配置要领**：①角色一段话说清「为谁、做什么、交付什么」；②工作流程写成**可判定的步骤**（每步有输入/动作/成功判据——对齐 meeting-minutes「写后回读三态」的 verified 口径【盘内：`assets/meeting-minutes/package/SKILL.md:57`】）；③红线**少量、可机判**（技能红线直接引用不转述，防双源漂移）；④全部路径 kit 内相对引用；⑤不做的事（边界）显式列出。
- **决策规则**：**必配**，且是 kit 唯一的强制入口件。多角色/多子代理需求出现时，才拆子代理定义文件（选配，见 §2.8）。

### 2.2 skills（技能）

- **作用**：域内可复用的程序性能力封装（对齐 agentskills.io SKILL.md 标准：frontmatter 描述触发时机，正文给规则与步骤）【盘内：TAXONOMY 锚 5】；对应 Harness「信息主线」的可复用能力资产【实访：§0.2】。
- **配置要领**：①kit 不复制技能正文，用 **skills.manifest** 引用：路径、版本、验收状态、用法、必装/选装；②主力技能必须是**验收状态最好**的（优先 accepted，至少确定性门过）；③每个技能注明「何时不用」（边界），防误触发；④技能间的**协作次序**写进 AGENTS.md 工作流程（谁先谁后、产物如何交接）。
- **决策规则**：任务存在**重复出现的程序性套路**（同样输入形态→同样产物规范）→ 必配并优先自产已验收件；无既有技能且套路未稳定 → 不配（用 AGENTS.md 写轻量流程即可），先沉淀技能再入 kit。

### 2.3 MCP servers（外部工具）

- **作用**：给 agent 挂真实世界的读写工具（文件/表格/文档/邮件/协同），对应 Harness「行动主线」【实访：§0.2】。选件从 `CATALOG.md` A4 段与 B 段任务域条目取，不自创目录外条目【盘内】。
- **配置要领**：①manifest 注明每台 server 的**理由、目录出处、挂载命令、安全机制**（如 excel-mcp-server 的 `--allow-dir` 目录沙箱、公式白名单、只读模式【盘内：`v2/evalbench/excel-mcp-server/ASSET-DOC.md:97-102,229-235`】）；②**读写分离**：只读场景一律挂只读模式；③写类工具默认进「ask」级权限（对齐 knowledge-work-plugins「发送/发布/写入类工具设为 ask」的官方建议【盘内：knowledge-work-plugins ASSET-DOC.md:126】）；④注明维护状态（归档仓如实标注，如 Office-Word/PPT-MCP-Server 2026-03 已归档但 uvx 仍可装【盘内：CATALOG.md:148-149】）。
- **决策规则**：agent 需要**读/写 kit 之外的真实系统**（Excel/Word/PPT/邮件/飞书）→ 必配对应任务域 server；纯文本进出任务（转写文本→Markdown 纪要）→ **不配**（内置读写文件已够，MCP 只添攻击面与安装负担）；外发自动化（发邮件/发消息）→ 选配网关型（Zapier MCP/Composio）且必须配 hooks 拦截（§2.4）。

### 2.4 hooks（护栏）

- **作用**：在生命周期事件上做**确定性护栏**——产物落盘校验、敏感信息拦截、危险命令阻断、审计留痕。接口面 = 官方 33 事件 × 5 handler，三层配置【盘内：TAXONOMY 锚 7】。这是「模型不可靠处用代码兜底」的件，也是 gaps #8（办公场景护栏 hook）的载体【盘内：CATALOG.md:446】。
- **配置要领**：①hook 判定逻辑用**脚本/正则**写死，不依赖模型自觉；②拦截类 hook（PreToolUse）返回非零退出即阻断，**必须**在输出里给用户可读原因；③校验类 hook（PostToolUse）遵循「写后回读三态」：文件存在+内容结构对+数值一致才算 verified；④sample 与启用分开：`hooks.sample.json` 只给样例，启用是宿主端配置动作，kit 文档写清装载位置。
- **决策规则**：任务产物有**硬性格式/合规要求**（落盘校验、敏感词、外发确认）→ 必配；一次性探索任务 → 不配。原则：**每条红线配一个 hook，模型负责遵守、hook 负责验证**。

### 2.5 slash commands（显式入口）

- **作用**：把 kit 的高频工作流固化为一键入口（对齐 knowledge-work-plugins 的 `commands/` 件与 `/sales:call-prep` 调用式【盘内：knowledge-work-plugins ASSET-DOC.md:64,52-56】；分类法可循「Workflow（编排）/Tool（单点）」二分【盘内：CATALOG.md:80】）。
- **配置要领**：①一个命令 = 一个**完整可交付的工作流**，正文写清参数（$ARGUMENTS）、前置条件、调用哪些技能/脚本、产物落到哪；②命令数宁少勿多——每个命令必须在 EVAL.md 里有验收路径；③命令是「显式入口」，与 skills 的「自动触发」互补，不重复封装同一逻辑（命令引用技能，不重写规则）。
- **决策规则**：任务域存在 **≥2 个高频固定工作流** → 必配；单一任务域只有一个动作 → 不配（AGENTS.md 工作流已够）。

### 2.6 plugin（插件壳，选配）

- **作用**：当 kit 需要**一条命令安装、跨用户分发**时，把全部件装进插件壳（对齐 knowledge-work-plugins 四件套与 marketplace.json 分发机制【盘内：knowledge-work-plugins ASSET-DOC.md:60-71,140】；「一份源码多端分发」范式见 wshobson/agents【盘内：CATALOG.md:73】）。
- **配置要领**：manifest（plugin.json）、连接器（.mcp.json）、commands/、skills/ 四目录；纯 Markdown/JSON、无构建步骤【盘内：knowledge-work-plugins ASSET-DOC.md:18】。
- **决策规则**：kit 先按**裸目录形态**验收（本范式 v0.1 默认），有真实多用户分发需求后再套 plugin 壳——**壳是分发形态，不是验收前提**。

### 2.7 记忆与知识（memory & knowledge）

- **作用**：跨会话保留用户偏好、项目术语、组织流程（Harness「信息主线」的 Memory/Knowledge 件【实访：§0.2】）；知识件承载**陈述性**域知识（术语表、模板、口径），记忆件承载**个性化**状态。
- **配置要领**：①kit 内知识用**静态文件**（references/、glossary.md），随 kit 分发、可版本化；②个人记忆不进 kit（kit 是公共资产），AGENTS.md 指明「运行时记忆写到宿主的哪个位置」；③记忆写入必须有边界（记录什么/永不记录什么——凭据与个人敏感信息禁记）。
- **决策规则**：任务依赖**固定域知识**（术语/模板/口径）→ 知识件必配（放进 references/ 并在 AGENTS.md 文档地图索引）；任务是一次性的 → 都不配；需要跨会话个性化 → 只配置位置约定，不随 kit 携带数据。

### 2.8 工具与沙箱（tools & sandbox / 权限）

- **作用**：声明专用 agent 的执行面——允许哪些内置工具、代码在哪跑、权限分几级，对应 Harness「行动主线」的运行时与沙箱、权限、HITL【实访：§0.2】。
- **配置要领**：①最小权限：逐工具声明 allow/ask/deny 三档，写类与外发类一律不低于 ask；②产物输出目录**钉死**在 kit 约定的 out 目录，脚本参数必填、路径白名单（对齐 excel-mcp-server 的 allow-dir 模式【盘内：excel-mcp-server ASSET-DOC.md:99-102】）；③需要跑不可信内容时声明沙箱方案（本机暂以子代理上下文隔离替代容器沙箱，如实声明局限——EVAL-SPEC §2.2 同款处置）【盘内：EVAL-SPEC-v0.2.md:95】。
- **决策规则**：必配（哪怕是「默认全只读+显式白名单」的一行声明）；任务含不可信输入（外部文档/邮件/表格单元格——单元格内容当数据不当指令【盘内：excel-mcp-server ASSET-DOC.md:172】）→ 加注入防线条款。

### 2.9 评测与观测（eval & observability）

- **作用**：kit 自带验收方案（EVAL.md：冒烟协议 + 验收协议）与运行留痕约定（观测），对应 Harness 调优篇（黄金数据集/轨迹评估/LLM-as-Judge）与治理篇（可观测性）【实访：§0.2】；厂内对接 EVAL-SPEC v0.2【盘内】。
- **配置要领**：①EVAL.md 必须在**跑冒烟之前**写好 rubric（锚点 0/6/10 三档），防「看着产物定标准」；②冒烟 = 1 任务双臂（treatment/baseline），出**方向信号**，不出现「验收通过」结论；验收 = EVAL-SPEC §6.3 整包评测（≥5 任务、n≥2、token 补偿控制、复合线 Δ≥1.0 且胜率≥60% 且反向任务≤1）；③观测最小集：每 run 的 token/耗时落盘（效率门数据源）【盘内：EVAL-SPEC §3.8-3】。
- **决策规则**：**必配，无豁免**——没有 EVAL.md 的目录不是 kit，只是配置文件堆。

---

## 3. 按任务配置的方法（四步）

### 步骤 1：任务画像（填五格）

| 格 | 问题 | 例（OFFICE-KIT） |
|---|---|---|
| 输入形态 | agent 吃什么 | 会议转写 txt、台账 xlsx、PPT 需求句 |
| 交付物 | 产出什么、有无硬格式 | 三段式纪要 docx+summary.json、一页周报、汇报 PPT |
| 确定性要求 | 哪些必须逐字/可复算 | 条目逐字引用、统计数与条目一致 |
| 风险面 | 错了伤什么 | 纪要里编造负责人、产物带敏感信息外发 |
| 运行环境 | 在哪跑、有什么 | 本机 Windows + python3；宿主 zcode/Claude Code |

### 步骤 2：选件矩阵（逐件过 §2 决策规则）

对 9 件逐条判「必配 / 选配 / 不配」并在 kit 的 README 或 AGENTS.md 尾部落一行**选件理由**（例：本 kit 文本进出为主 → MCP 全部选配；产物有硬格式+合规面 → hooks 必配）。矩阵结论变更 ⇒ kit 版本 bump。

### 步骤 3：装配（固定目录骨架）

```
<KIT-NAME>/
├── AGENTS.md            # 入口件（必配）：角色/流程/红线/件索引
├── skills.manifest      # 技能件索引（引用路径+状态+用法）
├── mcp.list             # MCP 选件与挂载建议（含理由与安全注记）
├── hooks.sample.json    # 护栏样例（sample，启用在宿主端）
├── commands/            # slash 命令（每文件一命令）
├── references/          # 域知识件（可选：术语/模板/口径）
└── EVAL.md              # 评测与观测件（冒烟+验收协议）
```

装配纪律：全部路径 kit 内相对引用；引用外部资产必须带**验收状态**；AGENTS.md 引用 skills.manifest，skills.manifest 引用技能本体——**单向引用，禁止循环**。

### 步骤 4：评测验证（两级）

1. **冒烟级**（本范式新增，出信号不出结论）：1 条任务域代表任务，双臂（treatment=挂 kit，baseline=裸做+禁读 kit/资产），同模型同通道同任务文本，唯一差异=资产挂载（EVAL-SPEC §4.2 同款纪律）；裁判按 EVAL.md 预写 rubric 盲评 0–10；结果记 `single_round_signal: true`。
2. **验收级**：EVAL-SPEC v0.2 §6.3 整包 kit 评测——treatment=kit 完整，baseline=同 kit 去配置件+**token 补偿**（等量中性占位文档），任务 ≥5 条、每臂 n≥2、甲乙轮换、裁判复评抽检，复合线三条件（Δ≥1.0 / 任务级胜率≥60% / 反向任务≤1）全过方可标 `kit-accepted`；对外引用数字遵守「数字四随」【盘内：EVAL-SPEC §3.6/§3.7/§6.3】。

---

## 4. 首个实例与已知局限

- 首个 kit：`OFFICE-KIT/`（办公文档生产力）。其选件矩阵结论：AGENTS.md/skills/hooks/commands/EVAL 必配，MCP 以 mcp.list 选配（冒烟任务为文本进出，不实装），plugin/记忆/沙箱不配（理由见 kit 内文件）。
- 已知局限（如实）：①骨架来源 aliyun/ai-agent-handbook 为架构白皮书，配置件接口面来自 Claude Code 系官方规范【盘内：TAXONOMY 锚 6/7】，两者不是同一家的自洽体系，组合方式是本厂决策；②锚 5/6/7 的外部实访发生在 2026-09-29 前轮（本轮转引盘内记录，未重访）；③冒烟级为 1 任务 × 每臂 1 次，统计效力为零，仅验证「kit 可装配、方向有信号」。

---

## 5. 证据索引（本轮）

**【实访】（本轮 WebFetch，2026-09-29）**：`github.com/aliyun/ai-agent-handbook` 根页（章节结构/Harness 三主线/评测章节定位）；`github.com/aliyun/ai-agent-handbook/tree/main/02-build`（第 3–6 章标题原文）。WebSearch 确认无 `alibaba/cloud-agent-handbook` 仓库。
**【盘内】（本轮实读）**：`skillfactory/v2/TAXONOMY.md`（锚 1–7、形态横轴）；`skillfactory/v2/CATALOG.md`（A2/A4/B1 段、gaps #4/#6/#7/#8）；`skillfactory/v2/standard/EVAL-SPEC-v0.2.md`（§2.2/§3/§4/§6.3）；`skillfactory/v2/leaderboard/LEADERBOARD.md`（8 资产盲评状态：仅 lark-cli 中期信号通过）；`skillfactory/report/DELIVERY.md`（4 资产验收状态：仅 meeting-minutes 接受）；`assets/meeting-minutes/package/SKILL.md` 全文；`assets/monthly-report-ppt/package/SKILL.md`、`assets/ppt-method-router/package/SKILL.md`（头部）；`v2/evalbench/{excel-mcp-server,knowledge-work-plugins,lark-cli}/ASSET-DOC.md`。
**【清单口径】（转引前轮采集，本轮未重访）**：agentskills.io、agents.md、Claude Code Hooks 官方文档的原文口径（均见 TAXONOMY 锚表）。

*KIT-SPEC v0.1 完。修订记录：v0.1（2026-09-29）首版，随 OFFICE-KIT 冒烟同轮产出。*

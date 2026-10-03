# 资产形态与国际标准 · 思考轨迹（GLM-5.3-Flash · 2026-10-03）

> 镜头：资产形态学与国际标准。核心问题：我们的「资产」应有哪些形态、按什么标准设计、如何组合成更大的通用资产？
> 本文是思考轨迹（推理过程 + 证据 + 带置信度的倾向性判断），不是成品规划。所有行号引用基于 D:/new-workspace/agent-asset 本盘当前状态。

---

## 1. 展开方法：我怎么拆解这个问题、信息源清单

### 1.1 问题拆解

从人类意图逐字稿里，本镜头必须回答的其实是一个三段式问题：

1. **有什么形态**——owner 说「形态包括 skill、MCP、agent 设置本身等」，这个「等」字必须展开成封闭清单还是开放清单？
2. **按什么标准设计**——「skill / MCP 设计必须符合现行国际通行标准」（意图 6c）这句话有两层：a) 我们的资产要能在客户的 agent 上装得上、跑得动；b) 标准本身在动（我必须查证 2026 年 10 月的「现行」是什么，而不是凭训练记忆）。
3. **如何组合**——意图 6c 要求「一个任务类型可以多资产混用也可分开；可以有特定方向 skill，也可以把方向 skill 结合成大的通用 skill」。这要求我给出组合模式，并且用盘内证据检验哪些组合方式被证明有效。

再叠加两个交付约束：资产要交给非开发者学员（安装/运行/自愈），最终要落成「资产规格 v1」草案要点。

### 1.2 信息源清单

**仓库文件（本轮全部亲读，只读）**：

| 文件 | 取用点 |
|---|---|
| `BASELINE.md` | 范围声明（:6）、§2 行 19-22（v5 评测全绿 + 红路 fail-closed A 级）、§3.6（zcode-research 基线卡：评测口径=产物根对 oracle、acceptor-agent 未被评测）、§8（修复路径） |
| `afp-clone/zcode-research/README.md` | :10 owner 口径（带着学员走一遍真实交付=收费逻辑）、:17 架构一句话（三齐口径）、:26-33 验收基线 8 门 |
| `afp-clone/zcode-research/TASK.md` | :23-26 G0-1~G0-4 产线底线、:30-38 K 线课堂交付层、:71-74 S-彩排（零上下文学员、盲态禁读）、:76 红线（红路永不修成 exit 0） |
| `afp-clone/zcode-research/worklog.md` | :19-22 R6-R10（zctl-mcp/acceptor-agent 扩线、双臂盲评 n=2、P-2 复核、总复核）、:24 R11（K-5 实物闭环、NUL 清理、安全分诊） |
| `afp-clone/zcode-research/skillfactory/REGISTRY.md` | :5 三齐口径原文、:14-16 三个 dist 包（形态=skill 包、front-matter、盲评 Δ）、:27 ppt-method-router（**路由对但端到端零增益**）、:162-164 v5 三件（体检 C 形态错配）、:191-194 两新形态首批（MCP/agent 定义）、注 1（体检器 5 项按 dist skill 包形态设计，对其他形态不适用） |
| `skillfactory/v2/standard/EVAL-SPEC-v0.2.md` | §4.4 模型钉版五元组与「装置变更⇒分数不可比」、§6 多形态适配四路径（文本直评/doc-gain/整包 kit/自指）、§7.1 六门一览、§8.1 benchmark.json schema、附录 A 对照表 |
| `skillfactory/v2/TAXONOMY.md` | :178-197 形态横轴 14 形态定义与锚定（agentskills.io / MCP / hooks 33 事件 / AGENTS.md）、:180「每资产记 1 个主形态，多形态能力写进能力字段」 |
| `skillfactory/v5/assets/hotwords/spec.md` | 全文：G1-G4 目标表、R1-R9 行为冻结（R7 中文报错）、A.1-A.8 常量全文披露（E-1 条款落地样例） |
| `skillfactory/v5/assets/hotwords/package/SKILL.md` | skill 文档面实物：渐进式知识注入 + CLI 用法，front-matter 仅 name+description |
| `skillfactory/v5/assets/speaker-mapping/contract.md` | :4「接口冻结，实现自由」、:40「仅 Python 标准库；无网络、无随机、无时间戳」 |
| `skillfactory/v5/assets/deploy-pack/spec.md` | 生成器+校验器双件套结构、C1-C7 校验器、检查 4 行级归一化（CRLF→LF、BOM 容忍）:162、§4 不内嵌期望常量的声明 |
| `skillfactory/v5/assets/zctl-mcp/{spec,contract}.md, package/INSTALL.md` | MCP 形态实物：只读 4 工具 + forbidden 名单（contract F1-F4）、protocolVersion 2024-11-05、INSTALL.md 配置片段 |
| `skillfactory/v5/assets/acceptor-agent/{spec,contract}.md, package/agent.md` | agent 设置形态实物：职责/输出契约/禁令三节 + verdict JSON schema + 盲评样本 blind/ |
| `skillfactory/classroom/walkthrough.md` | :9-22 环境自检、:38-49 红路自检进课堂、:188 scratch 红线（禁在 oracle/ 原地跑） |
| `skillfactory/dist/{meeting-minutes-skill,office-templates-skill,hot-templates-skill}/SKILL.md`（头部） | front-matter 实物：name/version/license/description/permissions + metadata |
| `skillfactory/dist/meeting-minutes-skill/` 目录列表 | 分发包形态实物：SKILL.md/eval/reference(s)/scripts/requirements.txt/MANIFEST/EVALUATION/CHANGELOG/LICENSE |

**Web 查证（本轮亲查，2026-10-03 访问）**：

| 来源 | 取用点 |
|---|---|
| https://agentskills.io/specification | SKILL.md 规范全文：字段表、目录约定、渐进披露三层、500 行建议、skills-ref validate |
| https://agentskills.io/clients | 客户端展示页（JS 数据内联，读取到 45+ 客户端全名单） |
| https://modelcontextprotocol.io/specification/2025-06-18 | MCP 基元（resources/prompts/tools + sampling/roots/elicitation）与安全原则 |
| https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle | 确认 2025-11-25 修订存在：tasks capability、elicitation form/url 模式 |
| WebSearch×5 | MCP 2025-06-18 修订要点（streamable HTTP 取代 HTTP+SSE、structured tool output、OAuth 2.1、JSON-RPC batching 移除）；2025-11-25 头部特性 Tasks（SEP-1686 异步执行）；.mcpb 打包与官方 Registry（preview 自 2025-09-08、server.json、API v0.1）；Agent Skills 采纳与治理（AAIF）；A2A v1.0/Agent Card/AAIF |
| https://code.claude.com/docs/en/sub-agents | 子代理定义格式：frontmatter name/description 必填 + tools/model 等可选、.claude/agents/ 与 ~/.claude/agents/ 目录 |

### 1.3 走过的弯路（如实记录）

- **弯路一**：最初想拿「skill / MCP / agent 设置」三分法直接套 v5 五资产，发现套不上——hotwords 的 SKILL.md 只是知识文档，真正的交付物是 CLI 工具 + 冻结行为契约；REGISTRY 里它的形态写的是「skill+CLI 工具」。结论：**产线视角必须用「主形态 + 能力字段」的二维记账**（这正是 TAXONOMY.md:180 自己的结论），规格 v1 不能只有单形态模板。
- **弯路二**：第一反应建议「把 zctl-mcp 立即升级到 MCP 2025-11-25」。深想后修正：zctl-mcp 是工具/基建件，不在课堂首批教学路径（walkthrough 三课=SM/DP/HW），升级收益低、且契约冻结意味着要重走 eval 红绿矩阵。降级为「低优先债务」而非近期动作。
- **弯路三**：一开始把「组合」理解为「合并成一个大 skill」的技术问题。REGISTRY.md:27 的 ppt-method-router 盲评数据（路由一致率 1.0 但 Δ0/胜率 33%）把我纠正过来：**组合的正确性判据是端到端增益，不是架构优雅**——这直接改变了我在链 4 的推荐。

---

## 2. 关键推理链（每条含「考虑过的分支 → 采纳/否决理由」）

### 链 1：三类形态的能力边界——按「注入面」划分，三形态是互补三角不是竞争项

**考虑过的分支**：
- (a) 按「技术载体」分：skill=markdown 文件、MCP=server 进程、设置=配置文件。
- (b) 按「注入面」分：skill 注入**上下文**（知识/流程/约束），MCP 注入**能力**（新动词），agent 设置注入**角色与护栏**（谁来做、什么不许做）。

**采纳 (b)，否决 (a)**。理由：(a) 是实现视角，回答不了「什么任务该用哪种形态」；(b) 直接映射到能力边界与风险面：

| 形态 | 能提升什么 | 不能提升什么 | 成本与风险 | 证据 |
|---|---|---|---|---|
| skill | 任务判断质量、产出结构、领域流程（「怎么做对」） | 不能新增动作能力（不能让 agent 调到宿主没有的 API）；不能强制执行（纯建议性） | 成本近零（复制文件）；风险=上下文预算、指令陈旧、引用外部内容时的提示注入面 | 渐进披露三层（metadata ~100 token / SKILL.md 正文 <5000 token / 资源按需）——agentskills.io/specification |
| MCP | 可达性与自动化（真 API、真数据、真子进程；「能做新的事」） | 不能提升知识判断：装了工具不会用=零增益（EVAL-SPEC §6.2 的 doc-gain 局限声明正是针对此：文档增益≠本体增益） | 成本=常驻进程+配置+凭据；风险=MCP 规范安全节明示 tools=任意代码执行、描述不可信除非来自可信 server | modelcontextprotocol.io/specification/2025-06-18 Security 节；EVAL-SPEC-v0.2.md:284-290 |
| agent 设置 | 角色封装（subagent=隔离上下文里的专责角色）与护栏执法（hook=确定性拦截） | 角色文本本身无执行力（acceptor-agent 的禁令要靠盲评/彩排来验证它真被遵守）；hook 脚本=确定性执法但仅在其宿主内有效 | 风险=**客户端锁定**：hooks 33 事件与 5 类 handler 是 Claude Code 专属锚（TAXONOMY.md:186）；子代理 frontmatter 格式是 Claude Code 专属（code.claude.com/docs/en/sub-agents）；zcode 有自己的 hook 体系（.mimosa 即实例） | TAXONOMY.md:186-187 锚 6/7；BASELINE.md:106 Mimosa hook 活体执法 |

**关键推论（课堂视角）**：课堂「高度确定性」（README.md:10）来自三角咬合——skill 管知识让学员做对、MCP 管动作让事真能办成、hook/验收员管执法让错误**必然被拦**。zctl-mcp 的设计是三角咬合的正面样例：只读工具（MCP 面）+ forbidden 名单反向冻结（contract F4）+ INSTALL 自检（红路 exit 1 验证评测器活着）。**缺任一角，课堂确定性就塌**：只有 skill 没有动作=学员看懂了办不成；只有动作没有执法=产物对错全凭运气。

### 链 2：国际标准核验结果——「现行」的时间线与我们的合规缺口

**Agent Skills（agentskills.io，2026-10-03 实访）**：
- SKILL.md 必备字段仅两个：`name`（≤64 字符，小写字母/数字/连字符，**必须与父目录名一致**）、`description`（≤1024，非空，须含触发关键词）。
- 可选：`license`、`compatibility`（≤500，环境要求）、`metadata`（字符串键值图，官方示例把 `version` 放在这里）、`allowed-tools`（**实验性**）。
- 目录约定：`SKILL.md` 必备 + `scripts/` `references/` `assets/` 三个可选约定目录；引用文件一层深。
- 渐进披露三层；SKILL.md 建议 <500 行；官方校验器 `skills-ref validate`。
- **采纳广度（本轮主源实锤）**：agentskills.io/clients 列出 45+ 客户端，包括 **OpenAI（ChatGPT & Codex，官方指引 developers.openai.com/codex/skills/）**、Google Gemini CLI、GitHub Copilot、VS Code、Cursor、Claude Code/Claude、Goose、Roo Code、Tabnine、TRAE 等。即：SKILL.md 已是跨全厂商的事实标准（WebSearch 旁证：标准 2025-10 由 Anthropic 发布；治理上并入 Agentic AI Foundation 的说法来自搜索摘要二手源，置信中）。

**MCP（modelcontextprotocol.io，2026-10-03 实访）**：
- 修订时间线：2024-11-05（首版）→ 2025-03-26 → **2025-06-18**（streamable HTTP 取代 HTTP+SSE、structured tool output `structuredContent`、OAuth 2.1 资源服务器、elicitation、JSON-RPC batching 移除）→ **2025-11-25（现行最新）**：头部特性 **Tasks**（SEP-1686，长时操作异步执行：轮询、飞行中补输入、持久句柄）；elicitation 增加 form/url 两模式。
- 基元：server 侧 resources/prompts/tools，client 侧 sampling/roots/elicitation，双侧 tasks；传输：stdio（本地）+ streamable HTTP（远程）。
- 分发通道：官方 MCP Registry（preview 自 2025-09-08，`server.json` manifest，API v0.1，GA 未确认）+ `.mcpb` 打包（zip+manifest，源自 Claude Desktop 的 Desktop Extensions/DXT，社区与 Docker MCP Catalog 亦在用）。治理：MCP 与 Agent Skills、A2A 同归 **Agentic AI Foundation（AAIF）**（modelcontextprotocol.info + 搜索摘要，置信中）。
- 对照我们的库存：**zctl-mcp 钉在 protocolVersion 2024-11-05**（contract.md F1），落后现行两版；无 server.json、无 .mcpb。

**其他生态**：
- A2A：Google 2025-04 发布→捐 Linux Foundation→**2026 年达 v1.0**、2026-08-17 移入 AAIF、150+ 组织参与；Agent Card 是 agent 身份发现原语（搜索摘要，置信中——未实访 a2a 主源）。
- AGENTS.md：60k+ 项目采用的「agent 的 README」（TAXONOMY.md:24 锚 6 实访口径）。
- Claude Code 子代理：`.claude/agents/*.md` / `~/.claude/agents/*.md`，frontmatter 必填 name/description，可选 tools/disallowedTools/model/permissionMode/maxTurns/skills/mcpServers/hooks 等，正文=system prompt（2026-10-03 实访）。

**对照出的合规缺口（重要产出）**：
1. **dist 三包 SKILL.md 三处不合规**（逐一对照现行字段表）：`version: 1.0.0` 顶层字段不在规范字段表内（应放 `metadata.version`）；`permissions: [shell]` 不在字段表内（最近的对应物是实验性 `allowed-tools`）；`name: meeting-minutes` ≠ 父目录名 `meeting-minutes-skill`（规范明文要求一致）。证据：dist/meeting-minutes-skill/SKILL.md:2-11 与 agentskills.io/specification 字段表对照。
2. v5 五资产 package/SKILL.md 均仅 name+description——合规（必备字段齐）但未利用 `compatibility`/`metadata`/`license`；且「skill 目录」实际是 `package/`，对外分发需目录改名以与 `name` 一致。
3. zctl-mcp 协议钉版滞后（见弯路二，降为债务）。

### 链 3：从 v5 实物提炼「即装即用」六要素（形态学经验）

v5 五资产 + 三个 dist 包 + 课堂彩排记录（worklog.md:20 R7 彩排揪出缺陷 D1-D5）共同指向六条可复用经验：

1. **零依赖运行时是第一设计决策**：speaker-mapping/hotwords 「仅 Python 标准库」（speaker-mapping contract.md:40），zctl-mcp 「零依赖 Node>=18」（contract.md:11）。非开发者机器上 pip/npm 装依赖=课堂事故源；dist 包里 requirements.txt 只在确需 python-docx 时出现（REGISTRY.md:18）。
2. **安装=一段可复制的配置片段**：zctl-mcp/package/INSTALL.md:9-20 的 mcpServers JSON 片段 + 前置条件 + 凭据说明，就是「一键安装」的务实形态。
3. **冻结输出契约（含报错文案）使「预期输出特征」可写进走查**：hotwords spec 附录 A.3 把 10 步 stdout/stderr 全文冻结（含中文错误文案），walkthrough.md 才能给学员写「预期输出特征」——彩排 D1-D5 的教训证明没有这个就教不了。
4. **红路自检内建于课堂**：每课第一步先跑 `runner.py <空目录> oracle/out` 期望 exit 1（walkthrough.md:38-49）——学员亲手验证「评测器有牙」，这既是教学动作也是资产完整性自检。INSTALL.md:24-27 已把红路自检写进安装说明，模式可推广。
5. **scratch 纪律=失败自愈机制**：oracle/ 只读、产物写 scratch、跑坏了删掉重复制（walkthrough.md:188 红线）。资产的不可变参照 + 可丢弃工作区的二分，让「失败自愈」降级为「重新复制」。
6. **eval 与资产同体分发**：dist 包自带 eval/（REGISTRY.md:58-79 关键 sha256 含 eval/runner.py 与 golden.json）——学员/客户拿到的包自带验收能力，这是「交付可验收」承诺的物质基础。

对应的验收口径即「三齐」（确定性评测 + 盲评 + 体检 A，REGISTRY.md:5）——本镜头补充的是：**体检器（v3/tools/healthcheck）按 dist skill 包形态设计 5 项，对 MCP/agent 定义/工具类形态全部不适用**（REGISTRY.md:166 注 1、:194 注 A1 已如实登记为 C+豁免待裁定）。资产规格 v1 必须为每种形态定义「体检项集合」，否则三齐口径对新形态永远凑不齐。

### 链 4：组合架构——ppt-method-router 的负增益教训是最大资产

**考虑过的分支**：
- (a) **合并成大通用 skill**：把方向 skill 的知识合并进一个大 SKILL.md。否决为默认路线：① 与渐进披露冲突（agentskills.io 建议 <500 行；合并知识必然超）；② 盘内反例 ppt-method-router：确定性门全过、路由一致率 1.0（20/20），但盲评 Δ0/胜率 33%「路由对但端到端零增益」（REGISTRY.md:27）——组合的账必须算端到端；
- (b) **路由模式**（薄路由 skill + 按需引用方向 skill）：有条件采用。ppt-method-router 证明「路由正确」不等于「有增益」，所以路由 skill 的准入必须同样过端到端盲评复合线（EVAL-SPEC §3.6），且路由层只承担真正不可预判的分支（意图分类类），流程已知的组合不需要路由；
- (c) **任务包 bundle**（一个任务类型 = manifest 绑定的 skill(s)+MCP(s)+设置+eval+走查，版本化为一个分发单元）：**采纳为交付默认单元**。依据：① 课堂卖的是「走通一次真实交付」，能独立走通的最小单元是 bundle 而非单件（walkthrough 三课每课=一资产，但环境自检+三课连贯才构成「课程合格线」walkthrough.md:224-229）；② 仓库先例 mcp-office-pack（10 条 MCP 配置按六办公场景打包，REGISTRY.md:34）与 classroom/teaching-assets.md（教学资产清单冻结，tag classroom-v0.1）；③ EVAL-SPEC §6.3 的「整包 kit 评测」已为组合形态定义了评测法（kit 含配置件 vs 同 kit 不含 + token 补偿控制 :292-299）——评测协议已经就位，缺的只是分发形态定义；
- (d) **分层**（通用 skill 只放跨任务方法论，方向 skill 放领域流程）：与 (c) 兼容，作为 bundle 内部的组织原则。acceptor-agent 就是「通用层」雏形（验收员角色泛化自 SM 场景，spec.md:4）——它可以服务任何任务类型，这解释了为什么它是首批双臂盲评 2/2 胜的资产（worklog.md:20 R7：评委一致命中「JSON 输出契约+禁令直接命中不虚报」）。

**版本与依赖管理**：现有锚点可复用——keyfiles.sha256（19 关键文件指纹，worklog.md:11）、EVAL-SPEC §4.4 装置钉版条款（评测模型/裁判/通道任一变更⇒evalbench bump、旧基线作废）、golden 只增不改（§5.2）、tag classroom-v0.1（教学资产冻结）。规格 v1 要做的是把这套实践提升为 manifest 字段：资产依赖图（bundle 依赖哪些资产/外部二进制/运行时）+ 标准钉版（skill spec / MCP protocol 版本号）+ eval 契约指纹。

### 链 5：交付给非开发者的形态——安装/门槛/自愈

- **安装**：三类形态的安装动作都应该被降维成「复制 + 粘贴」：skill=复制目录到客户端 skills 目录；MCP=粘贴 mcpServers JSON 片段；agent 设置=复制 .md 到 agents 目录（或 zcode 等价位置）。**「一键安装器」分支否决**：跨客户端安装路径尚未标准化（各客户端 skills 目录位置不同），自研 installer 的维护成本高于收益；v1 应提供「安装脚本 + 逐条手工命令」双轨，脚本按主客户端写，手工命令兜底。
- **运行门槛**：本机现实是 Python 3.12 + Node v22.23.2 双运行时（BASELINE.md:47）；课堂第 0 步环境自检（walkthrough.md:9-22）已是正确设计。规格 v1 应把「运行门槛」做成 SKILL.md `compatibility` 字段的内容（官方字段正为此设计）+ INSTALL.md 前置节。
- **客户端矩阵**：SKILL.md 资产天然跨 45+ 客户端（这是严格合规的最大红利），但 MCP 安装片段与 agent 设置格式是客户端专属。**必须收敛到「1 主 + 2 备」**：主客户端决定 INSTALL.md 的默认片段。这是需人类决断项（见 §5）。
- **失败自愈**：三件套——红路自检（装完先验「评测器活着」）、scratch 重置（删产物重复制）、中文错误文案+卡点表（K-2 手册要求「常见卡点与自检」，TASK.md:33）。三者全部已有仓库先例，规格 v1 只需将其升为硬性条款。

### 链 6：资产规格 v1 草案要点（给撰写者的原料，非成品）

**双根结构**（v5 已事实存在，需成文）：
- 资产根（工厂内，不分发）：`spec.md` + `contract.md` + `eval/runner.py` + `oracle/`（参照实现+fixtures+out）+ 可选 `blind/`（盲评样本）。
- 交付根 `package/`（对外分发物）：按形态各异（见下）。

**分形态 package 布局契约**：
- `skill`：严格 agentskills.io 布局——skill 目录名=`name`；SKILL.md 必备 name/description、推荐 license/compatibility/metadata（version 入 metadata）；scripts/、references/、assets/ 按需；**禁止**自造顶层字段（version/permissions 教训）。发布前过 `skills-ref validate`（建议纳入体检器）。
- `mcp`：`mcp-server.mjs`（或等价）+ `INSTALL.md`（含 mcpServers 片段+前置+自检）+ `oracle/expected_tools.json`（工具集恰等+forbidden 名单双向冻结，zctl-mcp F2/F4 模式）；manifest 记 `mcp_protocol_version`；远程分发预留 server.json/.mcpb（v1 不强制）。
- `agent-config`：**双层**——`agent.md` 通用角色定义（职责/输出契约/禁令三节，acceptor-agent 模式）+ 每客户端适配器（如 Claude Code `.claude/agents/*.md` frontmatter 薄壳）。理由：子代理格式无跨端标准（各客户端字段表不同），把「角色内容」与「客户端壳」分离才能一份内容多端交付。
- `hook`（如 office-guard-hooks 线）：按宿主事件表写，必须声明目标宿主+事件清单（33 事件是 Claude Code 锚）；体检项=事件名有效性+脚本语法+沙箱试跑。

**manifest 字段清单**（建议 asset.manifest.json 或入 REGISTRY 机读化）：`name`、`version`（semver）、`form`（TAXONOMY 14 形态之一）、`license`、`compatibility`（运行时/宿主要求）、`standards`（skill_spec / mcp_protocol 钉版+查询日期）、`task_types`（关联任务类型，供 bundle 组装）、`dependencies`（资产依赖+外部二进制+运行时版本）、`eval`（runner sha256 + oracle 指纹 + 红路矩阵清单）、`clients`（支持矩阵：主/备/未测）、`evidence`（确定性/盲评/体检三齐状态 + evidence_level，对齐 EVAL-SPEC §8.1 `evidence_level`）。

**eval 挂载约定**（固化为接口）：`python eval/runner.py <被测产物根> <参照产物根>`；退出码 0/1/2 三值（绿/红/用法错）；输出无时间戳、同参逐字节可复跑；红路矩阵每轮必跑（空目录为最小红路）；评测对象=**产物端态**而非源码单测（BASELINE.md:177 口径注 + EVAL-SPEC §3.8-7 端态判定原则）。

**需与 bench 镜头对齐的接缝**（我方让渡/共享）：① oracle 的新鲜度与重建责任（speaker-mapping 平台路径伪差事件表明 oracle 是平台相关物，基准重建流程归 bench 更稳）；② blind/ 样本从资产根剥离成 bench 侧资产（盲态隔离更干净，TASK.md:73 S-彩排禁读清单更简单）；③ benchmark.json 落盘与模型钉版五元组归 bench（EVAL-SPEC §4.4/§8.1 已定义，资产侧只需在 manifest 引用）；④ evidence_level 判定权归 bench，资产侧如实声明。

---

## 3. 证据（汇总表）

### 仓库证据（文件:行号）
| 主张 | 证据 |
|---|---|
| 三齐口径=确定性+盲评+体检 A ⇒ 可分发 | REGISTRY.md:5 |
| 体检器按 dist skill 包形态设计，对新形态不适用（C+豁免） | REGISTRY.md:166（注 1）、:194（注 A1） |
| ppt-method-router 路由对但端到端零增益 | REGISTRY.md:27（6/6 exit 0、一致率 1.0、盲评 Δ0/33%） |
| v5 评测体系全绿 + 红路 fail-closed（A 级、三方复现） | BASELINE.md:99-102（§2 行 19-20） |
| acceptor-agent 从未被六份输入评测 | BASELINE.md:182、:260 |
| 零依赖是设计决策 | speaker-mapping/contract.md:40；zctl-mcp/contract.md:11 |
| 红路自检进课堂与 INSTALL | walkthrough.md:38-49；zctl-mcp/package/INSTALL.md:24-27 |
| scratch 纪律红线 | walkthrough.md:188 |
| dist 三包 front-matter 实物（version/permissions 顶层字段） | dist/meeting-minutes-skill/SKILL.md:2-11（三包同构，office-templates:1-8、hot-templates:1-8 同证） |
| 整包 kit 评测协议已就位（token 补偿控制） | EVAL-SPEC-v0.2.md:292-299（§6.3） |
| doc-gain 局限（文档增益≠本体增益） | EVAL-SPEC-v0.2.md:284-290（§6.2） |
| 模型钉版与不可比条款 | EVAL-SPEC-v0.2.md:228-231（§4.4） |
| 14 形态与锚定 | TAXONOMY.md:178-197 |
| 教学资产冻结先例 | worklog.md:16（R3，tag classroom-v0.1） |
| 课堂彩排揪缺陷 D1-D5 | worklog.md:17（R4） |
| 接口常量全文披露条款（E-1） | EVAL-SPEC-v0.2.md:419-425；落地样例 hotwords/spec.md 附录 A |

### Web 证据（2026-10-03 实访，均公开来源）
| 主张 | 来源 |
|---|---|
| SKILL.md 字段表/目录/渐进披露/<500 行/skills-ref | https://agentskills.io/specification |
| 45+ 客户端官方支持，含 OpenAI ChatGPT & Codex、Gemini CLI、GitHub Copilot、VS Code、Cursor | https://agentskills.io/clients |
| MCP 2025-06-18 基元与安全原则 | https://modelcontextprotocol.io/specification/2025-06-18 |
| MCP 2025-11-25 修订存在（tasks capability、elicitation form/url） | https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle |
| 2025-06-18 要点：streamable HTTP、structured tool output、OAuth 2.1 | 搜索摘要（modelcontextprotocol.io Key Changes、forgecode.dev、speakeasy.com） |
| 2025-11-25 头部特性 Tasks=SEP-1686 | 搜索摘要（modelcontextprotocol.io、github.com/modelcontextprotocol/modelcontextprotocol/issues/1686） |
| .mcpb=zip+manifest；MCP Registry preview 自 2025-09-08、server.json、API v0.1 | 搜索摘要（glama.ai、docs.portainer.io、houtini.com、github.com issue） |
| A2A v1.0（2026）、2026-08-17 入 AAIF、150+ 组织、Agent Card | 搜索摘要（Linux Foundation 一年报告、splunk.com）——未实访 a2a 主源，置信中 |
| Agent Skills 2025-10 由 Anthropic 发布；Google 加入 Agent Plugins 标准 | 搜索摘要（OpenReview SkillSeek、GitHub awesome 列表）——二手源，置信中 |
| Claude Code 子代理格式与目录 | https://code.claude.com/docs/en/sub-agents |

---

## 4. 倾向性结论（每条标置信度）

1. **严格对齐 agentskills.io SKILL.md 是 ROI 最高的一步**：45+ 客户端官方支持（含 OpenAI/Google/Microsoft 全线），资产一次合规=全域可装；且合规成本是字段级改动。置信度：高。
2. **三形态是互补三角（知识/动作/执法），不是三选一**；课堂确定性=三角咬合，每类任务包应显式声明三个面各由哪个部件承担。置信度：高。
3. **dist 三包的 3 处 front-matter 不合规是真实债务**（version 顶层字段、permissions 字段、name≠目录名），发布前必须修——但修复=重新打包，会牵动 K-5 人工批准流程，时机需 owner 裁定。置信度：高（对照实锤）；处置时机：中。
4. **交付单元应是「任务包 bundle」**（manifest 绑定多资产+eval+走查，版本化一个单元），单件资产只是 bundle 的构件；仓库评测协议（整包 kit 评测）与先例（mcp-office-pack、teaching-assets）已备好。置信度：中高。
5. **组合资产（路由/合并/分层）必须过端到端盲评复合线才准入**——ppt-method-router 是盘内铁证：架构正确≠有增益。「大通用 skill」不做默认路线。置信度：高。
6. **agent 设置形态无跨端标准**，应采用「通用角色内容 + 客户端适配薄壳」双层设计；A2A Agent Card 是未来 agent 间分发的候补锚，v1 观望不绑定。置信度：中。
7. **体检器需按形态扩展成「分形态体检项集合」**，否则 MCP/agent 定义/工具类资产的三齐永远缺一角（现全靠豁免注记）。置信度：中高。
8. **「即装即用」的工程本质=零依赖+复制粘贴安装+冻结输出契约+内建红路自检+scratch 自愈**，五条全部有 v5 先例，规格 v1 只需把实践升为硬性条款。置信度：高。
9. **zctl-mcp 协议钉版（2024-11-05）是低优先债务**：不在课堂首批路径，升级应与其下一次功能性迭代合并做，同时重走红绿矩阵。置信度：中高。
10. **标准治理收敛（MCP+Agent Skills+A2A 同入 AAIF）对资产跨端分发长期利好**，manifest 应记录「标准钉版+查询日期」以对冲标准变动（EVAL-SPEC 装置钉版思想的形式移植）。置信度：中。
11. **「一键安装」的 v1 现实形态=安装脚本+逐条手工命令双轨**，不是自研 installer；主客户端收敛是前置条件。置信度：中高。

---

## 5. 未决问题与风险（需人类决断的单独列出）

**需人类决断**：
1. **课堂主客户端选型**（zcode？Claude Code？其他？）：决定 INSTALL.md 默认片段、agent 适配壳先做谁、合规修复优先级。此决策同时影响「讲课用的客户端学员买不买得起/装不装得上」——纯业务判断，我方无权代裁。
2. **dist 三包合规修复的时机**：修复=改包=重新走确定性门+体检（盲评材料或可复用），并牵动 K-5 发布批准（唯一人工例外）。选项：发布前修（推荐）/发布 v1.0.0 后出 v1.0.1 合规版。需 owner 裁定。
3. **形态收敛范围**：18 资产横跨 7+ 形态；v1 规格先收窄到 skill / MCP / agent-config 三形态（课堂直接需要），hook/plugin 等缓行——请 owner 确认。
4. **盲评加厚的模型配额**：n=2 小样本欠账（worklog.md:20 注 A2）与 owner「迭代到极限再进真实人类」的总路线直接相关——配额投放节奏是资源决策。

**技术风险（无需决断但需写入规划）**：
5. oracle 平台相关性：speaker-mapping 路径分隔符伪差事件（worklog.md:7 A-2 条款）证明 oracle 产物含平台指纹；多平台交付前 oracle 需声明「重建平台+归一化规则」。
6. dist 包内 CRLF 脏项（README.md:41）与 NUL 事件（BASELINE.md:267）说明**打包环节需要机器化格式门**（发布 checklist 已要求，建议升为体检项）。
7. acceptor-agent 是唯一未被独立评测的在库资产（BASELINE.md:260）——若它进入通用层组合，需先补 eval 或至少彩排验证。
8. MCP Registry 仍是 preview（API v0.1）、A2A 信息为搜索摘要二手源——两者都不宜作为 v1 硬依赖，manifest 预留字段即可。

---

## 6. 给最终规划撰写者（GLM-5.3）的具体建议

1. **把「严格 SKILL.md 合规」写成产线 G0 级新门**（建议名 G0-5 形式合规门）：skill 类资产发布前过 `skills-ref validate` + 三条自检（name=目录名、无自造顶层字段、version 入 metadata）；对 dist 三包开一张合规修复票（挂 K-5 前置，时机等 owner）。
2. **规格 v1 采用「双根 + 分形态 package 契约 + manifest」三件结构**（本文链 6 给了全部字段原料），形态先收窄 skill/MCP/agent-config；hook 形态留接口不展开。
3. **交付单元定为「任务包 bundle」**：manifest 的 `task_types` + `dependencies` 字段支撑「多资产混用/分开」两种交付模式；bundle 自身也要有 eval（用 EVAL-SPEC §6.3 整包 kit 评测法，含 token 补偿控制），防止「混装后反而变差」不可知。
4. **给组合立准入铁律**：任何路由/合并/分层组合必须过 EVAL-SPEC §3.6 复合线端到端盲评——把 ppt-method-router 写成规划里的「反面教材条款」。
5. **把「即装即用五条」（零依赖/复制粘贴安装/冻结输出契约/内建红路自检/scratch 自愈）升为资产规格硬性条款**，每条都有 v5 先例作模板（分别见链 3）。
6. **体检器扩展单列一个工作项**：为 MCP（协议握手+工具契约+forbidden 反向）、agent-config（三节齐备+schema 校验+承诺词反向）、tooling（运行时自检）各定义体检项集合，替代现在的「豁免注记」——否则三齐口径对新形态是空话。
7. **与 bench 镜头的接缝按本文链 6 末段四条分工**：oracle 新鲜度、blind/ 样本归属、benchmark.json/钉版、evidence_level 判定权归 bench；资产侧 manifest 只引用。
8. **INSTALL.md 模板固定为四节**：前置条件（运行时+凭据，不写凭据本体）/安装片段（主客户端默认+备选客户端）/自检（绿路 exit 0 + 红路 exit 1 两条命令）/安全说明（zctl-mcp INSTALL.md 已是完整样板）。
9. **manifest 增设 `standards` 字段记录标准钉版与查询日期**（skill_spec / mcp_protocol / hooks_events 各版本），把「符合现行国际标准」从口号变成可审计字段；标准漂移检查可并入体检器低频项（如每季度）。
10. **课程层复用而不要新造**：walkthrough 的「第 0 步环境自检 + 每课红路先行 + scratch 纪律」结构与 K-3 零上下文彩排法已是资产交付形态的验收机制，规划里应作为 bundle 出厂检验的一部分（bundle 级彩排），而非每资产各写一套。

---

*本轨迹由思考者B（GLM-5.3-Flash）于 2026-10-03 写成。仓库全部只读，未修改/删除任何既有文件，未 git commit/push；Web 仅访问公开来源，未外发本机数据。未做任何 runner 复跑（本镜头为形态学/标准核验任务，未收到复跑指令；引用的评测结论均标注来源为 BASELINE/REGISTRY/worklog 留档）。*

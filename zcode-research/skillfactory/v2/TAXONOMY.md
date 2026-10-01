# TAXONOMY v2 — AI 能力资产分类体系（skillfactory/v2）

| 项 | 值 |
|---|---|
| 文件 | `skillfactory/v2/TAXONOMY.md` |
| 版本 | v2.0（2026-09-29） |
| 范围 | 对 135 条资产清单（去重后 **132 个唯一资产**，见 §6）建立「主类目 × 细类目 + 形态横轴」分类体系 |
| 配套 | 全量目录见 `skillfactory/v2/CATALOG.md`；空白格（机会点）见 CATALOG §覆盖度矩阵 |
| 既有语境 | 与 `skillfactory/plan/MASTER-PLAN.md`（总体方案 v2.0）、`skillfactory/standard/SKILL-SPEC-v0.1.md` 同构：资产上位格式 = agentskills.io 开放标准（两文件本会话实读确认） |

---

## 一、锚定标准与核实记录（全部为本会话实际访问核实，2026-09-29）

> 纪律声明：下表每一行都是本轮亲自访问所得，标注了访问方式与所见事实；未逐页复核的内容明确标注"未复核"。

| # | 锚 | 出处 | 本轮核实方式与所见 | 采纳方式 |
|---|---|---|---|---|
| 锚1 | **O*NET Job Family**（美国劳工部 Employment and Training Administration 赞助） | `onetonline.org/find/`；`onetcenter.org/taxonomy.html` | web_reader 实访两页：Job Family 浏览页列出 **23 个 Job Family** 全名单（Arts, Design, Entertainment, Sports, and Media；Business and Financial Operations；Computer and Mathematical；Legal；Life, Physical, and Social Science；Management；Office and Administrative Support；Sales and Related 等）+ 1,016 个职业条目 + 16 Career Clusters（含 Marketing & Sales、Financial Services、Digital Technology、Management & Entrepreneurship）；taxonomy 页确认 O*NET-SOC 2019 = **98 minor groups / 459 broad occupations / 1,016 titles**（对齐 2018 SOC） | **B 段任务域命名的职业学依据**（见 §3 规则） |
| 锚2 | **Anthropic 官方资产体系**（skills 官方仓 + 知识工作官方插件库） | `github.com/anthropics/skills`；`github.com/anthropics/knowledge-work-plugins` | WebFetch 实访：① skills 仓四大分类 **Creative & Design / Development & Technical / Enterprise & Communication / Document Skills**，另有 `spec/`（"The Agent Skills specification"）与 `template/`（"Skill template"），文档技能 docx/pdf/pptx/xlsx 为 source-available；② knowledge-work-plugins 共 **11 个按职能打包的插件**：productivity、sales、customer-support、product-management、marketing、legal、finance、data、enterprise-search、bio-research、cowork-plugin-management（README 原文："针对特定工作职能打包了技能、连接器、斜杠命令和子智能体"） | A 段技能/插件类目的官方分类法；B 段职能切分的厂商权威依据 |
| 锚3 | **MCP 社区主索引分类**（punkpeye/awesome-mcp-servers） | `raw.githubusercontent.com/punkpeye/awesome-mcp-servers/main/README.md` | WebFetch 实访 raw README：顶层 8 个 ## 节，"Server Implementations" 下 **### 级分类约 57 个**（本轮确认前 7 个：Aggregators、Aerospace & Astrodynamics、Agreements & Coordination、Accessibility、Art & Culture、Architecture & Design、Biology, Medicine and Bioinformatics；正文超长未逐条取全） | A4 MCP 生态细类目框架（参考实现/任务域 server/网关/注册表目录） |
| 锚4 | **n8n 官方模板市场分类** | `n8n.io/workflows/` | WebFetch 实访：**12,574 个模板、7 大分类：AI / Sales / IT Ops / Marketing / Document Ops / Other / Support** | 工作流模板类目定义与 A8 渠道细类 |
| 锚5 | **Agent Skills 开放标准** | `agentskills.io`（+`/llms.txt`） | web_reader 实访三页：标准站在线，文档索引含 **Specification**（自述 "The complete format specification for Agent Skills"）、Client Showcase、Quickstart、Best practices、Evaluating skill output quality 等；官网仓库 `agentskills/agentskills` 25,776★。注：SKILL.md 内部结构（front-matter+正文+scripts/references/assets）本轮未逐页复核规范全文，采信资产清单与 `SKILL-SPEC-v0.1.md` 口径 | 形态横轴「skill」的定义依据；自产格式的上位标准 |
| 锚6 | **AGENTS.md 开放规范** | `agents.md` | web_reader 实访：官网自述 **"A simple, open format for guiding coding agents, used by over 60k open-source projects. Think of it as a README for agents."** | 形态横轴「agent配置」的定义依据 |
| 锚7 | **Claude Code Hooks 官方参考** | `code.claude.com/docs/en/hooks` | WebFetch 实访：**33 种 hook 事件**（SessionStart/Setup/UserPromptSubmit/PreToolUse/PermissionRequest/PostToolUse/SubagentStart/Stop/PreCompact/SessionEnd 等全名单已取）；配置三层结构（event → matcher 组 → handler 数组）；**5 种 handler 类型：command / http / mcp_tool / prompt / agent**。⚠️ 实测修正：资产清单原记"约 35 种事件"，官方文档当前为 **33 种**，本体系以 33 为准 | 形态横轴「hook」「command」的定义依据；A7 治理类目的机制边界 |

**为何不用 ISCO/O*NET 做全量主轴**：本集合 60% 以上是生态基建资产（协议、框架、目录渠道、评测基准、治理工具），它们没有职业对应物（不存在"MCP 注册表"职业）；O*NET 的 23 Job Family 只对 B 段任务域有命名校准力。故采取「**生态基建按资产形态路线（锚 2/3/5/6/7）+ 任务域按职业职能（锚 1/2/4）**」的双段主轴，而非单一职业分类硬套。此为有依据的选择，非发明私人体系：A 段每个主类目都能对应到上表某一官方分类法。

---

## 二、主轴设计：两段式主类目

- **A 段（生态基建，8 类）**：资产的核心价值在「跨任务域复用的形态工艺或生态机制」——标准、技能与配置件、提示词、MCP、平台框架、评测、治理、渠道。锚 2/3/4/5/6/7。
- **B 段（任务域方案，4 类）**：资产的核心价值在「解决某一职业任务域的具体问题」，形态各异但域集中。任务域命名参照 O*NET Job Family 与 Anthropic 官方职能插件（锚 1/2），n8n 官方 7 分类（锚 4）佐证「AI/Sales/Marketing/Document Ops」与市场真实切分一致。

**归类判定规则**（按序执行）：
1. MCP 专属资产（含 MCP 注册表与目录）→ 一律归 **A4**（MCP 是一条独立资产路线，集中便于选型与治理）；非 MCP 专属的渠道/索引 → **A8**。
2. 任务域专属且非 MCP、非标准/协议 → B 段对应任务域。
3. 两可时按该资产「对我们的价值」的核心语义判断：讲**形态工艺/生态机制**的归 A 段，讲**具体职业任务**的归 B 段；条目内注明另一视角。
4. 每个资产有且仅有一个「主类目 + 细类目 + 主形态」；多形态能力（如 CLI+skill 双形态）写入能力字段。

---

## 三、主类目 × 细类目定义（12 主类目，43 细类目）

### A 段：生态基建

#### A1 标准·协议·官方参考（13 条）
- **定义**：开放标准文本、agent 互操作协议、平台官方机制文档与官方教程库。
- **边界**：只收「定义规则或提供权威一手参考」的资产；社区教程、逆向档案不在此（分别归 A3/A6）。
- **锚定**：agentskills.io 与 agents.md 本身即开放标准（锚 5/6）；A2A/ANP 为 Linux Foundation 等托管协议（资产清单本轮沿用）。
- 细类：
  - A1.1 能力封装开放标准：agentskills.io、AGENTS.md
  - A1.2 Agent 互操作协议与官方实现：A2A、a2a-samples、a2a-inspector、ANP
  - A1.3 协议扩展规范：modelcontextprotocol/ext-skills（SEP-2640，Final）
  - A1.4 平台官方机制文档与参考仓：anthropics/claude-code、Claude Code Hooks 官方文档、Cursor Rules 官方文档、LibreChat agents 配置参考
  - A1.5 官方教程与示例库：anthropics/claude-cookbooks、openai/openai-cookbook

#### A2 技能·插件·配置件（14 条）
- **定义**：以 skill / plugin / command / hook / 子代理与规则定义形态存在的、跨任务域的 agent 能力封装与工程范式。
- **边界**：任务域专属技能归 B 段（如科研/小红书/飞书技能）；本类只收方法论级、官方规范级与范式级资产。
- **锚定**：anthropics/skills 官方分类与 template（锚 2）；agentskills.io 标准（锚 5）；hooks 官方 33 事件/5 handler（锚 7）。
- 细类：
  - A2.1 官方技能规范与示例：anthropics/skills
  - A2.2 方法论技能集：obra/superpowers、mattpocock/skills
  - A2.3 插件工程与官方插件包：wshobson/agents、microsoft/azure-skills、Shopify AI Toolkit
  - A2.4 命令与 hooks：wshobson/commands、disler/claude-code-hooks-mastery
  - A2.5 子代理与规则定义合集：VoltAgent/awesome-claude-code-subagents、contains-studio/agents、PatrickJS/awesome-cursorrules
  - A2.6 平台插件样本（Dify 生态）：DeepSeek 模型插件、MCP SSE/StreamableHTTP 插件、Agent Strategies 插件

#### A3 提示词资产（11 条）
- **定义**：prompt 模板本体、系统提示词语料档案、结构化 prompt 方法论与 prompt 管理工具。
- **边界**：收「以提示词为资产本体」的一切；Agent Skills 形态的提示词包归 A2/B 段；系统提示词的汉化镜像与其原仓分开立条（镜像本身是分发资产）。
- **锚定**：无单一官方分类，参照 WaytoAGI prompts 16 标签、prompts.chat、mcp.so「Loops=可复用提示工作流」分区（资产清单在案）。
- 细类：
  - A3.1 系统提示词语料档案：Piebald-AI/claude-code-system-prompts、其 GitCode 镜像、system-prompts-and-models-of-ai-tools-chinese
  - A3.2 结构化方法论与教材：LangGPT、Prompt-Engineering-Guide-zh-CN
  - A3.3 中文社区/个人 prompt 库：WaytoAGI 提示词库、归藏的提示词储存库、prompts.chat GitCode 镜像
  - A3.4 prompt 管理与优化工具：prompt-optimizer、quick-prompt、PromptHub

#### A4 MCP 工具生态（24 条）
- **定义**：MCP 协议路线的一切资产——参考实现、任务域 server、网关与托管执行层、注册表/目录、框架与调试工具。
- **边界**：只按「是否 MCP 专属」划线，不按任务域划线（任务域信息保留在能力字段）；A2A 等其他协议归 A1。
- **锚定**：punkpeye/awesome-mcp-servers 57 分类（锚 3）；MCP Registry v0 API 与 Docker MCP Catalog 企业分发形态（资产清单在案，本轮未重访）。
- 细类：
  - A4.1 参考实现与框架：modelcontextprotocol/servers、FastMCP
  - A4.2 开发调试工具：MCP Inspector
  - A4.3 任务域 server（办公协同）：excel-mcp-server（haris-musa）、excel-mcp-server（negokaz）、Office-Word-MCP-Server、Office-PowerPoint-MCP-Server、google_workspace_mcp、Google 官方 Gmail MCP
  - A4.4 任务域 server（浏览器/文档/电商）：Cloudflare Playwright MCP、Context7、Shopify Dev MCP
  - A4.5 网关与托管执行层：Zapier MCP、Composio
  - A4.6 注册表·目录·企业分发：MCP Registry（官方服务）、modelcontextprotocol/registry、Glama、PulseMCP、Smithery、mcp.so、mcpservers.org、punkpeye/awesome-mcp-servers、ModelScope MCP 广场、Docker MCP Catalog & Toolkit

#### A5 平台·框架·运行时（20 条）
- **定义**：可运行/可部署的 agent 平台、编排框架、专用底座（语音/浏览器/终端/采集/沙箱/记忆）。
- **边界**：收「自己就是一套可运行系统」的软件；评测工具归 A6、治理观测归 A7；任务域闭环应用（如短视频产线）归 B 段。
- **锚定**：参照各框架官方定位（多代理 SDK、语音框架等），无单一外部分类法——本类按运行时职能切分，属生态通识分类。
- 细类：
  - A5.1 自托管平台与环境：LibreChat、Coze Studio、n8n-io/self-hosted-ai-starter-kit
  - A5.2 多代理编排框架：openai/openai-agents-python、AgentScope、claude-flow(ruflo)、ms-agent、Qwen-Agent、千帆 AppBuilder SDK
  - A5.3 语音与实时多模态：Pipecat、livekit/agents
  - A5.4 浏览器/终端/GUI 操作底座：vercel-labs/agent-browser、Aider、Open-AutoGLM
  - A5.5 网页数据采集底座：Firecrawl、crawl4ai
  - A5.6 沙箱与代码执行环境：E2B、microsandbox、e2b-dev/fragments
  - A5.7 记忆与有状态 agent：Mem0、letta-ai/letta

#### A6 评测·基准·观测（11 条）
- **定义**：评测集/基准、评测与观测平台、技能安全评测。
- **边界**：评测「对象是 agent 或 prompt 资产」的一切；纯用量统计归 A7；任务域评测集若以办公/研究为主业仍先归本类（如 SpreadsheetBench），任务域属性记入能力字段。
- **锚定**：评测对象分类参照资产自身域（综合/工具交互/任务域/技能安全）；无单一外部权威分类。
- 细类：
  - A6.1 综合与终端基准：THUDM/AgentBench、laude-institute/terminal-bench
  - A6.2 工具交互基准（客服域）：tau-bench、tau2-bench
  - A6.3 任务域基准：SpreadsheetBench / SpreadsheetBench-2
  - A6.4 评测与观测平台：promptfoo、Coze Loop、Langfuse、Arize Phoenix、OpenCompass
  - A6.5 技能安全评测：sumleo/AgentSkillsScanner

#### A7 治理·审计·成本（3 条）
- **定义**：agent 行为审计、用量与成本治理的直接工具。
- **边界**：观测+评测一体的平台归 A6.4；本类只收「治理动作的执行件」（审计管道、状态栏、计量报表）。
- **锚定**：hooks 官方 33 事件与 5 种 handler（command/http/mcp_tool/prompt/agent，锚 7）定义了治理介入点的官方边界。
- 细类：
  - A7.1 行为观测与审计：claude-code-hooks-multi-agent-observability
  - A7.2 用量与成本：ccstatusline、ccusage

#### A8 目录·市场·分发渠道（15 条）
- **定义**：注册表、插件/技能/模板市场、awesome 索引、平台商店与内容场分发案例——「资产被发现与安装」的基础设施。
- **边界**：MCP 专属目录归 A4.6（规则 §二.1）；本类收非 MCP 专属渠道。单条 awesome 合集若本体是「可用资产包」而非索引（如子代理定义合集）归 A2。
- **锚定**：n8n 官方市场 7 分类（锚 4）；anthropics/claude-plugins-official 市场机制与 skills.sh 注册表形态（资产清单在案）。
- 细类：
  - A8.1 官方插件/技能市场：anthropics/claude-plugins-official、skills.sh（Vercel）
  - A8.2 生态索引与 awesome 精选：hesreallyhim/awesome-claude-code、travisvn/awesome-claude-skills、VoltAgent/awesome-agent-skills、VoltAgent/awesome-openclaw-skills、ithiria894/awesome-claude-code-hooks、github/awesome-copilot
  - A8.3 模板市场与聚合安装器：davila7/claude-code-templates、n8n 官方工作流模板库、awesome-n8n-templates
  - A8.4 国内平台商店：Dify 插件市场、Kimi+ 智能体广场、腾讯元器
  - A8.5 内容场分发案例：B 站「一个 skill 里面 10000+ 提示词」

### B 段：任务域方案

#### B1 办公·文档·知识工作（4 条）
- **定义**：面向办公室文职/知识工作的文档读写、跨职能插件与中文办公生态技能。
- **O*NET 对应**：Office and Administrative Support；Management（知识工作职能横切）。
- **锚定**：Anthropic knowledge-work-plugins 11 职能插件（锚 2）；n8n「Document Ops」分类（锚 4）。
- 细类：
  - B1.1 跨职能知识工作插件：anthropics/knowledge-work-plugins
  - B1.2 文档读写与解析工具：OfficeCLI、Microsoft MarkItDown
  - B1.3 中文办公生态技能：larksuite/cli（飞书 26 agent skills）

#### B2 内容·营销·销售经营（7 条）
- **定义**：内容生产（视频/图文/图像）、社媒分发、销售成交——个体经营与内容创作者的职业任务闭环。
- **O*NET 对应**：Arts, Design, Entertainment, Sports, and Media；Sales and Related。
- **锚定**：O*NET 上述两 Job Family（锚 1）；n8n「Marketing / Sales」分类（锚 4）。
- 细类：
  - B2.1 短视频生产：MoneyPrinterTurbo、ShortGPT
  - B2.2 图文与图像生产：RedInk、IC-Light
  - B2.3 skill 化内容产线：redbook-creator
  - B2.4 社媒分发：Postiz
  - B2.5 销售与成交：SalesGPT

#### B3 研究·金融·科学（7 条）
- **定义**：深度研究/调研、金融多代理研究、科学研究与科研技能包。
- **O*NET 对应**：Business and Financial Operations；Life, Physical, and Social Science。
- **锚定**：O*NET 上述两 Job Family（锚 1）。
- 细类：
  - B3.1 深度研究与调研：GPT Researcher、stanford-oval/storm、virattt/dexter
  - B3.2 金融多代理研究：AI Hedge Fund、TradingAgents
  - B3.3 科学研究与科研技能包：K-Dense-AI/scientific-agent-skills、codex-claude-academic-skills

#### B4 软件工程·编码（3 条）
- **定义**：编码任务域的改码、审查与工程方法论。
- **O*NET 对应**：Computer and Mathematical。
- **锚定**：O*NET Job Family（锚 1）；AGENTS.md/spec-kit 等规范由 Linux 基金会 Agentic AI Foundation 托管（资产清单在案）。
- 细类：
  - B4.1 结对编程与代码修改：Aider
  - B4.2 代码审查：PR-Agent
  - B4.3 规格驱动开发方法论：github/spec-kit

---

## 四、形态横轴（14 形态）

任务指定的 10 形态全部保留；因清单实际数据另含标准、目录、教程与媒体案例（源 assetType 多记为"其他"），增设 4 形态并给出定义。**每资产记 1 个主形态**，多形态能力写进能力字段。

| 形态 | 定义（判定标准） | 锚定 | 条数 |
|---|---|---|---|
| skill | 符合/对齐 agentskills.io SKILL.md 开放标准的技能包或技能集（锚 5） | agentskills.io | 7 |
| MCP | MCP server、网关或以 MCP 为主要交付面的托管服务 | MCP 官方规范生态 | 12 |
| hook | 挂接 hooks 生命周期事件（官方 33 事件）的护栏/脚本库（锚 7） | code.claude.com/docs/en/hooks | 2 |
| command | slash 命令集合 | Claude Code 斜杠命令机制 | 1 |
| plugin | 带 marketplace/plugin.json 清单、可一条命令安装的插件包 | claude-plugins-official 市场机制 | 8 |
| prompt模板 | 提示词文本/提示词语料库本体 | prompts.chat、WaytoAGI 等 | 7 |
| 工作流模板 | 可导入的工作流/编排模板（n8n JSON、docker compose 编排等） | n8n 官方市场（锚 4） | 1 |
| agent配置 | rules（.mdc）、AGENTS.md、子代理 .md 定义等上下文配置件 | AGENTS.md 规范（锚 6）、Cursor Rules 官方文档 | 3 |
| 评测集 | 基准任务集/评测数据集（含判分 harness） | AgentBench/tau2 等 | 6 |
| 软件系统 | 可运行/可部署的工具、框架、平台、CLI | — | 49 |
| 标准规范 | 协议/格式标准文本与其官方扩展 | agentskills.io、agents.md | 5 |
| 目录渠道 | 注册表、市场、商店、awesome 索引——发现与分发基础设施 | awesome-mcp-servers、n8n 市场 | 23 |
| 文档教程 | 官方文档、参考实现文档、教程库（权威一手参考） | 各平台官方文档 | 7 |
| 内容案例 | 内容场（视频/媒体）传播形态案例，非可用资产本体 | B 站等 | 1 |

---

## 五、覆盖度矩阵约定

CATALOG.md 中的「主类目 × 形态」矩阵使用三种记号：
- **●** = 该格有资产（格内数字为条数）；
- **○** = 语义上可生产、当前为空 → **机会点**（自研或优先生产，详见 gaps 清单）；
- **—** = 该形态与该类目语义不相干，不算空白。

---

## 六、去重记录（135 → 132）

| 合并 | 依据 |
|---|---|
| Composio（`composio.dev/` 与 `www.composio.dev`） | 同一官网两种写法；合并保留双来源（含【红队】标记） |
| ModelScope MCP 广场（`www.modelscope.cn/mcp` 与 `modelscope.cn/mcp`） | 同站；且 r2 轮已勘误 `mcp.modelscope.cn` DNS 不解析，正确入口为 modelscope.cn/mcp |
| AGENTS.md（`github.com/agentsmd/agents.md` 官方仓与 `agents.md` 官网） | 同一开放规范的仓与站；本会话 web_reader 实访 agents.md 确认 |

【红队】标记：发现来源以「红队-」开头的条目在 CATALOG 中标注 **【红队】**，共 17 个资产。

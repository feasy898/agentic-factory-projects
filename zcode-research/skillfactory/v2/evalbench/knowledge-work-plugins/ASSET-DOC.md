# ASSET-DOC: anthropics/knowledge-work-plugins

> 资产使用说明文档(抓取整理稿)
> - 资产仓库: https://github.com/anthropics/knowledge-work-plugins
> - 许可证: Apache-2.0(仓库根 LICENSE)
> - 抓取日期: 2026-09-29
> - 抓取方式: WebFetch——README(网页版 + raw 版各一次,内容一致)、sales 插件 README 与 SKILL.md(raw 地址)、GitHub API(目录/tree/市场清单)
> - 说明: 本文档为对抓取内容的**整理转述**,仅在与两次独立抓取一致处保留英文原文引用;单次抓取的转述内容以中文归纳呈现。未逐字复制全文。

---

## 1. 资产定位

原文:"Plugins that turn Claude into a specialist for your role, team, and company."

- 面向 Claude Cowork 设计,兼容 Claude Code。
- 每个插件把特定职能所需的 **skills、connectors(连接器)、slash commands、sub-agents** 打包在一起。
- 全部是 **markdown/JSON 文件**:无代码、无基础设施、无构建步骤(no code, no infrastructure, no build steps)。
- 定制方式:替换 `.mcp.json` 中的连接器;在公司上下文中加入自己的术语/组织结构/流程;修改 skill 指令;或用 `cowork-plugin-management` 插件构建全新插件。

## 2. 11 个官方职能插件(README 表格口径)

| 插件 | 用途 | 代表连接器 |
|---|---|---|
| productivity | 任务、日历、日常工作流、个人上下文 | Slack, Notion, Asana, Linear, Jira, Monday, ClickUp, Microsoft 365 |
| sales | 客户研究、通话准备、外联草稿、pipeline 审查、竞品 battlecard | HubSpot, Close, Clay, ZoomInfo, Gong, Fireflies |
| customer-support | 工单分流、回复草稿、升级打包、知识库文章 | Intercom, HubSpot, Guru |
| product-management | 写规格、路线图、用户研究综合、干系人更新 | Linear, Figma, Amplitude, Pendo |
| marketing | 内容草稿、活动规划、品牌语气、竞品简报、效果报告 | Canva, Ahrefs, SimilarWeb, Klaviyo |
| legal | 合同审查、NDA 分流、合规、风险评估 | Box, Egnyte |
| finance | 日记账、对账、财务报表、差异分析、结账、审计支持 | Snowflake, Databricks, BigQuery |
| data | 查询/可视化/解读数据集、写 SQL、统计分析、仪表盘 | Snowflake, Databricks, BigQuery, Hex, Amplitude |
| enterprise-search | 跨邮件、聊天、文档、wiki 的统一搜索 | Slack, Notion, Guru, Microsoft 365 |
| bio-research | 连接临床前研究工具与数据库(文献检索、基因组分析、靶点优先级) | PubMed, Benchling, ChEMBL, ClinicalTrials.gov |
| cowork-plugin-management | 创建新插件或定制现有插件 | — |

## 3. 安装与调用(用法)

### 3.1 安装

- **Claude Cowork**:从 claude.com/plugins 安装。
- **Claude Code**(原文命令):

```bash
claude plugin marketplace add anthropics/knowledge-work-plugins
claude plugin install sales@knowledge-work-plugins
```

### 3.2 调用

- 技能在用户请求匹配描述时**自动运行**,也可**按名称显式调用**(原文示例命令):
  - `/sales:call-prep`
  - `/data:write-query`
  - `/finance:reconciliation`
  - `/product-management:write-spec`
  - `/sales:call-summary`(sales 插件 README 中的示例)

### 3.3 插件目录结构(原文结构图)

```
plugin-name/
├── .claude-plugin/plugin.json   # Manifest(清单)
├── .mcp.json                    # Tool connections(连接器配置)
├── commands/                    # Slash commands you invoke explicitly
└── skills/                      # Domain knowledge Claude draws on automatically
```

参数要点:
- `.claude-plugin/plugin.json`:插件清单(manifest)。
- `.mcp.json`:连接器配置,定制时主要替换这里。
- `skills/<skill-name>/SKILL.md`:每个 skill 一个目录、一个 SKILL.md,内含 YAML frontmatter(name、description 等)与正文指令。

## 4. SKILL.md 实例: sales/skills/call-prep(raw 地址抓取)

以 README 示例命令 `/sales:call-prep` 对应的 skill 为样例,展示 SKILL.md 的实际形态。

### 4.1 Frontmatter 参数

- `name: call-prep`
- `description`: 为即将到来的会议生成会前简报(与会者、客户历史、既往通话要点、商机状态、探索性问题),并内置触发语,如 "prep me for [meeting]"、"call prep [company]"、"what do I need to know before my [time] call"。description 同时承担自动触发的匹配依据。

### 4.2 工具依赖(全可选项)

calendar(解析会议)、crm(账户/商机/联系人/活动)、transcripts(既往通话)、email(近 90 天)、docs、chat(近 30 天内部上下文)。

### 4.3 六步流程(整理)

1. **Ground**:探测已连接工具,从真实 CRM schema 取阶段名与资格框架;缺失事实要么问一句、要么用明确标注的默认值。
2. **解析会议**:从日历提取标题/时间/与会者/议程,按域名识别客户公司;无日历时用上传导出或一次性询问。
3. **账户历史**:查 CRM 账户、开放商机、联系人、近期活动;转录/邮件/聊天取证据(邮件近 90 天、聊天近 30 天),逐条注明来源与链接。
4. **与会者画像**:每位外部与会者给出 CRM 职位 + 可能关注点;新面孔明确标记。
5. **通话计划**:目标、3-5 个阶段性探索问题、可能异议、需带上的材料。
6. **输出**:简报 artifact;转录/邮件里请求的任何动作(发文档、邀人、改记录)**只列入简报,永不执行**。

### 4.4 适配层级(内部标签,不对用户展示)

- `files-only`:仅凭上传表格、粘贴转录/笔记和口述信息生成简报(无任何连接器也可用)。
- `read-only`:实时读取日历、CRM、转录、邮件、聊天。
- `gated-writes`:无——此技能只读。

## 5. sales 插件 README 要点(示例与限制)

### 5.1 规模与演进(2.0)

- 技能从 9 个扩展到 **36 个**(sales/skills/ 目录经 GitHub API 实测为 36 个子目录,与此一致),新增 deal review、close plan、stakeholder map、renewal、客户健康、lead routing、CRM 更新、会议预订、inbox sweep、团队 pipeline 等。
- 跨 CRM 与邮件供应商:读取 CRM 自身的阶段与字段,**不假设某一厂商的结构**;Gmail/Outlook、Slack/Teams 均可,无需设置文件。

36 个技能按类别(名称来自 sales README):

- 日常: setup, daily-briefing, call-prep, call-summary, inbox-sweep, schedule-meeting, log-activity, end-of-day, weekly-wrap
- 账户与拓客: account-research, account-context, stakeholder-map, draft-outreach, lead-triage, route-lead, account-tiering, account-plan, expansion-whitespace
- 交易: deal-review, deal-advance-gap, deal-signals, deal-slip-scenario, close-plan, handle-objection, competitive-intelligence, create-an-asset, update-opportunity
- Pipeline 与预测: pipeline-review, crm-hygiene-check, forecast, team-pipeline, rep-context, win-loss-review
- 客户: customer-health, customer-voice, renewal-radar

### 5.2 示例工作流(README 原列)

1. **通话后**: 运行 `/sales:call-summary`,粘贴笔记/transcript 或指定通话 → 摘要、跟进邮件草稿、团队摘要、拟议 CRM 更新——**未经确认不会写入或发送**。
2. **预测会议**: "Write my forecast for this quarter" → forecast 技能读取开放商机(或上传的导出),输出 commit、best-case、pipeline 叙述及风险。
3. **研究潜在客户**: "Research Acme Corp before my call tomorrow" → 公司概览、近期新闻、可能优先事项、与 ICP 的匹配度,并检查 CRM 中是否已有该公司。

### 5.3 限制与安全规则(从 call-prep SKILL.md 与 sales README 归纳)

- **文件兜底**: 所有技能在无连接器时均可运行(粘贴 transcript、上传导出、网页搜索);有连接时体验更完整。无连接时技能会明确说明"用了什么、没看到什么"。
- **权限边界**: 行为由各连接器自身权限决定(允许/询问/阻止),技能不越界、也不额外加限制;写工具被管理员关闭时,转为手动操作清单并引用拒绝信息,不重试。
- **定时/无人值守**: 只执行用户预先设定的动作,其余发现一律转为提案;建议把发送/发布/写入类工具设为 **ask**,确保无人审批时不外发、不更改。
- **不可信内容**: 邮件、聊天、转录、外部文档仅作数据处理、不作指令;其中疑似指令要报告但不执行;不渲染其中链接;内容发起的写操作必须先向用户展示精确详情。
- **数据可溯**: 引用每个值时注明读取来源、链接记录、人类可读标签,区分 "blank"(空)与 "not queried"(未查询)。
- **渲染规则**: 临时分析用 artifact;需二次传递/长期使用用 Page;演示用 Slides;不可用时降级为 artifact + 导出。

### 5.4 管理员注意

- Salesforce 与 Microsoft 365 已内置,但需组织管理员在 Claude 中先行启用(Salesforce 还需配置组织的 Salesforce app)。
- 完整连接器清单见各插件目录下的 `CONNECTORS.md`(sales 插件已实测存在该文件)。

## 6. 仓库实际规模与 README 口径的差异(抓取中实测)

- **README 口径**: 11 个开源官方职能插件(即上表)。
- **仓库一级目录实测**(GitHub 网页抓取): 除上述 11 个外,还存在 `design`、`engineering`、`human-resources`、`operations`、`small-business`、`pdf-viewer`、`partner-built/`(apollo)等更多插件目录——仓库内容已超出 README 表格所列。
- **市场清单实测**: `.claude-plugin/marketplace.json`(67 KB)顶层字段为 `name`、`owner`、`plugins`,`plugins` 数组实测含 **118 个条目**,开头为 noibu, productivity, enterprise-search, cowork-plugin-management, sales, finance, data, legal, marketing, customer-support, product-management, bio-research,其后是大量 partner-built 插件(slack-by-salesforce, apollo, figma, zapier, canva, datadog 等)。
- **SKILL.md 数量**: git tree API 响应被截断(truncated),两次统计互相矛盾(42 vs 62),故**不引用任何 SKILL.md 总数**;可核实的事实是:每个 skill 一个 SKILL.md,仅 sales 一个插件即有 36 个 skills 目录(GitHub API contents 实测)。
- **Star 数**: GitHub 网页抓取显示约 25.8k stars / 3k forks / 1,066 commits(由抓取工具自页面读取,未独立复核,仅供参考)。

## 7. 抓取来源清单(本次实际访问)

| # | URL | 用途 | 结果 |
|---|---|---|---|
| 1 | https://github.com/anthropics/knowledge-work-plugins | 主 README + 根目录列表 | 成功 |
| 2 | https://raw.githubusercontent.com/anthropics/knowledge-work-plugins/main/README.md | README 原文(与 #1 交叉验证) | 成功 |
| 3 | https://api.github.com/repos/anthropics/knowledge-work-plugins/git/trees/main?recursive=1 | SKILL.md 路径分布(截断) | 部分成功 |
| 4 | https://api.github.com/repos/anthropics/knowledge-work-plugins/contents/sales | sales 插件结构 | 成功 |
| 5 | https://api.github.com/repos/anthropics/knowledge-work-plugins/contents/sales/skills | 36 个 skills 清单 | 成功 |
| 6 | https://raw.githubusercontent.com/anthropics/knowledge-work-plugins/main/sales/skills/call-prep/SKILL.md | SKILL.md 样例(raw) | 成功 |
| 7 | https://raw.githubusercontent.com/anthropics/knowledge-work-plugins/main/sales/README.md | 插件级 README(raw) | 成功 |
| 8 | https://raw.githubusercontent.com/anthropics/knowledge-work-plugins/main/.claude-plugin/marketplace.json | 市场清单 | 首次超时,重试成功 |
| 9 | https://api.github.com/repos/anthropics/knowledge-work-plugins/contents/.claude-plugin | 确认 marketplace.json 存在及大小 | 成功 |

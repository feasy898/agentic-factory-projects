# 分发候选与上架清单（DISTRIBUTION-CHECKLIST）

| 项 | 值 |
|---|---|
| 文件 | `skillfactory/v3/report/DISTRIBUTION-CHECKLIST.md` |
| 日期 | 2026-09-30 |
| 数据来源 | 渠道：`skillfactory/v2/CATALOG.md` A8 全节（:450-508，37 条）+ A2.1 anthropics/skills（:98，任务点名）+ A4.6 四条〔待归类→A8〕注记（:247/:250/:251/:255）；评测：`v2/evalbench-v02/{meeting-minutes,lark-cli,hooks-mastery}/ab_summary.json` 与 `v3/assets/office-templates/tests/ab_summary.json`；体检：`v3/healthchecks/{mm-dist,ot-dist,guard-hooks,prompt-reg}/REPORT.md` |
| 纪律 | 渠道提交入口一律取自目录实录；目录只实录了店面 URL 的，如实标注「提交流程目录未实录」，不编造链接 |

---

## 一、可分发资产表

### 1.1 可进入分发流程（体检 A 级 + 盲评达标）

| 资产 | 版本 | 盲评达标情况 | 体检评级 | 许可证 | 包位置 |
|---|---|---|---|---|---|
| **meeting-minutes-skill**（会议纪要技能） | 1.0.0 | **达标**。v0.2 加厚复验（`v2/evalbench-v02/meeting-minutes/ab_summary.json`）：8 任务 × 双臂双重复，基线 4.75 → 治疗 10.0，**Δ+5.25，任务级胜率 100%（8/8），反向任务 0，accepted=true**；抽检分差 ≤2 裁判一致。包内 `EVALUATION.md` 另载 v0.1 三轮（终轮 5.67→10.00，Δ+4.33，胜率 100%）方向稳健。注：ab_summary 含 `correction` 字段（2026-09-30）——首测脚本 majority 甲乙判反已按留档翻转重算，均值与 Δ 未受影响 | **A**（5 检查 5 通过：SKILL.md 存在 6605B / front-matter 五字段齐全 / eval/ 存在 / eval_smoke exit=0（三节标题、待办表格列、summary 计数一致全过）/ scripts 语法可编译）——`v3/healthchecks/mm-dist/REPORT.md`（2026-09-30T08:44:54+0800） | **MIT**（`LICENSE`：Copyright (c) 2026 SkillFactory；`SKILL.md` front-matter `license: MIT`，本会话实读） | `skillfactory/dist/meeting-minutes-skill/`（含 CHANGELOG/README/EVALUATION/LICENSE/SKILL.md/eval/reference/references/scripts） |
| **office-templates-skill**（中文办公四类文书技能） | 1.0.0 | **达标（单轮信号）**。v0.2 双臂双重复（存档 `v3/assets/office-templates/tests/ab_summary.json`，本会话 python 实读对账：tasks=5、7.7→8.9、Δ+1.20、winRate=1、reverseTasks=0、accepted=true）：5 任务 majority 全 treatment，其中 ab4 两臂同分 8.5。⚠️ 按 `v3/report/V3-FORGE-DELIVERY.md` R3：仅单轮，对外引用须标 `single_round_signal` 并按 EVAL-SPEC §3.7-1 披露（第二轮盲评未做）。注：v2/evalbench-v02 下无此 suite，盲评存档在 v3 资产管线 | **A**（5 检查 5 通过：SKILL.md 10796B / front-matter 五字段齐全 / eval/ 存在 / eval_smoke exit=0（8 单元齐全、产物文件集精确）/ scripts 语法可编译）——`v3/healthchecks/ot-dist/REPORT.md`（2026-09-30T08:45:31+0800）；包内 EVALUATION.md 另载分发包复跑 68/68 checks 全过、字段填充一致率 100%（66/66） | **MIT**（同上，本会话实读） | `skillfactory/dist/office-templates-skill/`（另含 requirements.txt：`python-docx>=1.1`） |

**盲评达标线口径**（EVAL-SPEC v0.2 复合线，据 V3-FORGE-DELIVERY.md:25）：Δ≥1.0 ✓、任务级胜率 ≥0.6 ✓、反向任务 ≤1 ✓——两资产均全过。

### 1.2 暂不可分发（体检 C 级，整改前禁止上架）

| 资产 | 体检评级 | 失败项（`v3/healthchecks/*/REPORT.md` 实录） | 整改方向 |
|---|---|---|---|
| office-guard-hooks（护栏 hook 包） | **C**（2 过 / 3 败） | front-matter 缺 version/license/permissions（仅有 name/description）；缺 eval/ 目录；缺 scripts/ 目录 | 补 front-matter 三字段 + 确定性评测 + 脚本落盘后重检 |
| prompt-regression（prompt 回归黄金集） | **C**（2 过 / 3 败） | front-matter 块缺失（首行非 ---）；缺 eval/ 目录；缺 scripts/ 目录 | 同上；另按 V3 报告 R9，对外分发前须补 ≥30 条人工金标准对拍（现仅 3 题抽样） |

### 1.3 evalbench-v02 三个 suite 的归属澄清（如实）

`v2/evalbench-v02/` 下三个 suite 中**仅 meeting-minutes 是自产可分发资产**。另两个是第三方资产的盲评，**不在本清单分发范围**（归属他人）：
- lark-cli（larksuite/cli 官方资产）：accepted=true，Δ+1.6875，胜率 0.75（8 任务，t3/t4 为 tie）；
- hooks-mastery（disler/claude-code-hooks-mastery）：**accepted=false**，Δ+0.70，胜率 0.6（5 任务）。

### 1.4 全批共性欠账（对外披露口径，V3-FORGE-DELIVERY.md R3/R4/R8）

- 效率门未测（token/耗时全批无记录，R4）；
- 真实复验门未做（R8）：对外披露须双状态并列 **`synthetic-passed ✓ / real-verified ✗`**；
- office-templates 盲评为单轮信号（R3，见 1.1）。

---

## 二、渠道矩阵（A8 全 37 条 + 任务点名 1 条 + A4.6 待归类补充 4 条）

门槛列中「（推断）」= 由目录实录线索推理；其余均为目录原文实录。优先级：**P0** 零门槛本周可上 / **P1** 免费注册审核 / **P2** 需形态改造或变现实验 / **P3** 企业级或暂缓。

### A8.1 官方插件/技能市场（21 条，CATALOG.md:452-476）

| # | 渠道（目录行） | 提交入口（目录实录） | 适配形态 | 预估门槛 | 优先级 |
|---|---|---|---|---|---|
| 1 | anthropics/skills 官方规范+示例库（:98，任务点名） | 目录仅实录仓库 `https://github.com/anthropics/skills`（178.9k★）；**收录/贡献流程目录未实录**——上架前须现场核实 | skill 直收（四大分类含 Enterprise & Communication / Document Skills） | 低-中（推断：开源合集，但 docx/pdf/pptx/xlsx 文档技能为 source-available 非开源，收录口径需核实）；我方 MIT 全开是差异化 | **P0**（先核实流程） |
| 2 | anthropics/claude-plugins-official（:455） | GitHub 仓 `https://github.com/anthropics/claude-plugins-official`（/plugins + /external_plugins，marketplace.json + slug 不可变机制） | skill → 插件包（marketplace.json 结构） | 中（推断：按官方 marketplace.json 打包 + 仓库收录流程）；37.2k★ 官方分发面 | P1 |
| 3 | skills.sh（:456） | 目录实录 `https://skills.sh/`；安装侧 `npx skills add`；**发布命令目录未实录**，上架前实测 | skill 直收（20 个 agent 客户端、Packs、话题分类） | 低（CLI 生态；All Time 安装 1,480,008 为目录实测口径） | **P0** |
| 4 | ClawHub（:457） | `https://clawhub.ai` + npm CLI `clawhub`（**publish/sync/diff**，目录实录） | skill 直收（OpenClaw 生态） | 中：签名清单 + **moderated releases 审核**（目录实录） | P1 |
| 5 | cursor.directory（:458） | 提交页 **`cursor.directory/plugins/new`**（目录实录：GitHub/Google 登录后 "Paste a GitHub repo URL"，"no pull requests needed"；自动识别 `skills/*/SKILL.md` 等六类） | skill 直收（贴 repo URL 即可） | 低（零 PR 门槛，目录实录）。⚠️ 站点本体曾被 Vercel Security Checkpoint 拦截（429），核实依据为官方仓 cursor/community-plugins | **P0** |
| 6 | Claude Marketplace（:459） | `https://claude.com/marketplace`，页内 **"Submit a connector" / "Submit a plugin" 双提交入口**（目录实录） | skill → plugin | 中（提交制 + verified 体系，细则目录未实录）；863 connectors 实测口径 | P1 |
| 7 | Salesforce AgentExchange（:460） | 店面 `https://agentexchange.salesforce.com/`（partner 上架路径） | 需 CRM 生态产品化 | 高：企业级安全审核 + partner 资质（推断） | P3 |
| 8 | AWS Marketplace「AI Agents & Tools」（:461） | `https://aws.amazon.com/marketplace/solutions/ai-agents-and-tools` | 企业 agent/MCP 商品 | 高：PAYG/合同企业采购流程（推断） | P3 |
| 9 | GitHub Marketplace Copilot extensions（:462） | 类目页 `https://github.com/marketplace/category/copilot-extensions`，**'Create a new extension' → /marketplace/new**（目录实录） | 需改造为 Copilot 扩展（GitHub App 承载，免费上架） | 中-高（GitHub App 开发；扩展名录当时抓取失败，目录如实注记） | P2 |
| 10 | LobeHub MCP Market（:464） | `https://market.lobehub.com/s/plugins` + CLI `@lobehub/market-cli`（**register**/search，目录实录） | 需 MCP 形态改造 | 中（注册凭据接入；收录量未核实——目录如实注记）；国内团队高完成度市场 | P2 |
| 11 | Raycast Store AI（:465） | `https://www.raycast.com/store/category/ai` | 需 Raycast 扩展开发（macOS） | 中（开发门槛）；小渠道（AI 类约 50 个扩展） | P3 |
| 12 | Coursera（:466） | `https://www.coursera.org/search?query=ai%20agents` | 课程资产 | 高（机构合作制，推断）——当前无课程资产 | 暂缓 |
| 13 | Microsoft 365 Agent Store / Partner Center（:467） | 目录实录文档：`https://github.com/MicrosoftDocs/m365copilot-docs/blob/main/docs/publish.md`（ISV 经 Partner Center 提交） | 需 M365 app/agent 形态 | **高：验证含 RAI checks**（目录实录） | P3 |
| 14 | Slack Marketplace（:468） | `https://slack.com/marketplace` | app 与 MCP server 双形态 | 中-高（Slack app 审核，推断） | P3 |
| 15 | Atlassian Marketplace（:469） | `https://marketplace.atlassian.com`（Agents 一级类目实录） | 需 app 形态；受众为研发团队，fit 弱 | 中-高（推断） | P3 |
| 16 | JetBrains Marketplace（:470） | `https://plugins.jetbrains.com`（公开 API searchPlugins 实录） | 需 IDE 插件开发 | 中-高（IDE 插件开发门槛，推断） | P3 |
| 17 | Chrome Web Store（:471） | `https://chromewebstore.google.com` | 需浏览器扩展开发 | 中（扩展开发+商店审核，推断）；无 AI 顶级类目、可发现性弱（目录实录） | P3 |
| 18 | GPT Store（:472） | `https://chatgpt.com/store`（+ chatgpt.com/gpts 入口） | 需重建为 GPT（prompt 降维，**丢失确定性脚本优势**） | 中：Builder Profile 验证 + 人工与自动审核（目录实录）；目录实测登录墙（store 路由返回落地页） | P2 |
| 19 | Poe 创作者市场（:473） | `https://poe.com/creators`（+ creator.poe.com 官方文档） | 需重建为 bot（六类创建路径，目录实录） | 中：创作者面板需登录（目录实测）；**变现 price-per-message 经 Stripe，$10 起付，23 地区含香港不含中国大陆**（目录实录）——收款适配注意 | P2（变现实验位） |
| 20 | Hugging Face Spaces（:474） | `https://huggingface.co/spaces`（官方托管，三形态：Gradio/Docker/静态 HTML，可 embed） | **评测演示间托管**（非技能包本身） | 低（免费账号即可部署） | P1（服务课程转化） |
| 21 | Prime Intellect Environments Hub（:475） | `https://app.primeintellect.ai/dashboard/environments`（登录后入口）+ `prime env push` CLI（目录实录） | RL 环境资产（wheel） | —（**形态不符，不适配**） | 不适配 |
| 22 | PromptBase（:476） | `https://www.promptbase.com`（sell prompts 创作者上架分成，目录实录） | raw prompt 降维 | 低-中（上架分成制；站点反爬严格，成交数据未核实——目录如实注记） | P2/P3 |

### A8.2 生态索引与 awesome 精选（7 条，全部 GitHub PR 收录制，:478-487）

| # | 渠道（目录行） | 提交入口（目录实录） | 适配形态 | 预估门槛 | 优先级 |
|---|---|---|---|---|---|
| 23 | hesreallyhim/awesome-claude-code（:481，54.8k★） | 仓 `https://github.com/hesreallyhim/awesome-claude-code`（README 由 generate_readme.py 从 CSV 生成——PR 按仓内贡献说明，目录未实录细节） | 收录条目 | 低（提 PR 即可，推断） | **P0** |
| 24 | travisvn/awesome-claude-skills（:482） | 仓 `https://github.com/travisvn/awesome-claude-skills` | 收录条目 | 低（PR）；⚠️ 目录实测约 5 个月未更新，注意时效 | **P0** |
| 25 | VoltAgent/awesome-agent-skills（:483，35k★，MIT） | 仓 `https://github.com/VoltAgent/awesome-agent-skills` | 收录条目 | 低（PR） | **P0** |
| 26 | VoltAgent/awesome-openclaw-skills（:484，API 实测 52,854★） | 仓 `https://github.com/VoltAgent/awesome-openclaw-skills`（整理自 ClawHub） | 需先上 ClawHub 再被整理 | 低（顺势收录，推断） | P1 |
| 27 | ithiria894/awesome-claude-code-hooks（:485，仅 26★） | 仓 `https://github.com/ithiria894/awesome-claude-code-hooks` | hooks 向——guard-hooks 整改达标后再投 | 低（PR） | P2 |
| 28 | github/awesome-copilot（:486，39.5k★，MIT） | 仓 `https://github.com/github/awesome-copilot`（agents/instructions/skills/plugins/hooks 七类） | 需 Copilot 形态改造 | 低-中（PR + 形态改造） | P2 |
| 29 | GitHub Topics 聚合（:487） | **非提交制**：`https://github.com/topics/claude-skills`（同类 topic：agent-skills、mcp-server）——自有仓打 topic 标签即被聚合 | 被动发现 | **零门槛**（打标即可） | **P0** |

### A8.3 模板市场与聚合安装器（3 条，:489-494）

| # | 渠道（目录行） | 提交入口（目录实录） | 适配形态 | 预估门槛 | 优先级 |
|---|---|---|---|---|---|
| 30 | davila7/claude-code-templates（:492） | 仓 `https://github.com/davila7/claude-code-templates` + aitmpl.com 市场（六类组件聚合；**组件收录流程目录未实录**） | skill 组件收录 | 低-中（聚合器收录，推断） | P1 |
| 31 | n8n 官方工作流模板库（:493） | `https://n8n.io/workflows/`（目录实录「创作者可提交模板获利」） | 需 n8n 工作流形态改造 | 中（工作流重建） | P2 |
| 32 | awesome-n8n-templates（:494） | 仓 `https://github.com/enescingoz/awesome-n8n-templates` | 需 n8n 工作流形态 + PR | 低-中 | P2 |

### A8.4 国内平台商店（5 条，:496-503；均需平台内重建为智能体/prompt 形态）

| # | 渠道（目录行） | 提交入口（目录实录） | 适配形态 | 预估门槛 | 优先级 |
|---|---|---|---|---|---|
| 33 | Dify 插件市场（:499） | `https://marketplace.dify.ai/`（Tool/Model/Agent Strategy/Data Source/Extension/Triggers 六类 + Verified 认证 + Trending） | 需 Dify 插件规范改造（Extension/Tool 类可能适配） | 中：插件改造 + Verified 认证审核（推断）；头部插件安装百万级（DeepSeek ~1.83M，目录实测）——国内最可核验商店标杆 | P1 |
| 34 | Kimi+ 智能体广场（:500） | `https://www.kimi.com/kimiplus-square`（2026-09-29 目录实测匿名可访问） | 智能体（"Kimi+=预设 Prompt 模板垂直化"——与技能的 prompt 规则层天然契合，目录实录方法论） | 低-中（平台内创建，推断）；无公开热度数据（目录如实注记） | **P1**（国内 C 端首选） |
| 35 | 腾讯元器（:501） | `https://yuanqi.tencent.com/`（零代码创建；分发微信/应用宝） | 零代码智能体重建 | 低-中（平台内创建，推断）；总量未公布（目录如实注记）——微信生态触达位 | P1 |
| 36 | 文心智能体平台 AgentBuilder（:502） | `https://agents.baidu.com`（description 实录「流量分发路径，完成商业闭环」） | prompt 编排智能体 | 低-中（平台内创建，推断） | P2 |
| 37 | 扣子商店（:503） | `https://www.coze.cn/store`（目录实测 HTTP 200；商店列表 JS 渲染未抓到，规模未核实——如实注记） | 扣子平台内发布 | 低-中（平台内发布，推断）；国内最大体量之一（目录口径） | P1 |

### A8.5 内容场分发案例（1 条，:505-508）

| # | 渠道（目录行） | 入口（目录实录） | 性质 | 优先级 |
|---|---|---|---|---|
| 38 | B站 skill 教程案例（:508） | `https://www.bilibili.com/video/BV1zLKt6tEQn/`（"一个 skill 里面 10000+ 提示词"，播放 4,889） | **非上架渠道**——内容营销风向样本（"skill 化打包"叙事国内有真实需求） | 发布后推广动作（见节奏第三节） |

### 补充：A4.6 目录内〔待归类→A8〕注记的四条分发渠道（:247/:250/:251/:255）

| 渠道 | 目录实录入口 | 适配形态 | 门槛（推断） | 优先级 |
|---|---|---|---|---|
| npm registry（:247） | `https://registry.npmjs.org/`（目录口径：「MCP server 与 agent 技能包事实上的主分发通道」） | skill 包可 npm 打包（skills.sh 生态走 npx 安装） | 低 | P1（随 skills.sh 一并做） |
| PyPI（:250） | `https://pypi.org/`（官方 SDK mcp-server-fetch 均经此分发） | Python 端包形态 | 低 | P2 |
| Open VSX Registry（:251） | `https://open-vsx.org/`（支持企业自托管） | 需 IDE 扩展形态 | 中-高 | P3 |
| Visual Studio Marketplace（:255） | `https://marketplace.visualstudio.com/` | 需 VS Code 扩展形态 | 中-高 | P3 |

---

## 三、发布节奏建议（先免费层铺量）

**第 0 步（前置硬条件）**：建仓。`skillfactory` 当前**不是 git 仓库**（本会话 `git status` 实测 `fatal: not a git repository`）。GitHub 开源仓是一切渠道的地基：cursor.directory 要粘贴 repo URL、awesome 收录要 PR、claude-plugins-official 要 marketplace.json、GitHub Topics 要自有仓打标。没有仓，第一波全部无从谈起。

**第一波 P0——零门槛免费铺量（建仓后本周）**：
1. **GitHub 开源仓**：两包以 monorepo（`skills/meeting-minutes/` + `skills/office-templates/`）或分仓发布，MIT，打 topic `claude-skills` / `agent-skills`（→ 顺带覆盖渠道 #29）；
2. **cursor.directory**（#5）：网页粘贴 repo URL，自动识别 `skills/*/SKILL.md`，零 PR——成本最低的官方分发面；
3. **skills.sh**（#3）：先实测其发布命令（目录未实录），装入 20 个 agent 客户端的头号注册表；
4. **awesome PR ×3**（#23/#24/#25）：hesreallyhim/awesome-claude-code（54.8k★）、VoltAgent/awesome-agent-skills（35k★）、travisvn/awesome-claude-skills；
5. **anthropics/skills**（#1）：核实贡献流程，可接受则提交——官方合集是最高信任背书。

**第二波 P1——免费注册/审核（第 2-4 周）**：
6. **ClawHub**（#4）：CLI 发布，按要求做签名清单（有 moderation，周期长于 PR）；
7. **anthropics/claude-plugins-official**（#2）+ **Claude Marketplace Submit a plugin**（#6）：插件形态打包；
8. **HF Spaces**（#20）：把两技能的盲评对照 demo（基线 vs 技能产物并排 + eval/runner 可复跑）部署为可 embed 演示间，服务课程转化；
9. **国内首批：Kimi+（#34）与扣子（#37）**：prompt 规则层降维重建（两技能的「权威规则/红线/触发短语」本身就是 prompt 资产），服务国内课程获客；腾讯元器（#35）跟进微信生态。

**第三波 P2——形态改造与变现实验（第 1-2 月）**：
10. **Poe bot**（#19）：把打分器/出卷器类能力封装为 Script Bot 验证按量付费意愿（price-per-message 变现目录实录；**Stripe 23 地区含香港不含中国大陆**，收款先解决）；GPT Store（#18）平行试验；
11. **Dify 插件化**（#33）：国内最可核验的插件商店标杆，Extension/Tool 类改造；
12. **n8n 模板**（#31/#32）、**LobeHub MCP 化**（#10）、**npm 打包**（补充表）；guard-hooks 整改达标后投 awesome-claude-code-hooks（#27）与 awesome-copilot（#28）。

**第四波 P3——企业级（视业务再议）**：Salesforce/AWS/M365/Slack/Atlassian/JetBrains/Chrome/Raycast/PromptBase（#7-8/#13-17/#11/#22）——均需 partner 资质或全新形态，当前资产阶段不投入。

**不做**：Prime Intellect Environments Hub（RL 环境形态不符，#21）、Coursera（无课程资产，#12）。**B站内容**（#38）作为发布后的推广动作：仿「skill 化打包」叙事做两技能实测视频，为 GitHub 仓引流。

---

## 四、发布前检查项

### 4.1 本次已执行检查（2026-09-30 本会话实测）

| 检查 | 命令/方法 | 结果 |
|---|---|---|
| 许可证 | `head` 两包 `LICENSE` 与 `SKILL.md` front-matter | ✅ 两包均 MIT（`Copyright (c) 2026 SkillFactory`；front-matter `license: MIT`） |
| front-matter 五字段 | healthcheck `front_matter_fields` + SKILL.md 实读 | ✅ 两包 name/version/license/description/permissions 齐全（mm-dist/ot-dist REPORT.md PASS） |
| 密钥/内网信息扫描 | `grep -rniE "sk-[a-zA-Z0-9]{8}\|api[_-]?key\|password\|secret\|token...\|Bearer \|C:\\Users\|Administrator\|100.64.\|42.194\|36.139"` 于两包 | ✅ **0 命中**（无密钥、无机器名、无 tailnet/公网 IP） |
| 仓库就绪 | `git status`（cwd=skillfactory） | ❌ **未就绪**：`fatal: not a git repository`——需 init + GitHub 建远端 |
| 运行时产物混入 | `find meeting-minutes-skill/.mimosa -type f \| wc -l` | ❌ **发现 19 个文件**（finding-ledger/hook-state/hook-status/reports/history 五类 agent 运行时产物混入分发包）——**发布前必须删除**（同 V3 报告 R5 在 oracle/out 的同类问题） |
| 依赖声明 | `grep "from docx"` mm 包 scripts + `cat` ot 包 requirements.txt | ❌ **meeting-minutes 无 requirements.txt**，但 `scripts/minutes.py:128` `from docx import Document`（python-docx）——需补声明（office-templates 已有 `python-docx>=1.1` ✅） |
| MANIFEST/校验和 | `find … -iname "*MANIFEST*" -o -iname "*.sha256"` | ❌ 两包均无 MANIFEST.json/校验和（V3 报告 R2/R6 同口径欠账在 dist 包延续） |
| 内部路径字样 | `grep "zcode\|D:\\workspace\|SKILLFACTORY"` | ⚠️ 3 处低危：mm 包 `SKILL.md:59`「在 skillfactory 资产内时」、ot 包 CHANGELOG/EVALUATION 引用开发方存档相对路径——非敏感（无机器/用户名），建议发布前改为中性表述或确认保留 |
| 包内声称的仓库链接 | `grep -rhoE "github\.com/..."` 两包 | ✅ 无（不存在与未来建仓地址矛盾的旧链接） |

### 4.2 发布门（全部通过方可上架）

1. **包卫生**：删除 `dist/meeting-minutes-skill/.mimosa/`（19 文件）；补 `requirements.txt`（python-docx>=1.1）；两包打 MANIFEST.json（逐文件 sha256，V3-FORGE-DELIVERY.md「下一步」第 4 条原文要求）；内网相对路径表述清理；清理后**重跑体检确认维持 A 级**。
2. **仓库就绪**：`git init` + GitHub 建仓 + `v1.0.0` tag；README 载明 License/安装方式/评测结论；打 topic 标签。
3. **评测披露口径**（诚实红线）：office-templates 一切对外文案标注 `single_round_signal`（单轮盲评）；两资产统一披露 `synthetic-passed ✓ / real-verified ✗` 双状态（效率门未测、真实复验未做，V3 报告 R4/R8）；引用 meeting-minutes Δ+5.25 时注明该数字来自修正后重算（ab_summary `correction` 字段）。
4. **渠道格式适配**：cursor.directory 按 `skills/*/SKILL.md` 布局确认仓结构；skills.sh 发布命令、anthropics/skills 贡献流程均目录未实录——**上架前逐渠道现场核实，不预写链接**。
5. **许可证声明**：MIT 主体无障碍；声明运行依赖 python-docx（MIT）；若提交 anthropics/skills，注意其文档技能为 source-available 口径，我方 MIT 全开需在 README 明示授权边界。

---

## 五、本次核验记录（可复跑）

- 读：`v2/CATALOG.md` :450-511（A8 全节 37 条）、:98（anthropics/skills）、:247/:250/:251/:255（A4.6 待归类四条）；`v2/evalbench-v02/{meeting-minutes,lark-cli,hooks-mastery}/ab_summary.json` 全文；`v3/healthchecks/{mm-dist,ot-dist,guard-hooks,prompt-reg}/REPORT.md` 全文；`v3/report/V3-FORGE-DELIVERY.md` 全文；两包 SKILL.md/LICENSE/EVALUATION/requirements.txt。
- 实跑：`python -c` 实读 office-templates 盲评存档（`v3/assets/office-templates/tests/ab_summary.json` → tasks=5、Δ=1.2、winRate=1、accepted=True，与包内 EVALUATION.md 逐项吻合）；密钥扫描 grep（0 命中）；`git status`（非 git 仓）；`.mimosa` find（19 文件）；docx import / MANIFEST / github 链接 grep（见 4.1 表）。
- 未执行（如实声明）：未实际向任何渠道提交；skills.sh 发布命令与 anthropics/skills 贡献流程未现场核实（目录未实录，本清单如实标注而非代填）；office-guard-hooks 与 prompt-regression 整改未做（仅按体检报告列出失败项）。

# ASSET-DOC — AGENTS.md 开放规范（agents.md 官网 + agentsmd/agents.md 官方仓，合并条目）

- **资产 URL**：https://agents.md（官网）｜https://github.com/agentsmd/agents.md（官方仓）
- **对应目录条目**：`skillfactory/v2/CATALOG.md` 「AGENTS.md 开放规范」（官网 + 官方仓合并条目）
- **抓取日期**：2026-09-29
- **抓取方式**：WebFetch 直接抓官网 https://agents.md 两次（第一次取全貌，第二次定向补 "How to use"/示例/FAQ 的原文措辞）；另 WebFetch 官方仓 raw README（https://raw.githubusercontent.com/agentsmd/agents.md/main/README.md）作合并条目的仓库侧补充。**如实说明**：WebFetch 摘要模型对超过 125 字符的原文拒绝逐字复述，故本文以「要点整理 + 短引文（≤125 字符英文原文）」呈现，短引文为页面原文；未能逐字留存的整段原文以要点形式保留。
- **原文语言**：英文

---

## 一、资产定位

- 官网原文定位："a simple, open format for guiding coding agents"，即一种指导编码智能体的**简洁开放格式**。
- 宣传语："a README for agents"——给 AI 编码智能体提供一个**专门的、可预测的**位置存放项目上下文与指令，与面向人类的 README.md 互补。
- 采用规模：官网称已被 **over 60,000 open-source projects**（超 6 万个开源项目）使用（2026-09-29 实抓页面数字）。
- 知名采用者（官网示例展示）：openai/codex、apache/airflow、temporalio/sdk-java、PlutoLang/Pluto。
- 背景：由 OpenAI Codex、Amp、Jules、Cursor、Factory 等协作推出；现由 **Linux 基金会旗下 Agentic AI Foundation** 管理。
- 一句话本质：**无格式强制、无必填字段的一个 Markdown 文件**，放在仓库根目录，编码 agent 读它获取项目指令。

## 二、格式规范（"参数"/字段）

- **无必填字段**（"No required fields"）：FAQ 原文 "No. AGENTS.md is just standard Markdown."——就是标准 Markdown，**没有 schema、没有 frontmatter 要求**。
- 标题随意：agent 直接解析文本内容，不依赖特定标题层级。
- 官网建议覆盖的常见章节（推荐而非强制）：
  - Project overview（项目概览）
  - 构建/测试命令（setup & build & test commands）
  - 代码风格（code style）
  - 测试说明（testing instructions）
  - 安全注意事项（security considerations）
  - PR/提交规范（PR/commit instructions）
  - 部署步骤等其他团队约定
- 约束总结：**格式约束为零，价值全在内容**——写"你会告诉新同事的任何事"（"anything you'd tell a new teammate belongs here too."）。

## 三、使用方法（官网 How to use，四步）

1. **Add AGENTS.md**：在仓库根目录创建文件（"Create an AGENTS.md file at the root of the repository."）；多数编码 agent 也可以代为生成。
2. **Cover what matters**：覆盖项目概览、构建/测试命令、代码风格、测试说明、安全注意事项等关键内容。
3. **Add extra instructions**：补充提交规范、PR 指南、部署步骤、安全提醒等——"anything you'd tell a new teammate belongs here too."
4. **Large monorepo?**：在子包中放嵌套 AGENTS.md（见第五节）。

维护约定：
- 可随时后续更新，官方将其定位为**活文档**（"living documentation"）。
- 从其他格式迁移：重命名并建符号链接保兼容，如 `mv AGENT.md AGENTS.md && ln -s AGENTS.md AGENT.md`。

## 四、官方示例文件（官网示例，逐条保留）

官网给出的样例 AGENTS.md 包含三大部分（官网页面示例 + 官方仓 README 示例一致）：

**Dev environment tips（开发环境提示）**
- 用 `pnpm dlx turbo run where <project_name>` 快速定位包所在目录
- 用 `pnpm install --filter <project_name>` 添加工作区依赖
- 用 `pnpm create vite@latest` 创建新的 React+Vite 包（README 示例同款提示）
- 代码风格：TypeScript strict mode、单引号无分号、优先函数式写法（官网第一次抓取摘要）

**Testing instructions（测试说明）**
- CI 计划位于 `.github/workflows`
- 跑全部检查：`pnpm turbo run test --filter <project_name>`
- 聚焦单个测试：`pnpm vitest run -t "<test name>"`
- 移动文件后跑 `pnpm lint --filter <project_name>`
- 明确要求："Add or update tests for the code you change, even if nobody asked."（改了代码就补测试，即使没人要求）

**PR instructions（PR 规范）**
- 标题格式："Title format: [<project_name>] <Title>"
- 提交前必须先跑 lint 和 test

## 五、monorepo 嵌套与冲突规则

- **嵌套**：在每个子包里再放一个 AGENTS.md；"Agents automatically read the nearest file in the directory tree"——agent 自动读取目录树中**距离被编辑文件最近**的那个。
- **就近生效**（nearest file wins）：每个子项目可获得定制指令；官网举例 OpenAI 主仓库曾有 **88 个** AGENTS.md 文件。
- **冲突裁决**：多个文件冲突时，"The closest AGENTS.md to the edited file wins"（离被编辑文件最近的赢）。
- **最高优先级**：用户在聊天中的显式提示覆盖一切文件指令。

## 六、支持的工具（官网列表，2026-09-29 实抓）

OpenAI Codex、Google Jules、Factory、Aider、goose、opencode、Zed、Warp、VS Code、Devin (Cognition)、UiPath、JetBrains Junie、Amp、Cursor、RooCode、Gemini CLI、Kilo Code、Phoenix、Semgrep、GitHub Copilot coding agent、Ona、Windsurf、Augment Code。

工具侧适配方式（FAQ 给出的两例）：
- **Aider**：在 `.aider.conf.yml` 中配置 `read: AGENTS.md`
- **Gemini CLI**：在 `.gemini/settings.json` 设置 `{ "context": { "fileName": "AGENTS.md" } }`

## 七、FAQ（限制与常见问题，逐条保留）

| 问题 | 官方回答 |
|---|---|
| 有必填字段吗？ | 无。"No. AGENTS.md is just standard Markdown." 标题随意，agent 解析文本内容本身 |
| 多文件指令冲突怎么办？ | "The closest AGENTS.md to the edited file wins"；用户聊天显式提示优先级最高 |
| 会自动执行测试吗？ | 会——列出命令后，agent 会尝试运行相关检查并修复失败 |
| 以后能更新吗？ | 能，视为 living documentation（活文档） |
| 如何从别的格式迁移？ | 重命名 + 建符号链接：`mv AGENT.md AGENTS.md && ln -s AGENTS.md AGENT.md` |
| Aider 怎么接入？ | `.aider.conf.yml` 中 `read: AGENTS.md` |
| Gemini CLI 怎么接入？ | `.gemini/settings.json` 中 `{ "context": { "fileName": "AGENTS.md" } }` |

**固有限制（从规范性质如实归纳）**：规范本身不提供任何校验/约束机制（无 schema、无 lint），效果完全取决于写入内容的质量与 agent 的遵从度；官网未承诺任何执行保证。

## 八、官方仓 README 补充（agentsmd/agents.md，2026-09-29 raw 实抓）

- README 与官网同调："a simple, open format for guiding coding agents"、"a README for agents: a dedicated, predictable place"。
- README 仅给最小示例（三节：Dev environment tips / Testing instructions / PR instructions，内容与官网示例一致）；**README 不含**支持工具列表与 FAQ，官网为信息更全的一侧。
- 该仓库本体是 agents.md 官网源码：**Next.js 网站**，本地运行 `pnpm install` → `pnpm run dev` → 访问 http://localhost:3000。

## 九、抓取备注（疑点与未竟事项，如实记录）

- WebFetch 摘要模型明示"需将每段引用控制在 125 字符以内"，故整段英文原文未逐字留存；本档短引文均为两次抓取中出现的原文片段，要点内容经两次独立抓取交叉一致（如四步用法、FAQ 各条、嵌套规则两次结果吻合）。
- "60,000+ 项目采用"为官网自述数字，未独立核验仓库统计。
- "OpenAI 主仓库曾有 88 个 AGENTS.md"为官网页面举例表述（"曾有/there were"口径），未到 openai 仓库实数复核。
- 支持工具列表为官网页面当日实抓快照，工具阵容随时间变动，引用时注明日期。

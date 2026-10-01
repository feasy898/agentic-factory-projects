# 场景选型：wshobson/commands 命令库 —— Workflow vs Tool（三场景结论）

## 结论速览

| # | 场景（全文照录） | 选型 | 一句话理由 | 推荐命令（真实存在，已核实） | 是否精确匹配 |
|---|---|---|---|---|---|
| ① | 『每周一早上，把上周的访问日志、错误日志、成本账单各审一遍，交叉核对异常，最后汇总成一页周报』 | **Workflow** | 多数据源并行审阅 + 跨源交叉核对 + 聚合产出，是典型多代理编排任务，超出任何单一用途工具的职责边界 | 无精确匹配；结构上最近似 `/workflows:full-review`（workflows/），实用组合见下文 | ❌ 无语义精确匹配（已如实说明并给组合） |
| ② | 『把 src/utils/date.ts 里的 formatDate 函数优化一下性能』 | **Tool** | 单文件、单函数的单一用途优化，无需多代理编排 | `/tools:refactor-clean`（tools/） | ⚠️ 最接近匹配（库中无名为"性能优化"的独立 Tool） |
| ③ | 『对当前项目做一次依赖与配置的安全漏洞扫描』 | **Tool** | 一次性只读扫描是典型的单一用途操作；多代理编排属修复落地阶段，不属于"扫描"本身 | `/tools:security-scan`（tools/） | ✅ 精确匹配（描述明确覆盖依赖漏洞与安全配置错误） |

---

## 核查基础（清单来源与验证方式）

- 本机（windev-01）无本地安装副本：已检查 `C:\Users\Administrator\.claude\commands` 与工作区 `.claude/`，均不存在。因此以下全部以**源仓库实测**为准。
- 清单来源：GitHub API `https://api.github.com/repos/wshobson/commands/contents/{tools,workflows}?ref=main`，取数日期 **2026-09-29**，main 分支 commit **`27d3e77b1a844223721f6c983ddf261ac4441b89`**。
- 实测清单规模：`workflows/` 共 **15** 个命令，`tools/` 共 **42** 个命令。调用前缀按任务给定（`/workflows:` 与 `/tools:`）。
- workflows/ 全量名单（逐一核对了各文件正文开头描述）：
  `data-driven-feature` `feature-development` `full-review` `full-stack-feature` `git-workflow` `improve-agent` `incident-response` `legacy-modernize` `ml-pipeline` `multi-platform` `performance-optimization` `security-hardening` `smart-fix` `tdd-cycle` `workflow-automate`
- tools/ 全量名单（42）：
  `accessibility-audit` `ai-assistant` `ai-review` `api-mock` `api-scaffold` `code-explain` `code-migrate` `compliance-check` `config-validate` `context-restore` `context-save` `cost-optimize` `data-pipeline` `data-validation` `db-migrate` `debug-trace` `deploy-checklist` `deps-audit` `deps-upgrade` `doc-generate` `docker-optimize` `error-analysis` `error-trace` `issue` `k8s-manifest` `langchain-agent` `monitor-setup` `multi-agent-optimize` `multi-agent-review` `onboard` `pr-enhance` `prompt-optimize` `refactor-clean` `security-scan` `slo-implement` `smart-debug` `standup-notes` `tdd-green` `tdd-red` `tdd-refactor` `tech-debt` `test-harness`
- 注意：该库没有名为 `log-analyzer` / `performance-*` / `status-reporter` 一类的命令——场景①②的"无精确匹配"结论是基于全量名单逐一核对得出，不是猜测。

---

## 场景①：每周一早审访问日志、错误日志、成本账单，交叉核对异常，汇总一页周报

**选型：Workflow。**
理由：三个异构数据源需要并行独立审阅、结果要跨源交叉核对、最后聚合为一份统一产出——这正是"多代理编排"要解决的多阶段协同问题，任何单一用途 Tool 都只覆盖其中一个环节。

**诚实说明：库中没有语义匹配此任务的单一命令（Workflow 与 Tool 都没有）。**
- 15 个 workflows 已逐一核对描述：`incident-response` 是生产事故的应急响应（被动、单事件），`workflow-automate` 是**编写** CI/CD 流水线（对象是构建自动化，不是日志审计），`ml-pipeline`/`data-driven-feature`/`full-stack-feature`/`feature-development`/`multi-platform`/`git-workflow`/`tdd-cycle`/`smart-fix`/`improve-agent`/`legacy-modernize`/`performance-optimization`/`security-hardening` 均明显无关。
- **最近的 Workflow：`/workflows:full-review`（workflows/ 目录）**。其骨架与本任务完全同构——原文："Perform a comprehensive review using multiple specialized agents with explicit Task tool invocations"，多个专门代理并行审阅后 "consolidated into a unified action plan"（汇总为统一报告）。但必须指出：它的审阅维度是代码质量/安全/架构/性能/测试覆盖（各节 subagent_type 为 `code-reviewer`、`security-auditor`、`architect-reviewer`、`performance-engineer`、`test-automator`），**审阅对象是代码，不是日志与账单**。它只能作为多代理审阅的结构模板改造使用，不能开箱即用。

**可执行的最近组合（Tool 路线，按序手工编排）：**

1. `/tools:error-analysis`（tools/）——审**错误日志**。原文："Error Analysis and Resolution: Analyze and resolve errors in: $ARGUMENTS"。**访问日志**无专门命令（全量名单核实无 log 分析类工具），实务上可将访问日志中的异常模式（4xx/5xx 突增、慢请求）作为 `$ARGUMENTS` 一并喂给它，间接覆盖。
2. `/tools:cost-optimize`（tools/）——审**成本账单**。原文："Cloud Cost Optimization … Analyze cloud spending, identify savings opportunities"（AWS/Azure/GCP 云支出分析），与"成本账单审一遍"语义对应。
3. 汇总**周报**：库中最接近的汇报生成命令是 `/tools:standup-notes`（tools/），但它是**日报**导向且数据源固定为 Obsidian vault + Jira（原文："Generate daily standup notes by reviewing Obsidian vault context and Jira tickets"），不能直接产出日志/账单周报——**最终一页周报的聚合步骤需人工完成或在库外完成，如实说明**。

> 结论：①按任务性质应选 Workflow；库内无精确匹配，结构最近似 `/workflows:full-review`（仅可改造使用），实操推荐 `error-analysis → cost-optimize →（聚合）` 的工具组合，周报聚合环节库内缺位。

---

## 场景②：优化 src/utils/date.ts 中 formatDate 函数的性能

**选型：Tool。**
理由：作用域是一个文件里的一个函数，属单一用途的定向优化，拉起多代理编排（分析→数据库→前端→移动端的全栈流水线）纯属过度工程。

**推荐命令：`/tools:refactor-clean`（tools/ 目录）。**
核实依据（tools/refactor-clean.md 原文）：
- 角色定位："Analyze and refactor the provided code to improve its quality, maintainability, **and performance**"——"对提供的代码片段做优化"正是其职责，`$ARGUMENTS` 传入 `src/utils/date.ts` 的 `formatDate` 即可；
- 正文含专项内容：问题清单列有 "**Performance Issues** – Inefficient algorithms (O(n²) or worse)"，且报告模板含 "**### 7. Performance Optimizations**"、"Performance benchmarks included" 章节——函数级性能优化（算法复杂度、冗余计算、热路径）落在其明确覆盖范围内。

**诚实说明：库中没有独立命名的"性能优化" Tool，`refactor-clean` 是语义最近的命令。**
- `/tools:multi-agent-optimize`（tools/）名字里带 optimize，但其描述是 "Optimize **application stack** using specialized optimization agents"（数据库/性能/前端代理协作），面向整个应用栈，对单函数不成比例，不推荐。
- `/workflows:performance-optimization`（workflows/）是全栈端到端多代理流程（应用剖析→数据库→后端→API→前端→移动端），同样不成比例，不推荐。
- 可选辅助：若优化前需先定位热点，可先跑 `/tools:smart-debug`（tools/，其描述注明涉及性能问题时会引入 `performance-engineer` 支援），再交 `refactor-clean` 落地。

---

## 场景③：对当前项目做依赖与配置的安全漏洞扫描

**选型：Tool。**
理由：一次性的只读漏洞扫描是典型单一用途操作；库中对应的多代理 Workflow（`security-hardening`）是"实施加固与修复"的编排流程，不是扫描本身——扫描用 Tool，扫描出问题后的修复编排才轮到 Workflow。

**推荐命令：`/tools:security-scan`（tools/ 目录）——语义精确命中。**
核实依据（tools/security-scan.md 原文）：
- 标题 "Security Scan and Vulnerability Assessment"，定位 "Perform comprehensive security audits to identify vulnerabilities"；
- 关键句："Focus on OWASP Top 10, **dependency vulnerabilities, and security misconfigurations** with actionable remediation steps"——"依赖漏洞 + 安全配置错误"两个面**都在其显式覆盖范围内**，与场景表述逐点对应；
- 正文含 `dependency_scan` 专项（Python: safety/PyUp、pip-audit；Node: npm audit/Yarn audit/Retire.js/Snyk）、SAST（bandit/semgrep）、容器扫描（Trivy）与 secrets 检测（gitleaks/trufflehog/detect-secrets）的完整工具矩阵。

**备选与后续：**
- 若需分域深扫，可组合：`/tools:deps-audit`（tools/，"Dependency Audit and Security Analysis"——已知漏洞/许可证/供应链）+ `/tools:config-validate`（tools/，"…ensure configurations are **secure**, consistent, and error-free across all environments"），分别对应"依赖"与"配置"两个面。
- 扫描出问题后的修复编排：`/workflows:security-hardening`（workflows/，"Implement security-first architecture and hardening measures with coordinated agent orchestration"）——属下一阶段，不是本次"扫描"的答案。

---

## 附录：核查命令记录（全部于 2026-09-29 实际执行）

1. 本地安装副本检查：`ls C:/Users/Administrator/.claude/commands` 与 `ls D:/workspace/zcode研究/.claude` → 均不存在（No such file or directory）。
2. 目录清单：`curl -s https://api.github.com/repos/wshobson/commands/contents/tools?ref=main`（HTTP 200，38,035 字节，42 个 .md）；同法取 `workflows`（HTTP 200，14,219 字节，15 个 .md）。
3. main 分支 commit：`curl -s https://api.github.com/repos/wshobson/commands/commits/main` → `27d3e77b1a844223721f6c983ddf261ac4441b89`。
4. 逐文件原文核读（raw.githubusercontent.com，main 分支）：全部 15 个 workflows 的正文开头；tools 侧核读了 `security-scan` `deps-audit` `config-validate` `compliance-check` `tech-debt` `ai-review` `refactor-clean`（含全文 grep：performance/algorithms/complexity/O(n²)/Performance Optimizations 章节均在）`multi-agent-optimize` `error-analysis` `error-trace` `smart-debug` `debug-trace` `cost-optimize` `standup-notes` `monitor-setup` `data-pipeline` `multi-agent-review` `slo-implement`。
5. 场景①的"无精确匹配"结论：基于第 2 步全量名单 + 第 4 步对 15 个 workflows 描述的逐一核对；"库中无日志分析类工具"基于对 42 个 tools 文件名的逐一核对（无任何 `log-*` 条目）。

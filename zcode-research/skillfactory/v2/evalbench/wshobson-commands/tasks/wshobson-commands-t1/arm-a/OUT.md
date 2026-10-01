# wshobson/commands 命令选型 —— 三场景结论（arm-a）

> 依据：`../ASSET-DOC.md` 及其存档原文 `../_raw_README.md`（行号引用均出自该 raw README）。
> 所有推荐命令名已于本会话经 GitHub Contents API 实测存在于对应目录（验证记录见文末「核查记录」）。
> 调用语法：`/workflows:<name>` 与 `/tools:<name>`，参数为命令后自由文本（经 `$ARGUMENTS` 注入）。

## 结论速览

| 场景 | 选型 | 推荐命令（所属目录） |
|---|---|---|
| ① 每周例行：日志/账单审计 + 交叉核对 + 周报 | 任务形态应属 Workflow（多领域交叉），但**库中 15 个 workflow 无一语义匹配**，如实降级为 Tool 链组合 | `error-trace` + `error-analysis` + `cost-optimize` →（`data-validation`）→ `standup-notes`（全部 `tools/`） |
| ② formatDate 单函数性能优化 | **Tool**（单域、聚焦、路径明确） | `multi-agent-optimize`（`tools/`）；有测试护栏时改用 `tdd-refactor`（`tools/`） |
| ③ 依赖与配置安全漏洞扫描 | **Tool**（聚焦评估，无需多代理编排） | 单命令 `security-scan`（`tools/`）；精确覆盖两域用 `deps-audit` + `config-validate`（`tools/`） |

---

## 场景① 每周一早上：审访问日志、错误日志、成本账单，交叉核对异常，汇总一页周报

**选型：按库方决策矩阵应属 Workflow，但该库无语义匹配的 workflow —— 如实说明并降级为 Tool 组合。**
理由：该任务是多领域交叉（日志、错误、成本、报告四个领域 + 汇总编排），命中决策矩阵的 "Multi-domain, cross-cutting concerns / Multiple specialists required"（应选 Workflows 侧）；但逐一核对 15 个 workflow（`feature-development`、`full-review`、`smart-fix`、`tdd-cycle`、`git-workflow`、`improve-agent`、`legacy-modernize`、`multi-platform`、`workflow-automate`、`full-stack-feature`、`security-hardening`、`data-driven-feature`、`ml-pipeline`、`performance-optimization`、`incident-response`，经 API 实测）——最接近的 `incident-response` 是生产事故响应（L104 "Production issue resolution"）、`full-review` 是代码审查、`workflow-automate` 是 CI/CD 流水线，均非"周期性运营数据审计与周报"。**库中不存在语义匹配的单一命令**，故采用最接近的 Tool 链组合（README 自身的「Sequential Execution Pattern / Parallel Execution」链式策略正为此类组合而设）。

**推荐组合（命令均属 `tools/` 目录，均实测存在）：**

| 步骤 | 命令 | 覆盖子任务 | README 原文职能 |
|---|---|---|---|
| 1 | `/tools:error-trace 上周访问日志与错误日志审计，关联异常请求` | 访问日志 + 错误日志 | "Production debugging \| Log correlation, distributed tracing, error reproduction"（L179） |
| 2 | `/tools:error-analysis 上周错误日志，输出根因/频率/影响面` | 错误日志深析 | "Error patterns \| Root cause analysis, frequency analysis, impact assessment"（L178） |
| 3 | `/tools:cost-optimize 上周云成本账单分析` | 成本账单 | "Resource optimization \| Cloud spend analysis, right-sizing, reserved capacity"（L202） |
| 4（可选） | `/tools:data-validation 对日志与账单数据交叉核对，标记异常` | 交叉核对异常 | "Data quality \| Schema validation, anomaly detection, constraint checking"（L141）——库中唯一含"异常检测"的命令，属借力用法，需在参数中说明数据源 |
| 5 | `/tools:standup-notes 汇总以上结果为一页周报` | 一页周报 | "Status reporting \| Progress tracking, blocker identification, next steps"（L196）——库中最接近"报告产出"的命令 |

**组合方式**：步骤 1–3 相互独立，可按 README §8「Parallel Execution」并行；步骤 4、5 依序消费前序输出（「Iterative Refinement: Use tool outputs as inputs for subsequent commands」）。
**补充**：这是固定周一例行任务，长期方案是按该库 Development Guidelines 自建一个 workflow（如 `ops-weekly-review`）固化上述编排；亦可用 `context-save`/`context-restore` 保留周报模板与上周基线。

---

## 场景② 优化 `src/utils/date.ts` 中 `formatDate` 函数的性能

**选型：Tool。**
理由：单文件单函数、目标与路径明确，命中决策矩阵 Tools 侧全部判据——"Single domain, focused scope / Specific components / Clear implementation path"；且库方的性能 Workflow `performance-optimization` 定位是系统级优化（L103 "System-wide optimization | Profiling, caching, query optimization, load testing"），对单个函数明显过重。

**推荐命令：`/tools:multi-agent-optimize`（`tools/` 目录，实测存在）**
- README 职能：`multi-agent-optimize` | "Coordinated performance optimization | Database, application, and frontend tuning"（L124）——库中唯一以**性能优化为核心职能**的 Tool，本场景取其 application 层。
- 调用示例：`/tools:multi-agent-optimize 仅限 src/utils/date.ts 的 formatDate 函数，做应用层性能优化（算法/字符串拼接/重复计算），勿动其他模块`

**备选与组合：**
- 若该项目有测试套件，**更优**选择是 `/tools:tdd-refactor`（`tools/`）：职能 "Optimization while maintaining green tests"（L163），README 亦有原文先例 `/tools:tdd-refactor optimize validation performance`（L257）；需要完整护栏时按库方 TDD 套件顺序 `tdd-red → tdd-green → tdd-refactor` 执行（README §10 特色实现）。
- `/tools:refactor-clean`（`tools/`，L133）偏结构清理与死代码移除，与"性能"相邻但非对症，不作首选。
- `/workflows:performance-optimization` 保留给全栈/系统级性能问题，本场景不用。

---

## 场景③ 对当前项目做依赖与配置的安全漏洞扫描

**选型：Tool。**
理由：扫描目标（依赖、配置）与产出（漏洞报告）明确、单领域聚焦，属决策矩阵 Tools 侧（"Audit security vulnerabilities → /tools:security-scan" 是 README 官方 Tool 选型示例，L310）；无需多代理编排的探索性分析。

**推荐命令：单命令首选 `/tools:security-scan`（`tools/` 目录，实测存在）**
- README 职能：`security-scan` | "Vulnerability assessment | OWASP, CVE scanning, **dependency audits**"（L171）；特色实现节进一步明确其覆盖 "SAST/DAST analysis, **dependency scanning, secret detection**"（L425）——依赖审计与密钥检测（配置安全的主体）一并覆盖。
- 调用示例：`/tools:security-scan 对当前项目做依赖漏洞与配置安全扫描（OWASP/CVE/依赖审计/密钥泄露）`（用法先例：L238 `/tools:security-scan OWASP Top 10 vulnerability scan`）

**精确组合（当"依赖"与"配置"两域都要专门覆盖时）：**
- `/tools:deps-audit`（`tools/`）——依赖域："Security vulnerabilities, license compliance, version conflicts"（L187；用法先例 L276 `/tools:deps-audit check dependency vulnerabilities`）
- `/tools:config-validate`（`tools/`）——配置域："Schema validation, environment variables, secrets handling"（L186）
- 两命令相互独立，可按 README §8 并行执行；`security-scan` 适合先跑一遍拿总体漏洞面，再由这两个工具分域补细节。

---

## 核查记录（本会话实际执行）

1. **存在性验证**：`WebFetch https://api.github.com/repos/wshobson/commands/contents/tools` 与 `.../contents/workflows`（2026-09-29，本会话）。结果：`tools/` 42 个 `.md`，含 `security-scan.md`、`deps-audit.md`、`config-validate.md`、`error-trace.md`、`error-analysis.md`、`cost-optimize.md`、`data-validation.md`、`standup-notes.md`、`multi-agent-optimize.md`、`tdd-refactor.md`、`refactor-clean.md`；`workflows/` 15 个 `.md`。本文推荐的全部命令均在这两份实测清单中，**无虚构命令名**。
2. **描述依据**：各命令职能引文取自 `_raw_README.md` 对应行（上文 L 号），经 `grep -n` 于本会话提取核对。
3. **未做的事**：未在本地实际安装/执行这些 slash 命令（本机为 Claude Code 命令库资产文档，无 Claude Code 运行环境），本文选型基于库方文档与目录实测，非运行时实测。

## 说明与任务的冲突注记

ASSET-DOC 与任务**无实质冲突**，任务要求全部照办。一处如实记录的清单差异：ASSET-DOC §5.1 与 raw README 的 workflow 表格仅点名 14 个 workflow，而 GitHub Contents API 实测 `workflows/` 目录为 15 个文件（表格遗漏 `ml-pipeline.md`）；ASSET-DOC 头部宣称的"workflows/ 15 个文件"与目录实测一致。该差异不影响本文任何选型结论（本文未推荐任何 workflow 命令）。

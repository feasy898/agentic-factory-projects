# wshobson/commands 库编排方案：Python 单体仓库发布前三路并行体检（arm-b）

> 场景（照录）：『对一个 Python 单体仓库做发布前体检：代码质量审查、安全漏洞扫描、性能热点分析三路并行，全部完成后汇总为一份带优先级整改清单的报告。』
>
> 本文四个部分：① 命令选型与编排方案；② 执行序列图；③ 最终报告固定结构；④ 库覆盖不到的环节与补位方案。

---

## 0. 考证基础（本方案的证据来源）

- 库：`wshobson/commands`（MIT）。本机受限目录（`skillfactory/v2/evalbench/`、`skillfactory/v2/agentkit/`）内的任何文件均未读取；库源通过公开上游获取：`git clone --depth 1 https://github.com/wshobson/commands.git`，落位于工作区临时目录（commit `27d3e77b1a844223721f6c983ddf261ac4441b89`，最后提交 2025-10-11）。本机资产目录 `skillfactory/v2/CATALOG.md:80` 对该库的登记口径（57 命令 = 15 Workflows + 42 Tools，2025-10 起停更）与实测一致。
- 命令全量核实：`ls workflows | wc -l` = **15**，`ls tools | wc -l` = **42**，合计 **57**，与 `README.md:7`（"**57 production-ready slash commands** (15 workflows, 42 tools)"）一致。
- 调用约定（`README.md:43-56`）：按目录前缀调用——工作流 `/workflows:<name>`，工具 `/tools:<name>`；若把文件拷到根目录可免前缀直调 `/tech-debt` 等（`README.md:58-69`）。以下全部使用带前缀的真实命令名。
- 库内并行依据：`README.md:328`（Command Chaining Strategies 第 4 条）"**Parallel Execution**: Run independent tools simultaneously when possible"；库自身的并行原语是命令内部经 Claude Code Task tool 派子代理（`workflows/full-review.md:17`："Execute parallel reviews using Task tool with specialized agents"）。

### 0.1 全量命令清单（实测文件名，防幻觉对照用）

- **workflows/（15）**：`data-driven-feature`、`feature-development`、`full-review`、`full-stack-feature`、`git-workflow`、`improve-agent`、`incident-response`、`legacy-modernize`、`ml-pipeline`、`multi-platform`、`performance-optimization`、`security-hardening`、`smart-fix`、`tdd-cycle`、`workflow-automate`
- **tools/（42）**：`accessibility-audit`、`ai-assistant`、`ai-review`、`api-mock`、`api-scaffold`、`code-explain`、`code-migrate`、`compliance-check`、`config-validate`、`context-restore`、`context-save`、`cost-optimize`、`data-pipeline`、`data-validation`、`db-migrate`、`debug-trace`、`deploy-checklist`、`deps-audit`、`deps-upgrade`、`doc-generate`、`docker-optimize`、`error-analysis`、`error-trace`、`issue`、`k8s-manifest`、`langchain-agent`、`monitor-setup`、`multi-agent-optimize`、`multi-agent-review`、`onboard`、`pr-enhance`、`prompt-optimize`、`refactor-clean`、`security-scan`、`slo-implement`、`smart-debug`、`standup-notes`、`tdd-green`、`tdd-red`、`tdd-refactor`、`tech-debt`、`test-harness`

---

## 1. 编排方案

### 1.1 命令选型总表（三路 + 辅助）

| 环节 | 选定命令（真实名） | 类型 | 选型理由（引证） | 落选者及原因 |
|---|---|---|---|---|
| **路A 代码质量审查** | `/tools:tech-debt` | Tool（单点） | 唯一以"质量债量化"为主业的命令：盘点代码债（圈复杂度>10、长方法、God class、重复代码、循环依赖，`tools/tech-debt.md:28-49`）、四级风险评估（Critical/High/Medium/Low，`tools/tech-debt.md:117-120`）、按 ROI 排序的整改路线（Quick Wins→长期，`tools/tech-debt.md:165-224`）、输出含团队角色分工（tech_lead/senior_dev/dev，`tools/tech-debt.md:261-264`）。只读分析型，不改代码，正合"体检" | `multi-agent-review`：其三路子评审内含 Security Review（`tools/multi-agent-review.md:22-31`），与路B 重复计数；`refactor-clean`：输出是"重构后代码+测试"（`tools/refactor-clean.md:263-270`），体检阶段不改码，留到整改阶段 |
| **路B 安全漏洞扫描** | `/tools:security-scan`（主）＋ `/tools:deps-audit`（同路并行补充） | Tool ×2 | `security-scan` 对 Python 栈原生支持：自动选 bandit/semgrep（SAST）+ safety/pip-audit（依赖 CVE）+ trufflehog/gitleaks（密钥泄露）+ OWASP Top 10 评估（`tools/security-scan.md:23-51` 工具矩阵、`:996-1247` OWASP 与密钥检测），并自带报告生成器（Executive/Detailed/JSON/SARIF 四格式，`tools/security-scan.md:2270-2408`）。`deps-audit` 补齐 license 合规与供应链（typosquatting）视角，输出 8 节报告（`tools/deps-audit.md:765-775`） | `compliance-check`：面向 GDPR/HIPAA/SOC2/PCI-DSS 法规面，非本场景必需（可按需追加）；workflows `security-hardening`：Phase 2 起是"安全整改实施"（`workflows/security-hardening.md:21-36`），属于报告之后的动作 |
| **路C 性能热点分析** | `/tools:multi-agent-optimize` | Tool（单点） | 三子代理（database-optimizer / performance-engineer / frontend-developer）并行剖析：性能工程子代理明确定位 "Profile application code, identify CPU and memory bottlenecks"（`tools/multi-agent-optimize.md:27-39`），数据库子代理管慢查询/索引（`:12-24`）；产出 Consolidated Optimization Plan：性能基线 + Quick Wins(<1天)/Medium(1-3天)/Major(3+天) + 按 impact/effort 排序（`:56-88`）——正是"热点分析+优先级建议"的形态 | `performance-optimization`（workflow）：10 子代理 5 阶段，Phase 1 才是分析（`workflows/performance-optimization.md:9-19`），Phase 2 起为实施型（改代码/部署），体检阶段过重；如需深度 profiling 可取用但须限定"仅 Phase 1"。纯后端单体仓可将 frontend 子代理经 `$ARGUMENTS` 裁剪出范围 |
| **汇总** | **由主会话完成**（库内无合并命令）＋ `/tools:context-save`（存档） | — | 见 1.3：最接近的 `/workflows:full-review` 会重复派出自己的评审子代理，不适合作聚合器；`/tools:context-save` 把三路原件与汇总决策持久化到 `.claude/context/`（时间戳版本化，`tools/context-save.md:53-59`），供后续整改会话用 `/tools:context-restore` 恢复 | `issue`：实为"分析并修复某个 GitHub issue"的流程命令（`tools/issue.md:5`："Please analyze and fix the GitHub issue"），不是"由发现清单批量建 issue"，不能当汇总器用 |

> 注：库内所有命令均为 Markdown 提示词文件（`README.md:341-348`：文件名即命令名，`$ARGUMENTS` 接参数），执行体是宿主（Claude Code）+ 其子代理机制，命令内引用的 `subagent_type="code-reviewer"` 等角色的依赖关系见 §4.2。

### 1.2 并行与顺序

- **并行段**：路A、路B、路C 三条命令**同时启动、互不依赖**——三者都只读同一仓库、各自写独立报告文件（如 bandit/safety 的 `-o xxx-report.json` 输出路径互不相干，`tools/security-scan.md:29,41,47`），无写冲突。这正落在库支持的用法上（`README.md:328` "Run independent tools simultaneously"）。
  落地方式三选一（按宿主条件）：
  1. **主会话单消息并发 3 个 Task 子代理**，分别载入三条命令正文 + 各自的 `$ARGUMENTS`（最贴近库设计：`full-review.md:17` 的库内先例就是"一条指令并发多个 Task"）；
  2. 三个终端/会话同时各发一条命令；
  3. 同一会话顺序发出但明示并行意图（退化为串行，最慢，不推荐）。
  路B 内部 `security-scan` 与 `deps-audit` 也是一对无依赖命令，可同批并行（第 4 个并发位）。
- **汇合点**：三路（+deps-audit）全部返回后进入汇总。
- **顺序总规则**：准备（串行）→ 三路并行 → 汇合汇总（串行）→ （可选）整改与复检（串行）。库内耗时参考：Tools 单条 5–30s、Workflows 30–90s（`README.md:332-334`）；大仓以实际扫描器耗时为准。

### 1.3 汇总环节的归属（问题 1 的明确回答）

**汇总由主会话完成，库内没有可用的"多报告合并 + P0/P1/P2 分级"命令。** 论证：

1. `/workflows:full-review` 是库里最像"三路并行+汇总"的命令（并行 Code Quality / Security / Architecture / Performance / Test Coverage 五路子评审，`workflows/full-review.md:19-42`；汇总为 Critical / Recommendations / Suggestions / Positive，`:55-60`）。但若已并行跑完三路专用命令，再用它会**把五路评审重跑一遍**（token 与时间双倍）；且它固定五路（多出架构/测试两路）、不覆盖 deps-audit 的 license/供应链面、分级是 Critical/Recommendations/Suggestions 而非 P0/P1/P2、无 Owner 规则。
   → 它的正确位置是 **Plan B（低配一站式替代）**：只想要快速粗检、不要求三路可控时，单跑 `/workflows:full-review <repo> --tdd-review`（可选 TDD 合规路，`:44-53,73-78`）即可，取舍是控制粒度换省事。
2. 主会话汇总时**不空手合并**，而是复用三命令自带的输出骨架作为归一化输入：
   - `security-scan` 的整改分桶 immediate_actions(CRITICAL/HIGH) / short_term(MEDIUM) / long_term(LOW)（`tools/security-scan.md:769-771`）与 Executive 模板的 Immediate Actions 字段（含 `Owner`、Timeline、Impact，`:2325-2331`）；
   - `tech-debt` 的 Critical/High/Medium/Low 风险级（`:117-120`）与 Quick/Medium/Long ROI 分桶（`:165-224`）；
   - `multi-agent-optimize` 的基线指标 + Quick/Medium/Major 分桶 + impact/effort 排序（`:56-88`）。
   映射到 P0/P1/P2 的规则见 §3.4。
3. 汇总完成后立即 `/tools:context-save`（内容含"known issues、agent coordination history、technical debt to address"，`tools/context-save.md:24-49`），把三路原件 + 汇总决策存档；整改阶段另一会话用 `/tools:context-restore` 接续。

---

## 2. 执行序列图

```
[阶段0] 准备 —— 主会话（串行）
  安装命令库到 ~/.claude/commands/{tools,workflows}     (README.md:23-29, 352-363)
  固化范围参数 $ARGUMENTS = "release pre-check of Python monorepo @ <repo>;
                             analysis only, no code changes; target release <ver>"
        │
        ├──────────── ⫽⫽ 并行段 PARALLEL（4 个并发位同时启动）⫽⫽ ────────────
        │            （依据 README.md:328 "Run independent tools simultaneously"）
        ▼                          ▼                             ▼
  /tools:tech-debt           /tools:security-scan          /tools:multi-agent-optimize
  ── 路A 代码质量审查 ──      ── 路B 安全漏洞扫描 ──         ── 路C 性能热点分析 ──
  复杂度/重复/结构/测试/      SAST: bandit/semgrep          Task→database-optimizer
  文档债盘点                 依赖: safety/pip-audit        Task→performance-engineer
  risk: Critical/High/       secrets: trufflehog/               （frontend 子代理
  Medium/Low                 gitleaks                            经 $ARGUMENTS 裁剪）
  ROI 排序整改路线            OWASP Top 10 核查             慢查询/CPU/内存热点
        │                    → security-report.json            基线 + Quick(<1d)/
        │                      + SARIF + Executive             Medium/Major 分桶
        │                        (Owner 字段)                       │
        │                          ▲                                │
        │           （同批并行） /tools:deps-audit                   │
        │             依赖发现/license/供应链/        │              │
        │             Output 8 节 → deps-report      │              │
        ▼                          ▼                 ▼              ▼
        └─────────────────✕ 汇合点 JOIN（三路+依赖审计全部返回）─────────────────
                                   │
[阶段1] 汇总 —— 主会话（串行；库内无合并命令，full-review 不作聚合器，见 §1.3）
  ① 严重度归一化：三套分级 → P0/P1/P2 映射（§3.4）
  ② 跨路去重：同 file:line 多源命中合并，保留最高级并标注全部来源
  ③ 生成《发布前体检报告》（固定结构 §3；每项带负责人角色）
  ④ GO/NO-GO 门禁判定：P0 归零 → GO（规则 §3.5）
  ⑤ /tools:context-save → .claude/context/ 存档（三路原件+汇总决策）
                                   │
[阶段2] 整改与放行 —— （报告之后，可选，串行）
  /workflows:security-hardening   ← P0/P1 安全项的实施工作流（Phase2 起为整改动作）
  /tools:refactor-clean           ← P0/P1 质量项的重构实施（自带严重级定义 :254-261）
  /tools:deps-upgrade             ← 依赖升级（breaking change 检测+回滚）
  /tools:test-harness             ← 补性能/回归测试护栏（README.md:160 含 performance）
  /tools:deploy-checklist         ← 发布检查单
  复检：重跑路B（security-scan 确认 P0 归零）→ Release Manager 放行
```

Plan B（一站式低配替代，单命令）：

```
主会话 → /workflows:full-review <repo> [--tdd-review]
         （内部并行 5 路子评审 :19-42 → 自带汇总 :55-60）
         取舍：省事、一次到位；但路线固定、无 deps-audit/license 面、
         分级非 P0/P1/P2、无 Owner 规则 → 仍需主会话后处理映射
```

---

## 3. 最终报告固定结构

报告名：《`<repo>` 发布前体检报告》（版本化：`report-v<date>-<commit7>.md`）。

```markdown
# <repo> 发布前体检报告
## 0. 元信息
  - 仓库与 commit、体检时间、触发原因（release <ver>）
  - 使用命令与口径：/tools:tech-debt、/tools:security-scan、/tools:deps-audit、/tools:multi-agent-optimize
  - 实际执行的扫描器清单（bandit/semgrep/safety/pip-audit/trufflehog|gitleaks/…）与版本
  - 范围与排除（monorepo 内被排除的子目录及理由）
## 1. 执行摘要（给管理层，≤1 屏）
  - 总体风险等级（Critical/High/Medium/Low）＋ 三路各一句话结论
  - P0/P1/P2 条目计数表；**GO / NO-GO（条件 GO）结论**
## 2. 三路各自结论（分路详述，保留各命令原始分级）
  - 2.1 路A 质量（tech-debt）：债清单按 5 类（代码/架构/测试/文档/基础设施）计数；
        关键指标（圈复杂度 TopN、重复率、覆盖率、依赖健康），risk 分布，
        Quick Wins 摘录（含工时与 ROI，tech-debt.md:165-186 骨架）
  - 2.2 路B 安全（security-scan + deps-audit）：漏洞计数按严重度（CRITICAL/HIGH/MEDIUM/LOW）；
        OWASP Top 10 覆盖矩阵（A01–A10 逐项 有发现/无发现）；密钥泄露专项；
        依赖 CVE（immediate/short/long 分桶，security-scan.md:759-771）；
        license 合规与供应链风险（deps-audit.md:765-775 第 3/5 节）
  - 2.3 路C 性能（multi-agent-optimize）：热点 TopN（CPU/内存/慢查询，含 file:line）；
        性能基线指标；Quick(<1d)/Medium(1-3d)/Major(3d+) 分桶；
        预期收益（查询耗时↓X%、API 响应↓X%，multi-agent-optimize.md:79-83 骨架）
## 3. 优先级整改清单（核心交付物）
  - 3.1 P0（发布阻断）表 ｜ 3.2 P1（发布前应修，可条件放行）表 ｜ 3.3 P2（入下迭代）表
        每表列固定为：
        ID(如 SEC-01/QUA-02/PERF-03/DEP-01) | 源路 | 标题 | 位置(file:line) |
        原始级别(CRITICAL/HIGH/…) | P级判定依据 | 修复动作建议 | 预估工作量 |
        验收标准（可执行：复扫零命中/基准达标/覆盖率≥x%）| 负责人角色 | 建议时限
  - 3.4 P 级映射与升降级规则（见下）
  - 3.5 门禁规则：存在任一 P0 → NO-GO；P0=0 且 P1 均有 owner 与时限 → GO（P1 可条件放行）
## 4. 负责人角色矩阵
  | 角色 | 负责的整改类别 | 依据 |
  | Security Lead（安全负责人） | 全部 P0/P1 安全项；密钥泄露应急（轮换凭据） | security-scan Executive 模板自带 Owner 字段（security-scan.md:2330） |
  | Backend Tech Lead | 架构债、God class 拆分决策 | tech-debt Team Allocation 的 tech_lead（tech-debt.md:262） |
  | Senior Developer | 复杂重构、重复逻辑合并 | tech_lead/senior_dev/dev 分工（tech-debt.md:261-264） |
  | Developer / QA | 测试补齐、文档债 | 同上 dev 角色行 |
  | Performance Engineer | CPU/内存热点整改 | multi-agent-optimize 的 performance-engineer 子代理（multi-agent-optimize.md:27） |
  | DBA / 数据库优化 | 慢查询、索引、连接池 | multi-agent-optimize 的 database-optimizer 子代理（multi-agent-optimize.md:12） |
  | DevOps / 供应链负责人 | 依赖升级、license、CI 门禁接入 | deps-audit 的 CI 集成与 Monitoring 节（deps-audit.md:700-763） |
  | Release Manager | GO/NO-GO 终审、条件放行条款 | 本报告 §3.5（主会话定义） |
## 5. 交叉发现与去重记录
  - 同一位置被多路命中（如 secrets 泄露同时进 tech-debt Critical 与 security-scan CRITICAL）
    → 合并为单条目，保留最高 P 级，注明全部来源（防重复计数、防漏改）
## 6. 附录
  - 三路原始报告路径（quality/security/deps/perf 四份原始输出）
  - SARIF/JSON 机读件（security-scan.md:2396-2407 的 json/sarif 两种格式）
  - context 存档路径（.claude/context/<timestamp>，context-save.md:53-59）
  - 复扫指引（整改后重跑哪些命令、以哪个基线比对）
```

### 3.4 P 级映射与升降级规则（汇总环节由主会话执行）

| 来源分级（各命令原生） | 默认映射 | 升降级规则 |
|---|---|---|
| security-scan：immediate_actions（CRITICAL/HIGH） | **P0** | HIGH 但需内网/高权限才可触达 → 降 P1（须记录理由） |
| security-scan：short_term（MEDIUM） | P1 | 涉认证/会话/注入面 → 升 P0 |
| security-scan：long_term（LOW）；deps-audit 的 license 建议 | P2 | 上线涉商用分发且 license 不兼容 → 升 P1 |
| tech-debt：Critical | P0 | —（原文定义：安全漏洞、数据丢失风险，tech-debt.md:117） |
| tech-debt：High | P1 | 位于本发布周期活跃变更路径 → 升 P0 |
| tech-debt：Medium / Low | P2 | — |
| multi-agent-optimize：基线已破 SLO/用户可感劣化 | **P0** | 仅内部管理界面受影响 → 降 P1 |
| multi-agent-optimize：Quick Wins（高收益低成本） | P1 | 修动核心交易路径且来不及回归 → 降 P2 顺延 |
| multi-agent-optimize：Medium/Major | P2 | — |

> 升级总则（覆盖默认映射）：任一条目满足"可被外部利用 / 数据损坏丢失风险 / 阻塞核心功能"之一 → 一律 P0（该总则的语汇直接取自库内两处原文：tech-debt.md:117 "Security vulnerabilities, data loss risk" 与 refactor-clean.md:258 "Security vulnerabilities, data corruption risks, memory leaks"）。

---

## 4. 该库不能直接覆盖的环节与补位方案（如实）

| # | 缺口（库内实证） | 补位方案 |
|---|---|---|
| 4.1 | **无"多报告合并 + P0/P1/P2 分级"命令**。最接近的 `full-review` 会重跑自己的五路评审（`workflows/full-review.md:19-42`），不能当已跑三路的聚合器；`issue` 是"修复单个 GitHub issue"的流程命令（`tools/issue.md:5`），不是发现清单→issue 的生成器 | **主会话承担汇总**（本方案 §1.3、§3 的映射表与门禁规则即补位设计）。若需落成可跟踪 issue：主会话直接 `gh issue create` 批量建卡（deps-audit 的 CI 模板里本就有 `issues.create` 先例，`tools/deps-audit.md:746-762`，可借其 label 方案 `security/dependencies/critical`） |
| 4.2 | **命令引用的子代理角色不在本库内定义**：各命令的 Task 调用指定 `subagent_type="code-reviewer"/"security-auditor"/"performance-engineer"/"database-optimizer"` 等（如 `full-review.md:20,25,35`、`multi-agent-optimize.md:12,27`），但本仓只有 Markdown 命令、无 agents 定义；README 自己也提示更现代的做法是配套 `wshobson/agents` 插件市场（`README.md:19,35-39`） | 三选一：① 安装 `wshobson/agents`（提供上述子代理定义，README 明示该关系）；② 把命令内的 `subagent_type` 映射到宿主现有子代理（如 Claude Code 内置 general-purpose），保留命令原文 Prompt 不变；③ 单会话直接执行命令 Markdown 正文（提示词本身自足，子代理仅为组织方式） |
| 4.3 | **性能路缺"可执行 profiler 命令清单"**：security-scan 给了 bandit/pip-audit 等现成命令行（`tools/security-scan.md:29-47`），但 multi-agent-optimize 是方法论骨架，未给 py 侧 profiler 的具体命令 | 主会话在路C 启动前先实测采样：`py-spy record`/`cProfile`/`pytest-benchmark` 产出的火焰图与耗时数据，作为 `$ARGUMENTS` 上下文注入命令（对齐 README 对"提供详细上下文"的要求，`README.md:316-321`）；整改后用 `/tools:test-harness` 生成 performance 回归测试固化基线（README.md:160：Unit, integration, e2e, **performance**） |
| 4.4 | **无 GO/NO-GO 发布门禁语义**：`deploy-checklist` 是部署项检查单（`tools/deploy-checklist.md:5` "Deployment Checklist and Configuration"），不消费三路结果、不产出放行判定 | 主会话按 §3.5 规则判定（P0 归零 → GO），判定依据写进报告 §1；`deploy-checklist` 仍可用于放行后的部署项核对 |
| 4.5 | **无失败重试/断点续跑的编排器**：三路并行若有一路失败，库内没有 supervisor 类命令；跨会话状态仅有 `context-save`/`context-restore` 一对（`.claude/context/`，时间戳版本化，`tools/context-save.md:53-59`） | 主会话负责：失败路单独重跑（命令幂等、报告文件互不覆盖，重跑无副作用）；长跨度体检用 context-save/restore 接续（README.md:335 亦明示该用法："Use saved context for multi-session projects"） |
| 4.6 | **宿主绑定**：本库是 Claude Code slash 命令形态（`README.md:3`），并行落地依赖宿主 Task tool；换其他宿主需转换提示词形态 | 本场景默认 Claude Code 宿主（§1.2 的三种落地方式任选）；其他宿主将三条命令 Markdown 作为普通系统提示词注入各自的并行子代理机制即可，方案不变 |
| 4.7 | （条件性缺口）**ML/AI 代码面**：若该 Python 单体仓库含模型/LLM 调用代码，三路常规命令不覆盖 prompt 注入、数据泄露、模型版本管理等问题 | 追加第 4 路并行 `/tools:ai-review`（专用于 AI/ML 代码审查，含 prompt injection 防护、数据泄漏检测、LLM 专项检查，`tools/ai-review.md:5-67`），产出并入同一 P0-P2 清单，源路标 `AIR` |

---

## 附：本方案引用清单（全部实测读过）

| 文件 | 用途 |
|---|---|
| `README.md` | 命令总数/调用前缀/并行策略/耗时/插件市场关系 |
| `workflows/full-review.md` | 库内并行编排先例、Plan B、汇总结构对照 |
| `workflows/performance-optimization.md` | 路C 落选对照（Phase1 分析 / Phase2+ 实施） |
| `workflows/security-hardening.md` | 整改阶段命令（Phase2 起为实施动作） |
| `tools/security-scan.md` | 路B 主命令：工具矩阵/OWASP/整改分桶/报告模板（Owner 字段） |
| `tools/deps-audit.md` | 路B 补充：license/供应链/Output 8 节/CI 建 issue 先例 |
| `tools/tech-debt.md` | 路A 主命令：债盘点/风险分级/角色分工/ROI 路线 |
| `tools/multi-agent-optimize.md` | 路C 主命令：三子代理/热点剖析/基线+分桶+排序 |
| `tools/multi-agent-review.md` | 路A 落选对照（Security 子评审重叠） |
| `tools/refactor-clean.md` | 整改阶段命令；严重级定义交叉引证 |
| `tools/context-save.md`（`context-restore.md` 同对） | 汇总存档与跨会话接续 |
| `tools/ai-review.md`、`tools/issue.md`、`tools/deploy-checklist.md` | 排除/补位论证（ML 面、issue 语义、门禁缺口） |

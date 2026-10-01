# 用 wshobson/commands 编排「Python 单体仓库发布前三路并行体检」— 完整方案

> 场景（任务原文照录）：『对一个 Python 单体仓库做发布前体检：代码质量审查、安全漏洞扫描、性能热点分析三路并行，全部完成后汇总为一份带优先级整改清单的报告。』
> 本文件是交付物本身：命令选用与编排方案、执行序列图、报告固定结构、库能力缺口与补位方案。

---

## 0. 验证记录（本方案的每条命令名均经实测核实，非凭 README 转述）

本方案引用的所有命令名，均在本次会话中用以下手段逐一核实：

1. **本地读取**了 `ASSET-DOC.md`（整理稿）与 `_raw_README.md`（README 原文存档，483 行）。
2. **实测命令清单**（2026-09-29，curl GitHub Contents API，未认证公开接口）：

   ```
   curl -s "https://api.github.com/repos/wshobson/commands/contents/workflows"
   curl -s "https://api.github.com/repos/wshobson/commands/contents/tools"
   ```

   实测输出：`workflows/` 下 **15 个** `.md` 文件，`tools/` 下 **42 个** `.md` 文件，与 README 宣称的 57（15+42）一致。本方案选用的 7 个命令名全部出现在实测文件清单中：`full-review.md`、`performance-optimization.md`（workflows）；`security-scan.md`、`deps-audit.md`、`tech-debt.md`、`issue.md`、`context-save.md`（tools）。
3. **拉取了关键命令文件原文**（`curl https://raw.githubusercontent.com/wshobson/commands/main/<路径>`），确认每个命令的实际行为（见 §1 各条「原文证据」）。关键发现：
   - `workflows/full-review.md` 正文明确用 **5 个并行 Task 子代理**（code-reviewer / security-auditor / architect-reviewer / performance-engineer / test-automator）后合并为 Critical / Recommendations / Suggestions / Positive 四级报告；
   - `tools/security-scan.md` 内置 **Python 专用扫描命令**：SAST 用 `bandit -r . -f json -o bandit-report.json` 与 `semgrep --config=auto --json`，依赖扫描用 `safety check --json` 与 `pip-audit --format=json`；
   - `workflows/performance-optimization.md` 分 5 个 Phase 共 10 个子代理，**Phase 1 是纯分析**（Application Profiling + Database Performance Analysis），**Phase 2–5 是优化实施（会改代码）**——这决定了 T3 路必须用 `$ARGUMENTS` 显式约束只跑 Phase 1；
   - `tools/tech-debt.md` 给出可量化的债务判定阈值（圈复杂度 >10、嵌套 >3 层、方法 >50 行、上帝类 >500 行 >20 方法）；
   - `tools/deps-audit.md` 的依赖发现代码原生支持 Python 依赖文件（`requirements.txt`、`Pipfile`、`Pipfile.lock`、`pyproject.toml`、`poetry.lock`）。
4. **一处如实记录的文档缺口**：README 宣称 15 个 workflows，但其表格只列出 14 个名字；实测第 15 个文件是 `workflows/ml-pipeline.md`（README 全文未提及）。与本审计编排无关，但按「只写验证过的事实」原则记录在案。

调用语法依据 README：目录前缀 + 冒号，如 `/tools:security-scan perform vulnerability assessment`（`_raw_README.md:52`）；参数即命令后的自由文本，经命令文件内的 `$ARGUMENTS` 占位符注入（`ASSET-DOC.md:76-87`）。

---

## 1) 命令选用与编排方案

### 1.1 选用的命令（7 个，全部实测存在）

| 路线 | 命令 | 角色 | 选用理由（附证据） |
|---|---|---|---|
| T1 代码质量 | `/tools:tech-debt` | **主命令** | 表格定义即「复杂度分析、风险评分、整改规划」（`_raw_README.md:134`）；原文含可执行判定阈值（圈复杂度 >10、嵌套 >3、方法 >50 行、上帝类 >500 行），输出天然带「按风险排序 + 整改计划」，与体检报告的整改清单直接对接 |
| T2 安全 | `/tools:security-scan` | **主命令** | 「漏洞评估：OWASP、CVE 扫描、依赖审计」（`_raw_README.md:171`）；原文内置 Python 扫描器矩阵（bandit/semgrep/safety/pip-audit）及密钥检测（README 特色节明确列出 SAST/DAST、依赖扫描、secret detection，`_raw_README.md:425`；集成 Bandit、Safety、Semgrep、GitGuardian 等，`_raw_README.md:430`） |
| T2 安全 | `/tools:deps-audit` | 补充（与 security-scan 并行） | 专管供应链：依赖漏洞、**许可证合规**、版本冲突（`_raw_README.md:187`）——security-scan 的依赖扫描只覆盖漏洞维度，许可证/版本冲突维度由它补齐；原生识别 Python 依赖文件 |
| T3 性能热点 | `/workflows:performance-optimization` | **主命令（限定 Phase 1）** | 「全栈 profiling：查询优化、缓存、CDN」（`_raw_README.md:446`）；其 Phase 1 恰好是本场景所需：应用剖析（CPU/内存/IO 热点）+ 数据库慢查询/索引分析，且内部两路子代理再并行 |
| 汇总后置 | `/tools:issue` | **可选**：把 P0/P1 整改项逐条转工单 | 「标准化模板、复现步骤、验收标准」（`_raw_README.md:180`）——正对应整改清单每项需要的「复现/证据 + 验收标准」 |
| 全程 | `/tools:context-save` | **可选**：存审计基线与结论 | 「状态持久化：架构决策、配置快照」（`_raw_README.md:204`）；README 性能建议明确「多会话项目用 `context-save`/`context-restore`」（`_raw_README.md:335`） |
| — | 主会话（不占命令名额） | **汇总与定级** | 见 §1.3 与 §5 缺口 1：库内**没有**「合并多份外部报告 → 定级清单」的命令，汇总必须由主会话完成 |

### 1.2 明确不用、但容易被误选的命令（附理由）

| 候选 | 不选理由 |
|---|---|
| `/workflows:full-review` | 最接近场景的单命令方案（内部 5 路并行审查，含质量/安全/性能），**作为备选单命令方案见 §1.4**；但作为主方案不合适：① 它自己再造 5 个子代理，会与三路专项重复扫描；② 视角固定为「质量/安全/架构/性能/测试覆盖」，不含依赖许可证审计，且多出架构/测试两路，与任务要求的三路不对应；③ 其合并结构是 Critical/Recommendations/Suggestions，不是任务要求的 P0/P1/P2 + 负责人角色，改造它不如由主会话直接按 §4 结构汇总 |
| `/tools:multi-agent-review` | 同为「架构+安全+质量」多视角审查（`_raw_README.md:152`），与 full-review 同样的粒度错配问题，深度不如两条专项命令 |
| `/tools:refactor-clean` | 定位是「实施清理」（模式检测、死代码删除、结构优化，`_raw_README.md:133`），发布前体检应只读不动代码；其「发现问题」职能已被 tech-debt 覆盖 |
| `/tools:debug-trace` | 面向运行时故障排查（栈、内存剖析），需要可复现故障的环境；体检场景无既定故障，热点分析由 performance-optimization Phase 1 承担 |

### 1.3 编排方案：哪些并行、什么顺序、谁汇总

**总原则**：分析类命令相互独立且只读 → 并行安全（README 链式策略第 4 条明确背书："Parallel Execution: Run independent tools simultaneously when possible"，`_raw_README.md:328`）；所有涉及「合并、定级、出报告」的环节库内无对应命令 → 由主会话串行完成。

**Phase 0 — 准备（主会话，串行）**
按 README「上下文优化」要求（`_raw_README.md:316-321`：预先给出技术栈版本、约束、输出偏好以减少迭代），主会话先固定审计上下文并生成三路 `$ARGUMENTS`：

- 审计上下文模板：`Python 3.11 单体仓库 <repo-root>，Web 框架 <Django/FastAPI/Flask> <版本>，数据库 <PostgreSQL <版本>>，入口 <wsgi/asgi 模块>，本次为发布前只读体检，禁止修改任何代码`；
- 可选执行 `/tools:context-save` 存审计基线（范围、commit、参数），供多会话续接。

**Phase 1 — 三路并行（库命令，互不依赖，只读）**

四个分析任务全部同时发起（T2 内部两条命令也相互独立，一并并行）：

```bash
# T1 代码质量
/tools:tech-debt 对 <repo-root> 做发布前只读技术债体检：Python 3.11 单体，框架 <…>。
仅分析、不修改代码。输出：①重复代码（位置与行数）；②圈复杂度>10/嵌套>3层/方法>50行/
上帝类>500行的完整清单（文件:行）；③按风险评分排序；④每项附整改建议与预估工作量。

# T2a 安全漏洞扫描
/tools:security-scan 对 <repo-root> 做发布前安全扫描：OWASP Top 10、SAST
（bandit -r . -f json -o bandit-report.json；semgrep --config=auto --json）、
硬编码密钥检测、安全配置检查。Python 3.11，只读。输出按严重度分级，每个发现附
文件:行、触发规则、修复建议，并保存扫描器原始 JSON 输出路径作为证据。

# T2b 依赖审计
/tools:deps-audit 审计 <repo-root> 的依赖（requirements.txt、pyproject.toml、poetry.lock）：
已知 CVE、许可证合规、版本冲突、长期未维护的过期包。只读。输出按风险排序，
每项附 CVE 编号/许可证类型/建议修复版本。

# T3 性能热点
/workflows:performance-optimization 对 <repo-root> 仅执行 Phase 1 性能分析：
①应用剖析（CPU/内存/IO 热点、flame graph、资源利用率）；②数据库分析（慢查询、
执行计划、缺失索引、连接池）。硬性约束：本次是发布前体检，只读分析，
禁止进入 Phase 2–5 的任何优化实施与代码修改。输出热点 Top N（文件:行:函数）
与瓶颈类型分布（计算/IO/DB/锁）。
```

预期时长（README 标称值，未实测）：tools 各 5–30 秒，workflow 30–90 秒（`_raw_README.md:332-333`）——并行段墙钟时间 ≈ 最慢一路（T3，30–90 秒）。

**Phase 2 — 汇合点（barrier）**：三路全部返回才进入汇总。任一路失败则按 README 故障表处理（"Incomplete output → Insufficient context → Provide technology stack and requirements"，`_raw_README.md:398`）——补足上下文后仅重跑失败路，已完成的路线不作废。

**Phase 3 — 汇总（主会话，串行，不用命令）**
1. **交叉去重**，三类键：CVE/包名键（T2a 与 T2b 必然重叠，如 pip-audit 与 deps-audit 命中同一 CVE）、文件键（同一文件被多路命中则合并为一条、保留各路证据）、根因键（如 tech-debt 的高复杂度与 T3 的计算热点指向同一函数时合并并互引）；
2. **定级**：按 §4.4 的 P0/P1/P2 判定矩阵逐条定级；
3. **负责人角色映射**：按 §4.5 的角色表给每项建议 owner；
4. **产出《发布前体检报告》**（固定结构见 §4），写放行建议；
5. **后置落地（可选）**：对 P0/P1 逐条执行 `/tools:issue`（生成带复现步骤与验收标准的整改工单）；`/tools:context-save` 归档本次体检结论供下轮复查对比。

### 1.4 备选方案：单命令版（当无法驱动并行时）

若运行环境只能串行执行一条命令，退化为 `/workflows:full-review <repo-root> 发布前体检，Python 单体` 一条命令：其内部已并行 5 个子代理并自动合并为 Critical/Recommendations/Suggestions/Positive 报告（full-review.md 原文「Consolidated Report Structure」节）。代价：与三路专项相比缺依赖许可证审计、输出分级结构需人工转换为 P0/P1/P2。**仅在受环境限制时使用，不作为主方案。**

---

## 2) 执行序列图（‖ = 并行段，▮ = 汇合点/barrier）

```text
            ┌─────────────────────────────────────────────────┐
            │ Phase 0 准备（主会话，串行）                        │
            │  0.1 固定审计上下文（栈/版本/DB/入口/只读约束）       │
            │  0.2 生成三路 $ARGUMENTS                           │
            │  0.3 /tools:context-save 存审计基线（可选）          │
            └───────────────────────┬─────────────────────────┘
                                    │ 分发
          ┌─────────────────────────┼──────────────────────────────┐
          ‼                        ‼                              ‼
   ┌──────┴───────┐        ┌───────┴────────┐            ┌────────┴─────────┐
   │ T1 代码质量    │ ‼      │ T2 安全         │ ‼          │ T3 性能热点        │ ‼
   │ /tools:      │ 并     │ /tools:security │ 并         │ /workflows:      │ 并
   │ tech-debt    │ 行     │ -scan           │ 行         │ performance-     │ 行
   │ （只读）      │ 段     │ （SAST/密钥）    │ 段         │ optimization     │ 段
   │ 5–30s※       │        │ ─────────────  │            │ （仅 Phase 1，    │
   │              │        │ /tools:         │            │ 只读约束写进      │
   │              │        │ deps-audit      │            │ $ARGUMENTS）     │
   │              │        │ （CVE/许可证）   │            │ 内部 2 子代理并行：│
   │              │        │ 5–30s※         │            │ profiling ‖ DB   │
   │              │        │                │            │ 30–90s※          │
   └──────┬───────┘        └───────┬────────┘            └────────┬─────────┘
          │质量结论+债务清单          │漏洞清单+依赖清单               │热点TopN+瓶颈分布
          └─────────────────────────┼──────────────────────────────┘
                                    ▼
                    ▓▓▓▓▓▓ 汇合点 barrier ▓▓▓▓▓▓
                    三路全部完成才进入（墙钟≈最慢一路 T3）
                    任一路失败：补上下文→只重跑该路
                                    │
            ┌───────────────────────▼─────────────────────────┐
            │ Phase 3 汇总（主会话，串行；库内无对应命令）          │
            │  3.1 交叉去重（CVE键 / 文件键 / 根因键）             │
            │  3.2 P0/P1/P2 定级（§4.4 矩阵）                    │
            │  3.3 负责人角色映射（§4.5 角色表）                   │
            │  3.4 产出《发布前体检报告》（§4 固定结构）            │
            │  3.5 /tools:issue 将 P0/P1 转整改工单（可选）        │
            │      /tools:context-save 归档结论（可选）           │
            └─────────────────────────────────────────────────┘
※ 5–30s / 30–90s 为 README 标称值（_raw_README.md:332-333），非本会话实测。
```

并行段 = Phase 1 的三条竖栏（4 个分析任务同时发起，T2 内部 2 条也并行；T3 内部 profiling 与 DB 分析两个子代理并行）。汇合点 = barrier，只有 T3 是 workflow、最慢，整体墙钟由它决定。

---

## 3) 最终报告固定结构（《发布前体检报告》模板）

> 设计约束：三路结论可追溯（每条带来源命令与证据）、整改清单可执行（每项带验收标准与负责人角色）、结构固定以便多轮发布前体检纵向对比。以下即报告骨架，`<>` 为占位：

```markdown
# 《<项目名> 发布前体检报告》

## 0. 元信息
- 体检日期 / 触发事由（发布 <版本号>）/ 代码基线（commit <sha>，分支 <branch>）
- 审计范围（<repo-root> 内含/排除目录）与只读声明（本次未修改任何代码）
- 使用命令清单：/tools:tech-debt、/tools:security-scan、/tools:deps-audit、
  /workflows:performance-optimization（仅 Phase 1）；汇总：主会话
- 扫描器原始输出存档：<bandit-report.json / semgrep-report.json / pip-audit-report.json …路径>

## 1. 执行摘要（≤10 行）
- 放行建议：☐ 放行 ☐ 有条件放行（条件=） ☐ 阻断（原因=）
- 计数仪表盘：P0 <n> 项｜P1 <n> 项｜P2 <n> 项
- 三路一句话结论（质量 / 安全 / 性能各一句）

## 2. 三路各自结论
### 2.1 代码质量（来源：/tools:tech-debt）
- 健康度总评与风险评分分布；债务总量（重复代码 <n> 处 <m> 行；复杂度超标方法 <n> 个…）
- Top 5 风险文件（文件:行 + 触发阈值，如圈复杂度 17 > 10）
- 本路限制声明（如：未跑运行时剖析，静态结论）
### 2.2 安全（来源：/tools:security-scan + /tools:deps-audit）
- 漏洞计数（按 严重/高/中/低）；密钥泄露 <n> 处；OWASP 覆盖情况
- 依赖：含已知 CVE 的包 <n> 个（附 CVE 号与修复版本）；许可证风险 <n> 项；版本冲突 <n> 项
- 每条发现：文件:行（或 依赖名@版本）、触发规则/CVE、修复建议
### 2.3 性能热点（来源：/workflows:performance-optimization Phase 1）
- 热点 Top N（文件:行:函数 + 剖析数据：耗时占比/内存/调用次数）
- 瓶颈类型分布（计算 / IO / DB 慢查询 / 锁竞争）与对应证据（profile 输出摘要）
- 数据库专项：慢查询清单、缺失索引建议、连接池配置评估
- 本路限制声明（如：剖析基于静态分析/预发环境，未见生产流量）

## 3. 整改清单（核心交付物；按级别排序，级别内按风险×工作量排序）
### 3.1 P0（发布阻断，修复前不得发布）
| ID | 级别 | 来源路 | 问题 | 证据（文件:行 / CVE / profile 数据） | 整改建议 | 负责人角色 | 验收标准 | 预估工作量 |
|----|------|--------|------|--------------------------------------|----------|------------|----------|------------|
| Q-001 | P0 | T2a | <硬编码数据库口令> | config.py:42，GitGuardian/bandit 规则 <…> | 移入密钥管理并轮换该口令 | 后端工程师+安全工程师复审 | 扫描复扫为 0 命中；口令已轮换 | 0.5d |
| … |
### 3.2 P1（发布前应修 / 有条件放行的条件项）
（表同上）
### 3.3 P2（发布后跟进，进入下轮迭代）
（表同上）

## 4. 定级标准（判定矩阵，保证多轮体检间口径一致）
- **P0**：可利用的安全漏洞（有公开 CVE 且攻击面可达）｜硬编码密钥/凭据｜数据损坏或丢失风险｜核心功能性能劣化至不可用（如核心接口超时）
- **P1**：已知 CVE 但利用条件受限（需内网/特定配置）｜核心路径高复杂度热点（圈复杂度>15 且在主链路）｜压测阈值边缘的慢查询｜许可证冲突（若不对外分发可降 P2）
- **P2**：重复代码与结构坏味道｜非关键路径性能问题｜过期但无 CVE 的依赖｜文档/注释缺失

## 5. 交叉发现（同一根因被多路命中的合并项）
- <例：utils/pricing.py:88 同时被 T1（圈复杂度 19）与 T3（CPU 热点 Top1）命中 → 合并为一条 P1，重构兼修两症>

## 6. 放行建议与残余风险
- 结论与条件；带病上线时的监控补偿措施（日志/告警点）

## 附录
- 三路原始输出文件索引；去重记录（合并前 n 条 → 合并后 m 条）
```

**负责人角色表（§3 表格「负责人角色」列的取值域）**：

| 角色 | 承担的整改类型 |
|---|---|
| 后端工程师 | 代码坏味道、复杂度重构、业务逻辑漏洞修复、算法热点优化 |
| 安全工程师 | 漏洞定级复核、密钥轮换方案、安全配置、修复验收 |
| DBA / 数据工程师 | 慢查询改写、索引方案、连接池与迁移 |
| 平台 / DevOps | 依赖升级与 CI 门禁、扫描器接入、监控补偿 |
| QA | 整改项验收测试、回归确认 |
| 技术负责人 | P0/P1 仲裁、放行签字、跨项冲突裁决 |

---

## 4) 该库不能直接覆盖的环节与补位方案（如实说明）

| # | 缺口 | 依据 | 补位方案 |
|---|------|------|----------|
| 1 | **无「多报告汇总→定级清单」命令**。full-review 的合并逻辑只服务于它自己内部 5 个子代理的输出（其 Consolidated Report Structure 节），没有命令接受三份外部产物做交叉去重、P0/P1/P2 定级、负责人映射 | 实测 57 个命令名清单中无 report/merge/summarize 类命令；full-review.md 原文佐证 | **主会话承担汇总**（Phase 3 步骤 3.1–3.4），定级用 §4.4 固定矩阵保证口径一致；`/tools:issue` 只做汇总后的「单条发现→工单」模板化，不是合并器 |
| 2 | **库内无跨命令编排器（fan-out/join）**。命令是彼此独立的 markdown 提示文件，README 只以策略形式建议并行（`_raw_README.md:328`），没有任何命令负责「同时发起三条命令并等待全部完成」 | 命令架构（每命令一个 .md + `$ARGUMENTS`，`ASSET-DOC.md:76-87`）；57 个命令名中无 orchestrator/runner | 并行由**运行平台驱动**：在 Claude Code 中由主会话用 Task/子代理机制各发一条命令；在本次所处的动态工作流环境中由编排脚本并发三个子代理。barrier = 收齐三路返回值，任一失败只重跑该路 |
| 3 | **性能路默认会改代码**。performance-optimization 的 Phase 2–5 是优化实施（后端/API/前端/云/部署），与「发布前只读体检」冲突；该约束只能写进 `$ARGUMENTS`，库本身没有只读开关强制保证 | performance-optimization.md 原文 Phase 2–5 各节均为「Optimize…」并产出「Optimized code」 | 双保险：① `$ARGUMENTS` 写硬性约束「仅 Phase 1、禁止修改代码」（§1.3 T3 调用文）；② 以只读权限模式运行该路子代理，或运行后 diff 复核确认零改动 |
| 4 | **真实性能热点需要可运行环境与代表性负载**。库只能产出剖析/压测的指令与测试代码（`/tools:test-harness` 声称含 performance 测试），不能提供预发环境、流量回放或基线数据 | 库定位是 slash 命令集（提示词），不含环境供给类命令 | 在预发布环境跑 Phase 1 剖析后再进入汇总；环境不可得时，T3 退化为静态热点分析（复杂度×调用链），并在报告 §2.3 的「本路限制声明」中如实标注置信度降级 |
| 5 | **命令是 LLM 提示词而非确定性扫描器**。security-scan 给出 bandit/pip-audit 的确切命令行，但「是否真的执行、结果是否如实引用」取决于运行 agent 的环境与自觉，输出质量有方差 | security-scan.md 原文为指令性提示（「Choose appropriate security scanning tools…」），非硬性执行契约 | 证据强制：`$ARGUMENTS` 中要求每个发现附扫描器原始 JSON 输出路径（§1.3 T2a 调用文），主会话在 Phase 3 抽查证据文件存在性与结论一致性；证据缺失的发现降级为「待复核」 |
| 6 | （附带记录）**README 文档缺口**：宣称 15 个 workflows，表格只列 14 个；实测第 15 个为 `ml-pipeline.md`，README 全文未提及 | GitHub Contents API 实测文件清单 vs `_raw_README.md` 全文核对 | 不影响本编排（未选用该命令）；选型时一律以 API 实测文件清单为准，不依赖 README 表格的完备性 |

---

## 5. 结尾说明

- 本方案中所有命令名均经 GitHub Contents API 与 raw 文件实测核实（§0）；三路主命令的行为描述均引自命令文件原文，非 README 单行简介的转述。
- 标称执行时长（tools 5–30s、workflows 30–90s）转引自 README（`_raw_README.md:332-333`），本次会话**未实际运行**这些命令——本任务是编排设计，且场景中的目标 Python 仓库由使用方在实际运行时提供。
- 本方案严格按任务要求编写；ASSET-DOC 提供的方法论（命令清单、调用语法、链式策略）与任务无冲突，无需偏离。

# EVAL-SPEC v0.2 — skillfactory 资产评测标准（评价协议 v0.1 → v0.2 升级版）

| 项 | 值 |
|---|---|
| 文件 | `skillfactory/v2/standard/EVAL-SPEC-v0.2.md` |
| 版本 | v0.2（2026-09-29） |
| 前版 | v0.1 = `SKILL-SPEC-v0.1.md` §3（评价体系）与 §4 门 2（盲评门）；本文件将其独立成文并升级 |
| 状态 | 生效。生效后评测协议与盲评验收线以本文件为准；`SKILL-SPEC-v0.1.md` §3.3 与 §4 门 2 同时废止，其余门与格式条款继续生效（迁移条款见 §7.2） |
| 适用范围 | skillfactory 全部资产的评测：自产 skill 包（对齐 SKILL-SPEC）+ v2 目录收录的其他形态资产（MCP/插件/agent 配置/prompt/command/工作流模板等） |
| 本版修订动因 | 首夜实测教训（§1 在案）：同一资产三轮独立盲评 Δ 波动 3.67→1.67→4.33（极差 2.66）；3 任务×1 对裁决的样本量撑不起「delta≥1.0 且胜率≥60%」单线判定 |
| 证据纪律 | 本文件每一外部论断标注口径：【实访】= 本轮 web_reader 亲自访问原始仓库；【清单口径】= 转引 `v2/CATALOG.md`（该轮采集口径，本轮未重访）；【盘内】= 本轮实际读取的本地文件。未核实项一律如实声明（附录 C） |

---

## 0. 总则

### 0.1 用语分级（沿用 SKILL-SPEC v0.1 §0.1）

- **【必须】**：无条件要求，不满足即评测无效/验收不通过。
- **【禁止】**：无条件不得出现，出现即评测无效/验收不通过。
- **【应当】**：默认要求；偏离必须在 CHANGELOG 或评测报告记录理由。
- **【可以】**：允许，且仅允许在该条款写明的范围内实施。

### 0.2 与 SKILL-SPEC v0.1 的关系

1. 本文件**取代** `SKILL-SPEC-v0.1.md` §3.3（盲评协议）与 §4 门 2（盲评门）。
2. SKILL-SPEC §3.1（runner.py 确定性评测）、§3.2（golden.json 黄金集 schema）、§4 门 1/3/4/5 **继承有效**；本文件在其上加严与补充，冲突处以本文件为准。
3. 评测证据等级、两级晋级、多形态适配（§5、§6）为本 v0.2 新增条款，适用于全部形态资产。

### 0.3 评测对象与形态

评测对象按 `v2/TAXONOMY.md` §四形态横轴判定（skill / MCP / hook / command / plugin / prompt模板 / 工作流模板 / agent配置 / 评测集 / 软件系统等 14 形态）。每个被测资产**【必须】**在评测报告声明其主形态；多形态能力记入能力字段，评测覆盖**【必须】**至少含主形态（适配方式见 §6）。

---

## 1. 本版修订动因：首夜盲评噪声（证据在案）

### 1.1 三轮盲评波动实测

同一资产（meeting-minutes）、同一黄金任务集（3 条 ab_tasks）、同协议独立盲评三轮，Δ 与逐任务分数全部漂移【盘内】：

| 轮次 | 出处 | baseline→treatment | Δ | 胜率 | 逐任务（基线: treatment） |
|---|---|---|---|---|---|
| 第 1 轮 | `report/archive/交付报告-旧稿-20260929T0721-已废弃.md:7`（版本说明引更早旧稿） | — | **3.67** | — | — |
| 第 2 轮 | 同上归档 `:54`、`:182`（该轮 ab_summary 对账） | 8.00→9.67 | **1.67** | 0.67 | 10:9 负 / 5:10 胜 / 9:10 胜 |
| 第 3 轮 | `assets/meeting-minutes/tests/ab_summary.json:1-29`（现行盘内） | 5.67→10 | **4.33** | 1.00 | 7:10 / 4:10 / 6:10 |

- Δ 极差 = 4.33 − 1.67 = **2.66**，为验收线（1.0）的 2.66 倍；基线逐任务分数在轮间漂移最大 3 分（ab-003：9→6）。ask 下发的首夜教训「波动达 ±1.5 分以上」与盘内数据吻合。
- ppt-method-router 两轮：Δ=0.67/胜率 0.67（逐任务 9:10 胜 / 9:10 胜 / 9:9 平，归档 `:185`）→ Δ=0/胜率 0.33（现行 `assets/ppt-method-router/tests/ab_summary.json` 实读：ab1-clear-single-category 9:8 基线胜 / ab2-ambiguous-fallback 8:9 负 / ab3-mixed-priority 9:9 平）——**任务 ab1 在两轮间由 treatment 胜翻为基线胜**（对齐依据：现行文件载任务 ID，旧轮逐任务行按同序排列且两轮平局均处第 3 位；旧轮逐任务行本身不带任务 ID，此对齐为有序推断而非 ID 直读），仅 3 任务样本下，这一翻即翻转全部统计叙事。
- paper-to-skill 两轮 Δ 均为 −0.5（方向稳定），但胜率 0.5→0（仅 2 任务，1 对翻转即全变）。

### 1.2 样本量的统计学不足

第 2 轮口径为每任务每臂 1 对裁决（`DELIVERY.md` §4.1"本批规模：每任务每臂 1 对裁决（n=1/臂）"）：

1. 3 任务 → 胜率只能取 {0, 0.33, 0.67, 1.0}；「胜率 ≥60%」等价于「≥2/3」，**单对翻转即改变判定**（1.1 实测正是如此）。
2. Δ 由 3 个任务均分构成，单任务裁判分漂移 ±1 即可移动 Δ ±0.33；叠加任务间独立漂移，Δ 的轮间波动实测达 2.66。
3. 结论：v0.1 门 2 的「Δ≥1.0 且胜率≥60%」在 2–3 任务×1 对规模下**判据不稳定**，必须以协议结构（任务数下限 + 同任务重复 + 裁判校验 + 复合线）共同吸收噪声，而非调高/调低阈值。

### 1.3 v0.2 的设计响应（本文件四处核心修订）

| 修订 | 条款 | 对应噪声源 |
|---|---|---|
| 任务数下限 5–8 | §3.1 | 任务数过少 → 统计粒度粗 |
| 同任务多臂重复 + 任务级多数判定 | §3.2/§3.3 | 单次采样的裁判/执行噪声 |
| 裁判一致性校验（复评分差>2 换裁判） | §3.4 | 裁判自身不稳 |
| 复合接受线（+反向任务约束） | §3.6 | 均分被个别极端任务拉动的伪增益 |

---

## 2. 拿来主义：目录内评测资产的逐个评估与本地化

以下逐个评估 `v2/CATALOG.md` 中评测集/评测框架类条目（A6 全部 11 条 + A2.3/A5.3/B3.1 各 1 个带评测机制条目），给出「可采纳 / 怎么本地化 / 不采纳及理由」。

### 2.1 tau2-bench（`CATALOG.md:246`）——本规范最大外部来源【实访】

本轮实际访问（2026-09-29，web_reader）：`raw.githubusercontent.com/sierra-research/tau2-bench/main/README.md`、`.../docs/evaluation.md`、`.../src/tau2/metrics/agent_metrics.py`。核实所见：域 = policy+tools+tasks（+可选 user_tools），5 个域（telecom/airline/retail/banking_knowledge/mock）；任务 schema 含 `evaluation_criteria`（actions/env_assertions/communicate_info/nl_assertions/reward_basis 五字段）；源码含 `pass_hat_k` 函数。

| # | 采纳项 | 原文机制 | 本地化（v0.2 条款） |
|---|---|---|---|
| A1 | **Pass^k 一致性度量** | `agent_metrics.py` 实读：`pass^k = C(success_count, k)/C(num_trials, k)`，代码注释注明出处 arXiv:2406.12045（原版 τ-bench 论文）；按任务算 k=1..n 再平均，衡量「随机抽 k 次全成功」的概率 | 本地化为**任务级多数判定**（§3.3）：任务级胜负由任务内 n 次重复的多数决定（n=2 需 2:0，n=3 需 ≥2/3），单次侥幸胜负不再直接计入胜率；pass^k 原式作为披露指标（n=2 时任务「双次全过率」）记入 benchmark.json |
| A2 | **端态判定而非轨迹判定** | `evaluation.md` 实读：`actions` 是**一条参考轨迹**，重放于全新 gold 环境推导目标终态（DB end state）；「agent is not required to take this specific path」——只要到达等价终态即得分；reward = 各 reward_basis 分量**乘积**（默认 DB×COMMUNICATE） | 本地化为**产物端态判定原则**（§3.8-7）：确定性断言判"产物是否达成目标态"，不锁定实现路径；oracle 参照产物只作参照，**禁止**要求 treatment 与 oracle 逐字节一致（除非任务本身考格式保真——此时保真即端态，须在 rubric 显式声明） |
| A3 | **基础设施失败与被测失败分离** | 源码实测：`TerminationReason.INFRASTRUCTURE_ERROR` 的运行行从指标中剔除 | 本地化为**装置失败剔除条款**（§3.5）：harness 崩溃/超时/上下文超限/平台错误 → 标 `infra_error`，不入统计、单独计数披露 |
| A4 | **评分装置版本变更 ⇒ 分数不可比** | `evaluation.md` 实读：v1.0.1 grading update 修正任务错误后，官方明示「results produced with tau2-bench < 1.0.1 are not comparable with >= 1.0.1」，榜单全部重评、复现须钉 pre-v1.0.1 tag | 本地化为**评测装置钉版条款**（§4.4/§8.1）：golden/rubric/runner/裁判 prompt 任一变更 ⇒ evalbench 版本号 bump；跨 evalbench 版本的分数**禁止**直接比较与合并披露 |
| A5 | **任务集质量自审（SABER）** | `evaluation.md` 实读：v1.0.1 即 SABER 审计产出——修复 75+ 处任务缺陷（错误的期望动作、歧义指令、不可能约束、缺失兜底）；任务集缺陷会系统性污染分数 | 本地化为**黄金任务自检清单**（§5.1 L1-3）：每个合成任务模板发布前过「歧义指令 / 不可能约束 / 缺失兜底 / 期望产物错误」四项自检 |
| A6 | 域三元组 policy+tools+tasks | 每域 = 行为策略 + 可用工具 + 任务集 | 借为 **MCP/插件型「文档增益评测」的装配结构**（§6.2）：被测文档包（≈policy）+ 执行环境可用工具（≈tools）+ 盲评任务（≈tasks） |
| A7 | 不采纳 | 用户模拟器多策略对话、语音全双工；DB hash 级终态比对 | 我方资产多为单向文本产物任务，无需用户模拟器；DB hash 比对成本高，以文件/结构断言（SKILL-SPEC §3.1 断言枚举）替代。tau-bench 原版（`CATALOG.md:245`，已 superseded）仅作 pass^k 概念源流引用，不直接采用 |

### 2.2 terminal-bench（`CATALOG.md:240`）——任务标准件【实访】

本轮实际访问（2026-09-29）：`raw.githubusercontent.com/laude-institute/terminal-bench/main/README.md`。核实所见：每任务 = **任务指令（英文）+ 验证测试脚本 + 参考解法（oracle solution）** 三件套；每任务独立 Docker 沙箱终端环境执行；beta 约 100 任务；榜单用版本化数据集 terminal-bench-core v0.1.1。

- **采纳 B1——任务三件套**：本地化为每条盲评任务的**标准装配**（§3.8-2）：任务指令 + 可执行验证脚本（确定性部分）+ oracle 参照产物（可选，供裁判对照）+ rubric（主观部分）。这与首夜实践（每资产 oracle/ 红绿校验，`DELIVERY.md` §4.1 第一层）同构，v0.2 起固化为任务件标准。
- **采纳 B2——数据集版本化**：榜单级任务集独立版本号（terminal-bench-core 模式）→ 本地化为 golden 冻结升版（继承 SKILL-SPEC §3.2 规则 4）+ evalbench 版本（A4）。
- **不采纳**：Docker 沙箱硬依赖——本机（windev-01）无此保证，当前以独立子代理上下文隔离替代，如实声明局限；沙箱列为可选升级。

### 2.3 AgentBench（`CATALOG.md:239`）【清单口径，本轮未重访】

多轮交互 + 多环境分维度打分框架（ICLR 2024，8 交互环境）。**采纳 C1——分维度分项报告**：benchmark.json 的 aggregate 除总均分外**【必须】**按任务模板/能力域分组给出分项均分（§8.1），防"总分掩盖短板"。**不采纳**：其容器化环境矩阵（本地资源与维护成本不匹配；我们只评自有资产，不评通用 agent 能力）。

### 2.4 SpreadsheetBench（`CATALOG.md:251`）【清单口径，本轮未重访】

V1=912 真实 Excel 任务程序化判分；V2=321 端到端工作流、程序化断言评分、最佳 34.89%。**采纳 D1——程序化判分优先哲学**：确定性 checks 承载的权重**【应当】**≥ rubric 总权重 50%（§5.1 L3-2），裁判只裁机判覆盖不到的维度。**采纳 D2——「真实数据复验」层的同类参照**：真实任务集的构造方向（真实文件/真实工作流）与 §5.3 一致。**不采纳**：任务规模（912 条对我们是长期目标非门槛；真实复验层起步 ≥3 条并如实标注「小样本、非统计结论」，见 §5.3-3）。

### 2.5 promptfoo（`CATALOG.md:256`）【清单口径，本轮未重访】

声明式用例 + 断言 + CI 流水线自动检查，本地运行。**采纳 E1——评测即 CI 门禁定位**：eval/ 目录 + runner 是发布流水线的强制前置步骤（对齐 SKILL-SPEC §4 门 1）；golden.json 保持声明式 schema（机读、可 diff、可归档）。**不采纳**：其红队/漏洞扫描能力不并入本规范（安全评测独立，见 2.7）。

### 2.6 Coze Loop / Langfuse / Phoenix / OpenCompass（`CATALOG.md:257-260`）【清单口径，本轮未重访】

- **采纳 F1——三层抽象**（Coze Loop 评测集/评测器/实验）：benchmark.json 落盘 schema 按三层组织：`tasks`（评测集）/ `judge_consistency`+`checks`（评测器）/ `aggregate`+`acceptance`（实验）（§8.1）。
- **采纳 F2——裁判 prompt 版本化**（Langfuse prompt 管理）：裁判提示词**【必须】**随轮次落盘版本标识（§8.1-4）；裁判 prompt 变更 ⇒ evalbench 版本 bump（A4）。
- **采纳 F3——可复现报告**（OpenCompass）：报告**【必须】**含模型钉版、采样参数、种子、日期、执行通道版本（§8.1-3）。
- **不采纳（暂缓）**：自托管观测平台（Langfuse/Phoenix）——列为 D31–60 可选基建（`DELIVERY.md` §6.3-4 已列待办），不阻塞本规范生效。

### 2.7 AgentSkillsScanner（`CATALOG.md:265`）与安全评测的分立【清单口径，本轮未重访】

该资产 = 静态扫描 + AI 审计 + Docker 沙箱动态监控的 8 步管道（98,380 skills 中标 157 恶意）。**采纳 G1——质量门与安全门分立**：本规范只管质量评测；凡含可执行代码/外部请求面的资产（scripts/、MCP、plugin），发布前**【必须】**另行过安全门（静态扫描 + 沙箱动态，专项规范另行制定，本文件仅定门位与互斥关系：安全门不过，质量评测结果不得对外引用）。**采纳 G2——供应链自证**：评测报告随包分发（对齐治理方案「缺报告=不可分发」）。

### 2.8 其他机制借用

| 来源 | 机制【清单口径，本轮未重访】 | 处置 |
|---|---|---|
| wshobson/agents 的 plugin-eval（`CATALOG.md:73`） | 静态评审 + LLM 评审 + Monte Carlo 多次采样 | Monte Carlo 思想即 §3.2 多次重复（已采纳）；静态评审并入 SKILL-SPEC 门 5（断言复审），不另建 |
| livekit/agents 内置测试框架 + LLM judge（`CATALOG.md:205`） | 框架内建评测 | 印证「评测内建于资产包」路线（SKILL-SPEC §1.1 eval/ 必选），无需另行采纳 |
| virattt/dexter 的 LLM-as-judge 评测套件（`CATALOG.md:381`） | LLM-as-judge + 循环检测/步数上限防失控 | 裁判制沿用 v0.1 §3.3；防失控参数（最大步数/超时）纳入装置失败剔除（§3.5） |
| Glama 三维 A–F 评级（`CATALOG.md:171`） | license/quality/maintenance 三维目录评级 | **不进验收门**；借为资产目录层标注维度（quality 由本规范评测结果填充，对应 SKILL-SPEC metadata.quality） |

### 2.9 采纳汇总

**直接采用**：任务级多数判定（pass^k 本地化）、端态判定原则、装置失败剔除、装置钉版不可比条款、任务自检四项、任务三件套、程序化判分优先、三层落盘抽象、裁判 prompt 版本化、质量/安全门分立。
**改造后采用**：域三元组（→ 文档增益装配）、沙箱执行（→ 子代理上下文隔离替代）。
**明确不采纳**：用户模拟器、912 条级任务规模、观测平台自托管（暂缓）、DB hash 端态比对（以结构断言替代）。

---

## 3. 抗噪声评测协议（v0.2 核心）

### 3.1 任务规模

1. 每资产盲评任务数（ab_tasks）**【必须】≥5、目标 8**（取代 SKILL-SPEC §3.2 规则 2 的「≥3 条」）。少于 5 条**【禁止】**出具验收结论（可出具「中期信号」，标注 n 并禁止用于入库判定）。
2. 任务集**【必须】**覆盖三维：能力域维度（每个声明的能力 ≥1 条）、难度维度（≥1 条高难/边界）、陷阱维度（≥1 条 negative 或 adversarial——对齐 SKILL-SPEC §2.1 三类用例纪律）。
3. 融合路由型资产（SKILL-SPEC §5.2）：每方法 ≥1 条之外，跨方法任务 ≥1 条，总数仍按本条下限执行。
4. 任务数超过 8 条时**【可以】**全量评测；**【禁止】**为凑任务数注水（同模板无差异变体 ≤2 条）。

### 3.2 同任务多臂重复

1. 每条任务每臂重复次数 n **【必须】≥2**（标准验收轮 n=2；取代「每臂 1 对」实践）。**【禁止】** n=1 出具验收结论。
2. **【应当】**升级 n=3 的情形：Δ 落在 0.5–1.0 边界带、任务级胜率落在 55%–65% 边界带、或复检轮。
3. 重复间**【必须】**上下文隔离：每次运行为独立子代理会话（干净上下文，无跨次记忆——继承 v0.1 §3.3 规则 1）。
4. 甲乙（treatment/baseline 呈现位置）**【必须】**在任务间与重复间轮换，防顺序偏置（继承首夜实践）。
5. 采样参数（温度 / reasoning variant）两臂一致并落盘；执行通道不可控采样时**【必须】**如实记录「平台默认采样」，残余随机性由 n≥2 与 §3.3 多数判定吸收。

### 3.3 任务级胜负判定（pass^k 本地化）

1. 任务分 = 该任务 n 次重复加权分的算术平均（先任务内平均，再对任务平均；臂均分 = 各任务分的平均；**Δ = treatment 臂均分 − baseline 臂均分**）。
2. 任务级胜负（多臂多数判定，抗单次噪声）：
   - n=2：该任务 treatment 两重复加权分**均**高于 baseline 同序对 → 任务胜；均低 → 任务负；其余（1:1）→ **任务平**。
   - n=3：≥2 次更高 → 任务胜；≤1 次更高 → 任务负。
   - 加权分 = Σ(维度分×权重)/Σ权重（0–10 制，继承 v0.1）。
3. **任务级胜率 = 任务胜数 ÷ 任务总数**（平局计入分母、不计胜——与 v0.1「平局不计胜」口径一致）。配对级胜率（对粒度）另记为辅助披露指标，不用于判定。

### 3.4 裁判一致性校验

1. 每轮盲评**【必须】**做裁判自洽抽检：每任务至少抽 1 份产物（两臂轮换覆盖），以**匿名化**形式（文件名去臂标、混入新批次、不告知为复评）由**同一裁判**按同一 rubric 复评一次。
2. 同份产物两次评分差 **>2**（0–10 加权制）→ 判该裁判本任务失格：**换裁判**（更换裁判会话实例；具备条件时更换裁判模型）重评该任务全部产物；重评后仍 >2 → 该任务标 `unjudgeable` 退出本轮统计并在报告披露。
3. 抽检记录（任务、被抽产物、两次分、分差、处置）**【必须】**落盘 `judge_consistency` 字段（§8.1-5）。
4. 裁判**【禁止】**对两臂来源与顺序知情（继承 v0.1 盲态）；**【禁止】**同情分，评分**【必须】**附实测证据（复跑脚本/逐字比对/回读证据——继承首夜裁判实践，见 `ab_summary.json` 判词范式）。
5. 裁判模型与裁判 prompt 版本**【必须】**随轮次落盘（§8.1-4）。

### 3.5 装置失败剔除（tau2 A3 本地化）

1. 以下情形标 `infra_error`，**不入统计、单独计数披露**：harness/runner 崩溃、非被测原因超时、上下文超限、执行平台错误（重试 1 次仍失败）、裁判通道故障。被测产物自身的交付失败（答非所问、产物损坏）是被测失败，正常计分。
2. 单任务 `infra_error` 计数 > 有效重复数一半 → 该任务本轮作废，**【必须】**以有效任务数 ≥5 复核 §3.1-1 门槛，不足则本轮整体无效。

### 3.6 接受判定：复合线（取代 v0.1 门 2 的单线「Δ≥1.0 且胜率≥60%」）

盲评门 v0.2 **【必须】同时满足**以下三条：

| # | 条件 | 防的伪增益 |
|---|---|---|
| ① | **均分差 Δ ≥ 1.0**（0–10 加权制，§3.3-1 口径） | 无增益/负增益 |
| ② | **任务级胜率 ≥ 60%**（§3.3-3 口径；5 任务需 ≥3 胜，8 任务需 ≥5 胜） | 单点拉动、胜负翻转 |
| ③ | **反向任务 ≤ 1**。反向任务 = 任务级 treatment 均分 < baseline 均分，**或** treatment 任务均分 = 0（完全失败） | 「大胜大败并存」的高方差资产——均分被个别满分任务抬高、多数任务实际被基线反超 |

平局任务不进反向计数；三条以最严格者裁决。验收记录**【必须】**逐条给出三条件的实算值。

### 3.7 稳态披露要求（对外引用纪律）

1. 单轮结果**【可以】**判「通过/不通过」，但对外引用**单点 Δ 值****【必须】**有两轮独立评测方向一致（Δ 同号且两轮均 ≥1.0）支撑；否则**【必须】**披露区间 [Δ_min, Δ_max] 与 n、轮次数。
2. 一切对外披露**【必须】**附带：任务数、每臂重复数、评测模型钉版（§4.4）、evalbench 版本（§8.1-2）。缺任一项的数字**【禁止】**外引（对齐 `DELIVERY.md` §6.3-6「对外引用外部数字前逐项复核」纪律的内向版）。
3. 存量首轮数字（v0.1 协议、每任务 1 对）对外引用时**【必须】**标注「首轮信号」，见 §7.2-3。

### 3.8 流程控制清单（评测执行件）

1. 两臂唯一差异 = 资产挂载（§4.2）；同 harness、同 prompt 模板、同上下文装配顺序、同采样参数。
2. 每条任务**【必须】**按三件套装配（terminal-bench B1 本地化）：任务指令 prompt + 确定性 checks（复用 eval_inputs 断言子集，双臂同判）+ oracle 参照产物（可选）+ rubric（维度×权重×分档描述，**【必须】**含正确性/完整性/可验证性三维——继承 v0.1 §3.2）。
3. 效率记录**【必须】**逐 run 落盘：token 用量与耗时（效率门 §7.1 门 3 的数据来源，v0.1 §3.3 规则 6 继承加严）。
4. 装置随机种子、执行通道版本、日期落盘。
5. 全部产物与转录**【必须】**归档（失败轮同样归档——`DELIVERY.md` §6.3-3「失败现场与成功现场同等归档」升级为条款）。
6. 同批裁判评审时两臂产物**【必须】**混洗且匿名。
7. **端态判定原则**（tau2 A2 本地化）：断言与裁判均判"是否达成任务目标态"，**【禁止】**因实现路径与参照不同而扣分；仅当任务目标本身是格式/保真时方可按 rubric 显式条款判格式分。

---

## 4. 标准评测模型：GLM-5.3-Flash

### 4.1 定标与理由

1. **GLM-5.3-Flash 定为 skillfactory 全部评测臂（treatment/baseline/裁判）的标准评测模型**，自本版起统一。
2. 理由：①代表大多数人**成本可负担的主流水平**——我方评测目标是「普通模型 + skill」的增益结论（`总体方案` §3「普通模型+skill bench 护城河」），在旗舰模型上测得的增益对目标用户外推效度存疑，在主流可负担模型上测得的最有代表性；②通道已在本机配置可用且容量适配：`C:\Users\Administrator\.zcode\cli\config.json` 实读——`model.main = builtin:bigmodel-coding-plan/GLM-5.3-Flash`，provider `builtin:bigmodel-coding-plan`（kind=anthropic，baseURL `https://open.bigmodel.cn/api/anthropic`），上下文 1,000,000 / 输出 128,000，多模态输入，满足办公文档型任务产物的评测需要【盘内，本轮 python 实读；凭据字段不引用】。
3. 执行通道：zcode CLI headless（`--mode yolo`，独立子代理会话承载每臂每重复，配置见上）。

### 4.2 双臂同模型协议

1. treatment 臂与 baseline 臂**【必须】**同一模型、同版本、同执行通道、同采样参数、同 prompt 模板、同上下文预算；**唯一差异 = 资产挂载**（with_skill 臂注入 SKILL.md/资产文档；without_skill 臂不注入）。
2. 裁判首期用同一 GLM-5.3-Flash（盲态与证据要求见 §3.4）；**【应当】**在 D31–60 升级双裁判矩阵（跨模型家族互评），届时裁判模型与被测模型解耦并落盘（`DELIVERY.md` §4.3-2 待办承接）。
3. **【禁止】**两臂中任一臂使用不同模型或不同版本——跨模型双臂测得的不是资产增益而是模型差异。

### 4.3 公平性禁令

1. **baseline 臂禁读资产**：baseline 臂**【禁止】**访问被测资产目录（SKILL.md、references/、eval/、scripts/）与评测装置目录（evalbench/、oracle/、golden）；实现方式 = 工作目录物理隔离（两臂不同目录树，资产不在 baseline 臂可访问路径内）。
2. **prompt 无泄漏**：两臂任务 prompt 逐字相同；**【禁止】**在任何臂的 prompt 中提示资产存在（不得出现资产名、"你有一个技能可用"类 baseline 臂暗示）。
3. **污染即作废**：抽检任一 baseline 臂转录发现资产正文片段进入其上下文 → 判污染事故，该任务两臂作废重跑，事故记录落盘；同轮污染 ≥2 任务 → 整轮无效。
4. **oracle 对两臂皆不可见**：任务**【必须】**自包含——首夜教训（归档 `:22` 所载：任务指令曾指向不存在的 `inputs/` 且禁读 `oracle/`，被测方无法合法取得输入，连续 2 轮 15 项全红）定 为反面条款：黄金输入**【必须】**随任务在两臂同等提供，oracle 参照产物两臂皆禁读。
5. **禁止事后补课**：评测轮内**【禁止】**用资产内容修改/增强 baseline 臂的任何产物。

### 4.4 模型钉版与变更规程

1. 每轮评测报告**【必须】**落盘模型钉版五元组：模型 ID、provider baseURL、CLI/runtime 版本、评测日期、reasoning variant（当前 config 默认 `max`）。
2. **评测模型/裁判模型/执行通道任一变更 ⇒ evalbench 版本 bump，旧基线全部作废重测**（tau2 A4 本地化：跨装置分数不可比）。**【禁止】**将不同钉版的 Δ 值并列比较或合并披露。

---

## 5. 合成黄金集 SOP

### 5.1 三层构造法

纯合成黄金集**【必须】**按三层构造，三层产物全部入库资产 `eval/` 目录：

**L1 任务模板层**（`eval/templates/`）：
1. 任务模板 = 字段化结构：`{能力域, 输入形态, 任务目标, 难度档, 陷阱开关(positive|negative|adversarial|edge), 变量槽[], 参照模板}`。
2. 每资产**【必须】≥5 个模板**（与 §3.1 任务下限对齐）；每个模板**【必须】**能生成 ≥2 个不同实例（可泛化性自检，防单例伪模板）。
3. 模板**【必须】**过任务自检四项（tau2 A5 本地化）：无歧义指令、无可行性矛盾（约束互斥）、失败路径有兜底判据、期望产物可构造。

**L2 输入生成层**（`eval/gen_inputs.py` 或等价生成器）：
1. 生成器按模板**程序化批量**生成任务输入，并**同步**产出该输入的 oracle 参照产物（由独立参照实现执行得到——继承首夜 oracle/ 三件套实践）。
2. 固定随机种子，种子与生成参数入库；同种子重跑**【必须】**逐字节复现（可复现性自检）。
3. 生成器自带**红绿自检**（继承首夜红检实践）：对 oracle 产物跑 runner 应全绿（exit 0）；对空输入/损坏输入跑 runner 应全红（exit 1）。红检不过的生成器**【禁止】**投产。
4. negative/adversarial 用例由模板「陷阱开关」生成（如误导性输入、近邻但不该触发的请求），**【禁止】**人工事后单独造而绕过生成器（保证可复现与可回归）。

**L3 评分 rubric 层**（模板内嵌 `rubric` 字段）：
1. 每模板配套 rubric：确定性 checks（机判）+ 主观维度分档描述（0/6/10 三档锚点，dimension×weight×descriptor——继承 v0.1 §3.2 schema）。
2. **程序化判分优先**（SpreadsheetBench D1 本地化）：确定性 checks 承载权重**【应当】**≥ rubric 总权重 50%；凡 runner 可机判的维度（文件存在、格式、数值、逐字溯源、路由结果）**【禁止】**交给裁判主观评分。
3. rubric 分档描述**【必须】**与确定性 checks 口径一致（首夜教训：rubric 字面与技能契约冲突导致 treatment 忠实复现 oracle 反被判失分——归档 `:54` ab-001 败因），评审时**【必须】**做「rubric↔checks 对齐走查」。

### 5.2 冻结与版本

继承 SKILL-SPEC §3.2 规则 4 并加严：golden.json 冻结于验收时版本；**只增不改**（追加用例合法，修改/删除既有用例与断言**【禁止】**）；修订**【必须】**升版本号并在 CHANGELOG 记录、旧版归档 `eval/archive/golden-v<N>-<date>.json`；evalbench 装置变更（§4.4）与 golden 变更**【禁止】**同轮发生（避免「新装置×新题」无法归因）。

### 5.3 两级晋级

| 级别 | 名称 | 通过条件 | 授予状态 |
|---|---|---|---|
| 第一级 | **合成达标** | §7.1 全部门在合成黄金集上通过（含 v0.2 盲评复合线） | `synthetic-passed` |
| 第二级 | **真实复验** | 真实任务集上过**回退门**（见下） | `real-verified` |

1. **真实复验任务集**：≥3 条真实任务（真实用户素材/真实业务语料，经 consent 与脱敏，对齐治理方案「课程真实素材回流黄金集」通道）；来源与脱敏记录落盘。
2. **回退门**（真实集只防回退、不重设增益线——真实集小样本+域移大，如实声明非统计结论）：a) 无任务 treatment 任务分 = 0；b) 无任务基线反超 ≥1.0；c) 真实集 Δ ≥ −0.5。
3. 两级状态齐备方可入库分发（§7.1 门 6）；**只**达 `synthetic-passed` 的资产**【禁止】**进入分发管线，对外披露**【必须】**双状态并列（如「合成达标 ✓ / 真实复验 ✗」）。
4. 回退门任一触发 → 打回合成层归因修订后重走两级；**【禁止】**通过改 rubric/删任务放水（§5.2 只增不改）。

---

## 6. 多形态适配

形态判定按 `v2/TAXONOMY.md` §四定义执行。四种评测路径：

### 6.1 文本说明书型（skill / prompt模板 / command / 工作流模板 / hook）

**直接双臂文本评测**：按 SKILL-SPEC 格式条款（skill 类）或本文件等价要求装配，treatment 臂挂载资产文本本体，走 §3 全协议。此为默认路径，无附加局限声明。

### 6.2 MCP / 插件型：文档增益评测（doc-gain evaluation）

MCP/插件的本体是**服务/代码**，首期评测对象为其**文档包**（README、工具清单、参数说明、最佳实践、示例命令）：

1. **装配**（tau2 A6 域三元组本地化）：两臂同一执行环境（同宿主、同可用基础工具、同上下文预算）；treatment 臂附加资产文档包，baseline 臂无；任务按资产声明的目标场景构造 ≥5 条（§3.1 同限）。
2. **判定**：产物按目标任务 rubric 判分，走 §3 全协议（含裁判校验与复合线）。
3. **局限声明【必须】**随评测报告披露四条：①本结果证明的是「文档增益」（文档能否让模型把任务做得更好），**不等于**服务/工具本体的增益；②未验证真实 server/plugin 的安装与运行行为；③存在文档与实现漂移风险；④证据等级为 `provisional`（文档级）。
4. **升级路径（实连接评测，live eval）**：treatment 臂真实安装并连接服务（连接性先用 MCP Inspector 类 smoke 工具验证——`CATALOG.md:141` 清单口径）、baseline 臂保持裸环境后重跑 §3 协议；通过后证据等级升为 `verified`（服务级），方可摘除 3 的局限声明。

### 6.3 agent 配置型（AGENTS.md / rules / .cursorrules / 子代理定义）：整包 kit 评测

配置件的价值只在完整工作目录上下文中兑现（agents.md 锚：「agent 的 README」——`TAXONOMY.md` 锚 6 实访口径），故**禁止**孤立评配置文本：

1. **评测单元 = 整包 kit**：目标仓库/工作目录快照。treatment 臂 = kit 含配置件；baseline 臂 = 同一 kit **不含**配置件。
2. **token 补偿控制**：baseline 臂**【必须】**放置等量中性占位文档（与配置件 token 量对齐、不含任何任务相关信息），排除「上下文多多益善/越少越好」混杂效应。
3. **任务**：kit 所服务领域的典型开发/操作任务 ≥5 条（§3.1 同限），在 kit 上下文中执行；**判定**：交付物质量（rubric）+ 回归测试通过率（机判优先，D1）；走 §3 全协议。
4. 配置件自身的格式检查（如 AGENTS.md 无必填字段——`CATALOG.md:26` 清单口径）归形式门，不属盲评门。

### 6.4 评测集型 / 软件系统型资产（自指评测）

1. **评测集资产**：对拍法——抽样 ≥30 条任务与人工标注金标准对拍，一致率**【必须】**≥95% 方可自用/分发；自身红绿自检（§5.1 L2-3）必过。
2. **软件系统资产**：任务完成率（≥5 个典型任务）+ 既有回归套件全绿；效率与稳定性记录同 §3.8-3。
3. 两类资产的详细细则不在本文件展开，门位引用 §7.1，专项规范另行制定。

---

## 7. 门禁整合与迁移

### 7.1 v0.2 全门一览

| 门 | 名称 | 判据 | 出处 |
|---|---|---|---|
| 1 | 确定性门 | runner exit 0 + 全部确定性 checks 过 + 生成器红绿自检过 | 继承 SKILL-SPEC §4 门 1 + §5.1 L2-3 |
| 2 | 盲评门（v0.2 复合线） | **Δ≥1.0 且 任务级胜率≥60% 且 反向任务≤1**（§3.6，任务≥5、n≥2、裁判校验通过为前置） | **本文件取代 v0.1 门 2** |
| 3 | 效率门 | token 比率 ≤2.0 且耗时比率 ≤2.0（逐 run 落盘为前提） | 继承 v0.1 门 3，数据义务加严（§3.8-3） |
| 4 | 形式门 | SKILL-SPEC §1 全部格式检查（skill 类）；其他形态按其格式规范 | 继承 |
| 5 | 断言复审门 | 无恒过/恒败/双臂同过断言 | 继承 v0.1 门 5 |
| 6 | **真实复验门（新增）** | §5.3 回退门通过，双状态齐备 | 本文件新增；MCP/插件型在 doc-gain 阶段保持 provisional、实连接评测后方可过本门 |
| — | 安全门（分立） | 静态+沙箱扫描（专项规范另行）；不过则质量结果**【禁止】**外引 | §2.7，不属本六门 |

### 7.2 迁移条款

1. **本文件生效即**：新资产评测一律按 v0.2；SKILL-SPEC §3.3 与 §4 门 2 同时废止（§0.2-1）。
2. **存量 4 资产**（meeting-minutes / monthly-report-ppt / ppt-method-router / paper-to-skill）：既有盲评结论保留并**永久标注**「v0.1 协议·每任务 1 对·首轮信号」；复检按 v0.2 执行（任务扩至 ≥5、n=2、含裁判校验）；复检结论覆盖首轮。meeting-minutes 在复检通过前维持「两门过、待五门复检」状态（`DELIVERY.md` † 注承接）。
3. golden 迁移到 v0.2 任务规模（≥5 条）时按 §5.2 只增不改 + 升版归档执行。
4. 评测模型钉版（§4.4）自 v0.2 起追溯：v0.1 轮次未落盘钉版五元组的，报告**【必须】**标注「钉版未记录」。

---

## 8. 落盘与披露

### 8.1 `eval/results/benchmark.json` v0.2 必填结构（三层抽象，Coze Loop F1 本地化）

```json
{
  "asset": {"name": "", "version": "", "form": "skill|MCP|plugin|agent-config|prompt|command|workflow|hook|evalset|software"},
  "evalbench": {"version": "", "golden_version": "", "gate_version": "v0.2"},
  "model_pin": {"model_id": "builtin:bigmodel-coding-plan/GLM-5.3-Flash", "provider_base_url": "", "cli_version": "", "date": "", "reasoning_variant": "", "judge_model_id": "", "judge_prompt_version": ""},
  "tasks": [{"id": "", "template_ref": "", "type": "positive|negative|adversarial|edge",
             "arms": {"treatment": {"runs": [{"score": 0, "tokens": 0, "duration_s": 0, "infra_error": false}]},
                      "baseline":  {"runs": []}},
             "task_mean_t": 0, "task_mean_b": 0, "task_verdict": "win|loss|tie|unjudgeable", "reverse_flag": false}],
  "judge_consistency": [{"task": "", "resample_of": "", "first_score": 0, "second_score": 0, "delta": 0, "action": "pass|re-judged|unjudgeable"}],
  "infra_errors": [{"task": "", "arm": "", "run": 0, "reason": ""}],
  "aggregate": {"mean_baseline": 0, "mean_treatment": 0, "delta": 0, "task_win_rate": 0, "pair_win_rate": 0, "reverse_tasks": 0, "by_domain": [{"domain": "", "delta": 0}]},
  "acceptance": {"gates": {"deterministic": true, "blind_v02": true, "efficiency": true, "format": true, "assertion": true, "real_recheck": false},
                 "blind_detail": {"delta_ok": true, "winrate_ok": true, "reverse_ok": true},
                 "evidence_level": "synthetic-passed|real-verified|provisional|verified",
                 "verdict": "accepted|rejected|provisional"},
  "disclosure": {"rounds": 1, "single_round_signal": true, "delta_range": [0, 0]}
}
```

### 8.2 披露口径纪律（汇总）

1. 数字四随：任务数 n、每臂重复、模型钉版、evalbench 版本必须随数字披露（§3.7-2）。
2. 单轮结果标注 `single_round_signal: true`；对外单点 Δ 需两轮一致（§3.7-1）。
3. 首轮存量数字永久标注「首轮信号」（§7.2-2）。
4. 装置失败计数与 `unjudgeable` 任务必须披露，**【禁止】**静默剔除（§3.5）。

---

## 附录 A：v0.1 → v0.2 关键条款对照

| 条款 | v0.1（SKILL-SPEC §3.3/§4 门 2） | v0.2（本文件） |
|---|---|---|
| 任务数 | ab_tasks ≥3 | **≥5，目标 8**（§3.1） |
| 每臂重复 | ≥3 次（首夜实践为 1，未达） | **标准 n=2，禁止 n=1**；边界带/复检轮 n=3（§3.2） |
| 胜负粒度 | 逐对胜负，胜率=胜对/总对 | **任务级多数判定**（pass^k 本地化），配对胜率降为辅助披露（§3.3） |
| 裁判校验 | 盲态+证据，无自洽校验 | **复评抽检，分差>2 换裁判重评**（§3.4） |
| 接受线 | Δ≥1.0 且胜率≥60% | **复合线**：Δ≥1.0 且 任务级胜率≥60% 且 反向任务≤1（§3.6） |
| 装置失败 | 未规定 | **infra_error 剔除并披露**（§3.5） |
| 评测模型 | "同一模型"未定标 | **GLM-5.3-Flash 定标 + 钉版 + 公平性禁令**（§4） |
| 黄金集 | golden schema + 冻结 | **合成三层 SOP + 真实复验两级晋级**（§5） |
| 形态适配 | 仅 skill | **四路径：文本直评 / doc-gain / 整包 kit / 自指**（§6） |
| 披露 | 记录均分±σ、逐对胜负 | **数字四随 + 两轮稳态 + 失败披露**（§3.7/§8.2） |

## 附录 B：验收检查单增量（评测部分，对 SKILL-SPEC 附录 B 评测行的替换）

- [ ] ab_tasks ≥5 且 ≤8（或超 8 无注水），覆盖能力域×难度×陷阱三维
- [ ] 每任务每臂 n≥2，独立子代理上下文，甲乙轮换，采样参数一致并落盘
- [ ] 任务级胜负按多数判定计算；任务级胜率为判定口径，配对胜率为披露口径
- [ ] 裁判复评抽检 100% 任务覆盖，无 >2 分差未处置项，judge_consistency 落盘
- [ ] infra_error 与 unjudgeable 剔除有记录且有效任务数 ≥5
- [ ] 复合线三条件实算值逐条落盘（Δ、任务级胜率、反向任务数）
- [ ] 模型钉版五元组 + 裁判 prompt 版本落盘；baseline 臂无资产路径可达（隔离目录树实查）
- [ ] 生成器红绿自检双过；同种子复现一致；rubric↔checks 对齐走查完成
- [ ] 真实复验 ≥3 条且回退门三条件过；双状态披露；doc-gain 资产四条局限声明在位
- [ ] benchmark.json 按 §8.1 schema 落盘；对外材料含数字四随

## 附录 C：证据索引

**本轮实际读取（盘内，文件级）**：
- `skillfactory/standard/SKILL-SPEC-v0.1.md`（386 行全文；§0.2 取代关系、§3.2/3.3 继承条款的原始出处）
- `skillfactory/report/DELIVERY.md`（全量定稿 v1.2；§4.1 三层方法、§4.3 待复验清单、§6.3 纪律条款）
- `skillfactory/v2/CATALOG.md`（全量；§2 拿来主义全部条目的出处行号：:73/:141/:171/:205/:239/:240/:245/:246/:251/:256-260/:265/:381）
- `skillfactory/v2/TAXONOMY.md`（全量；形态横轴定义 §四、锚 5/6/7）
- `skillfactory/assets/meeting-minutes/tests/ab_summary.json`（全文 31 行：tasks=3、5.67→10、Δ=4.333、winRate=1、逐任务 7:10/4:10/6:10 与三份裁判判词）
- `skillfactory/assets/ppt-method-router/tests/ab_summary.json`（实读任务级明细：ab1-clear-single-category 9:8 基线胜 / ab2-ambiguous-fallback 8:9 / ab3-mixed-priority 9:9 平；Δ=0、winRate=0.333）
- `skillfactory/report/archive/交付报告-旧稿-20260929T0721-已废弃.md`（grep Δ/胜率定位：:7 更早轮 Δ=3.67、:54 第 2 轮 8→9.67/Δ=1.67/0.67、:56 ppt-method-router Δ=0.67/0.67、:57 paper-to-skill −0.5/0.5、:182-186 对账记录）
- `C:\Users\Administrator\.zcode\cli\config.json`（python 实读：`model.main = builtin:bigmodel-coding-plan/GLM-5.3-Flash`；provider baseURL `https://open.bigmodel.cn/api/anthropic`、kind=anthropic；GLM-5.3-Flash 上下文 1,000,000/输出 128,000/多模态输入/reasoning defaultVariant=max。凭据字段已核存在、本文件不引用）
- paper-to-skill 仅 2 任务口径引自 `DELIVERY.md` 附录 A2（:187）与其第三节资产表，本轮未重读该资产 ab_summary.json。

**本轮实际访问（web_reader，2026-09-29）**：
- `raw.githubusercontent.com/sierra-research/tau2-bench/main/README.md`——域清单（telecom/airline/retail/banking_knowledge/mock）、任务为 JSON 清单、v1.0.1 grading update 与「跨版本不可比」公告
- `raw.githubusercontent.com/sierra-research/tau2-bench/main/docs/evaluation.md`——evaluation_criteria 五字段、actions=单条参考轨迹重放推终态、"not required to take this specific path"、reward=分量乘积、SABER 审计（75+ 修复，arXiv:2512.07850 转引）
- `raw.githubusercontent.com/sierra-research/tau2-bench/main/src/tau2/metrics/agent_metrics.py`——`pass_hat_k` 源码与 `C(success,k)/C(trials,k)` 公式、arXiv:2406.12045 出处注释、INFRASTRUCTURE_ERROR 剔除逻辑
- `raw.githubusercontent.com/laude-institute/terminal-bench/main/README.md`——任务三件套（instruction/test script/oracle solution）、Docker 沙箱、terminal-bench-core v0.1.1 版本化
- 首次 WebFetch（WebFetch 工具）两次均以 TLS ECONNRESET 失败，改用 web_reader 成功——通道事实如实记录

**清单口径（本轮读 CATALOG 转引，未重访外部页面）**：AgentBench、SpreadsheetBench、promptfoo、Coze Loop、Langfuse、Phoenix、OpenCompass、AgentSkillsScanner、Glama、wshobson/agents（plugin-eval）、livekit/agents、dexter、agents.md 的相关机制描述。

**本轮未执行（如实声明）**：未运行任何新盲评（v0.2 协议的首次实测是下一步工作）；未重读 paper-to-skill / monthly-report-ppt 的 ab_summary.json 原文（口径转引自 `DELIVERY.md` 附录 A2 对账记录）；未实测 pass^k 代码（仅读源码）；未验证 GLM-5.3-Flash 定价（「成本可负担」系 ask 下发理由与 zcode coding-plan 通道事实，未查价目表）。

---

## 增补条款 E-1（2026-09-30）：同上

（同 `SKILL-SPEC-v0.1.md` 增补条款 A-1：接口常量全文披露。）

1. 凡 eval 对常量（token 名、要素名、字段名、枚举值）做逐字节或高阈值（如结构一致率阈值）比对者，该常量全集**【必须】**全文列于该资产的 `spec.md` 或 `contract.md` 附录——逐条给出字面值与语义注记，使实现者不读参照实现即可产出逐字节合规的产物；**【禁止】**以「以某文件为冻结源」式引用替代披露（指向冻结源的引用仅可作来源佐证）。
2. 本案案例：hot-templates 资产重生成曾因四平台开放槽位 token 名、video 要素命名、xhs 七要素占位符、wx `total_filled_from_input` 语义只存在于 `oracle/gen.py` 而连续两轮受阻，经雇主批准有限例外方通过——本条款为该接口文档缺陷的根治。
3. 重生成实现者因此类披露缺陷受阻时**【必须】**升级（向发题方/雇主申请裁定）而非硬猜；豁免裁定**【必须】**记录于资产目录。

---

*（EVAL-SPEC v0.2 完。修订记录：v0.1=SKILL-SPEC-v0.1 §3/§4 门 2，2026-09-29；v0.2 同日独立成文升版，动因=首夜盲评噪声实测。）*

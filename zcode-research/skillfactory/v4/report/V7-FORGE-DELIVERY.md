# V7 铸造批次交付报告（V7-FORGE-DELIVERY）

| 项 | 值 |
|---|---|
| 文件 | `skillfactory/v4/report/V7-FORGE-DELIVERY.md` |
| 日期 | 2026-09-30（距 90 天路线图起算日 2026-09-29 为 D1） |
| 批次内容 | 4 件资产：1 个 skill（hot-templates）+ 3 个 tooling（content-evaluator / mcp-office-pack / office-eval-suite），均在 `skillfactory/v4/` 下 |
| 数字口径 | 资产表 `oracleOk / evalOk / regenPassed / regenRounds / abDelta / winRate / accepted` 以**任务下发 assetInventory 为唯一权威口径**；盲评均分与逐任务分数取自盘内 `assets/hot-templates/tests/ab_summary.json`（本会话实读，与下发口径逐项一致）；确定性评测与红检为本会话实际复跑结果（命令与输出见附录 A） |
| 材料来源 | ① 任务下发 assetInventory（4 条）；② 四资产盘内 spec.md / contract.md / CHANGELOG.md / golden.json / 评测产物（本会话全文读取关键件）；③ `skillfactory/standard/SKILL-SPEC-v0.1.md` §3.3/§4（五门条款实读）；④ `skillfactory/plan/MASTER-PLAN.md`（总体方案 v2.0，D31–60 排期实读） |
| 版本说明 | v1.1（同日）按独立审读意见修订三处：① §2.1 补披露 ab-001/arm-a/rep2 缺 OUT.md（20 rep 中唯一缺件，实测 19/20 在位）；② spec.md 行数引用按 `wc -l` 实测勘误三处（154/227/127）；③ 附录 A 为每条命令标注实际执行目录（两条 runner 相对参数命令 CWD 敏感，已实测根目录失败/资产目录通过双口径） |

---

## 一、执行摘要

**本批产出 4 件，全件过确定性门，skill 件全胜过盲评门。**

1. **hot-templates（四平台爆款内容结构模板技能）**：oracle 验收、确定性评测、重生成门禁三过；双臂盲评 **Δ=6.1、胜率 1.0（5/5 任务全胜）、reverse=0，accepted=true**——工厂**第二个**过盲评门的 skill 资产（第一个为 meeting-minutes Δ=4.33），且 **Δ=6.1 刷新「聚焦单能 + 确定性 oracle」画像的增益上限锚点**（原锚点 4.33，总体方案 §3.2 读数 3）。baseline 均分 3.9 → treatment 均分 10.0（treatment 五任务全部满分）。
2. **content-evaluator / mcp-office-pack / office-eval-suite（三个 tooling 件）**：按任务下发分 kind 口径不做盲评（ab=null），三件确定性评测全绿、重生成门禁全过，作为**评测/连接基建**入库。

**哪些达到可分发线（按 SPEC §4 五门口径，`SKILL-SPEC-v0.1.md:266-276` 实读）：**

| 资产 | 结论 | 依据 |
|---|---|---|
| hot-templates | **评测门口径已过（确定性门 + 盲评门双过），形式门主体达标；效率门未测、每臂重复 2<3、验收记录未落盘——五门复检完成前不进分发** | 本会话复跑 eval 40/40 exit 0 + 盲评 Δ=6.1/胜率 1.0；front-matter 六字段齐、正文 97 行/4,338 字符（§4 形式门线为 ≤500 行/≤10,000 字符）；但 token/耗时比率无记录（效率门，`SKILL-SPEC-v0.1.md` §4 第 3 门）、每臂 2 次重复低于 §3.3 第 3 条「每臂 ≥3 次」、`eval/results/benchmark.json` 与 MANIFEST.json 在 v4 全域 find 零命中 |
| content-evaluator / office-eval-suite | **达基建入库线**（确定性评测全绿即入库作基建件；不适用盲评门） | 本会话复跑：6/6 与 4/4 检查 exit 0 |
| mcp-office-pack | **达基建入库线，且具备对内分发形态**（零真值密钥政策 + 自带校验器 + 10 条真实协议握手实录） | 本会话复跑 oracle validate 7/7、eval 5/5 均 exit 0；三份 `samples.json`（oracle 预置/复跑/package）逐份实读均 10/10 pass |

**门有牙（本会话实测）**：四个 runner 对空目录的红检全部 exit 1——没有一扇门是摆设。盲评门在本厂史上累计战果：拦 2（ppt-method-router Δ=0、paper-to-skill Δ=−0.5）、收 2（meeting-minutes 4.33、hot-templates 6.1）。

**一句话结论**：本批把「确定性 oracle + 对照盲评」这条验收线又向前压实了一格——第二个全胜 skill 说明 meeting-minutes 不是孤例而是可复制的画像；三个基建件（内容域评测器、办公 MCP 配置包、50 题办公评测集）把下一批资产的评测成本与课程产线的连接层提前铺好。欠账也原样延续：效率门、每臂重复数、验收记录落盘三类缺口在 v4 四件上全部存在，复检前一律不得对外分发。

---

## 二、逐资产明细

### 2.1 hot-templates — 四平台爆款内容结构模板技能（kind=skill）✅ 盲评接受

| 项 | 结果 |
|---|---|
| 目录 | `skillfactory/v4/assets/hot-templates/`（资产根含 spec.md / contract.md / CHANGELOG.md / inputs ×8 / oracle / package / eval / tests/ab） |
| oracle（参照实现） | `oracle/gen.py` 确定性渲染引擎（纯标准库、无时间戳无随机）+ `verify.py` V1–V6 验收。**本会话复跑 `python oracle/verify.py` → 74 项全 PASS、exit 0、0 fail**（含 V5 同输入复跑逐字节一致、V6 非法 platform 不建产物） |
| spec | `spec.md`（154 行，`wc -l` 实测）：R1 命令行契约与失败路径（非法参数 exit 2 且零产物）、R2 确定性（逐字节复跑一致）、R3A 四平台模板冻结（dy 6 要素/xhs 7 要素/wx 5 要素/video 6 镜 45 秒，分镜时长 `[3,7,10,10,10,5]` 冻结）、R4 卖点规整（恰 3 槽位、缺失补 `【占位:价值点N】`、超出入 `points_unused`）、R5/R6 双产物 schema、§10 十四行验证记录（T1–T9 探针 + 红绿矩阵全部实跑留痕） |
| contract | `contract.md` v1.0（2026-09-30 冻结）：目录布局、package 命令行契约、golden schema（eval_inputs 恰 8 / ab_tasks 恰 5）、runner 5 项检查与 90% 一致率阈值冻结；变更须升版本 + 归档旧 golden |
| 重生成门禁 | **通过，2 轮**（任务下发口径 regenPassed=true, regenRounds=2）。诚实注明：盘内无逐轮失败现场归档（`tests/` 下仅存终版盲评产物；`.mimosa/` 内文件为安全扫描钩子产物，与重生成轮次无关），第 1 轮是否失败、失败原因不可复溯——归入第四节 P0-3 落盘欠账 |
| 确定性评测 | **本会话实跑 `python eval/runner.py package/out oracle/out` → exit 0，40/40 通过**（8 case × 5 检查），结构一致率 8×100.0%（阈值 90%），stderr 0 字节 |
| 形式门抽测（本会话实测） | `package/SKILL.md` front-matter 六字段齐（name/version/license/description/permissions `[shell]`/metadata）；description 三段式：能力段 + 触发段 6 个口语短语（「爆款骨架」「抖音口播」「小红书图文」「公众号文章」「短视频分镜」「口播稿」≥3 达标）+ 边界段（不用于成文代写、一次一平台、长文转交写作类 skill）；正文 97 行 / 4,338 字符 ≤ 500 行 / 10,000 字符；资产根 CHANGELOG.md 在位（1.0 初版冻结） |
| **盲评（skill 附数字）** | **5 任务 × 双臂 × 每臂 2 重复 = 20 次运行**（盘内 `tests/ab/` 下 ab-001…005 × arm-a/arm-b × rep1/rep2 共 20 目录，本会话逐一清点）。**缺件披露：ab-001/arm-a/rep2 无 OUT.md 执行记录**（20 rep 中唯一缺件，本会话逐目录实测 19/20 在位）；该 rep 的 `骨架.md` 与 `structure.json` 与 rep1 **逐字节一致**（`cmp` 实测，确定性引擎同输入同产物），可作 rubric 交付物机械核验，汇总数字（Δ=6.1/胜率 1.0）不受影响。据审读意见转述（judge 会话本会话不可访问），当轮裁判已如实记录「Arm A rep2 没有 OUT.md」，改以 rubric 交付物核验后给分。`tests/ab_summary.json`（本会话实读）与任务下发口径逐项一致：**tasks=5，baselineMean 3.9 → treatmentMean 10，delta=6.1，winRate=1，reverseTasks=0，accepted=true**。逐任务（base:treat）：ab-001 抖音口播 3:10、ab-002 小红书图文 3:10、ab-003 公众号文章 3:10、ab-004 短视频分镜（1 条卖点缺槽）2:10、ab-005 确定性+失败路径工程验收 8.5:10——**五任务多数裁决全部 treatment，零反向**。盲评任务与 rubric 冻结于 `eval/golden.json`（本会话实读：5 条 ab_tasks，rubric 每条 3–4 个可判定维度，覆盖四平台各一 + 工程验收） |
| 读数 | baseline 在 ab-005（照步骤执行的工程验收任务）也能拿 8.5，差距最大的是开放式内容任务（2–3 分 vs 满分）——增益来自「确定性模板引擎 + 冻结结构红线」，与 meeting-minutes 的获胜画像完全同构，且 treatment 全满分说明该画像下技能把任务压到了判分上限 |

### 2.2 content-evaluator — 内容确定性评测器（kind=tooling）✅ 基建入库

| 项 | 结果 |
|---|---|
| 目录 | `skillfactory/v4/tools/content-evaluator/`（spec.md / contract.md / oracle{evaluate.py + fixtures ×4 + out 基线} / eval/runner.py / package{README.md + evaluate.py + fixtures + out}） |
| oracle（参照实现） | `oracle/evaluate.py` 1.0.0：对 md 文案按平台（dy/xhs/wx）做 9 项确定性合规打分——9 检查名与顺序冻结（`title_length → emoji_density → body_length → paragraph_max → tag_count → banned_words → structure_hook → structure_cta → structure_para`，spec R2）；44 词极限词表；平台阈值表冻结（xhs emoji 硬区间 [2,15] vs dy/wx 软上限警告，spec R3）；只报告不设门（红绿均 exit 0，参数错 exit 2，spec R9）。四 fixtures 基线：good_dy 9/9、good_xhs 9/9、bad_xhs 4/9（5 FAIL）、bad_wx 6/9（3 FAIL + 1 WARN） |
| spec | `spec.md`（173 行）：R1–R10 逐条可判定，§2.2 本会话前身探针记录（非法 platform exit 2 不建目录、干净重建仅 `generated_at` 一键之差等） |
| contract | `contract.md`：CLI/产物 schema/六检查项冻结；兼容性承诺（新增检查只能追加尾部、阈值不变） |
| 重生成门禁 | **通过，1 轮**（任务下发口径） |
| 确定性评测 | **本会话实跑 `python eval/runner.py`（零参自校验）→ exit 0，6/6 检查通过**：good_fixtures_all_pass / bad_xhs_expected_fails / bad_wx_expected_fails / score_recompute / report_md_consistency / oracle_agreement_90pct，stderr 0 字节 |
| 红检 | 本会话实跑空目录 → exit 1 ✅ |

### 2.3 mcp-office-pack — 办公 MCP 配置包（kind=tooling）✅ 基建入库（具备对内分发形态）

| 项 | 结果 |
|---|---|
| 目录 | `skillfactory/v4/assets/mcp-office-pack/`（spec.md / contract.md / oracle{mcp.office.json + validate.py + run_samples.py + docs ×10 + out} / eval/runner.py / package{同构 + SKILL.md}） |
| oracle（参照包） | 10 条 curated MCP server（filesystem/excel/word/powerpoint/google-workspace/gmail-official/playwright/excel-npm/tavily/context7），六格场景矩阵（文件/Excel/Word/PPT/浏览器/搜索）每格 ≥1；**零真值密钥**（`secret_env` 声明 + `${VAR}` 占位 + 11 条密钥正则族扫描，spec §3.4/§6 C1）；每条带目录溯源（`skillfactory/v2/CATALOG.md:<行号>` + record_url）；选型踩坑实录（powerpoint 钉 `mcp<2`、excel-npm 包名陷阱、cloudflare/playwright-mcp 换型理由，spec §3.6） |
| spec | `spec.md`（227 行，`wc -l` 实测）：S1–S3 场景矩阵规则冻结（含「换实现不换场景」等价通道）、D1–D3 手册一一对应、C1–C4 校验器行为、R1–R4 协议实跑器行为、§9 runner 四类判定；附录 A 为固化时实测记录（10/10 握手、红绿矩阵 6 例、google-workspace 冷拉包 300s 超时 → 600s 复跑通过的教训） |
| contract | `contract.md` v1.0 冻结：三条命令行、产物 schema、5 个检查项、防假绿条款（零 check 不允许判绿）；runner 不执行被测/参照任何模块（唯一例外裸跑被测自带 validate.py） |
| 重生成门禁 | **通过，1 轮**（任务下发口径） |
| 确定性评测 | **本会话实跑：① `python oracle/validate.py` → exit 0，7/7 全绿（all_green=true）；② `python eval/runner.py package oracle` → exit 0，5/5 检查通过**（package_validate_all_green / config_json_valid / scenario_coverage_matrix / docs_one_to_one / coverage_equivalent_to_reference），stderr 0 字节 |
| 协议握手实录（未重跑，引落盘件） | 三份 `samples.json` 逐份实读（oracle/out 预置 2026-09-30 10:11、oracle/out/samples-recheck.json 复跑 11:01、package/out）均 **10/10 pass**（8 条 stdio MCP 握手 + 2 条 http initialize）。本会话未重跑网络握手——引 spec 附录 A 与上述落盘记录 |
| 红检 | 本会话实跑空目录 → exit 1 ✅ |

### 2.4 office-eval-suite — 中文办公评测集 v2（kind=tooling）✅ 基建入库

| 项 | 结果 |
|---|---|
| 目录 | `skillfactory/v4/assets/office-eval-suite/`（spec.md / contract.md / oracle{suite.json + validate.py + export_legacy.py + out 含 8 个红灯夹具} / eval/runner.py + eval/out 红绿记录 / package{SKILL.md + 同构三件套}） |
| oracle（参照套件） | **50 题 × 8 域**（文档写作 8 / 表格数据 6 / 会议纪要 6 / PPT要点 5 / 邮件沟通 7 / 流程规范 6 / 信息抽取 6 / 改写润色 6），每题带易/中/难三档 + 3–5 条可判定 checks（全 suite 230 条）；题干自含材料（80–2000 字符 + 18 词材料标记 cue 表）；全局 易10/中32/难8。是 v3「中文办公 Prompt 回归黄金集」（25 题/6 域）的扩容版，附 v1 兼容导出器 |
| spec | `spec.md`（127 行，`wc -l` 实测）：R1–R9 套件数据规则（带 validate.py 行号）、V1–V4 校验器行为、X1–X4 导出器行为、E1–E4 runner 四项检查（含自评豁免与「异地逐字节拷贝不豁免」的防整卷抄袭条款）；§7 六步验证记录（绿/红/定向负例/确定性/布局解析全部实跑留痕） |
| contract | `contract.md`：root/package 双布局 + 报告目录单层回退冻结；50 题内容可自由重生成但结构/配比/难度规则冻结；eval 只增不删 |
| 重生成门禁 | **通过，1 轮**（任务下发口径） |
| 确定性评测 | **本会话实跑：① `python oracle/validate.py --suite oracle/suite.json` → exit 0，ALL GREEN ✓（9/9，50 题 / 230 条 check）；② `python eval/runner.py package oracle` → exit 0，4/4 检查通过**：被测校验器全绿 9/9、八域精确配比+难度分布一致、**与参照集完全相同题 0 ≤ 10（self_eval=false——package 是真实重生成的独立套件，最大相似度 0.352）**、legacy 兼容导出 25 题（六域 6/5/3/3/4/4）过 v1 校验器 7/7。stderr 0 字节 |
| 红检 | 本会话实跑空目录 → exit 1 ✅（spec §5 另录 8 个定向变异夹具逐一实跑全红，本会话未重跑） |

### 2.5 批次红检汇总（本会话实测）

```text
四个 runner 对同一空目录作被测输入（工作目录=skillfactory 根，runner 与参照均给显式路径）：
  python v4/assets/hot-templates/eval/runner.py     <空目录> v4/assets/hot-templates/oracle/out     → exit 1
  python v4/tools/content-evaluator/eval/runner.py  <空目录> v4/tools/content-evaluator/oracle/out  → exit 1
  python v4/assets/mcp-office-pack/eval/runner.py   <空目录> v4/assets/mcp-office-pack/oracle       → exit 1
  python v4/assets/office-eval-suite/eval/runner.py <空目录> v4/assets/office-eval-suite/oracle     → exit 1
```

---

## 三、与 D31–60 排期和课程主线的对齐说明

依据 `skillfactory/plan/MASTER-PLAN.md`（总体方案 v2.0）§7.1 D31–60 段（:346-352）与 §五课程体系（:267-315）。逐项对齐如下：

**1. 资产量：累计过验收 ≥8（净新增 ≥7）——本批推进 1 格，缺口仍大。** hot-templates accepted 使「过评测门（确定性+盲评）」资产累计达 **2**（meeting-minutes + hot-templates），D60 目标 8，D1 时点净新增 1，进度在轨但剩余 6 个的产能压力未减。本批另 3 件为 tooling 基建，按总体方案 §6「与 skill 资产同等对待」入库，但**不计入**「过五门验收资产数」KPI（无盲评臂）。D31–60 的「蒸馏 2 个（S2）」本批为 **0**，未推进。

**2. 课程主线：hot-templates 直接服务课程一/三的内容脚本环节。** 课程一（日更短视频量产）与课程三（门店短视频工厂）的核心交付是短视频内容，hot-templates 的 video 分镜表（6 镜 45 秒冻结）+ dy 口播稿正是脚本生产件；xhs/wx 两模板覆盖图文与长文引流层。诚实标注：总体方案 §5.1 所列课程一「免费单点三件」是打字幕/我的声音/素材入库，hot-templates **不是**那三件，而是脚本环节的增强件与候选免费引流件（上架前须先过第四节 P0-1 五门复检）。它同时是课程五（技能封装工坊）的第二个正例教材：「确定性红线 + 对照盲评」画像从孤例（meeting-minutes）变成可复制模式（Δ=6.1 全胜）。

**3. content-evaluator = 总体方案 §6.4「oracle 配方库」的内容域配方落地。** 文案合规/结构的确定性判定器（44 极限词 + 平台阈值 + 结构计数），与 hot-templates 同域互补（一个生成、一个评测），为内容域后续资产提供现成确定性门——同域第二个 skill 的评测成本从「天」降到「小时」（§2.5 复用杠杆 3）。

**4. mcp-office-pack = §6.5「MCP server 集」的办公场景落地 + 治理方案 §4.6 MCP 通道的配套件。** 六格矩阵（文件/Excel/Word/PPT/浏览器/搜索）对应课程二（Word 成品）与课程四（Excel/PPT）产线的连接层节点；配置片段 + 启动前校验（自带 validate.py）正是治理方案 §4.6「mcpServers 配置片段 + 启动前校验」条款的实物件；阶段 2/3 托管底座的连接层由此起步。上游风险已实录（word/powerpoint 上游归档但 PyPI 可装，spec §10），为阶段 2 进入条件③「fork 自维护清单」提供了现成输入。

**5. office-eval-suite = §6.1「黄金评测集」的办公域扩容，服务 D31–60 bench 主线。** D31–60 要求「第二模型进矩阵、效率门数据、首轮全量回归、增益榜 v0」——本套件 50 题 × 8 域 × 三档难度正是办公域首轮回归的现成题库；`semantic` 判分接口预留给裁判模型，`contains/regex` 可机判部分可直接跑；v1 兼容导出（25 题，runner 第 4 项检查对每次导出实证过 v1 校验器）保证与 v3 时代基准的可比性。

**6. 未被本批推进的 D31–60 项（如实列出）**：效率门（token/耗时）数据——本批 skill 同样未测；治理 consent/观测 shim v0——不在本批范围；上架在架件次 ≥10——四件均未上架（hot-templates 复检前禁分发，三个 tooling 件的分发形态待第四节 P1-4 台账登记后另议）；课程二试点开卖与课程一计时试跑——依赖项不在本批。

---

## 四、返工清单与下一步

### 4.1 返工清单

| # | 级别 | 事项 | 证据（本会话实查） | 修法 |
|---|---|---|---|---|
| 1 | **P0** | hot-templates 五门复检四件套：① 效率门（token/耗时比率 ≤2.0）从未测量；② 每臂重复 2 次 < SPEC §3.3 第 3 条「每条 ab_task 每臂 ≥3 次」；③ `eval/results/benchmark.json` + 五门验收单未落盘；④ MANIFEST.json 未生成 | 本会话 `find v4 -name benchmark.json -o -name MANIFEST.json -o -name protocol.md` → 0 命中；`tests/ab/` 每臂仅 rep1/rep2；盲评 20 次运行无 token/耗时记录 | 第二轮盲评补至每臂 ≥3 并同步记录 token/耗时；落盘验收单；发布时生成逐文件 sha256 MANIFEST。**复检通过前不进分发、不上架**（总体方案 §4.6 第 7 条负增益自我管理纪律） |
| 2 | **P0** | golden schema 代差 + 三类用例配比缺口（首批全批欠账在 v4 原样延续） | 本会话实读 `eval/golden.json`：eval_inputs 8 条仍为 `case/input/output` 旧键（SPEC §3.2 要求 `id/type/prompt/checks`）；ab_tasks 5 条全部为「应生成」型正向任务，**无近邻负例、无 adversarial（相关但误导）用例**——四平台模板对「不该触发的场景」与「误导指令」的行为从未被测过 | golden 迁移到 §3.2 schema 并补三类用例（正例 ≥4、近邻负例 ≥正例 50%、adversarial ≥1）；修订须升版归档，禁止为通过而改断言（contract §4 冻结规则已就位） |
| 3 | **P0** | 验收记录落盘制度化缺失：重生成 2 轮的逐轮现场无归档（第 1 轮失败原因不可复溯）；本会话四个 runner 的绿检输出也未落盘进资产 | 盘内仅有终版产物与 ab_summary；hot-templates `.mimosa/` 为安全扫描钩子产物，与重生成轮次无关 | 按 SPEC §1.1/§4 补 `eval/results/`（成功与失败现场同等归档）；monthly-report-ppt「失败不可复核」教训的制度化在 v4 仍未执行 |
| 4 | P1 | 三个 tooling 件无 CHANGELOG、未登记基建台账 | `ls v4/{assets,tools}/*/CHANGELOG.md` 仅 hot-templates 命中；content-evaluator 以 `oracle/README.md` 承担用法文档系 contract §1 明文约定（可豁免），mcp-office-pack / office-eval-suite 无版本台账 | 按总体方案 §6「基建资产与 skill 同等带版本与台账」补 CHANGELOG 与基建清单登记 |
| 5 | P1 | hot-templates `metadata.route-to` 为空串 | 本会话读取 front-matter：`route-to: ""`；description 边界段写「长文成稿转交对应写作类 skill」但厂内尚无写作类 skill 可指名 | 写作类 skill 入库后回填指名路由（SPEC §1.3 边界段互相互相导流的要求） |
| 6 | P2 | mcp-office-pack google-workspace 冷拉包超时教训未进交付 SOP | spec 附录 A-3：`--timeout 300` 首轮 9/10 → 600s 复跑 10/10 | 将「workspace-mcp 实跑超时给足 600s」写入上架/交付 SOP，避免课程产线现场复演 |

### 4.2 下一步（按 D31–60 排期倒排）

1. **hot-templates 五门复检**（P0-1/2/3 打包做）：补重复数与效率门 → 二轮盲评 → benchmark.json + 验收单落盘 → MANIFEST → 达成后作为第二个可分发资产进入 build.py 渠道变体与上架管线。
2. **office-eval-suite 接入 bench**：以 50 题套件跑办公域首轮回归（含第二模型），产出增益榜 v0 的办公域首批数据点——这是 D31–60 bench 主线上成本最低的一步（套件与 runner 已全绿就绪）。
3. **mcp-office-pack 进课程二/四产线演示**：用自带 validate.py 做「配置包健康检查」环节演示；同步把六个上游 server 的维护状态核对纳入 fork 自维护清单。
4. **内容域第二资产排产**：以 content-evaluator 为确定性门、hot-templates 为对照模板，排「扩写/成文」类 skill（同时解 P1-5 的 route-to 回填）。
5. **照旧推进**（不在本批、不因本批改变）：三拒资产闭环（monthly-report-ppt 复裁 / ppt-method-router 二次盲评 / paper-to-skill 归因）、build.py 两变体、WorkBuddy/Qoder 首批上架、课程二产线缺件——均按总体方案 §7.1 D0–30/D31–60 原计划。

---

## 附录 A：本会话核验记录（可复跑，2026-09-30）

```text
工作目录：D:\workspace\zcode研究\skillfactory

A1 绿检（确定性评测复跑，4 项全过，stderr 均 0 字节；每条命令标注实际执行目录）：
   # 工作目录 = D:\workspace\zcode研究\skillfactory（被测/参照均为显式相对路径，不受 CWD 影响）：
   python v4/assets/hot-templates/eval/runner.py v4/assets/hot-templates/package/out v4/assets/hot-templates/oracle/out
     → exit 0，ok=true，{cases:8, checks_total:40, passed:40, failed:0}，
       一致率 8×1.0（阈值 consistency_threshold:0.9）
   # 工作目录 = v4/tools/content-evaluator（零参自校验，缺省相对 runner 脚本定位，CWD 无关）：
   python eval/runner.py
     → exit 0，6/6：good_fixtures_all_pass / bad_xhs_expected_fails /
       bad_wx_expected_fails / score_recompute / report_md_consistency /
       oracle_agreement_90pct 全 pass
   # 工作目录 = v4/assets/mcp-office-pack（⚠ 被测/参照为相对参数 `package oracle`，按 CWD 解析：
   #   在 skillfactory 根原样执行会 exit 1「被测包根不在盘」，本会话实测；须在资产目录下执行）：
   python eval/runner.py package oracle
     → exit 0，5/5：package_validate_all_green / config_json_valid /
       scenario_coverage_matrix / docs_one_to_one / coverage_equivalent_to_reference 全 pass
   # 工作目录 = v4/assets/office-eval-suite（⚠ 同上 CWD 敏感，根目录执行实测 exit 1）：
   python eval/runner.py package oracle
     → exit 0，4/4：validate_all_green（被测校验器 9/9，items=50，checks_in_suite=230）、
       ratio_difficulty_per_spec（八域精确配比+三档难度一致）、
       no_dup_vs_reference（完全相同题 0 ≤ 10，self_eval=false，max 相似度 0.352）、
       legacy_export_v1_green（导出 25 题，v1 校验器 7/7）

A1' oracle 自检（3 项）：
   # 工作目录 = D:\workspace\zcode研究\skillfactory：
   python v4/assets/hot-templates/oracle/verify.py            → exit 0，74 PASS / 0 fail
   # 工作目录 = v4/assets/mcp-office-pack：
   python oracle/validate.py                                  → exit 0，7/7 all_green
   # 工作目录 = v4/assets/office-eval-suite：
   python oracle/validate.py --suite oracle/suite.json        → exit 0，ALL GREEN ✓（9/9，50 题/230 条）

A2 红检（空目录作被测，4 项全部 exit 1）：
   四个 eval/runner.py <空目录> <各自 oracle 参照> → exit=1 ×4

A3 盲评数字对账（实读 v4/assets/hot-templates/tests/ab_summary.json，与任务下发口径逐项一致）：
   tasks=5，baselineMean=3.9 → treatmentMean=10，delta=6.1，winRate=1，reverseTasks=0，accepted=true
   逐任务 base:treat = ab-001 3:10 / ab-002 3:10 / ab-003 3:10 / ab-004 2:10 / ab-005 8.5:10（多数全部 treatment）
   盘内 tests/ab/ 目录清点：5 任务 × 2 臂 × 2 重复 = 20 个 rep 目录（逐一 ls 确认）

A4 形式门抽测：
   v4/assets/hot-templates/package/SKILL.md front-matter 实读：
     六字段齐（name/version/license/description/permissions [shell]/metadata）；
     description 含 6 个触发短语 + 边界段；metadata.route-to 为空串（P1-5）
   正文测量：97 行 / 4,338 字符（≤500 行 / ≤10,000 字符）

A5 落盘件缺失核查：
   find v4 -name benchmark.json -o -name MANIFEST.json -o -name protocol.md → 0 命中
   find v4 -maxdepth 4 -type d -name results → 0 命中
   ls v4/assets/*/CHANGELOG.md v4/tools/*/CHANGELOG.md → 仅 hot-templates 命中

A6 其他实读：
   mcp-office-pack 三份 samples.json（oracle 预置 / oracle 复跑 / package）逐份解析：
     total=10 passed=10，statuses 全为 'pass' ×3 份
   四资产 spec.md / contract.md / CHANGELOG.md / golden.json 关键节全文读取
   standard/SKILL-SPEC-v0.1.md:255-276（§3.3 盲评协议 + §4 五门）实读
   plan/MASTER-PLAN.md（总体方案 v2.0）§7.1 D31-60 段 :346-352、§五课程体系实读

A7 v1.1 修订轮核验（2026-09-30，按独立审读意见逐条复测）：
   OUT.md 在位清点：20 个 rep 目录逐一实测 → 19/20 在位，唯一缺件 = tests/ab/ab-001/arm-a/rep2；
   cmp ab-001/arm-a/rep1/骨架.md ab-001/arm-a/rep2/骨架.md         → identical
   cmp ab-001/arm-a/rep1/structure.json ab-001/arm-a/rep2/structure.json → identical
     （确定性引擎同输入同产物，缺 OUT.md 的 rep 仍可由 rubric 交付物机械核验）
   wc -l 四份 spec.md → hot-templates 154 / content-evaluator 173 / mcp-office-pack 227 /
     office-eval-suite 127（v1.0 报告误写 155/173/228/156，三处已按实测勘误）
   CWD 敏感性实测：`eval/runner.py package oracle` 两条命令在 skillfactory 根执行 → exit 1 ×2；
     在各自资产目录执行 → exit 0 ×2（5/5 与 4/4，与 A1 数字一致）
```

**未复跑项（如实声明）**：双臂盲评 20 次运行未重跑（Δ/胜率为任务下发数字，已与盘内 `tests/ab_summary.json` 逐项对账一致）；盲评 judge 会话记录不可访问——ab-001/arm-a/rep2 缺 OUT.md 的当轮裁判处理（记录缺件、改以 rubric 交付物核验给分）为审读意见转述，本会话仅独立实测了缺件事实与 rep1/rep2 产物逐字节一致；mcp-office-pack 的真实 MCP 协议握手（`run_samples.py` 需拉起 10 个 server 进程，本会话引 spec 附录 A 与三份落盘 samples.json，未重跑网络握手）；office-eval-suite 的 8 个定向红灯夹具与 hot-templates spec §10 的 T1–T9 探针（两者均为固化时实跑记录，本会话以各自 oracle 全量自检 + 空目录红检替代）；重生成第 1 轮的失败现场（盘内无归档，不可复溯）。

---

*（本报告数字口径：第二节各表「任务下发口径」字段以 assetInventory 为唯一权威；确定性评测、红检、oracle 自检、形式门测量均为本会话实跑，命令见附录 A。盲评每臂 2 次重复低于 SPEC §3.3 每臂 ≥3，全部盲评数字按「第二轮前的首轮信号」采信。）*

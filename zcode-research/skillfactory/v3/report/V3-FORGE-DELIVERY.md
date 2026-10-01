# V3 Forge 交付报告 — 四件资产（办公模板 skill + 护栏 hooks + 体检流水线 + prompt 回归黄金集）

| 项 | 值 |
|---|---|
| 文件 | `skillfactory/v3/report/V3-FORGE-DELIVERY.md` |
| 日期 | 2026-09-30 |
| 数字口径 | 四资产的 `oracleOk / evalOk / regenPassed / regenRounds / ab` 状态以**任务下发材料**为唯一权威口径；盲评数字另经盘内 `v3/assets/office-templates/tests/ab_summary.json` 实读对账一致（Δ=1.2、胜率 1.0、反向 0、accepted=true，逐项吻合）；确定性评测为本会话**实际复跑**结果（命令与输出见附录 A） |
| 评测协议依据 | `skillfactory/standard/SKILL-SPEC-v0.1.md`（五门验收线 §4:266-276、格式规范 §1、黄金集 schema §3.2）+ `skillfactory/v2/standard/EVAL-SPEC-v0.2.md`（本批盲评适用协议：任务 ≥5 §3.1、每臂 n≥2 §3.2、任务级多数判定 §3.3、复合接受线 §3.6、稳态披露 §3.7、两级晋级与真实复验门 §5.3、六门一览 §7.1、benchmark.json schema §8.1；该文件 §0.2 明示其取代 SKILL-SPEC §3.3/§4 门 2） |
| 空白格口径 | `skillfactory/v2/CATALOG.md:588-610` 覆盖度矩阵（14 个 ○ 机会格，:605 注记）与 `:614-630` 机会点清单（gaps 15 条） |
| 本会话实际执行的核验 | 四资产确定性评测复跑全部 exit 0（附录 A1–A5）；office-templates `oracle/verify.py` 复跑发现 oracle/out 混入 5 个 `.mimosa` 运行时目录致 5 个非产物 FAIL（8 个产物单元全 PASS，见 4.1 节与返工清单）；三份 SKILL.md/README 的 front-matter 逐份实查（office-templates 0/6、office-guard-hooks 2/6 字段）；CHANGELOG/MANIFEST/protocol.md/eval/results 全 v3 检索零命中 |

---

## 一、执行摘要

**本批产出四件资产**（任务下发材料，目录均经本会话实查在位）：

| # | 资产 | 形态 | 目录 | 状态（任务下发口径） |
|---|---|---|---|---|
| 1 | office-templates — 中文办公模板技能（周报/请示函/会议通知/工作总结，python-docx 模板引擎+填充规范） | skill | `skillfactory/v3/assets/office-templates` | oracle ✓ / eval ✓ / 重生成 1 轮过 / **盲评 accepted=true** |
| 2 | office-guard-hooks — 办公护栏 hook 包（产物落盘校验 fail-closed + CN 手机号/身份证 PII 拦截，hooks.json 配置即资产） | tooling（hook） | `skillfactory/v3/assets/office-guard-hooks` | oracle ✓ / eval ✓ / 重生成 1 轮过 |
| 3 | healthcheck-pipeline — skill 体检流水线（对任意 skill 包目录跑结构校验并产出体检报告） | tooling（软件系统） | `skillfactory/v3/tools/healthcheck` | oracle ✓ / eval ✓ / 重生成 1 轮过 |
| 4 | prompt-regression — 中文办公 prompt 回归黄金集（25 题带可判定检查要点 + 校验器） | tooling（评测集） | `skillfactory/v3/assets/prompt-regression` | oracle ✓ / eval ✓ / 重生成 1 轮过 |

**v0.2 盲评结果（仅 skill 类 office-templates 参评）**：5 任务 × 2 臂 × 每臂 2 次独立运行，任务级多数判定后 **baseline 均分 7.7 → treatment 均分 8.9，Δ=1.2（≥1.0 ✓），任务级胜率 1.0（≥0.6 ✓），反向任务 0（≤1 ✓）**，v0.2 复合线三条件全过、判定 accepted（`tests/ab_summary.json` 实读；与任务下发数字逐项一致）。这是 EVAL-SPEC v0.2 生效后**首个按新协议完成的盲评**（任务数 5 达 §3.1 下限、n=2 达 §3.2、判定口径为 §3.3 任务级多数），但属**单轮结果**——按 §3.7-1，对外引用单点 Δ 须两轮独立评测方向一致，当前须标注 `single_round_signal` 并披露区间口径（见返工清单 R3）。

**哪些达到可分发线——如实结论：评测门口径 4/4 过，六门口径 0/4 达线。**

- **已达标（本会话复跑实证）**：四资产确定性门全过（runner 逐个复跑 exit 0，附录 A）；office-templates 盲评复合线数值达标；工具类三件的红绿自检/阴性对照在位（guard-hooks 红绿基线条款、healthcheck broken/no-eval 双阴性样本、prompt-regression 4 个定向红例）。
- **未达标（全批共性欠账）**：效率门未测（全 v3 无 token/耗时记录，检索零命中）；形式门欠账（两个 SKILL.md front-matter 分别为 0/6 与 2/6 必填字段，无 CHANGELOG.md/MANIFEST.json/eval/protocol.md/eval/results/）；真实复验门未做（EVAL-SPEC §5.3 第二级）。按 SKILL-SPEC §4「五门全过方可入库分发」与 EVAL-SPEC §7.1 六门口径，**四件资产当前均不可进入分发管线**；评测门证据链已齐，补齐落盘件与效率/复验数据是进入分发前的最后一段路。

---

## 二、逐资产明细

### 2.1 office-templates（skill · 中文办公模板技能）

| 项 | 结果 | 证据 |
|---|---|---|
| oracle / spec | ✓ 参照实现 + 黄金输入 + 参照产物三件齐；spec.md V1–V8 版式 / F1–F7 字段语义 / S1–S4 台账 / C1–C3 CLI / D1 确定性逐条可判定，固化时实测记录在附录 A（`spec.md:172-183`） | `assets/office-templates/spec.md`、`oracle/out/`（8 单元） |
| 确定性评测（本会话复跑） | **✓ exit 0，ok=true，字段填充一致率 100%（66/66，阈值 90%）**，8 单元 × 6 类检查全过 | `python eval/runner.py package/out oracle/out`（附录 A1） |
| oracle 复核（本会话复跑） | 8 个产物单元全 PASS；`verify.py` 整体 exit 1 系 `oracle/out` 混入 5 个 `.mimosa` 运行时目录被误计（非产物单元、非回归，见 R5） | `python oracle/verify.py oracle/out`（附录 A2） |
| 重生成 | 任务下发口径 regenPassed=true / regenRounds=1；被测 package 即按 spec/contract 独立实现的再生成物，对同一版 golden 全量回归一次通过（含 4 条负路径 exit 2、双跑 D1 确定性，ab 各 run 报告实测） | golden=8 eval_inputs + 5 ab_tasks（`eval/golden.json` 实读）；20 份 run 报告 `tests/ab/*/arm-*/rep*/OUT.md` 实查在位 |
| **盲评（v0.2）** | **baseline 7.7 → treatment 8.9，Δ=1.2 ✓；任务级胜率 1.0（5/5，ab1 7:9 / ab2 8:9 / ab3 7.5:9 / ab4 8.5:8.5 多数判胜 / ab5 7.5:9）✓；反向任务 0 ✓；accepted=true** | `tests/ab_summary.json` 实读（数字与任务下发一致） |
| 盲评执行结构 | 5 任务 × 2 臂（treatment=被测 package / baseline=oracle 参照）× 每臂 2 次 = 20 份独立 run 报告；匿名盲评工作区 6 个在位（ab1→`_tmp_judge_ab1_rep1/2`、ab2–ab5→`_tmp_ab2..5_judge/`），两臂产物以匿名副本入评，命名随任务而异（ab2–ab4 为 `a/`、`b/`，ab5 为 `p_run1/2`、`o_run1/2`，ab1 为 `regen/` 与 `det_pkg*/det_orc*`；ab5 rep2 另有 `oc/` 复评副本） | 本会话 find/ls 实查 |
| 已知分歧（如实记录） | ab1 两臂对三处成文结构结论相左：arm-a 判「冻结契约口径下可替代」（D2–D4 属 contract 明示自由区，被测与 `package/references/` 逐字一致）、arm-b 判「不能无条件整体替代」（周报信息行无部门字段、请示函无套语、会议通知编号组织不同）。冻结口径（spec §10 只比字段填充）下 runner 100% 过；当前 package 信息行仍为 `填报人：王小明　　周期：…`（references 公式口径，本会话解包实读） | `tests/ab/ab1-.../arm-a/rep1/OUT.md` §0/§5、`arm-b/rep1/OUT.md` §6、本会话 docx 解包 |
| 判定 | **评测门口径接受（accepted=true）；六门口径未达分发线**（效率门未测、形式门 front-matter 0/6、真实复验未做） | 本文 §一、§四 |

### 2.2 office-guard-hooks（tooling · 办公护栏 hook 包）

| 项 | 结果 | 证据 |
|---|---|---|
| oracle / spec | ✓ spec R1.1–R4.2 逐条可判定，fail-closed（validate_output：结构坏 → exit 2 阻断）与 fail-open（pii_guard：不可扫对象放行）双 hook 职责切分明确；hooks.json 绑定 `PostToolUse × Write|Edit`，事件白名单取自 Claude Code 官方文档口径（`spec.md:103`） | `assets/office-guard-hooks/spec.md` |
| 确定性评测（本会话复跑） | **✓ exit 0，7/7 检查全过**：root-resolution / reference-baseline / structure / fixtures-generated / self-suite（run_tests.py exit 0）/ invalid-json-stdin（4 次非法 stdin 均 exit 2 无 Traceback）/ hooks-json-config | `python skillfactory/v3/assets/office-guard-hooks/eval/runner.py`（附录 A3） |
| 自测套件基线 | oracle 侧 12/12 PASS、package 侧 12/12 PASS（6 fixtures：good.txt / pii.txt / clean.docx / bad_empty.txt / bad_encoding.txt / corrupt.docx；PII 命中脱敏输出 `138****5678`、`1101**********4258` 不回显完整 PII） | `oracle/out/tests.json`、`package/out/tests.json` 实读 |
| 重生成 | 任务下发口径 regenPassed=true / regenRounds=1（package 为独立再生成物，与 oracle 同判 12/12） | 同上 |
| 盲评 | 未做（tooling 类本批未安排盲评；hook 形态按 EVAL-SPEC §6.1 属文本说明书型，如需增益结论须补双臂盲评） | 任务下发材料 ab=null |
| 判定 | **评测门口径过（确定性+红绿）；六门口径未达分发线**（front-matter 仅 name+description 2/6，无 CHANGELOG/MANIFEST，效率门未测） | 本文 §四 |

### 2.3 healthcheck-pipeline（tooling · skill 体检流水线）

| 项 | 结果 | 证据 |
|---|---|---|
| oracle / spec | ✓ R1–R12 逐条可判定：恰 5 检查项（skill_md_exists → front_matter_fields → eval_present → eval_smoke → scripts_syntax）名称与顺序冻结，评级 A/B/C=失败数 0/1/≥2（skip 不计），`--target` 非目录 exit 2 不落产物，除 generated_at 外确定性 | `tools/healthcheck/spec.md`、`contract.md` |
| 确定性评测（本会话复跑） | **✓ exit 0，5/5 全过**：meeting_minutes_all_pass / broken_skill_expected_fails / no_eval_eval_present_fail / rating_consistency（三样本 A/C/B 与失败数 0/3/1 一致）/ oracle_agreement_90pct（**15/15 一致，100%**） | `python eval/runner.py`（零参自校验，附录 A4） |
| 三样本基线 | meeting-minutes-skill → **A**（5/5 过，即 v1 首批过线资产被新工具复检为全绿）；broken-skill → **C**（front_matter_fields/eval_present/scripts_syntax 三红）；no-eval → **B**（仅 eval_present 红） | `oracle/out/*/report.json` 与 `package/out/*/report.json` 实读，两侧一致 |
| 重生成 | 任务下发口径 regenPassed=true / regenRounds=1（package/healthcheck.py 独立实现与 oracle 产物全对齐） | package 侧三样本 report.json 与 oracle 基线一致（实读） |
| 自指评测契合度 | 契合 EVAL-SPEC §6.4-2 软件系统型口径的下限形态：3 样本 + 2 阴性 fixtures = 5 个典型对象、回归全绿；但 §6.4-1 评测集型要求的 ≥30 条对拍不适用亦未做（本资产是工具非题集） | spec §2.1/§2.2、runner 5 项检查 |
| 判定 | **评测门口径过；六门口径未达分发线**（README 无 front-matter 之责——它不是 skill 包，但作为可分发工具缺 MANIFEST 与版本化发布物；效率与真实复验未覆盖） | 本文 §四 |

### 2.4 prompt-regression（tooling · 中文办公 prompt 回归黄金集）

| 项 | 结果 | 证据 |
|---|---|---|
| oracle / spec | ✓ R1–R6 数据规则 + V1–V4 校验器行为 + E1–E4 评测器行为逐条可判定；黄金集冻结「只增不改」条款在位（spec §6） | `assets/prompt-regression/spec.md` |
| 黄金集本体（实读） | **25 题 / 125 条 check（每题恰 5 条）**，六域配比精确达标：doc-writing 6 / table-data 5 / meeting-minutes 3 / ppt-outline 3 / email-comm 4 / process-spec 4；类型分布 regex 80 / contains 8 / semantic 37——**88/125（70.4%）为程序化可判**，符合 EVAL-SPEC §5.1 L3-2「程序化判分优先（应当 ≥50%）」 | `oracle/golden.json`、`oracle/out/validate.json` 实读（Counter 统计） |
| 确定性评测（本会话复跑，两条命令） | **✓ 自评（oracle vs oracle）exit 0，4/4 全过**（validate_all_green / domain_coverage_per_spec / no_duplicate_vs_reference 自评豁免 self_eval=true / sampled_checks_decidable 固定种子抽样）；**✓ package 独立再生成物 vs oracle 亦 exit 0，4/4 全过** | 附录 A5 两条命令 |
| 红检（定向负例，固化时实测+报告在盘） | 4 份红例报告在位：空目录全红、缺 1 题精确判红、oracle 异地逐字节拷贝判红（25>5 不豁免）、抽中题 regex 换 `.*` 恒真判红 | `eval/out/runner-red-{empty,missing-q,copy,trivial-regex}.json` 实查 |
| 重生成 | 任务下发口径 regenPassed=true / regenRounds=1（package 版 golden version=1.0.0-package，25 题六域同构，过同一 runner） | 本会话 package 侧复跑为证 |
| 质量基线（固化时人工复核） | 抽样 3 题（seed=20260930 → ppt-001/meeting-002/email-004）15/15 条 check 实际可判；已记录 1 处弱点（meeting-002 `中旬?` 使 regex 实际只需「10月」命中，记录不改——eval 只增不删） | spec §5 |
| 判定 | **评测门口径过；六门口径未达分发线**；另按 EVAL-SPEC §6.4-1 评测集型资产的对拍法要求（≥30 条与人工金标准对拍、一致率 ≥95%）**尚未执行**（现仅 3 题抽样人工复核）——自用可、对外分发前须补 | 本文 §四 R7 |

---

## 三、这批资产如何回填 CATALOG 的 14 个空白格

CATALOG v2 覆盖度矩阵共 **14 个 ○ 主类目级机会格**（`v2/CATALOG.md:590-605`），对应 gaps #1–11、#13–15（#12 为细类目口径不计格）。此前四轮合并轮净增 151 条（46+40+30+35，唯一资产总数 132→283，`CATALOG.md:7`）**无一格被填充**（:607-610、:671）。本批四件资产的回填对应关系：

| 空白格 | gap #（原文要点，`:614-630`） | 回填资产 | 命中方式 | 落格建议 |
|---|---|---|---|---|
| **B1×hook** | #8 缺办公场景护栏 hook（邮件外发确认、文档覆盖保护） | office-guard-hooks | **直接命中**：成品护栏 hook 包（非教程/索引形态）——产物落盘结构校验（文档损坏/空文件/编码坏 → 阻断，即「文档覆盖保护」近邻）+ PII 外泄拦截 | ○→●（hook 形态、B1 域，无争议） |
| **A3×评测集** | #2 prompt 资产无回归测试集，发布前自动验证缺失 | prompt-regression | **直接命中**：prompt 资产的回归黄金集 + `validate.py` 七项自动校验器，正是「发布前自动验证环节」本体 | ○→●（评测集形态、A3 域） |
| **B1×评测集** | #7 缺中文办公 agent 评测集（借 SpreadsheetBench 程序化判分思路自研） | prompt-regression（同一资产双格命中） | **直接命中**：六域中文办公 25 题 / 125 checks，88 条程序化可判（70.4%，超 §5.1 L3-2 的 50% 建议线） | ○→●（同一资产按双格各计 1 条，注记双命中） |
| **A2×评测集** | #1 缺 skill/plugin 上架前质量门禁成品工具——原文点名的产品形态即「**资产体检流水线**」（「质量验收维度仍空白」） | healthcheck-pipeline | **语义命中**：本资产就是 gap 命名的「资产体检流水线」首块（5 检查项 + A/B/C 评级 + report.json/REPORT.md 双产物） | 需分类学决策：资产形态为软件系统工具（评测**装置**），而矩阵中 A2×软件系统格现记「—」。建议按「评测装置」语义填 A2×评测集格并在 gaps #1 注记，或开 TAXONOMY 细类讨论（返工清单 R9） |
| **B1×工作流模板** | #6 缺中文办公自动化工作流模板包（周报/纪要/发票），中文场景自研优先 | office-templates | **语义命中（形态升级）**：周报/请示函/会议通知/工作总结四类中文办公模板包，且交付的是「模板+引擎+填充规范」的可判定 skill 生成管线，强于静态工作流模板 | 按形态落 B1×skill（该格已 ●1，本资产使其强化）；gaps #6 注记「已由 skill 形态升级填充」，格本身可维持 ○ 或由 TAXONOMY 裁定 |

**回填结果小结**：14 个空白格中 **3 格直接命中**（B1×hook、A3×评测集、B1×评测集）、**2 格语义命中待落格决策**（A2×评测集、B1×工作流模板）、**9 格未动**：A4×工作流模板(#3)、A7×skill(#4)、A8×评测集(#5)、B2×评测集(#9)、B2×MCP(#10)、B2×prompt模板(#11)、B3×评测集(#13)、B4×评测集(#14)、B4×MCP(#15——名义上已由 github-mcp-server 填充但按 TAXONOMY §二.1 落格 A4.4，:630）。

两点如实说明：

1. **gap #4（A7×skill 治理 hooks 护栏包）未填充**：office-guard-hooks 证明了「成品护栏包」形态在本仓可复制（oracle→spec/contract→package→eval 全链 + 12/12 自测），但其域是办公（B1）非治理（A7），形态是 hook 非 skill——该格维持 ○，本资产可作为下一件「治理向通用护栏包」的工程模板。
2. **回填的是「自产填充物」**：CATALOG v2 收录的是外部生态资产，本批四件是按 gaps 清单自研的填充物；回填动作 = 在 gaps 对应条目注记 + 覆盖度矩阵改格（建议下轮统一重算时一并执行，此前四轮的格内条数本就是「待统一重算」口径，:607-610）。

---

## 四、返工清单与下一步

### 4.1 返工清单（按优先级）

**P0——进分发管线前必须补齐：**

| # | 项 | 现状（本会话实证） | 条款依据 |
|---|---|---|---|
| R1 | **形式门欠账：front-matter** | office-templates `package/SKILL.md` 无 YAML front-matter（6 必填字段 0/6，实查）；office-guard-hooks `package/SKILL.md` 仅 name+description（2/6） | SKILL-SPEC §1.2（:57-76）、§4 门 4 |
| R2 | **形式门欠账：落盘件** | 全 v3 检索 CHANGELOG / MANIFEST / protocol.md / eval/results/ 均零命中（find 实查）；golden.json 亦无版本字段（SKILL-SPEC §3.2 schema 要求 `version`） | SKILL-SPEC §1.1（:33-55）、§3.2 规则 4 |
| R3 | **盲评稳态**：office-templates 补第二轮独立盲评 | 现仅单轮（Δ=1.2）；单点 Δ 对外引用须两轮同号且均 ≥1.0，当前须标 `single_round_signal` | EVAL-SPEC §3.7-1（:188-192）、§8.2-2 |
| R4 | **效率门数据**：逐 run token/耗时落盘 | 全批未测（检索零命中）；效率门 token/耗时比率 ≤2.0 为一票否决门，未测即未过 | SKILL-SPEC §4 门 3、EVAL-SPEC §3.8-3 |
| R5 | **基线卫生**：office-templates `oracle/out/` 混入 5 个 `.mimosa` 运行时目录（hook-state/hook-status/reports/history/finding-ledger），`oracle/verify.py` 复跑 5 个非产物 FAIL、exit 1（8 个产物单元本身全 PASS）。清理运行时目录，并让 verify.py 忽略非产物目录防复发 | 本会话 `python oracle/verify.py oracle/out` 实跑复现（附录 A2） | spec 附录 A-1 口径（固化时 PASS=8 FAIL=0） |
| R6 | **benchmark.json 落盘**：四资产均未按 EVAL-SPEC §8.1 schema 落盘评测记录；ab_summary.json 亦无逐重复分数——ab4 两臂均分同为 8.5 却判 treatment 多数胜，其逐对依据在资产目录内不可复读 | EVAL-SPEC §8.1（:334-353）、§8.2-4 |
| R7 | **裁判一致性结构化落盘**：本次有匿名复评工作区痕迹（`_tmp_ab5_judge/rep2/oc/`）但无 judge_consistency 结构化记录 | EVAL-SPEC §3.4（:163-169） |

**P1——分发后第一迭代：**

| # | 项 | 说明 |
|---|---|---|
| R8 | 真实复验门（全批）：按 EVAL-SPEC §5.3 补 ≥3 条真实任务回退门，达成 `real-verified` 双状态；此前对外披露必须双状态并列（`synthetic-passed ✓ / real-verified ✗`） | EVAL-SPEC §5.3（:261-272）、§7.1 门 6 |
| R9 | prompt-regression 对拍法：按 §6.4-1 抽 ≥30 条与人工金标准对拍（现仅 3 题 15 checks 人工复核），一致率 ≥95% 后方可对外分发该题集 | EVAL-SPEC §6.4-1（:301-303） |
| R10 | office-templates 成文结构口径决策：references（信息行无部门、请示函/会议通知无套语）vs oracle（含套语）的分歧在两臂盲评中结论相左；冻结口径下 runner 全过，但若目标客户要求「与政务/国企公文惯例逐段对齐」，需改 references 并同步 spec——这是产品决策非工程缺陷 | ab1 arm-a rep1 §5-D5、arm-b rep1 §6 |
| R11 | CATALOG/TAXONOMY 落格：按 §三 建议执行 3+2 格改注与 gaps 注记；A2×软件系统格「—」语义是否为「评测装置」开口，交 TAXONOMY 复核 | CATALOG :588-630 |

### 4.2 下一步（建议顺序）

1. **补落盘件**（R1/R2/R5/R6/R7：front-matter、CHANGELOG、MANIFEST、benchmark.json、清理 .mimosa）——纯工程动作，无评测风险；
2. **第二轮盲评 + 效率记录**（R3/R4）：office-templates 复评走同协议独立轮，全批补 token/耗时；
3. **入库**：五门/六门证据齐后迁入 `skillfactory/assets/`，metadata.quality 按评测结果填写，状态标 `synthetic-passed`；
4. **打包分发准备**：MANIFEST.json 逐文件 sha256 + 安全门（含可执行代码的 scripts/hooks 按治理方案分立安全门）→ 进入 `dist/` 分发管线；
5. **回填 CATALOG**（R11）：与下一轮目录统一重算合并执行。

---

## 附录 A：本会话核验记录（可复跑）

全部命令于 2026-09-30 在本机（windev-01，Windows Server 2022 / Python 3.12.10）实际执行：

**A1 office-templates 确定性评测**（cwd=`skillfactory/v3/assets/office-templates`）：
```
python eval/runner.py package/out oracle/out   → "ok": true, exit 0；8 单元全过；field_fill_agreement_ge_90pct = 100.0%（66/66，阈值 90%）
```

**A2 office-templates oracle 复核**（同上 cwd）：
```
python oracle/verify.py oracle/out   → 8 个产物单元全 PASS；另报 5 个 FAIL 均为 oracle\out\.mimosa\{finding-ledger,history,hook-state,hook-status,reports}（运行时目录误计，非产物）→ 汇总 PASS=8 FAIL=5，exit 1
```

**A3 office-guard-hooks 确定性评测**（cwd=`D:\workspace\zcode研究`）：
```
python skillfactory/v3/assets/office-guard-hooks/eval/runner.py   → "ok": true, 7/7 检查全过, exit 0（fixtures-generated / self-suite / invalid-json-stdin / hooks-json-config 等全过）
```

**A4 healthcheck 确定性评测**（cwd=`skillfactory/v3/tools/healthcheck`）：
```
python eval/runner.py   → "ok": true, 5/5 全过, exit 0；oracle_agreement_90pct = 15/15（100.0%）；rating_consistency：A / C / B 三档与失败数 0/3/1 一致
```

**A5 prompt-regression 确定性评测**（cwd=`skillfactory/v3/assets/prompt-regression`）：
```
python eval/runner.py oracle oracle --out eval/out/runner-green-rerun.json   → ALL GREEN 4/4, exit 0（self_eval=true）
python eval/runner.py package oracle --out eval/out/runner-pkg-rerun.json   → ALL GREEN 4/4, exit 0（package 独立再生成物对同一 runner 全过）
```

**A6 实读核验（非运行）**：
- `tests/ab_summary.json`（office-templates；位于 `tests/` 根——`tests/ab/` 下仅 ab1–ab5 五个任务目录）：tasks=5、baselineMean 7.7、treatmentMean 8.9、delta=1.2、winRate=1、reverseTasks=0、accepted=true；taskAggs 逐任务 7:9 / 8:9 / 7.5:9 / 8.5:8.5(多数 treatment) / 7.5:9——与任务下发 ab 数字逐项一致；
- `eval/golden.json`（office-templates）：eval_inputs=8、ab_tasks=5（id 与 ab_summary 一致）；
- 三份 SKILL.md/README front-matter：office-templates 无 front-matter（正文 132 行/5,165 字符）；office-guard-hooks 仅 name+description；healthcheck 为 README（工具形态）；
- `oracle/out/validate.json` 与 `package/out/validate.json`（prompt-regression）：7/7 全绿，25 题/125 checks，六域 6/5/3/3/4/4；`oracle/golden.json` 与 `package/golden.json` 分布一致（version 分别为 1.0 / 1.0.0-package）；
- healthcheck 三样本 report.json（oracle 与 package 两侧）：A(5/5) / C(2过3败) / B(4过1败) 一致；
- 盲评执行结构：`tests/ab/` 下 5 任务 × arm-{a,b} × rep{1,2} 共 20 份 OUT.md 实查在位；匿名评审工作区 6 个实查在位（工作区根 `_tmp_judge_ab1_rep1/2` 与 `_tmp_ab2..5_judge/`），内部为两臂匿名副本，命名随任务而异：ab2–ab4 为 `a/`+`b/`，ab5 为 `p_run1/2`+`o_run1/2`（rep2 另有 `oc/` 复评副本），ab1 为 `regen/`（rep1）与 `det_pkg1/2`+`det_orc1/2`（rep2）。

**A7 本会话未执行（如实声明）**：未重跑五条 AB 任务本身（复用的是固化时产物与汇总）；未测 token/耗时（效率门数据不存在，非本会话省略）；未做第二轮盲评；未做真实任务复验；未运行 skills-ref validate（渠道校验器）；未验证 .mimosa 目录的产生方（按目录内 session 标识与时间戳推断为 agent 运行时 hook 状态产物，mtime 2026-09-30 07:21，晚于资产固化时刻）。

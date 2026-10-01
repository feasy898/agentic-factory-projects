# V6 交付报告：分发准备（打包 + 体检 + 渠道清单）

| 项 | 值 |
|---|---|
| 文件 | `skillfactory/v3/report/V6-DIST-PREP.md` |
| 日期 | 2026-09-30 |
| 任务材料 | 打包结果（distPath + selfCheckNote）、体检结果 ×4、清单（`DISTRIBUTION-CHECKLIST.md`，任务指示"请读取"） |
| 本会话复核 | 详见文末「附：本会话核验记录（可复跑）」——所有关键数字均经实跑或实读对账，未复核的均如实标注出处 |
| 审读修订 | 2026-09-30 二轮，5 条意见逐条落实：①ot 包 `.mimosa` 复发核实（实数 6 枚/43 文件）并二清恢复 37；②§五补 anthropics/skills 授权边界确认（清单:172）；③低危「3 处」改「≥9 处」（逐行核实）；④prompt-regression「体检判不适用」改为「工具本体判 C、不适用系报告解读」；⑤阻断清单改「两包 `.mimosa` 清点删除」 |

---

## 一、执行摘要

**分发就绪度：2 个包就绪，2 个资产暂缓。**

| 资产 | 版本 | 体检 | 盲评 | 结论 |
|---|---|---|---|---|
| meeting-minutes-skill | 1.0.0，MIT | **A**（5/5，`v3/healthchecks/mm-dist/report.json`） | 达标：8 任务 4.75→10.0，Δ+5.25，胜率 100%（8/8），反向 0，accepted=true（`v2/evalbench-v02/meeting-minutes/ab_summary.json`，本会话实读对账；含 2026-09-30 majority 修正字段 `correction`） | **可分发** |
| office-templates-skill | 1.0.0，MIT | **A**（5/5，`v3/healthchecks/ot-dist/report.json`） | 达标（单轮信号）：5 任务 7.7→8.9，Δ+1.20，胜率 100%，反向 0，accepted=true（`v3/assets/office-templates/tests/ab_summary.json`，本会话实读对账）；对外须标 `single_round_signal` | **可分发** |
| office-guard-hooks | — | **C**（2 过/3 败） | — | 暂缓（缺 front-matter 三字段、eval/、scripts/） |
| prompt-regression | — | **C**（2 过/3 败——**工具本体判定**，`prompt-reg/REPORT.md`:5/:18 明言「失败项 ≥2，分发前必须完成整改」；「数据包而非 skill 结构、非质量缺陷」系**报告解读**，见 §三 dogfood 1） | — | 暂缓 |

- **渠道清单要点**：`v3/report/DISTRIBUTION-CHECKLIST.md`（180 行，本会话全文读取）覆盖 A8 全部 37 条 + 任务点名的 anthropics/skills + A4.6 待归类补充 4 条（npm/PyPI/OpenVSX/VSM），共 42 条，每条含目录实录入口、适配形态、门槛与 P0-P3 优先级；发布节奏四波（零门槛铺量 → 注册审核 → 形态改造变现 → 企业级暂缓）；Prime Intellect 与 Coursera 判不适配。
- **发布阻断项 3 个**（须雇主确认后处置，见第五节）：**两包 `.mimosa` 运行时污染**——meeting-minutes 包 19 文件（本会话 `find` 复核 =19）、office-templates 包交付后复发（审读发现：写报告动作自身触发 hook 写入；本会话实数 6 枚/43 文件，已二清恢复 37，机制与规则见 §2.3 与 §三 dogfood 2）；meeting-minutes 包缺 `requirements.txt` 而 `scripts/minutes.py:128` 实际依赖 python-docx；skillfactory 非 git 仓（本会话 `git status` 复核 `fatal: not a git repository`）。
- **本会话全链路复跑**：office-templates 分发包内 8 条生成命令 + 两参数评测（68/68 checks 全 pass、field_fill_agreement 100.0%、exit 0）+ 绿自检 exit 0，全部复现成功，与打包留档及 v3 rep1（`step6_runner_final.json`）一致。

---

## 二、打包与自验证记录

### 2.1 交付物

- **distPath**：`skillfactory/dist/office-templates-skill`（任务材料「打包」）。
- **包结构 37 文件**（交付口径；本会话 `find … -type f | wc -l` 实数 =37，会话期间 hook 瞬时写入的偏差见 §2.3），构成：顶层 5（SKILL.md / README.md / EVALUATION.md / CHANGELOG.md / LICENSE）+ eval/ 2（runner.py + golden.json）+ scripts/ 1（gen_doc.py）+ references/ 4（周报/请示函/会议通知/工作总结）+ requirements.txt 1 + reference/inputs 8 + reference/out 16（8 单元 × 文书.docx+fields.json）。

### 2.2 打包时自验证（引自任务材料「打包」selfCheckNote，打包方当时实跑）

1. **8 条生成命令**全部 exit=0：`python scripts/gen_doc.py --template <四类> --data reference/inputs/<模板>/<case>.json --outdir out/<模板>/<case>`；
2. **两参数评测**（contract §5）：`python eval/runner.py out reference/out` → JSON ok=true、68/68 checks 全 pass、field_fill_agreement 100.0%（66/66，阈值 90%）、exit 0，与 v3 rep1 留档 `step6_runner_final.json` 的 68/68、100% 一致；
3. **绿自检** `python eval/runner.py reference/out reference/out` exit 0；**红检**空目录 exit 1（units_found 失败）；
4. **D1 确定性**：同输入双跑 fields.json 除 outputs 路径外逐字节一致、文书.docx zip 17 条目解压 CRC 全等；8 单元新产物与 reference/out 参照逐字段相等（差异仅 spec S4 明文不比较的 outputs 路径键；docx XML 字节级差异属 contract §6 实现自由区，冻结判据为语义等价）；
5. **路径契约**（spec.md §2 / contract §5）：runner 无参数缺省写死 `<包根>/oracle/out`，包内无 oracle/（实测无参数运行 exit 1）——保持 runner.py/golden.json **逐字节不改**，README「快速开始」写明运行目录约定：包根运行且须显式传 `out reference/out`，golden.json 的 oracle/... 路径对应包内 reference/...；
6. **复制完整性**：gen_doc.py / runner.py / golden.json / SKILL.md 正文 / references×4 / requirements.txt / reference 全部经 cmp 或 md5 对源逐字节一致；SKILL.md 仅按指令新增 front-matter（含 `license: MIT`，体例对齐 meeting-minutes）；CHANGELOG.md 为分发时新写并已在文内注明（v3 资产源无 CHANGELOG）；LICENSE 为 MIT，Copyright (c) 2026 SkillFactory；
7. 包内 EVALUATION.md 载 v0.2 双臂双重复 5 任务结果（逐任务数字引自 `tests/ab_summary.json` taskAggs）与合成数据局限声明。

### 2.3 本会话复跑核验（2026-09-30，命令与结果实录）

在 `skillfactory/dist/office-templates-skill` 内执行：

1. **先证伪后复现**：直接跑 `python eval/runner.py out reference/out` → ok=false、units_found 失败（包内本无 `out/`，交付包只含 reference/，属预期——必须先生成）；
2. **8 条生成**：`for t in 周报 请示函 会议通知 工作总结; do for c in case1 case2; do python scripts/gen_doc.py …; done; done` → 8 条全部成功，输出实录：满字段单元（周报/case1 7/7、请示函/case1 8/8、会议通知/case1 11/11、工作总结/case1 7/7）与缺省单元（周报/case2 必填缺失 ['部门','周期','本周工作内容']、请示函/case2 ['主送机关','请示事项']、会议通知/case2 ['会议名称','会议地点'] + 模板外键 ['备注']、工作总结/case2 ['总结主体','主要成绩']）边界记账正确；
3. **两参数评测** `python eval/runner.py out reference/out` → ok=true，68 项 checks（3 项全局 + 8 单元×8 项 + 1 项一致率）全 pass=true，`field_fill_agreement_ge_90pct` =「100.0%（66/66，阈值 90%）」，**EXIT=0**；
4. **绿自检** `python eval/runner.py reference/out reference/out` → **GREEN_EXIT=0**；
5. 与打包留档（§2.2 之 2）及 v3 rep1 `step6_runner_final.json`（68/68、100%）三方一致。

> 复跑遗留处置（含审读修订）：评测触发 Mimosa hook 向包内写入 `.mimosa/hook-state/…json`，首清后复核 37 文件——**但该「37」只是中间态**：写本报告的 Write 动作自身又触发 PostToolUse/Write hook 写入（审读发现；本会话实读 `.mimosa/hook-status/sess_dwf-…-99fa0cb3e3.json`：`recordedAt=2026-09-30T01:13:55.648Z`、`event=PostToolUse`、`toolName=Write`、`file` 字段=本报告路径），此后会话工具调用在工作目录停留包内期间持续累积至 **6 枚/43 文件**（hook-state×2 + baseline×3 + hook-status×1）。已二清（`rm -rf` 后 `find | wc -l` =37），并把会话工作目录迁出包内以阻断再写入。结论：**「恢复 37 文件」只对清除那一刻成立，最终清点必须作为发布打包的最后一道工序**（规则见 §三 dogfood 2）。

### 2.4 meeting-minutes 包状态（对照）

包位置 `skillfactory/dist/meeting-minutes-skill`；体检 A（见第三节）；盲评数字本会话 `grep` 实读 `v2/evalbench-v02/meeting-minutes/ab_summary.json`：tasks=8、baselineMean=4.75、treatmentMean=10、delta=5.25、winRate=1.0、reverseTasks=0、accepted=true、含 `correction` 字段。**遗留阻断**：`.mimosa` 运行时 19 文件混入（本会话 `find` 复核 =19）、无 requirements.txt（本会话 `Test-Path` =False）而 `scripts/minutes.py:128` `from docx import Document`——发布前处置（见第五节）。

---

## 三、体检流水线试用结果

工具：`skillfactory/v3/tools/healthcheck/package/healthcheck.py`（本会话 `ls` 确认存在）。4 个 target 各产出 `report.json` + `REPORT.md`，本会话逐一读取 report.json 核实评级与通过数：

| target | reportPath | 评级 | 通过/总 | 生 成时间 | 关键项实录（report.json） |
|---|---|---|---|---|---|
| dist/meeting-minutes-skill | `v3/healthchecks/mm-dist/report.json` | **A** | 5/5 | 2026-09-30T08:44:54+0800 | eval_smoke 真实实跑 exit=0（3 case：三节标题/待办表格/计数一致全 pass）；scripts_syntax：gen_docx.py、minutes.py 可编译；SKILL.md 6605 字节 |
| dist/office-templates-skill | `v3/healthchecks/ot-dist/report.json` | **A** | 5/5 | 2026-09-30T08:45:31+0800 | eval_smoke 真实实跑 exit=0（8 期望单元齐全、每单元恰含 文书.docx+fields.json）；scripts_syntax：gen_doc.py 可编译；SKILL.md 10796 字节 |
| v3/assets/office-guard-hooks/package | `v3/healthchecks/guard-hooks/report.json` | **C** | 2/5 | 2026-09-30T08:44:43+0800 | FAIL：front_matter_fields（缺 version/license/permissions，仅有 name/description）、eval_present（缺 eval/）、scripts_syntax（scripts/ 不存在）；PASS：skill_md_exists（6784 字节）、eval_smoke（skip: 缺 eval/，skip 按 spec R8 不计失败） |
| v3/assets/prompt-regression/package | `v3/healthchecks/prompt-reg/report.json` | **C**（工具本体判定；「不适用——数据包而非 skill 结构」为报告解读） | 2/5 | 2026-09-30T08:44:26+0800 | FAIL：front_matter 块缺失（首行非 ---）、eval_present、scripts_syntax；PASS：skill_md_exists（4076 字节）、eval_smoke（skip） |

### dogfood 发现（工具问题与处置）

1. **布局错配（2 例，来自任务材料「体检结果」）**：guard-hooks 实际用 hooks/ + tests/run_tests.py 自测布局，prompt-regression 是数据包（golden.json 25 题 + validate.py，SKILL.md 只是使用说明；其评测器在资产根 eval/runner.py）——两者 3 个 FAIL 均为 healthcheck 冻结约定目录（eval/、scripts/、front-matter）与资产类型的结构错配，**非质量缺陷**。prompt-regression 按资产自身契约健康（validate.py --golden golden.json → 7/7 PASS，任务材料实录）。**处置**：未改工具代码（5 项冻结检查为 spec R2 序列），以如实分级（C / 不适用）+ 整改方向列明方式处置——整改（补 front-matter 三字段 + eval/ + scripts/ 布局）仅在未来要升级为可分发 skill 时才相关。
2. **hook 运行时写入分发包（本会话新发现 + 审读补充证据）**：只要会话工作目录停留在 dist 包内，工具调用（Bash 与 Write 均实测）就会触发 Mimosa hook 向 `<cwd>/.mimosa/` 写运行时文件。实测两例：①ot 包内复跑评测后出现 `hook-state/sess_dwf-…json`；②首清后，**写本报告的 Write 动作（PostToolUse/Write，`file` 字段=本报告路径）又落下一枚 `hook-status/…-99fa0cb3e3.json`**，至审读时已累积 **6 枚/43 文件**（本会话 `find` 实数）。这与 meeting-minutes 包混入 19 个 .mimosa 文件（finding-ledger/hook-state/hook-status/reports/history 五类，见清单 4.1 表）**同源同类别**。**处置与规则**：已全部 `rm -rf` 二清（复核 37 文件）；规则固化为——**任何在包内跑过命令/写过文件的包，发布前最后一道工序必须清点删除 `.mimosa`**（清单 4.2 第 1 条已含删除动作，本报告补充成因与「最后一道工序」时点要求，并同步更新 §一/§五/§六 的处置清单）。
3. **路径约定错配（打包方发现，引自任务材料「打包」）**：runner 无参数缺省写死 `oracle/out` 而分发包无 oracle/。未改代码（保持 runner.py/golden.json 与源逐字节一致），以 README 运行目录约定解决——与体检工具的 eval//scripts/ 约定同类，属「工具约定 vs 分发布局」的通用错配模式。

---

## 四、分发候选清单要点

（全文见 `skillfactory/v3/report/DISTRIBUTION-CHECKLIST.md`，180 行，本会话读取；以下为要点转录。）

### 4.1 可分发资产与达标口径

- **meeting-minutes-skill v1.0.0**：v0.2 加厚复验 8 任务×双臂双重复 4.75→10.0、Δ+5.25、胜率 8/8、反向 0、accepted=true；ab_summary 含 `correction`（2026-09-30 majority 甲乙判反已按留档翻转重算，均值与 Δ 未受影响）；包内 EVALUATION.md 另载 v0.1 三轮（终轮 5.67→10.00）方向稳健。
- **office-templates-skill v1.0.0**：5 任务 7.7→8.9、Δ+1.20、accepted=true（本会话实读 taskAggs：ab1 7→9、ab2 8→9、ab3 7.5→9、ab4 两臂同分 8.5 majority 仍 treatment、ab5 7.5→9）；⚠️ 按 V3 报告 R3 仅单轮，对外标 `single_round_signal`（第二轮盲评未做；v2/evalbench-v02 下无此 suite，存档在 v3 资产管线）。
- **达标线**（EVAL-SPEC v0.2 复合线，据 V3-FORGE-DELIVERY.md:25）：Δ≥1.0 ✓、胜率 ≥0.6 ✓、反向 ≤1 ✓——两资产全过。
- **归属澄清**：evalbench-v02 三 suite 中仅 meeting-minutes 自产可分发；lark-cli（accepted=true，Δ+1.6875，胜率 0.75）与 hooks-mastery（accepted=false，Δ+0.70，胜率 0.6）系第三方资产盲评，**不在分发范围**。
- **全批共性欠账**（对外披露口径，V3 报告 R3/R4/R8）：效率门未测；真实复验门未做（双状态 `synthetic-passed ✓ / real-verified ✗`）；ot 单轮信号。
- **暂不可分发**：guard-hooks 与 prompt-regression 体检 C 级（见第三节），整改前禁止上架。

### 4.2 渠道矩阵（42 条）

- **P0 零门槛（建仓后本周）**：GitHub 仓 + topics（#29 被动聚合）、cursor.directory（目录实录 `plugins/new` 贴 repo URL、零 PR、自动识别 `skills/*/SKILL.md`）、skills.sh（发布命令目录未实录，上架前实测）、awesome PR×3（hesreallyhim 54.8k★ / VoltAgent 35k★ / travisvn）、anthropics/skills（收录流程目录未实录，先核实）。
- **P1 注册审核（第 2-4 周）**：ClawHub（CLI publish，moderated 审核）、claude-plugins-official + Claude Marketplace（Submit a plugin）、HF Spaces（盲评对照演示间）、国内 Kimi+（国内 C 端首选）/ 扣子 / 腾讯元器。
- **P2 形态改造与变现（第 1-2 月）**：Poe（price-per-message 经 Stripe，**23 地区含香港不含中国大陆**）、GPT Store（prompt 降维丢失确定性脚本优势）、Dify 插件化（国内最可核验商店标杆）、n8n 模板、LobeHub MCP 化、npm 打包。
- **P3 暂缓**：Salesforce/AWS/M365（RAI checks）/Slack/Atlassian/JetBrains/Chrome/Raycast/PromptBase/Open VSX/VSM。**不做**：Prime Intellect（RL 环境形态不符）、Coursera（无课程资产）。B 站案例（#38）作发布后内容营销参考。
- 纪律：渠道提交入口一律取自目录实录（`v2/CATALOG.md` A8 :450-508、:98、:247/:250/:251/:255）；目录只实录店面的如实标注「流程未实录」，未编造链接。

### 4.3 发布前检查（清单 4.1 表，9 项本会话前实测；标 ✓ 者（3 项）本报告会话再次复核）

| 结果 | 项 |
|---|---|
| ✅ | 许可证 MIT（两包 LICENSE + front-matter）；front-matter 五字段齐全（体检 PASS）；密钥/内网扫描 0 命中（无 sk-/api_key/tailnet IP/机器名）；包内无自相矛盾仓库链接 |
| ❌ 阻断 | mm 包 `.mimosa` 19 文件（✅ 本会话 `find` 复核 =19）；mm 缺 requirements.txt 而 minutes.py:128 依赖 python-docx（✅ 本会话 `Test-Path` =False）；skillfactory 非 git 仓（✅ 本会话 `git status` = fatal） |
| ⚠️ 低危 | 内部路径表述**≥9 处**（审读修订：原「3 处」系 grep 模式漏抓不含 `zcode\|D:\workspace\|SKILLFACTORY` 字样的存档引用。审读列举 9 处经本会话逐行核实全命中：mm SKILL.md:59「在 skillfactory 资产内时」；ot CHANGELOG.md:5/:12、EVALUATION.md:3/:7/:21/:50/:68、README.md:35；同类另有 EVALUATION.md:41 两处 rep1 留档路径。其中 **ot README.md:35「原始数据见开发方存档 `tests/ab_summary.json`」在包内悬空**——包内无 tests/，实测 `find` 报 No such file or directory。⚠️ 清单 4.1 表同句仍写「3 处」，须同步修正，不在本报告修订范围）；两包无 MANIFEST.json/校验和 |

---

## 五、对外发布前待雇主确认事项（唯一人工闸口）

以下均超出本会话权限或属包内容/对外口径变更，须雇主拍板后方可执行：

1. **3 个阻断项处置授权**：**两包 `.mimosa/` 清点删除**（mm 19 文件；ot 本会话已二清至 37 文件，但按 §三 dogfood 2 规则须在发布打包时作最后一道工序再清点一次）、补 mm `requirements.txt`（python-docx>=1.1）、`git init` + GitHub 建远端 + `v1.0.0` tag。前两项改包内容，处置后须重跑体检确认维持 A 级。
2. **建仓形态**：monorepo（`skills/meeting-minutes/` + `skills/office-templates/`）还是分仓；GitHub 账号/组织名；README 是否载明评测结论与披露口径。
3. **评测披露口径（诚实红线）**：ot 一切对外文案标注 `single_round_signal`；两资产统一披露 `synthetic-passed ✓ / real-verified ✗` 双状态；引用 mm Δ+5.25 时注明来自修正后重算。是否接受该口径对外可见。
4. **渠道现场核实投入**：skills.sh 发布命令、anthropics/skills 贡献流程、aitmpl.com 组件收录流程均目录未实录，需逐渠道现场核实（耗时）；是否授权作为第一波动作。
5. **许可证授权边界声明**（清单发布门第 5 条后句，`DISTRIBUTION-CHECKLIST.md:172`，审读修订补入）：若提交 anthropics/skills，其文档技能为 source-available 口径，我方 MIT 全开需在 README 明示授权边界——是否提交该渠道及声明措辞，须雇主确认。
6. **变现收款主体**：Poe 变现经 Stripe，23 地区含香港不含中国大陆——我方是否具备可收款主体，决定 P2 变现实验是否可行。
7. **国内平台口径**：Kimi+/扣子/元器需 prompt 规则层降维重建，是否与课程引流口径绑定、以何品牌出现。
8. **低危项取舍**：≥9 处内部路径表述（含 ot README.md:35 悬空引用）改中性还是保留；MANIFEST.json（逐文件 sha256，V3 报告「下一步」第 4 条要求）是否作为发布门必做项。

---

## 六、下一步

1. **处置阻断项**（待第五节 1-2 确认）：两包 `.mimosa` 清点删除（作发布打包最后一道工序）、补 requirements.txt、建仓打 tag；改后两包重跑体检确认 A 级，并将「包内命令跑完清点 .mimosa」纳入发布门操作步骤（成因见第三节 dogfood 2）。
2. **打 MANIFEST.json**：两包逐文件 sha256，回填 V3 报告遗留欠账。
3. **第一波 P0**：GitHub 建仓 + topics → cursor.directory（零 PR）→ skills.sh（先实测发布命令）→ awesome PR×3 → anthropics/skills 流程核实。
4. **ot 第二轮盲评**：消除 `single_round_signal` 标注依赖；随后安排真实复验门，补齐 `real-verified` 状态。
5. **C 级资产整改**：guard-hooks 补 front-matter 三字段 + eval/ + scripts/ 布局；prompt-regression 按 V3 报告 R9 补 ≥30 条人工金标准对拍——达标后 guard-hooks 可投 awesome-claude-code-hooks（#27）。

---

## 附：本会话核验记录（可复跑）

| 动作 | 命令/方法 | 结果 |
|---|---|---|
| 读清单 | Read `skillfactory/v3/report/DISTRIBUTION-CHECKLIST.md` | 180 行全文 |
| ot 包文件数 | `find dist/office-templates-skill -type f \| wc -l` | 37（复跑污染清除后复核仍 37） |
| ot 盲评对账 | Read `v3/assets/office-templates/tests/ab_summary.json` | tasks=5、7.7→8.9、delta=1.2、winRate=1、reverseTasks=0、accepted=true；taskAggs 与包内 EVALUATION 引用一致 |
| mm 盲评对账 | `grep -E '"tasks"\|baselineMean\|…' v2/evalbench-v02/meeting-minutes/ab_summary.json` | tasks=8、4.75→10、delta=5.25、winRate=1.0、reverseTasks=0、accepted=true、correction 字段存在 |
| ot 评测复现 | 包内 `python eval/runner.py out reference/out`（先跑 8 条 gen_doc.py） | ok=true、68 checks 全 pass、field_fill_agreement 100.0%（66/66）、EXIT=0 |
| ot 绿自检 | 包内 `python eval/runner.py reference/out reference/out` | GREEN_EXIT=0 |
| 体检产物核实 | Read mm-dist/ot-dist report.json；PowerShell 读 guard-hooks/prompt-reg report.json | A 5/5、A 5/5、C 2/5、C 2/5，失败项与任务材料一致 |
| 体检工具存在 | `ls v3/tools/healthcheck/package/healthcheck.py` | 存在 |
| mm 污染复核 | `find dist/meeting-minutes-skill/.mimosa -type f \| wc -l` | 19 |
| mm 依赖缺失复核 | `Test-Path dist/meeting-minutes-skill/requirements.txt` | False |
| 仓状态复核 | `git -C skillfactory status` | fatal: not a git repository |
| 复跑污染首清 | `rm -rf` 包内 `out/` 与 `.mimosa/` | 当时复核 37 文件（后被审读证伪为中间态，见下两行） |
| 审读：复发核实 | `find dist/office-templates-skill -type f \| wc -l` → **43**；`find .mimosa -type f` → 6 枚（hook-state×2 + baseline×3 + hook-status×1）；Read `hook-status/…-99fa0cb3e3.json` | `recordedAt=2026-09-30T01:13:55.648Z`、`event=PostToolUse`、`toolName=Write`、`file`=本报告路径——写报告动作自身触发，审读发现属实且此后续有累积 |
| 审读：二次清除 | `rm -rf` 包内 `.mimosa/` && `find … \| wc -l`（cwd 已先迁出包内） | **37** |
| 审读：悬空引用核实 | `find dist/office-templates-skill/tests -type f` | No such file or directory（README.md:35 引用的 tests/ 包内不存在） |
| 审读：低危逐行核实 | Read mm SKILL.md（:50-69）、ot CHANGELOG.md / EVALUATION.md / README.md 全文；Read prompt-reg/REPORT.md | 9 处列举全命中（mm SKILL.md:59；ot CHANGELOG.md:5/:12、EVALUATION.md:3/:7/:21/:50/:68、README.md:35）；REPORT.md:5「评级：**C**」、:18「失败项 ≥2，分发前必须完成整改」 |

**未执行（如实声明）**：未向任何渠道提交；skills.sh 发布命令与 anthropics/skills 贡献流程未现场核实；meeting-minutes 包内未复跑其 eval smoke（该包体检 A 级结论引自 mm-dist report.json 实读，未重复执行）；D1 确定性双跑与逐字节 cmp/md5 复制校验引自打包材料（本会话未重做，本会话复现的是生成+评测链）；guard-hooks 与 prompt-regression 整改未做。

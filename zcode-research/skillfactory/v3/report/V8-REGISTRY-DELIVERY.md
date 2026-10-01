# V8 交付报告：三包入账 · 资产总台账 · 五门课程就绪度（V8-REGISTRY-DELIVERY）

| 项 | 值 |
|---|---|
| 文件 | `skillfactory/v3/report/V8-REGISTRY-DELIVERY.md` |
| 日期 | 2026-09-30 |
| 报告性质 | 交付汇总：hot-templates-skill 打包入 dist + `skillfactory/REGISTRY.md` 总台账建立 + 五门课程就绪度对照（`v3/report/COURSE-READINESS.md`） |
| 输入材料 | ① hot-templates 打包会话回执（distPath、包内自检、复制忠实性、适配点、体检、终扫、建仓记录）；② `skillfactory/REGISTRY.md`（本会话全文实读，2026-09-30 台账登记员产出）；③ `skillfactory/v3/report/COURSE-READINESS.md`（本会话全文实读，课程对照师产出） |
| 本会话核实动作（实跑） | `git -C dist/hot-templates-skill log --oneline -1` → `52187cf v1.0.0: initial release candidate (v0.2 eval passed)`；`git -C dist/hot-templates-skill status --porcelain` → 0 行；`git -C dist/meeting-minutes-skill log` → `29bd123`、`git -C dist/office-templates-skill log` → `1e4ada5`（均同 commit 信息）；`ls dist/` → 恰 3 包；`find dist (-name .mimosa -o -name __pycache__ -o -name *.pyc)` → **0 命中**；python 实读 `v3/healthchecks/ht-dist/report.json` → `rating: A`、target=dist/hot-templates-skill、5 检查项（skill_md_exists / front_matter_fields / eval_present / eval_smoke / scripts_syntax）、generated_at 2026-09-30T15:40:59+0800 |
| 口径声明 | 评测数字（12 项 runner 复跑、5 份 ab_summary 对账、三包体检复跑、13 项 sha256）转引 `REGISTRY.md` 附录 A 的 2026-09-30 当日实跑记录；打包自检 ①–④ 转引打包会话回执；课程组件状态与 nextWave 转引 `COURSE-READINESS.md`（其为文档对照分析，未重跑评测、未实跑外部组件）。本会话未重跑任何评测/盲评/体检工具本体，仅做上表列出的盘内只读核实。 |

---

## 一、执行摘要

1. **三包就绪**：`dist/` 下三个分发包（meeting-minutes-skill / office-templates-skill / hot-templates-skill，均 v1.0.0）全部达到「确定性评测通过 + 盲评达标 + 体检 A」三门口径（`REGISTRY.md:5`），git 短哈希 `29bd123` / `1e4ada5` / `52187cf`（本会话逐一实查 commit 在位、工作区干净），**发布动作统一待雇主批准**。
2. **台账规模**：`skillfactory/REGISTRY.md` 已建账，统计行「**资产总数 18 ｜ 可分发 3 ｜ v0.2 达标 4**」（`REGISTRY.md:4`）。18 条 = dist 三分发包 + 自产资产 12 件（assets/ 4、v3/assets 3、v3/tools 1、v4/assets 3、v4/tools 1）+ `v2/evalbench-v02/` 三评测对象；状态分布为可分发 3 / 内部就绪 9 / 待迭代 6。
3. **课程就绪度总览**（`COURSE-READINESS.md:147`）：**0 门可立即开课；2 门「组件齐待集成」（课程二会议纪要、课程五技能封装）；3 门「有硬缺口」（课程一短视频、课程三门店工厂、课程四月度汇报）**。开课进入条件「≥2 门课端到端产线可复跑且现场验收彩排通过」尚未满足任何一门。
4. **厂史最高盲评**：hot-templates v0.2 盲评 Δ+6.10 / 胜率 100%（5/5）/ 反向 0、accepted=true（`REGISTRY.md:16,115`），已按 release-candidate 形态入 dist，本报告第二节为打包记录。

---

## 二、hot-templates 打包记录

**产物**：`D:\workspace\zcode研究\skillfactory\dist\hot-templates-skill`（39 文件），本地 git 仓初始 commit `52187cf`「v1.0.0: initial release candidate (v0.2 eval passed)」（本会话实查在位）。

### 2.1 包内实跑自检（转引打包回执，全绿）

1. **8 条生成命令**（`scripts/gen.py --platform/--topic/--points reference/inputs/<p>/<c>.json --outdir out/...`）全部 exit=0（Python 3.12.10）。
2. **spec 契约**：两参数形式 `python eval/runner.py out reference/out` → ok=true、40/40 checks 全 pass、8 例结构一致率均 100.0%（consistency_min=1.0）、exit 0。
3. **红绿自检**：绿检 `reference/out reference/out` → exit 0（40/40）；红检空目录 → exit 1（40 项判红）。
4. **确定性双跑**：骨架.md / structure.json 逐字节一致；新生成 out/ 与 reference/out **16/16 文件逐字节一致**。

### 2.2 复制忠实性

- `scripts/gen.py` 与 `eval/runner.py` 同开发资产（`v4/assets/hot-templates`）sha256 逐字节一致。
- `reference/out` 与开发资产 oracle 参照产物 16/16 逐字节一致；`reference/inputs` 与 oracle/inputs 8/8 一致（体例同 meeting-minutes-skill：reference/out 取 oracle 参照产物）。

### 2.3 适配点（已在包内 README「运行目录约定」写明）

- `eval/golden.json` 的 `eval_inputs` 路径由开发资产的 `oracle/inputs|oracle/out` 适配为 `reference/inputs|reference/out`（case 值与 ab_tasks 断言未动；否则 runner 检查 4 找不到样例输入必判红）。
- `SKILL.md`：license 改 MIT；验收判据行 `oracle/out` 改 `reference/out`。

### 2.4 EVALUATION.md 数字来源

取自开发方存档 `tests/ab_summary.json`（5 任务、基线 3.9 → 治疗 10.0、Δ+6.10、胜率 100% 5/5、反向 0、accepted=true；逐任务 3/3/3/2/8.5→10 全 majority=treatment）+ CHANGELOG 1.0.1 第 2 轮 40/40 记录 + 本次发包实跑。存档均按「**开发方评测存档（未随包分发）**」表述，含合成数据局限节。与 `REGISTRY.md:33` 源资产行数字一致。

### 2.5 体检与终扫

- 体检：`python skillfactory/v3/tools/healthcheck/package/healthcheck.py --target skillfactory/dist/hot-templates-skill --out skillfactory/v3/healthchecks/ht-dist` → **评级 A（5/5）**，eval_smoke 实跑 exit=0；本会话实读 `v3/healthchecks/ht-dist/report.json` 确认 `rating: A`（generated_at 2026-09-30T15:40:59+0800）。
- 终扫（本会话实跑复现）：`find dist/hot-templates-skill (-name .mimosa -o -name __pycache__ -o -name *.pyc)` → **0 命中**；`git status --porcelain` → **0**。

### 2.6 本地建仓

`git init` + 仓库级 `user.name=SkillFactory / user.email=skillfactory@localhost`，初始 commit `52187cf` 共 39 文件；`git remote -v` 为空、**未 push**（无对外动作）。

**Mimosa hook 提示（如实转告）**：git commit 时 Mimosa hook 报的 high 风险全部位于 `skillfactory/library/doubao/skill-090298bb.../scripts/format_docx.py`（**库内另一技能，不在本包**；本包仅 `gen.py` / `runner.py` 两个纯标准库脚本，无 XML/路径拼接逻辑），未阻断提交。

### 2.7 欠账披露（不隐藏）

hot-templates 按 SKILL-SPEC §4 五门口径仍有欠账：效率门未测、盲评每臂 2<3 重复、`benchmark.json` 未落盘（`REGISTRY.md:19` 注 2，源头 `v4/report/V7-FORGE-DELIVERY.md` P0-1）。V7 原文要求「复检通过前不进分发」，本包以 **release-candidate** 形态入 dist，是否随三包一并放行**待雇主裁决**（见第五节决策项 2）。

---

## 三、台账要点（`skillfactory/REGISTRY.md`）

### 3.1 台账结构

| 分区 | 条数 | 状态分布 |
|---|---|---|
| A. 分发包 `dist/` | 3 | 可分发 3（均待雇主批准） |
| B. 自产资产（assets/ 4、v3/assets 3、v3/tools 1、v4/assets 3、v4/tools 1） | 12 | 内部就绪 7（mm 源 / ot 源 / healthcheck / ht 源 / mcp-office-pack / office-eval-suite / content-evaluator）/ 待迭代 5（monthly-report-ppt、ppt-method-router、paper-to-skill、office-guard-hooks、prompt-regression）；C 区另内部就绪 2 / 待迭代 1——9/6 为全台账合计，与统计行一致（2026-09-30 审读修正，机械清点 REGISTRY.md 复核） |
| C. 评测对象 `v2/evalbench-v02/` | 3 | 内部就绪 2（lark-cli、meeting-minutes 复检现场）/ 待迭代 1（hooks-mastery，不采用口径） |

每条含名称/目录/形态/状态/评测数字/许可/一句话用途；统计行与文末「发布就绪汇总」（`REGISTRY.md:134-149`）均已落位。

### 3.2 三个分发包（发布就绪汇总，`REGISTRY.md:136-141`）

| 包 | commit | 体检 | 盲评 v0.2 |
|---|---|---|---|
| meeting-minutes-skill v1.0.0 | `29bd123`（2026-09-30 10:00:11） | A（5/5，本轮复跑复核） | 8 任务 4.75→10.0，Δ+5.25 / 100%（8/8）/ 反向 0，accepted |
| office-templates-skill v1.0.0 | `1e4ada5`（10:00:31） | A（5/5，本轮复跑复核） | 5 任务 7.7→8.9，Δ+1.20 / 100%（5/5）/ 反向 0，accepted（单轮信号） |
| hot-templates-skill v1.0.0 | `52187cf`（15:42:21） | A（5/5，本轮复跑复核） | 5 任务 3.9→10.0，Δ+6.10 / 100%（5/5）/ 反向 0，accepted |

关键文件 sha256（SKILL.md/scripts/eval 共 13 项）本轮实算并机械复核 **13/13 相符**，计算命令附台账内（`REGISTRY.md:50-79`）。

### 3.3 数字全部为本轮亲测（2026-09-30）

- **12 个确定性 runner 复跑全 exit 0**：20/20、16/16、6/6、3/3、68/68、7/7、5/5、4/4×2、40/40、6/6、5/5、4/4（命令与输出逐条见 `REGISTRY.md:85-106` 附录 A1）。
- **5 份 ab_summary.json python 实读对账**（`REGISTRY.md:108-116`）：mm Δ+5.25/100%/反向 0 accepted；ot Δ+1.20/100%/0 accepted；ht Δ+6.10/100%/0 accepted；lark-cli Δ+1.6875/75%（6/8）/0 accepted；hooks-mastery Δ+0.70/60%（3/5）/0 **rejected**。
- **体检**：工具对三 dist 包复跑均 A（5/5，输出存 `_tmp_registry_hc/` 未写入包内）；盘内核实 guard-hooks 与 prompt-reg 引盘内 report.json 为 **C**（2/5）。
- **V6 报告两项阻断已清（本轮实查）**：`.mimosa` 污染零命中；三包 `requirements.txt` 在位；git 各 1 commit、工作区干净（`REGISTRY.md:18,128`）。

### 3.4 台账如实声明（未做项，`REGISTRY.md:130`）

未重跑任何双臂盲评（Δ/胜率为盘内 ab_summary.json 数字，本轮实读对账）；未在 dist 包内做被测-参照全量对拍（以源资产 runner 复跑 + 包内体检绿自检替代）；未重跑 mcp-office-pack 真实协议握手（引三份落盘 samples.json）；未核验第三方仓（lark-cli/hooks-mastery）远端现况（引 ASSET-DOC 2026-09-29 抓取记录）。

---

## 四、课程就绪度与下一波生产建议（`v3/report/COURSE-READINESS.md`）

### 4.1 五门课就绪度总表

| 课程 | 评级 | 自产达标件 | 外部已达标件 | 主要硬缺口 |
|---|---|---|---|---|
| 二 会议纪要 | **组件齐待集成** | meeting-minutes-skill（三门齐）、office-templates-skill、mcp-office-pack、office-eval-suite | lark-cli | 说话人映射、热词表、compose 部署包、FunASR 实跑 |
| 五 技能封装 | **组件齐待集成** | SOP+4 案例+healthcheck+SPEC | 无 | 三个免费单点、货架流程实测、教材化改造；hooks-mastery Δ+0.70 / 60% **accepted=false** 不满足达标定义、仅作教材（本行原转引 COURSE-READINESS 汇总表时错置于外达标列，2026-09-30 审读修正） |
| 一 短视频 | **有硬缺口** | hot-templates（带欠账）、content-evaluator | 无 | 五环外部件全未实跑、免费单点三件、全链路编排、「现场 10 条」试跑 |
| 三 门店工厂 | **有硬缺口** | 同课程一 | 无 | 课程一全部缺口 + 店铺 Schema + 零技术部署包 + 行业模板 + rembg 换权重 |
| 四 月度汇报 | **有硬缺口** | monthly-report-ppt（**未过确定性门**）、ppt-method-router（盲评未达线）、office-eval-suite | 无 | 核心件复裁返工、模板保真校验器（验收依赖它）、VI 模板工程、excel-mcp fork 回归 |

关键事实：课程二是唯一核心 skill 已过**确定性 + 盲评（Δ+5.25/100%）+ 体检 A 三门**的端到端课，仅缺说话人映射/热词表/compose 部署包三件自研与 FunASR 实跑；课程四核心自产件 monthly-report-ppt 下发 evalPassed=false（盘内 16/16 复跑不推翻下发判定），且验收口径「真 PowerPoint 不跑版」依赖的模板保真校验器是开源空白尚未启动自研；课程一/三核心五环（配音/字幕/采集/合成/发布）全部是未实跑外部件，「现场 10 条」验收目标值从未计时试跑。

### 4.2 下一波生产建议（nextWave，按「开课最快收益最大」排序，`COURSE-READINESS.md:151-158`）

1. **课程二三件自研空白生产**：说话人映射交互 + 单位热词表 + 一键 compose 部署包——把唯一「组件齐待集成」的端到端课推到试点就绪（其核心 skill 三门达标可直接内嵌）。
2. **课程二真实录音计时彩排**（验收口径：三段式纪要 + ≥1 条催办任务）——兑现 D60 试点 1 期，同场实测 FunASR CPU 转写速度（调研明示开课前必测）。
3. **hot-templates 五门复检清账**（V7 P0-1：效率门 + 每臂 3 重复 + benchmark.json 落盘）——一次动作解锁课程一/三脚本增强件合规使用与免费层第二件上架（厂史最高盲评 Δ+6.10）。
4. **课程一免费单点三件生产**（whisperX 打字幕 skill / GPT-SoVITS 我的声音 MCP / yt-dlp 素材入库 skill）——课程一/三共享前置件，生产即免费层上架物并倒逼三个核心外部件首次实跑。
5. **课程一整链计时试跑**（选题清单→成片→草稿箱，学员典型硬件）——「现场 10 条」验收目标值从未验证，试跑数据决定课程一/三能否排期或验收口径需降级。
6. **monthly-report-ppt 按同一版 golden 复裁落盘**——课程四排期讨论重启的前提动作。

---

## 五、待雇主决策事项

1. **三包发布批准**：meeting-minutes-skill / office-templates-skill / hot-templates-skill 均为评测门口径就绪（确定性门 + 盲评门 + 体检 A），**发布与否待雇主批准**（`REGISTRY.md:142`）。批准即须执行发布 checklist（`v3/report/DISTRIBUTION-CHECKLIST.md`），最后一道工序为再次清点删除包内 `.mimosa/`（本轮实查三包为 0，动作本身须进 checklist，`REGISTRY.md:149`）。
2. **hot-templates 放行口径裁决**：V7 报告原要求「五门复检通过前不上架」，本包以 release-candidate 形态已入 dist——是「随本批放行」还是「复检清账（nextWave 第 3 项）后再放」，随三包一并裁决。
3. **对外披露口径确认**（5 条，引自盘内报告、本轮未重测，`REGISTRY.md:144-149`）：① 全批 synthetic-passed ✓ / real-verified ✗，效率门未测；② office-templates 对外一切文案标注 `single_round_signal`；③ meeting-minutes Δ+5.25 来自 2026-09-30 majority 判定反演修正后的重算（均值与 Δ 未受修正影响）；④ hot-templates 五门欠账未清；⑤ `.mimosa` 清点动作进发布 checklist。
4. **nextWave 排期裁决**：第四节 6 项建议的顺序与取舍（尤其课程二三件自研 vs hot-templates 复检谁先）。
5. **monthly-report-ppt 复裁**：下发 evalPassed=false 与盘内 16/16 复跑的矛盾，需批准按同一版 golden 复裁落盘（课程四排期重启前提）。

---

## 六、审读修订记录（2026-09-30）

收到审读意见 4 条，逐条于本修订会话实查并修订：

1. **§3.1 表 B 行状态分布笔误已修正**：原写「内部就绪 9 / 待迭代 3」，机械清点 `REGISTRY.md` B 区实为**内部就绪 7 / 待迭代 5**（C 区 2/1）；9/6 为全台账合计（B 7 + C 2、B 5 + C 1），与统计行（`REGISTRY.md:4`）一致。核实命令：python 按 `## B.` / `## C.` 分段计数 → `B: ready=7 iter=5`、`C: ready=2 iter=1`。`REGISTRY.md` 本体无误，属本报告转抄笔误。
2. **§4.1 课程五「外部已达标件」错置已修正**：改为「**无**」。核实命令与输出：python 实读 `skillfactory/v2/evalbench-v02/hooks-mastery/ab_summary.json` → `accepted= False delta= 0.70 winRate= 0.6`，不满足达标定义；源头错置在 `COURSE-READINESS.md:142`（与其 `:124`「外达标·不采用」及 `:13` 图例「全厂仅 lark-cli 一件」自相矛盾），已一并修正该文件同格——数据本体（accepted=false、仅教材）原文即如实写明，属标签错置非数字造假。
3. **路径基准说明已补**：`research/oss-research-report.md` 实际位于工作区根 `D:\workspace\zcode研究\research\`（本会话 `ls research/oss-research-report.md` 命中；`ls skillfactory/research` → No such file or directory），`COURSE-READINESS.md` 所引相对路径以工作区根为基准，文件所指无误，已在该文件输入材料行加注。
4. **核验范围如实声明**（转引审读会话自述，非本会话动作，本会话未复核复跑）：审读会话未重跑盲评本体；12 项确定性 runner 中仅自行复跑 meeting-minutes 一项（课程二抽查），其余 11 项为对 `REGISTRY.md` 附录 A 记录的转引核对；healthcheck 工具本体未重跑（实读其落盘 report.json 共 8 份：ht-dist / mm-dist / ot-dist + `_tmp_registry_hc` 三包 + guard-hooks / prompt-reg）；lark-cli、hooks-mastery 远端仓现况未验证。本修订会话另行实读落盘 report.json 共 10 份（`v3/healthchecks/*/report.json` 7 份 + `_tmp_registry_hc/*/report.json` 3 份；评级：三 dist 包及其 recheck 均 A、guard-hooks 与 prompt-reg 均 C、_tmp 三包均 A），与审读声明一致。

---

*本报告由交付报告撰写人会话产出（2026-09-30），同日按审读意见 4 条完成修订（见第六节）。打包自检与建仓记录转引打包会话回执；台账数字转引 `skillfactory/REGISTRY.md` 附录 A（2026-09-30 实跑）；课程结论转引 `v3/report/COURSE-READINESS.md`；撰写与修订两会话均仅做盘内只读核实（git 短哈希、终扫 find、体检 report.json 实读、dist 目录清点、台账分段计数、hooks-mastery 盲评本体实读），未重跑评测/盲评/体检工具本体，未执行任何对外动作。*

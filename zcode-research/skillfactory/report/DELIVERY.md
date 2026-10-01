# Skill 工厂首夜交付报告

| 项 | 值 |
|---|---|
| 文件 | `skillfactory/report/交付报告.md` |
| 日期 | 2026-09-29 |
| 版本说明 | 本文件为全量重写定稿，**替换同日早前旧稿**——旧稿所载盲评数字（meeting-minutes Δ=1.67/胜率 0.67、ppt-method-router Δ=0.67/0.67、paper-to-skill −0.5/0.5）为**上一轮**盲评快照，与本任务下发的权威实测结果及盘内现行 `tests/ab_summary.json` 不符，已废弃（旧稿原文已归档 `report/archive/交付报告-旧稿-20260929T0721-已废弃.md`，原 `report/DELIVERY.md`，本会话 mv 归档，避免双报告同目录误引）。本版所有资产数字以任务下发 assetInventory 为唯一权威口径，并经本会话与盘内三份 `tests/ab_summary.json` 逐项对账一致（附录 A2）。**v1.2（同日）按独立审读意见修订六处**：① 执行摘要与第三节「接受」标注补「评测门口径 + SPEC §4 五门待复检」限定（效率门未测、盲评每臂 1 对低于 §3.3）；② golden 三类用例配比缺口由「paper-to-skill 一项」改为**全批逐资产点清**（4.3-4 与 6.2#5，本会话实读 4 份 golden 证实）；③ 旧稿归档（前述）；④ 6.3 新增「对外引用外部数字前逐项复核」纪律；⑤ 6.2#3「description 非三段式」由报告口径升级为本会话全文读取实证（两者均无触发段与转交路由）；⑥ 附录 A 补记本轮核验命令 |
| 数字口径 | 资产表 `evalPassed / abDelta / winRate / accepted` 以任务下发 assetInventory 为准；baseline→treatment 均分与逐任务分数取自盘内 `tests/ab_summary.json`（本会话实读，两者逐项一致）；确定性评测为本会话实际复跑结果（命令见附录 A1） |
| 材料来源 | ① 首批技能资产实测结果（任务下发 assetInventory，4 条）；② 四路侦察（豆包 106 包逆向 / Qoder·Kimi·千问三家逆向 / Agent Skills 外部权威标准与生态 / 分发渠道与商业模式，任务下发，引用保持转述口径）；③ `skillfactory/standard/SKILL-SPEC-v0.1.md`（386 行）、`skillfactory/plan/总体方案.md`（v2.0）、`skillfactory/plan/治理面输出方案.md`（v0.3），本会话全文读取 |
| 本会话实际执行的核验 | 四资产确定性评测复跑均 exit 0（附录 A1）；红检（空目录应报失败）实测 exit 1；三份 `tests/ab_summary.json` 逐项对账（A2）；front-matter/CHANGELOG/NUL/golden 归档/落盘件缺失逐项实查（A3）；monthly-report-ppt 产物 15/15 文件哈希异于 oracle 实测（A4） |

---

## 一、执行摘要

**今晚产出了什么（四类）：**

1. **标准 1 份**：`skillfactory/standard/SKILL-SPEC-v0.1.md`（2026-09-29 定稿生效，386 行）——自产 skill 包企业标准，含格式规范（§1）、质量红线（§2）、评价体系（§3）、五门验收线（§4）、蒸馏与融合规范（§5），全部条款可判定。
2. **技能资产 4 项**：meeting-minutes、monthly-report-ppt、ppt-method-router、paper-to-skill，各带 spec / contract / oracle（参照实现+黄金输入+参照产物）/ eval（runner.py + golden.json）/ package 五件套（本会话逐目录实查在位）。
3. **盲评实测**：3 项资产完成有无对照双臂盲评（with_skill vs without_skill，逐任务 0–10 分）；monthly-report-ppt 被确定性门拦截，未进入盲评（盘内无 `tests/` 目录，本会话实查）。
4. **方案 2 份**：`skillfactory/plan/总体方案.md` v2.0（三源生产管线 / 商业模式四阶段 / 课程体系 / 90 天路线图与 KPI）与 `skillfactory/plan/治理面输出方案.md` v0.3（个人版治理随行包 skilldock / 企业版治理套件 / skill 与 MCP 两类资产的注入与管理 / CloudCrane 对接与风险）。

**哪些达到验收线：4 进 1 出。** 按任务下发 assetInventory：仅 **meeting-minutes** 接受为资产（evalPassed=true，Δ=4.33 ≥1.0，胜率 1.0 ≥0.60，盲评门双条件全过，三局全胜）——**「接受」是评测门（确定性+盲评）口径**：按 SPEC §4（`SKILL-SPEC-v0.1.md:266-276`）五门须全部通过方可入库与分发，该资产效率门从未测量、盲评每臂仅 1 对裁决（低于 SPEC §3.3 每臂 ≥3），**五门复检未完成，复检通过前不可入库分发**（见第三节 † 注与 4.3）；**monthly-report-ppt 未通过确定性评测，判返工**；**ppt-method-router（Δ=0、胜率 0.33）与 paper-to-skill（Δ=−0.5、胜率 0）确定性门通过但盲评未达验收线**，判「技能本体或 spec 需迭代」。确定性门拦下 1 个、盲评门拦下 2 个——两扇门都真实拦截过。

**一句话结论：** 验收线首轮就展示了牙齿（拒 3 留 1，没有为产出数字放水：meeting-minutes 全胜给出「聚焦单能+确定性 oracle」的增益上限锚点，paper-to-skill 的 Δ=−0.5 实测证明「挂上 skill 反而更差」是会发生的，ppt-method-router 的 Δ=0 证明「路由对了」不等于「有增益」）；但四个数字（全胜/返工/零增益/负增益）也同时说明——**「评测门通过」成立，「可入库可分发」尚未成立**：落盘欠账（benchmark.json / MANIFEST.json / protocol.md 均未落盘，本会话 find 零命中）与盲评规模（每臂仅 1 对裁决）待补，3 个未接受项的返工/迭代是下一步主线。

---

## 二、技能格式与评价标准要点

标准文件：`skillfactory/standard/SKILL-SPEC-v0.1.md`（本会话全文读取，386 行）。要点：

**格式规范（§1）**
- 目录硬约定（:33-55）：`SKILL.md` 唯一入口 + 可选 `references/`、`scripts/`、`assets/`，必选 `eval/`（runner.py + golden.json + protocol.md + results/）与 `CHANGELOG.md`，发布时生成 `MANIFEST.json`（逐文件 sha256）；包内禁止 `.git/`、缓存、占位文件——豆包 106 包实测有 3 包把完整 `.git/` 打进分发 zip（`library/doubao/CATALOG.md:22`，本会话实读），属不得重演的发布事故。
- front-matter 必填 6 字段（:59-76）：`name`（=目录名，小写连字符）、`version`（语义化）、`license`、`description`（1–1024 字符）、`permissions`、`metadata`（平铺 string→string，自有扩展唯一挂载点）；禁止顶层新增字段。核心 build 只依赖 name、description、SKILL.md 三要素——全部渠道的最大公约数，平台私有增强一律编译期可剥离（§1.5，:110-144）。
- description 三段式触发设计（:78-91）：能力段 + 触发段（≥3 个具体口语触发短语，国内宿主必须含中文触发词）+ 边界段（负面边界并指名转交哪个 skill，互斥 skill 互相导流）。
- 渐进披露分层是格式红线而非建议（:93-108）：L1 元数据（唯一常驻界面）→ L2 正文（≤500 行且 ≤10,000 字符，gotchas 节必备）→ L3 资源（reference 一层深、每处引用写明触发条件、文档地图表必备）。

**质量红线（§2）**：可判定触发条件，触发场景映射 golden 用例（:150-156）；步骤确定性——显式命令+显式成功判据、写后回读 pending→written→verified 三态、验收矩阵、脚本门卫「校验不过不交付」、MUST RELOAD 多轮重载条款（§2.2，:157-166）；防幻觉——数值断言内联来源、禁止凭记忆复述、不确定即声明（§2.3，:168-176）；错误处理——降级链显式、定向修复一次禁止循环重试、敏感操作强制用户接管、高风险领域「硬约束+禁止项+免责+可溯」四件套（§2.4，:177-183）；打包安全——MANIFEST、脚本禁收凭据（§2.5，:184-190）。

**评价体系（§3）**：每个 skill 必须捆绑可执行评测包——确定性评测 runner.py 机器可判 + 断言卫生四条 pattern 规则（§3.1，:195-203）；黄金集 golden.json（eval_inputs 三类用例缺一不可：positive / negative 近邻负例 / adversarial 相关但误导，ab_tasks ≥3 条带 0–10 rubric，golden 冻结+升版归档，§3.2，:205-253）；双臂盲评协议（with/without、独立子代理、裁判盲态附证据、禁止同情分，§3.3，:255-263）。

**五门验收线（§4，:266-276）**：① 确定性门 exit 0（重生成实现必须对同一版 golden 全量回归）；② 盲评门 Δ≥1.0 且胜率 ≥60%（:271）；③ 效率门 token/耗时比率 ≤2.0 一票否决（:272）；④ 形式门；⑤ 断言复审门。五门全过方可入库与分发；验收记录必须落盘 `eval/results/benchmark.json` + 验收单（:276）。

标准的证据基础是四路侦察（任务下发材料，转述口径）。两项关键口径已获本地佐证（本会话实查）：`ls library/doubao | grep -c "^skill-"` = **106**，与侦察①「豆包 106 包」一致；`library/doubao/CATALOG.md:22` 载 3 包内嵌完整 `.git`，与侦察①一致。其余外部数字（agentskills.io「40+ 客户端」、SkillsBench 增益、SWE-Skills-Bench token +451% 等）本会话未访问原始来源，保持转述口径。四路侦察的落点：豆包/三家逆向 → SPEC 条款与「四家均无 skill 质量度量」的差异化空位；外部标准调研 → 对齐 agentskills.io 不自造方言、效率阈值一票否决、三类测试集缺一不可；分发调研 → 开放格式+GitHub canonical 源、不签独家、不赌分成、平台流量是期限资产。

---

## 三、首批资产明细表

| 资产 | 目录 | 确定性评测 | 盲评（baseline → treatment，Δ / 胜率） | 是否接受 | 一句话点评 |
|---|---|---|---|---|---|
| **会议纪要三段式**（转写稿进、决议/待办/风险纪要出） | `skillfactory/assets/meeting-minutes` | **通过**（下发 evalPassed=true。首轮过；中途重生成连续 2 轮失败（15 项全红，根因是交付流程矛盾而非断言不可满足），specfix 修订后对同一版 golden 全量回归 20/20 过——golden 只增不改（追加 case4 全零边界）、v1.0→v1.1 双版归档、runner 零改动（`assets/meeting-minutes/CHANGELOG.md:5-38`，本会话全文读取）；本会话复跑 exit 0，20/20） | **5.67 → 10，Δ=4.33 / 胜率 1.0**（3 任务：7:10 / 4:10 / 6:10，全胜） | ✅ **接受**（下发 accepted=true）† | 首批唯一过线资产，三局全胜：逐字溯源红线、负责人抓不到填「待定」禁猜测、全零边界 case4 等可判定红线是增益来源——裁判实测 baseline 存在条目改写溯源失败、待办构成错误、负责人语义猜测、节标题与 summary 格式违规等硬伤，treatment 与官方参照 oracle 逐字全同且官方 runner 满分（`tests/ab_summary.json` 判词，本会话全文读取） |
| **月度汇报生成器**（Excel 台账进、图表+PPT 出） | `skillfactory/assets/monthly-report-ppt` | **未通过**（下发 evalPassed=false——资产或实现需返工。本会话复跑**盘内存量产物** exit 0（16/16），但失败轮产物未落盘、失败现场无归档，无法回溯失败原因；15/15 产物文件哈希与 oracle 全不同，排除照抄参照） | 未进入盲评（确定性门未过即拦截；盘内无 `tests/` 目录，本会话实查） | ❌ **不接受（返工）** | 首批唯一未过确定性门项，如实写失败：下发判定针对铸造时点最终被测实现；盘内存量产物可过现行 golden 属另一轮产物，需按同一版 golden 全量重跑并落盘评测记录后复裁，此前不进分发 |
| **PPT 方法意图路由**（多方法融合大 skill：按意图选最优路径） | `skillfactory/assets/ppt-method-router` | **通过**（下发 evalPassed=true；本会话复跑 exit 0，6/6 检查过，路由与 oracle 一致率 20/20=100%，阈值 80%） | **8.67 → 8.67，Δ=0 / 胜率 0.33**（3 任务：9:8 负 / 8:9 胜 / 9:9 平，平局不计胜） | ❌ **不接受（盲评未达线）** | 「路由得对」已被 100% 一致率证明，「挂上技能端到端更好」被证明为零（均分与 baseline 完全持平）；负场败因是 treatment 清理了复跑临时证据致复现链不可独立复核、缺对任务三问的专门作答节——是证据留存与作答结构问题，不是路由质量问题；迭代方向=方法 references 执行质量 + 把证据留存写进技能契约，路由逻辑不动 |
| **知识蒸馏器**（论文/官方文档 → 可用 skill） | `skillfactory/assets/paper-to-skill` | **通过**（下发 evalPassed=true；本会话复跑 exit 0，3 项检查全过：五要素齐 / 6 步可判定 / 13 项统计偏差最大 0.0%≤30%） | **9.00 → 8.50，Δ=−0.5 / 胜率 0**（2 任务：9:8 负 / 9:9 平） | ❌ **不接受（盲评未达线）** | 全批最有信息量的失败：首批唯一 treatment 均分低于 baseline——ab-001 裁判实测败因：缺可运行参考实现（baseline 的 qc_check.py 实跑 29 项全过）、漏 POSIX/Windows 平台差异坑（`os.rename` 静默覆盖）、产物 SKILL.md 混入评测元叙事；「挂上技能反而更差」与学术结论（误导性流程是技能致害最大类）在自家资产上复现，须先归因再裁决；其盲评仅 2 条任务、样本最小 |

汇总：确定性门 3 过 1 拒；盲评门（Δ≥1.0 且胜率 ≥60%，双条件与门）1 过 2 拒。**每扇门都杀过东西。**

> **† 口径说明**：「接受」= 任务下发 accepted=true，其含义是**评测门（确定性+盲评）通过**；按 SPEC §4（`SKILL-SPEC-v0.1.md:266-276`）五门须**全部通过**方可入库与分发——该资产效率门从未测量（token/耗时比率无任何落盘记录，见 4.3-3）、盲评每臂仅 1 对裁决（低于 §3.3 每臂 ≥3，见 4.3-1）、`eval/results/benchmark.json` 与验收单未落盘（见 6.2#1），准确状态是「**两门过、待五门复检**」，复检通过前不可入库分发。单独摘引「接受」二字会高估资产成熟度。

---

## 四、测试方法说明与实测效果解读

### 4.1 三层方法：oracle 红绿校验 → 重生成门禁 → 有无对照盲评

**第一层：oracle 红绿校验（确定性评测）。** 每资产带 `oracle/`（oracle.py 参照实现 + inputs 黄金输入 + out 参照产物）与 `eval/runner.py + golden.json` 机判检查。绿检（应过）与红检（应报失败、exit 1）两侧都有设计——本会话对红检做了实测：空目录作被测输入跑 meeting-minutes 与 monthly-report-ppt 的 runner，均 exit 1 且首项 `ok:false`/`units_found: pass=false`。检查全部机器可判：docx 可打开且三节标题齐、summary 与独立重算一致（容差 5%）、条目逐字溯源、条数容差 ≤2、路由一致率 ≥80%、统计偏差 ≤30%、脏数据清洗规则等。

**第二层：重生成门禁。** 重生成实现必须对同一版 golden.json 全量回归、全部通过方可进入盲评。首批实战案例是 meeting-minutes（`assets/meeting-minutes/CHANGELOG.md`，本会话全文读取）：重生成连续 2 轮 15 项检查全红（detail 逐字为「被测用例目录不存在」），根因是**交付流程矛盾**——任务指令指向不存在的 `inputs/` 且禁止读 `oracle/`，实现方无法合法取得黄金输入；specfix 修订 = golden **只增不改**（追加 case4 全零边界用例，case1–3 与 ab_tasks 逐字未动）、旧版归档 `eval/archive/golden-v1.0-20260929.json` 与 `golden-v1.1-20260929.json`（本会话实查在位）、runner 零改动，修订后独立实现 20/20 过。这杜绝了「为让实现通过而静默改断言」（SPEC §3.2 规则 4，`SKILL-SPEC-v0.1.md:253`）。

**第三层：有无对照盲评。** with_skill（treatment）vs without_skill（baseline）双臂，同一模型同一 prompt，逐任务按 0–10 rubric 打分；裁判盲态且必须附实测证据（如 python-docx 逐段回读、复跑双方自验脚本、对声称的行号逐条核实、对冲突场景实跑复现），不合格处明示扣分理由（三份 `tests/ab_summary.json` 各 verdict 的 reason 字段，本会话全文读取）；甲乙位置在任务间轮换防顺序偏置。**本批规模：每任务每臂 1 对裁决（n=1/臂）**，未达 SPEC §3.3 每臂 ≥3 次的要求——这是解读全部盲评数字的前提。

### 4.2 数字怎么读

- **Δ = treatment 均分 − baseline 均分**（0–10 制）。盲评门 = Δ≥1.0 **且** 胜率 ≥60%（胜 = 同任务中 treatment 严格更高；**平局不计胜**——paper-to-skill 2 任务 1 负 1 平故胜率 0；ppt-method-router 3 任务 1 胜 1 负 1 平故胜率 0.33）。
- **meeting-minutes 的 Δ=4.33/胜率 1.0**：baseline 三局 7/4/6 分、treatment 三局满分 10。裁判实测 baseline 的失分全部来自技能红线针对的失败模式（条目改写后无法逐字溯源、待办构成错误、负责人语义猜测、格式违规），而 treatment 与官方参照逐字全同——「确定性红线 + 对照评测」组合的价值得到最直接的内部印证。
- **ppt-method-router 的 Δ=0**：双臂均分完全持平（8.67:8.67）。三局里负局（9:8）与平局（9:9）的判词均显示双方路由输出正确且一致（本会话亦实测一致率 100%），差距出在证据链留存与报告结构等周边维度——「路由正确性是必要条件而非价值来源」这一模式教训由此成立。
- **paper-to-skill 的 Δ=−0.5**：负 Δ 说明当前版本的 skill 内容在部分任务上**误导实现**（ab-001 裁判实测证伪其产物判据与坑点覆盖）。1 负 1 平不是噪声量级的大败，但方向为负——必须先归因再迭代，而不是微调重评。
- **monthly-report-ppt 没有 Δ/胜率**：确定性门未过即拦截，盲评臂从未运行。本会话复跑盘内存量产物 exit 0（16/16）**不推翻**下发判定——失败轮产物未落盘，无法确认失败实现与盘内产物是同一份（15/15 文件哈希异于 oracle 恰恰说明盘内产物是真实被测产物而非参照副本）；这正是要求评测记录落盘的原因（治理方案 §0.3 P0-1）。

### 4.3 哪些结论可靠、哪些待复验

**可靠（本会话已独立复验）：**
1. 四资产确定性评测本会话实际复跑：全部 exit 0（meeting-minutes 20/20、monthly-report-ppt 16/16、ppt-method-router 6/6 且一致率 1.0、paper-to-skill 3/3）；红检实测 exit 1。
2. 盲评数字盘内对账成立：三份 `tests/ab_summary.json` 的 baselineMean/treatmentMean/delta/winRate 与任务下发 assetInventory 逐项吻合（5.67→10、4.33、1.0；8.67→8.67、0、0.33；9→8.5、−0.5、0），逐任务分数与均值复算一致。
3. 未接受 3 项的拒因有裁判实测证据支撑（非评分黑箱）：见第三节点评与 `tests/ab_summary.json` 判词原文。
4. monthly-report-ppt「非照抄参照」有实测支撑：15/15 产物文件哈希与 oracle 全不同（本会话 sha256 比对）。

**待复验（材料与盘内证据显示的缺口，非本会话新结论）：**
1. **盲评样本量**：每任务每臂仅 1 对裁决，SPEC §3.3 要求每臂 ≥3 次——首轮盲评数字（含 meeting-minutes 的 Δ=4.33/胜率 1.0）只应作为强初步信号采信，不足以单独支撑对外口径；paper-to-skill 仅 2 对、样本最小。
2. **单模型单裁判**：全部盲评为单一模型单裁判；双模型矩阵是 D31–60 待办（总体方案 §7.1）。
3. **效率门未测**：token/耗时比率无任何落盘记录（四资产均无 `eval/results/benchmark.json`，本会话 find 零命中），SPEC §4 门 3 目前无法核对。
4. **golden 三类用例配比为全批欠账，非 paper-to-skill 一项**（本会话实读 4 份 golden.json 证实）：四份条目均为 `case/input/output` 旧 schema、无 SPEC §3.2 规定的 `id/type/prompt/checks` 字段，结构上无法承载 positive/negative/adversarial 分类；按内容逐一核对，四资产的 eval_inputs **全部为「应处理」型正例输入，均无近邻负例与 adversarial（相关但误导）用例**——monthly-report-ppt golden 中唯一含 "negative" 字样的是 `ab_tasks[1]/id = "ab2-small-negative-sample"`（任务编号，非负例用例）。配比上 monthly-report-ppt eval_inputs=3、paper-to-skill=2，均低于 SPEC §2.1（:154）「正例 ≥4」线；meeting-minutes=4、ppt-method-router=20 达到条数但类型单一。paper-to-skill 另有 ab_tasks=2（<≥3）双重不达标。按 SPEC「三类用例缺一即验收不通过」口径，**四资产的盲评与验收结论均叠加「用例集类型覆盖不全」一层保留**（明细见 6.2#5）。
5. **monthly-report-ppt 的口径张力**：下发 evalPassed=false 与盘内存量产物复跑 16/16 并存，需按同一版 golden 复现官方评测后复裁；裁决前以任务下发口径为准（总体方案 §3.2 披露）。
6. 本会话未重跑双臂盲评（成本原因）——Δ/胜率沿用「下发=盘内」一致口径，第二轮盲评须按 SPEC 补齐重复次数后执行。

---

## 五、三份方案的位置与要点指针

| 文件 | 位置 | 要点指针 |
|---|---|---|
| **SKILL-SPEC v0.1**（标准/门禁） | `skillfactory/standard/SKILL-SPEC-v0.1.md`（386 行） | §1 格式规范（六必填字段 :59-76、description 三段式 :78-91、渐进披露 :93-108、兼容矩阵与 build 变体 :110-144）；§2 质量红线（写后回读三态/验收矩阵/脚本门卫 :157-166、防幻觉 :168-176）；§3 评价体系（golden schema :205-253、盲评协议 :255-263）；**§4 五门验收线 :266-276**（资产准入=生产门禁）；§5 蒸馏边界与融合路由规范 :280-300；附录 A 骨架模板 :312-352、附录 B 验收检查单 :354-365、附录 C 证据索引 :367-384 |
| **总体方案 v2.0**（生产与商业模式） | `skillfactory/plan/总体方案.md` | §一 执行摘要与现状一页账（:28-34，含工程欠账六条实查记录）；§二 三源管线（S1 开源借鉴 / S2 论文蒸馏 / S3 厂商搬运融合，:38-131）+ 产能模型「写了不算过了才算」（:97-117）+ intent-router 融合模式与首批教训（:119-131）；§三 评价与迭代体系（首批实测解读 :145-163、「普通模型+skill」bench 护城河 :172-182、体检报告即分发物料 :186-197、三信号迭代循环 :199-208）；§四 商业模式四阶段（圈量期判断 :214-216 → 阶段 0 免费铺量 :218-229 → 阶段 1 课程变现 199–1999 元带 :231-237 → 阶段 2 订阅与定制 :239-247 → 阶段 3 治理面托管 :249-253）与风险纪律七条（不赌分成/不签独家/期限资产/供应链自证/负增益自我管理等，:255-263）；§五 课程体系与课程×资产对照表（课程二首发、课程四返工解锁，:267-283）；§六 十项基建资产清单（:319-332）；§七 90 天路线图与 KPI 表（:336-381） |
| **治理面输出方案 v0.3**（治理输出） | `skillfactory/plan/治理面输出方案.md` | **§0 材料实态与本轮实测核验（V0–V10 检查表 :16-31 + 首批资产台账 :32-43 + P0 返工单六项 :45-56）——本报告第六节的直接依据**；§2 个人版最小可用包 skilldock v0 四件（注入器 fail-closed / consent 开关默认关 / 轻量观测 shim lens，与 eunomia-bpf/AgentSight 路线明确切割 / 升级权益兑现，:74-128）；§3 企业版套件（私有 registry、审计计量单表、租约裁剪版、定制 holdout 评测服务=最高毛利件，:132-168）；§4 **skill 与 MCP 两类资产**的注入与管理（三态生命周期 current/fallback/hidden :179-183、sha256 双钉 :185-189、评测报告随包缺报告=不可分发 :202-206、失效停更 :208-213、**§4.6 MCP 通道：mcpServers 配置片段+@exact 版本钉+启动前校验+network/fs-write 类强制 consent :215-219**）；§5 与 CloudCrane 逐项对接（直接复用/裁剪复用/不输出/新建四表，:222-268）；§6 风险（R1 命名切割最高优先——与 eunomia-bpf/AgentSight 撞名且路线相悖，定名前四重查重 :274-283；R2 隐私合规；R3 平台依赖；R4 供应链；R5 内部件【建成·未复核】的诚实声明 :302-304）；§7 路线图（P0 立即/D0-30/D31-60/D61-90，:308-315） |

三者关系：**SPEC 是门禁**（条款可判定、五门全过才可分发），**总体方案是作战图**（怎么产、怎么证、怎么卖、90 天干什么），**治理方案是输出面**（资产怎么装进客户环境、治理怎么随行、对内部件的依赖边界）。四路侦察为三者供证：厂商逆向 → SPEC 条款与差异化空位；外部标准 → 格式对齐与评测 SOP；分发调研 → 渠道节奏与商业纪律。

**自含摘要（读者不开两份方案即可得的四组要点；详细论证见上表指针）：**

- **商业模式**：现状=所有 skill 分发平台免费、平台内卖 skill 零证据，行业处「圈量期」（6–12 个月窗口）；演进四阶段=免费铺量（北极星：≥3 条外部用户装用证据）→ 课程变现（199–1999 元带）→ 订阅与 ToB 定制（consent-first 轨迹回流换技能升级 / 模板工程按件计价）→ 治理面托管；全阶段纪律=不赌分成、不签独家、平台流量是期限资产、审核供应链自证。
- **课程体系**：免费技能即引流（免费单点=过验收资产）、付费交付端到端成果（学员带走产线+skill 包+验收单）、学员工坊产出过五门后反哺工厂；课程二（会议纪要）首发←meeting-minutes 已过评测门，课程四（月度汇报）←monthly-report-ppt 返工后解锁；课程即评测场（学员真实素材 consent+脱敏回流黄金集）。
- **十项基建**：黄金评测集、eval runner 框架、spec 模板库、oracle 配方库、MCP server 集、模板工程（PPT VI/公文规则/店铺 Schema）、SOP 文档、蒸馏语料库台账、治理随行包（consent+观测 shim）、自有「普通模型+skill」增益榜——均为「一次建设、处处复利」件，与 skill 资产同等带版本管理。
- **治理输出（skill 与 MCP 两类资产）**：三件可售/共用输出=① 个人版 skilldock v0 + ② 企业版（私有 registry、审计计量、租约裁剪版、定制 holdout 评测服务）+ ③ 资产分发体系（build 渠道变体、MANIFEST sha256 双钉、评测报告随包——缺报告=不可分发、失效停更流程、MCP 通道版本钉+权限确认）。

---

## 六、风险与返工清单

### 6.1 未接受项怎么修（按拒因分路）

**① monthly-report-ppt（确定性门未过 → 复裁 + 返工）**
1. 先复裁再改实现：对现行 golden.json **全量重跑**并落盘 `eval/results/benchmark.json`、归档失败轮现场——盘内存量产物本会话复跑已过（16/16），实现可能已达线，但按纪律「重生成实现必须对同一版 golden 全量回归 + 记录落盘」后方可裁定；裁定前不进分发（治理方案 §0.3 第 4 条）。
2. 形式门补齐：front-matter 仅 name+description（本会话读取其 `package/SKILL.md` 确认），需补 version/license/permissions/metadata 四字段、description 改三段式；补资产根 CHANGELOG.md。
3. 解锁价值：返工过线后排期课程四（总体方案 §5.2 课程×资产对照表）。

**② ppt-method-router（盲评 Δ=0 → 技能本体迭代）**
1. 迭代方向=**方法 references 的执行质量 + 证据留存契约，路由逻辑不动**——路由确定性已证（机判一致率 100%），把「每次运行落盘原始 stdout + sha256 溯源清单、输出报告强制逐问作答节」写进 SKILL.md 正文（负场败因即复跑临时证据被清理、缺逐问作答节；治理方案 §0.3 第 5 条）。
2. 把平局场景的差异化做实：增益必须体现在 rubric 可分维度上；每方法至少 1 条 ab_task 度量端到端质量，防「路由对、东西差」（总体方案 §2.6）。
3. 形式门欠账（front-matter 仅 2 字段）与 monthly-report-ppt 同单补齐。

**③ paper-to-skill（Δ=−0.5、胜率 0 → 先归因再裁决）**
1. 先做失败归因（SkillTriage 式五类归因），再裁决「迭代 or 降级为纯脚手架工具」（总体方案 §2.3/§3.6）——负 Δ 说明 skill 内容可能误导实现，微调重评不够。
2. 按裁判实测败因修蒸馏模板三处：①模板必须要求产出可运行参考实现并实跑验证；②坑点清单必须含平台差异类（POSIX/Windows 行为分叉，如 `os.rename` 静默覆盖）；③产物 SKILL.md 禁止混入评测元叙事（「treatment 组」「评测装置」等词不得出现在交付文本）。
3. 补 golden 配比：eval_inputs 迁移到 §3.2 schema 并补齐三类用例（现仅 2 条）、ab_tasks 增至 ≥3（现 2 条）；删除 `paper-to-skill/NUL`（456 字节杂散文件，违反 SPEC §1.1 打包卫生；本会话 ls 确认在位）。

### 6.2 已接受资产与全批共性欠账（P0，全部资产适用）

本会话实际核验（`find` 落盘件与 `build.py` 零命中；逐包读 front-matter；逐资产根查 CHANGELOG；4 份 golden.json 实读）：

| # | 欠账 | 证据（本会话实查） | 修法 |
|---|---|---|---|
| 1 | 四资产均无 `eval/results/benchmark.json`，全库无五门验收单落盘 | find 零命中 | 按 SPEC §1.1/§4 补落盘；盲评数字按第三节台账登记为本轮记录并注明轮次 |
| 2 | 四资产均无 `MANIFEST.json`、`eval/protocol.md` | find 零命中 | 发布前生成逐文件 sha256 清单（SPEC §2.5）；补盲评协议文件（SPEC §3.3） |
| 3 | monthly-report-ppt、ppt-method-router front-matter 仅 2 字段且 description 非三段式 | 逐包读取确认；description 全文本会话实读：两者均无「当用户…时使用」触发句与 ≥3 个口语触发短语（SPEC §1.3 触发段），monthly-report-ppt 无边界段，ppt-method-router 仅「只做路由决策，不执行制作」一句范围声明、无指名转交哪个 skill 的边界段 | 补齐六字段、description 按能力段+触发段+边界段重写；暂不补者按 SPEC §6.3 书面豁免（豁免不构成先例） |
| 4 | 仅 meeting-minutes 有资产根 CHANGELOG.md | `ls assets/*/CHANGELOG.md` 仅 1 命中 | 另三资产补建并记录首轮验收 |
| 5 | 四包 SKILL.md 均在 `package/` 子目录而非包根；4 份 golden.json 均为 `case/input/output` 旧 schema，且**三类用例配比全批不达标**（逐资产：meeting-minutes eval_inputs=4 条全正例；monthly-report-ppt=3 条全正例、<正例 ≥4 线；ppt-method-router=20 条全正例；paper-to-skill=2 条全正例、<4 且 ab_tasks=2<3——四者均无 negative/adversarial 用例，见 4.3-4） | `ls assets/*/SKILL.md` 零命中于包根；4 份 golden 实读 + 逐条内容核对 | 按 SPEC §1.1 归位包根；golden 迁移到 §3.2 schema（id/type/prompt/checks）并按 §2.1 补齐三类用例配比（正例 ≥4、近邻负例 ≥正例 50%、adversarial ≥1），补齐前各资产验收结论维持「待复检」 |
| 6 | 盲评无每臂 ≥3 重复、效率门无 token/耗时记录 | 三份 ab_summary 每任务 1 对裁决；benchmark.json 缺失 | 第二轮盲评补重复；落盘时同步记录效率比率（SPEC §3.3 第 6 条），否则门 3 形同虚设 |
| 7 | `build.py` 渠道变体生成器未建 | find 零命中 | D0–30 最小实现 standard + claude-code 两变体（SPEC §1.5.2） |

### 6.3 方法论风险与下一步

1. **三个被拒资产的去向全部落定是 D30 硬节点**（总体方案 KPI #10）：monthly-report-ppt 复裁裁决 / ppt-method-router 二次盲评 / paper-to-skill 归因裁决——形成首批完整的「拒→改→复判」档案，同时是课程五教材与对外内容素材（「我们的每个技能都有体检报告，被拒的也会公示拒因」）。
2. **第二轮盲评按 spec 补规模**：每臂 ≥3 重复、paper-to-skill 增补 ab_tasks 至 ≥3；首轮数字对外引用时一律注明「每臂 1 对裁决的首轮信号」；单模型结论不可迁移，双模型矩阵 D31–60。
3. **评测记录落盘制度化**：monthly-report-ppt 的「失败不可复核」是反面教材——失败现场与成功现场同等归档（评测只增不删）；本轮 `assets/_report_check/` 已留存本会话复跑产物（reeval_*.json + 空 .err）。
4. **对外承诺前置条件**：治理方案 R1（命名切割与四重查重）与 R2（Langfuse 终端侧可达性复测；其 V8 单机 200 实测不构成 SLA）在向客户承诺前必须完成。
5. **节奏**：三拒闭环 → 四资产形式门复检 + 落盘补齐 → runner 框架抽取（四包 runner 已同构）→ build.py 两变体 → WorkBuddy/Qoder 首批 1–3 资产带体检报告上架（以复检通过为准）→ 课程二产线缺件。KPI 基线见总体方案 §7.2（过五门资产 1、上架 0、体检报告覆盖 0%）。
6. **对外引用外部数字前必须逐项复核原始来源**：本报告与 SPEC 的部分差异化论据——agentskills.io「40+ 客户端」、SkillsBench 增益（33.9%→50.5%）、SWE-Skills-Bench token +451%、arXiv:2608.11888 失败分类（Task-Implementation Fault 68.8%）、「四家厂商均无技能质量度量」等——全部来自任务下发侦察的**转述口径**，本会话与本轮审读均未访问原始来源（仅豆包 106 包与 CATALOG.md:22 两项获本地佐证）。内部使用时保持转述标注；写入对外材料、客户交付物或 SPEC 修订依据前，逐项复核并留存取证（页面快照/原文摘录），复核不过的数字不得外引。

---

## 附录 A：本会话核验记录（可复跑）

```text
工作目录：D:\workspace\zcode研究\skillfactory

A1 确定性评测复跑（4 项，均 exit 0，stderr 0 字节；产物存 assets/_report_check/reeval_*.json）：
   python assets/meeting-minutes/eval/runner.py   assets/meeting-minutes/package/out   assets/meeting-minutes/oracle/out
     → exit 0，20/20 检查过（case1–4，含全零边界 case4）
   python assets/monthly-report-ppt/eval/runner.py assets/monthly-report-ppt/package/out assets/monthly-report-ppt/oracle/out
     → exit 0，16/16 检查过（盘内存量产物；不推翻下发 evalPassed=false，见 4.2）
   python assets/ppt-method-router/eval/runner.py  assets/ppt-method-router/package/out  assets/ppt-method-router/oracle/out
     → exit 0，6/6 检查过，路由一致率 20/20=1.0（阈值 0.8）
   python assets/paper-to-skill/eval/runner.py     assets/paper-to-skill/package/out     assets/paper-to-skill/oracle/out
     → exit 0，3/3 检查过（五要素齐/步骤可判定/统计偏差最大 0.0%）

A1' 红检实测（空目录应报失败）：
   python assets/meeting-minutes/eval/runner.py <空目录> assets/meeting-minutes/oracle/out   → exit 1，ok:false
   python assets/monthly-report-ppt/eval/runner.py <空目录> assets/monthly-report-ppt/oracle/out → exit 1，units_found fail

A2 盲评数字对账（读取三份 tests/ab_summary.json，与任务下发 assetInventory 逐项一致）：
   meeting-minutes：tasks=3，baseline 5.667 → treatment 10，delta=4.333，winRate=1
                    （逐任务 7:10 / 4:10 / 6:10，对应下发 abDelta=4.33 / winRate=1）
   ppt-method-router：tasks=3，baseline 8.667 → treatment 8.667，delta=0，winRate=0.333
                    （逐任务 9:8 / 8:9 / 9:9 平，对应下发 0 / 0.33）
   paper-to-skill：tasks=2，baseline 9 → treatment 8.5，delta=-0.5，winRate=0
                    （逐任务 9:8 / 9:9 平，对应下发 -0.5 / 0）
   monthly-report-ppt：无 tests/ 目录（ls 确认）——未进入盲评，与下发 abDelta=null/winRate=null 一致

A3 落盘件与形式门检查：
   find . -name benchmark.json -o -name MANIFEST.json -o -name protocol.md -o -name build.py
     （排除 library 与 .mimosa）→ 0 命中
   ls assets/paper-to-skill/NUL → 456 字节在位
   ls assets/*/CHANGELOG.md → 仅 meeting-minutes 命中
   ls assets/*/SKILL.md → 零命中（四包 SKILL.md 均在 package/ 子目录）
   四包 package/SKILL.md front-matter 逐包读取（awk 提取）：
     meeting-minutes / paper-to-skill 六字段齐（name/version/license/description/permissions/metadata）；
     monthly-report-ppt / ppt-method-router 仅 name+description
   4 份 eval/golden.json 实读：条目键均为 case/input/output（旧 schema，无 id/type/prompt/checks）；
     eval_inputs/ab_tasks 条数 = meeting-minutes 4/3、monthly-report-ppt 3/4、ppt-method-router 20/3、
     paper-to-skill 2/2；四资产 eval_inputs 内容逐条核对均为「应处理」型正例输入，
     均无 negative/adversarial 用例（monthly-report-ppt golden 中唯一 "negative" 字样为
     ab_tasks[1]/id = "ab2-small-negative-sample"，任务编号非负例用例）——按 SPEC §2.1:154
     「三类用例缺一即验收不通过」为全批欠账；paper-to-skill 另有 2<4 与 ab_tasks 2<3 双重不达标
   ls assets/meeting-minutes/eval/archive/ → golden-v1.0-20260929.json、golden-v1.1-20260929.json

A4 monthly-report-ppt 非照抄核验：
   diff <(cd assets/monthly-report-ppt/oracle/out && find . -type f -exec sha256sum {} \; | sort) \
        <(cd assets/monthly-report-ppt/package/out && 同上)
     → 15/15 文件哈希全部不同（左 15 行、右 15 行）

A5 本地佐证：
   ls library/doubao | grep -c "^skill-" → 106（与侦察①口径一致）
   sed -n '22p' library/doubao/CATALOG.md → 「内嵌 .git | 3 个包带完整 .git」
   wc -l standard/SKILL-SPEC-v0.1.md → 386

A6 v1.2 修订轮新增核验（2026-09-29，按独立审读意见执行）：
   golden 负例痕迹检索：grep -n negative assets/monthly-report-ppt/eval/golden.json → 仅 :34
     "ab2-small-negative-sample"（ab_tasks[1] 任务编号，非 eval_inputs 负例用例）；
     四份 golden 全文检索 negative/adversarial/route_to → 仅该一处命中
   description 三段式核验：grep "^description:" 两包 package/SKILL.md 全文读取——
     monthly-report-ppt（~100 字）：能力段+确定性声明+脏数据口径，无触发句、无边界段；
     ppt-method-router（~85 字）：能力段+「只做路由决策，不执行制作」范围声明，
     无触发句、无指名转交的边界段 → 两者均不满足 SPEC §1.3 三段式（证实 6.2#3）
   旧稿归档：mv report/DELIVERY.md report/archive/交付报告-旧稿-20260929T0721-已废弃.md
     （归档前核验 sed -n '22p;54p' DELIVERY.md 含旧轮数字 Δ=1.67/0.67，与版本说明所废弃口径吻合）
```

未复跑项（如实声明）：双臂盲评（Δ/胜率为任务下发数字，已与盘内三份 ab_summary.json 逐项对账一致，本会话未重跑双臂）；四路侦察的外部原始来源（agentskills.io、论文基准、平台分发页面等，引用保持转述口径）；治理方案 V8 之外的 Langfuse 终端用户侧网络表现。

---

*（本报告数字口径：第三节资产表与任务下发 assetInventory 一致，且与盘内三份 `tests/ab_summary.json` 逐项核实一致；baseline→treatment 均分与逐任务分数取自 ab_summary.json；确定性评测与红检为本会话实跑。旧稿所载上一轮盲评数字（Δ=1.67/0.67）已废弃——现行 ab_summary.json 为重跑后的定稿轮。本文件替换同日早前版本。）*

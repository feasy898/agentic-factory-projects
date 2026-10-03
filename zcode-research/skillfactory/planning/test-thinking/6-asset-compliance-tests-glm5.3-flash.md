# 资产与合规测试面 · 思考轨迹（GLM-5.3-Flash · 2026-10-03）

> 镜头：资产与合规测试面。核心问题：PLAN §4 资产体系（任务包 bundle、build.py、learner 变体、G0-5 形式合规门、dist 三包修复、组合资产端到端盲评门）需要什么测试才能拦住真实的失败模式。
> 本文是思考轨迹（拆解 + 推理链 + 证据 + 带置信度的倾向），不是成品测试文档——那是撰写者的工作。
> 证据纪律：凡「实测」= 本会话亲手跑的只读命令，附命令与输出要点；凡未跑的，明确写「未跑」。所有行号引用基于 D:\new-workspace\agent-asset 本盘当前状态；PLAN.md 行号按其自身文件。

---

## 1. 展开方法与信息源

### 1.1 镜头问题的拆解

PLAN §4 落到我镜头上的不是六个孤立测试对象，而是「三层一个交界带」：

| 层 | 对象 | PLAN 依据 |
|---|---|---|
| 门本身 | G0-5 形式合规门（新门，塞进 TASK.md:23-26 的 G0 系列） | PLAN §4.3-2（:272） |
| 门作用的对象 | build.py 三变体产物、dist 三包重打包、bundle manifest | PLAN §4.2/§4.3、§7 WS2（:458） |
| 门的替代/扩展 | 体检器分形态（替代豁免注记） | PLAN §4.5（:286-288）、§7 WS10（:472） |
| 资产↔评测交界带 | 任务包 bundle 硬不变量、oracle 哈希门、组合资产端到端盲评门 | PLAN §3.3（:164-181）、§4.4（:278-284）、§7 WS11（:479） |

每个测试对象先过一遍我的职业信条审问——「这个测试拦的是谁的不诚实/谁的无能」：

1. **合规门拦的是「无检查的承诺」**：人类意图 6c 要求「skill/MCP 符合国际通行标准」，而轨迹4 结论 12 的实测结论是「目前没有任何机器检查能证明这一点」。G0-5 之前，这句话是空话；G0-5 本身如果没测试，它就是第二句空话。门没测试 = 门可以被静默弱化、报错退化、作用面漂移，最后变成走过场的橡皮章。
2. **build.py 测试拦的是「规则-实现漂移」**：SPEC §1.5.2（SKILL-SPEC-v0.1.md:130-144）把变体规则写对了，总体方案.md:33/:105/:343/:395 四处记「build.py 未建」——规则齐了工具没建，承诺落空了三个月。build.py 的测试还要拦另一种漂移：**实现做出来了但和规则不一致**（剥离错字段、目录名不对、learner 偷剥 eval/）。
3. **manifest 测试拦的是「分发单元不可追溯」**：bundle 是新的收费单元（PLAN §0.2 意图映射 6b/6c），版本化失败 = 收费对象含糊、升级触达机制（PLAN §6.7）失灵。还有更坏的一种：**台账注水**——manifest.evidence 声称盲评达标但记录不支持。
4. **端到端盲评门拦的是「自我欺骗」**：ppt-method-router 是盘内铁证（REGISTRY.md:27：确定性 6/6 全过、路由一致率 1.0，盲评 Δ0/胜率 33%）——「架构正确≠有增益」。把这个教训制度化成测试，防的是开发者（包括未来的我们自己）用组件绿拼凑组合绿。
5. **红路测试拦的是「门本身的腐败」**：TASK.md:24「红路永远不许修成 exit 0；红路验证纳入每批评测」+ TASK.md:76「禁止改评测阈值/判据凑绿（全卡信用底线）」。合规门的红路 = 故意不合规的包必须被拦。
6. **可见性划分拦的是「背题」**：意图 e 要求防「开发者通过背题让资产看起来好」。本镜头的分界原则：**尺子和形式可见，内容和题目盲态**（§2 链 H）。

### 1.2 信息源清单

**通读**：planning/PLAN.md（630 行全文）；BASELINE.md（338 行全文）；skillfactory/standard/SKILL-SPEC-v0.1.md（395 行全文）；skillfactory/v2/standard/EVAL-SPEC-v0.2.md（430 行全文）；skillfactory/REGISTRY.md（219 行全文）；zcode-research/TASK.md（79 行全文）；planning/thinking/2、4、5（全读，覆盖本镜头的主供轨迹）；轨迹1/轨迹3 按需 grep（bench 侧细节，避免越界复述）。

**实物抽读**：v5/assets/speaker-mapping/eval/runner.py（头部 60 行）；v5/assets/zctl-mcp/contract.md（全文）；v5/assets/acceptor-agent/eval/runner.py（头部）；v5/assets/hotwords/oracle/run_all.py（:25-60）；v3/tools/healthcheck/package/healthcheck.py（:25-165）；classroom/rehearsal/round-1/record.md（全文）；classroom/walkthrough.md（:36-52、:184-192）；classroom/teaching-assets.md（:1-12、:50-60）；v5/eval-round-20261001/scorecard.md（头部）；dist/meeting-minutes-skill/{SKILL.md 头部、MANIFEST.md 头部、目录列表}。

**本会话亲手跑的只读检查**（细节见 §3.1）：
1. 全仓 SKILL.md 合规审计脚本（python，只读遍历 + frontmatter 解析）——复核并精确分解轨迹4 C2 的「29/29」。
2. `where skills-ref` / `pip list | grep -i skill` / `npm ls -g | grep -i skill`——验证校验器可用性。
3. dist 三包 frontmatter 字段集与 name≠目录名实值提取。
4. `ls deploy-pack/package/`——NUL 残留在盘确认。
5. `ls dist/meeting-minutes-skill/`——README.md 在包内、reference/ 与 references/ 并存、MANIFEST.md 为人读表格确认。
6. `git ls-files -- zcode-research/skillfactory/dist`——dist 补迁进 monorepo 的现状确认。
7. `ls deploy-pack/oracle/fixtures/`、`ls zctl-mcp/{package,oracle}/`、`ls v5/eval-round-20261001/`、evalkit/ 不存在确认。
8. `grep REQUIRED_FIELDS healthcheck.py`——两把尺子冲突的实锤。

### 1.3 与其他测试镜头的边界（防重复劳动）

- 盲评协议细节（任务数/n/裁判校验/题面质量/checker 对拍）→ bench 方法镜头（轨迹3 系）。我只测「门把复合线判据执行对了」（BG 组），不测协议本身。
- 模型钉版五元组内容、通道、限流 → eval-ops 镜头（轨迹5 系）。我只测「包里 model_pin.json 存在且字段齐」（PK-1），不验其值真伪。
- holdout 题集的生产与蒸馏 SOP → bench 镜头。我只划「哪些东西必须进 holdout」的边界并测隔离（PK-4、链 H）。
- 课程四层彩排（L0-L3）→ 课程镜头。learner 变体的「学员能自验」我只测物性（eval/ 在包内且 smoke 可跑），彩排归课程。

---

## 2. 关键推理链（含被否决分支）

### 链 A：测「门」还是测「包」？——两层都要，且先解「两把尺子打架」

**考虑过的分支 (a)：只测包**——对 dist 三包重打包产物断言合规。否决理由：门本身无测试 = 门可以被静默弱化。这不纯是假设：本会话实测发现 **healthcheck 与未来的 G0-5 在同一字段上语义相反**——healthcheck.py:34 `REQUIRED_FIELDS = ("name", "version", "license", "description", "permissions")`（要求顶层 version/permissions **非空**才 pass），而 G0-5 按 agentskills.io 白名单要把顶层 version/permissions **剥进 metadata**（SPEC:134 的 standard 变体规则）。WS2 按规划修完 dist 三包后，若 healthcheck 不同步升级，**合规包会被体检打红、不合规包反而体检全绿（现状正是如此：三包体检 A（REGISTRY.md:14-16）与三处不合规并存）**。两把尺子打架而无人发现，恰恰说明「门/尺子自身的测试」是空白。

**采纳 (b)：两层四件**——① 门的实现正确性（绿路 + 红路矩阵 + 精确报错断言 + 工具钉版前置）；② 门与既有体检器的一致性（同一包上两把尺子必须同向）；③ 门作用面的防误用断言；④ 门应用在产物上的回归（重打包包必须过门）。②③ 是本次实测直接催生的，PLAN 没写，属于本镜头对规划的增量。

### 链 B：name=目录名到底在哪一层测？——「29/29」的口径拆穿

轨迹4 C2 实测「29 个 SKILL.md，29/29 name≠父目录名」，PLAN §4.3（:268）照录。本会话复算（§3.1 实验 1）精确分解：

- 轨迹4 的口径是遍历 `{dist, v5/assets, assets, v3/assets, v4/assets}` 五个根，共 29 个 SKILL.md：其中 **25 个有 name 且全部 name≠直接父目录名；4 个无 frontmatter**。
- 但这 25 个「违规」里大部分是**双根结构使然**：canonical 资产的 SKILL.md 住在 `<asset>/package/` 里，直接父目录名是 `package`——name 永远不可能等于它。真正的分发形态违规只有 dist 三包（name=`meeting-minutes` vs 目录=`meeting-minutes-skill`，本会话逐包实读确认）。
- 轨迹2 链 2 缺口 2 其实已经点了这一点（「『skill 目录』实际是 package/，对外分发需目录改名以与 name 一致」），但 PLAN 的行文没有把「测点在哪层」钉死。

**推论（测试设计的关键防误用）**：G0-5 的 `name==目录名` 自检必须作用在**构建产物根**（build.py 输出的分发目录 / dist 包根），不是「SKILL.md 所在的目录」。若撰写者照 PLAN 字面写成「SKILL.md 父目录」，门会对全部 canonical 资产开火——25 个假阳性，门的信用当场破产（学员和开发者学会的第一件事将是「这个门的话不能全信」）。

**配套断言（AC-9）**：门入口对 canonical 源布局（SKILL.md 在 package/ 下）要么拒绝、要么要求显式标注「非分发形态检查」，防止有人拿源目录跑门然后得出「29 个全违规」的恐慌结论。

### 链 C：合规工具本身是依赖——skills-ref 本机未装（实测），且网络断

`where skills-ref`、`pip list`、`npm ls -g` 三查全空（§3.1 实验 2）——**G0-5 的核心外部校验器在本机不存在**。而 SPEC:143 的原文是「上架前必须用渠道校验器跑一遍：官方参考 skills-ref validate（agentskills/agentskills 仓库）对 standard 变体必须通过」。叠加 BASELINE §6-1（:252）的 GitHub 三次 21s 代理超时（R-4），工具获取本身就是 WS2 的第一风险。

**推论**：G0-5 的测试面必须包含一个前置检查（AC-7）：① skills-ref 的版本与来源（URL/commit/哈希）落盘钉版——这是 EVAL-SPEC §4.4「装置钉版」思想在合规工具上的移植，也是 SPEC §6.2 季度复核条款的机器抓手（标准漂移时，钉了版的工具才会被人想起来升级）；② **外部校验器不可用时门必须 fail-closed**（红路先例：v5 一切 runner 的 exit 1 纪律），绝不允许「skills-ref 跳过，其余自检过了就算过」——否则「符合国际标准」的证明又退化成自说自话。曾有分支考虑「先只上自研校验器，skills-ref 以后再说」，否决：自研校验器对标准漂移零感知，恰好复刻「SPEC 写对答案但从不执行」的老病。

### 链 D：build.py 的测试矩阵——三变体 × 五性质，learner 的豁免要钉白名单

build.py 的验收不是「跑通」而是五条性质，每条都能独立失败：

1. **变换正确性**（standard：version→metadata.version、permissions→metadata.permissions、顶层白名单外零字段、产物目录名==name——SPEC:134/:141 逐字对应；claude-code：仅 `<!-- cc-only -->` 标注段生成私字段，无标注必须生成零私字段——SPEC:135 的 absence 断言最容易被偷懒漏测）。
2. **learner 保留 eval/**：PLAN §4.3-1（:271）定义 learner = standard + 人读层 + **不剥离 eval/**。这是交付型课堂的命根（学员能自己复验，轨迹4 §2.7），测试必须断言 learner 产物里 eval/（至少 runner.py + golden.json）在位且 smoke 可跑（绿 exit 0 + 红 exit 1），不是光看目录存在。
3. **豁免的精确边界**：SPEC:54 禁包内 README，learner 的人读层按 O-13 默认值豁免（PLAN:274）。但 PLAN 没钉「人读层是哪些文件名」。若豁免写成「learner 变体允许任意附加文件」，豁免即刻变后门——任何包自称 learner 就能塞任何东西。测试（BP-5）必须钉：人读层文件名集合 ⊆ 白名单（快速开始/常见卡点/故障卡类命名，具体名单是 §5 未决问题 1），canonical 包出 README.md 仍必须被拒。
4. **产物↔源一致性**：除声明变换面（SKILL.md frontmatter、人读层、MANIFEST）外，逐文件 sha256 与源相等；`.git/`/`__pycache__`/缓存/NUL 零容忍（SPEC:55 豆包 3 包带 .git 事故先例；deploy-pack/package/NUL 本会话实测仍在盘）。
5. **重建确定性**：连跑两次产物逐字节一致（无时间戳——v5 runner 契约先例，speaker-mapping runner.py:30「无时间戳，同输入同输出」；scorecard dp01b 字节稳定门先例）；rebuild(源) == 新 dist 建立首个基线后成为长期回归。

**被否决分支**：「build.py 只测 standard 变体，claude-code/learner 后补」——否决。learner 是 WS5 样例课 B 的直接依赖（WS5 依赖 WS2 的 learner 包，PLAN:461），课程开不了课比分发晚更疼；且三个变体共享同一套剥离/一致性机制，边际测试成本极低。

### 链 E：bundle manifest 是 greenfield——测试从 PLAN 字段清单 + 三个仓内先例拼装

本会话确认：仓内 manifest 类工件只有 dist 三包的 `MANIFEST.md`，而那是**人读的目录说明表格**（head 实读：顶层条目用途表），不是 SPEC §2.5 要求的「逐文件 sha256 + 文件大小 + 总数」的 `MANIFEST.json`；bundle 级 manifest（name/version/form/standards/task_types/dependencies/eval/clients/evidence，PLAN §4.2 :259）无任何先例。

greenfield 测试的推导来源：
- **schema 完整性**：直接对 PLAN §4.2 字段清单逐字段断言（form 必须是 TAXONOMY 14 形态之一——EVAL-SPEC §0.3 与 TAXONOMY.md:180 的「主形态记账」；standards 必须带钉版+查询日期——轨迹2 建议 9）。
- **eval 指纹**：manifest.eval.runner_sha256 必须等于实际文件——先例是 REGISTRY.md:65-79 的三包关键文件 sha256 表和 v5/eval-round-20261001/keyfiles.sha256（19 个关键文件指纹）。
- **版本纪律**：manifest.version == SKILL.md metadata.version == CHANGELOG 头版本，**禁止 latest**——先例 teaching-assets.md:5「latest 不入课堂口径——课堂承诺可复刻，就必须钉版本」。
- **依赖解析**：PLAN §4.6-① 零依赖条款给了绿路（干净 profile 上 import 扫描，轨迹4 C3 的 grep 命令就是现成检测器：全 v5 仅 deploy-pack 3 处 `import yaml`，requests/urllib/httpx 零命中）；红路（未声明依赖/循环/冲突/缺二进制）无先例，标 [假设] 由撰写者按 manifest schema 设计。
- **台账交叉审计（BM-6）**：manifest.evidence 声称的三齐状态必须可从其引用的 benchmark.json **独立复算**——先例是 REGISTRY 附录 A2 的「python 逐份读 ab_summary.json 对账」文化（:108-116）。这条拦的是资产作者最大的不诚实面：在台账里写「盲评达标」而数字不支持。

### 链 F：端到端盲评门的制度化——把 ppt-method-router 钉成永久负例

PLAN §4.4 铁律（:280）已经是政策；政策要变成测试需要三件，缺一件就还是纸面：

1. **复合线计算审计（BG-1）**：给定 benchmark.json，审计器独立重算 Δ、任务级胜率、反向任务数，与 acceptance.blind_detail 三布尔逐一对账。判据全部来自 EVAL-SPEC §3.6（:176-186，「验收记录必须逐条给出三条件的实算值」）。先例：REGISTRY 附录 A2 的实读对账 + 2026-09-30 的「majority 修正后重算」记录（REGISTRY.md:14）——证明人工对账真实发生过，值得机械化。
2. **永久负例回归（BG-2）**：把 ppt-method-router 的评测记录形态（确定性 6/6 exit 0 + 路由一致率 1.0 + Δ0/胜率 33%）做成 golden 负 fixture，门必须输出 NO，且拒绝理由必须恰好是复合线未达——不许因为别的旁支理由碰巧拒绝（那样负例就失去了针对性）。这条 fixture 是盘内既有公开材料（REGISTRY.md:27 + assets/ppt-method-router/tests/ab_summary.json），不构成背题面：它是历史事实，不是可优化的题。
3. **判据排除断言（BG-3）**：组合资产的 acceptance 判据字段里不得出现中间指标（路由一致率、组件确定性门、组件体检级）。ppt-method-router 事件的机制正是「组件指标全绿」在心理上替代了「端到端增益」；断言层面排掉它，比指望 reviewer 记得铁律可靠。

**配套（BG-4/BG-5）**：组合臂实际挂载的组件版本必须与 bundle manifest.dependencies 一致（盲评的组合 ≠ 卖的组合）；kit 评测的 token 补偿控制（EVAL-SPEC §6.3-2，:296-297 baseline 臂放等量中性占位文档）要有落盘记录可查。这两条拦的是「混装后反而变差不可知」（PLAN §4.2 :264）之外的另一种漂移：评的时候是 v1+v2，卖的时候是 v1.1+v2。

### 链 G：任务包与 oracle 哈希门——「runner 零改动」要从未成文纪律变机检

PLAN §3.3 的两条硬不变量（:177-181）全部有盘内血案背书，测试逐条对应：

- **oracle 树 sha256 前后一致（PK-5）**：机制实证 = hotwords/oracle/run_all.py:31 `OUT = os.path.join(HERE, "out")` + :56-58 `if os.path.isdir(OUT): shutil.rmtree(OUT)`（本会话 sed 实读原文）；事故实证 = record.md:42 缺陷 D3「实际触发一次」。这条门是「防装置自杀」，其测试除了绿路（正常跑批哈希不变）还要红路：故意在跑批中间往 oracle/ 写一个字节 → harness 必须 abort 而不是继续评分。
- **runner 零改动机检（PK-6）**：TASK.md:76 红线 + record.md:48 的核查方式（「git diff runner.py 全部为 0 行变更」）已经演示了机检形态。薄封套方案（轨迹5 §2.3 选项 B）下，测试断言三件事：包内 checks/run_check.py 存在且只是 import+透传（不含判分逻辑副本）；包内不存在 runner.py 的拷贝（防漂移——拷贝出来的副本会让「分数对着哪版 runner 算」失去文件级答案）；每轮收口时资产树 runner 的 git diff 面为 0。
- **brief 双臂逐字相同 + 禁资产名（PK-2/PK-3）**：EVAL-SPEC §4.3-2（:223）原文「两臂任务 prompt 逐字相同；禁止在任何臂的 prompt 中提示资产存在」。机检形态：两臂落盘的 brief 副本 sha256 相等；brief.md + inputs/ 全文本对资产名与「你有一个技能可用」类暗示句式做扫描（负例句式库标注 [假设]，首版覆盖：资产名清单 + 少量暗示模板）。
- **臂树隔离实测（PK-4）**：PLAN §5.4 第 1 步的 abort 判据原文「baseline 树能摸到任一资产文件」（:338）——直接升格为每轮断言，不止 MVP 一次。

### 链 H：可见性分界——尺子可见、题目盲态；防背题在本镜头的三个落点

意图 e（防背题）在本镜头的具体化。分界原则与推演：

| 类 | 内容 | 理由 |
|---|---|---|
| **开发者可见** | G0-5 门代码 + 全部红 fixtures（不合规包样本）；build.py 及其全部测试；manifest schema 与依赖解析器；oracle 哈希门；PK-1/2/3/5/6 结构机检；体检器分形态 golden+红 fixtures；Windows 卫生门 | 这些是**尺子与形式**：知道尺子长什么样无法帮你把「内容不好」伪装成「内容好」，只能帮你把包做合规——这正是我们想要的激励方向。红路 fixtures 公开另有一个正面先例：walkthrough.md:44-49 本来就教学员公开跑红路（「红路退出码为 0 即评测器被破坏」）——「评测器有牙」是卖点是公开信息 |
| **holdout** | 组合资产端到端盲评的题目集与 rubric（BG 组判定所依据的任务文本）；holdout 10 题池（PLAN §3.4）；nonce 种子登记 | 这些是**内容性判据**：题目进资产作者上下文 = 背题通道打开。PLAN §3.4 纪律原文「holdout 题永不进入任何资产作者/迭代者上下文」（:194） |
| **灰区（可见但不构成题面）** | BG-2 的 ppt-method-router 历史记录作负例 fixture；BG-1 审计器逻辑本身 | 前者是历史事实不可「针对优化」；后者公开反而防注水（审计器越透明，台账作弊越难） |

防背题三机制在本镜头的落点（与 bench 镜头分工）：
1. **物理隔离 + 访问纪律**（PLAN §3.5-2 / O-11）：本镜头的增量是 PK-4 把「隔离」从纪律变成每轮断言。
2. **转录扫描**（EVAL-SPEC §4.3-3「污染即作废」）：bench 镜头own；本镜头只保证资产侧被扫描的正文有确定清单（manifest 可列资产正文文件集）。
3. **manifest/台账交叉审计（BM-6）**：本镜头独有——拦的不是「模型背题」而是「人改台账」，这是资产作者最便宜的一条作弊路（改一行 REGISTRY/manifest 比训练资产便宜得多）。

### 链 I：Windows 事故族的打包卫生门——三个前科都在盘内

- **NUL 保留名**：`v5/assets/deploy-pack/package/NUL` 本会话 `ls` 仍在盘（PLAN §9.4 :552 已列清理项但未清）；BASELINE:267 的机制结论是「git 层面删除永远清不掉磁盘本体」。build.py/打包器必须自带保留名扫描（HY-1），且扫描要在**写入前**（打包输入侧）与**产物侧**各一道——dist 补迁后（本会话 git ls-files 实证 dist 已入 monorepo）打包输入面比以前更杂。
- **CRLF**：K-5 发布 checklist 已含 CRLF 复核（TASK.md:36），但那是人检；升机检（HY-2）。healthcheck 的 read_text_flex 连 gbk 都容忍（healthcheck.py:129-132 实读）——体检器的宽容不应传染给发布门。
- **非纯 JSON 留档**：hw_student_eval.json 前科（BASELINE:270-271，json.load 直接炸）——HY-3 对一切评测留档做 json.load 断言。

### 被否决分支汇总

| # | 被否决的主张 | 否决理由 |
|---|---|---|
| 1 | 全仓 29 个 SKILL.md 一次性修到 name==父目录名 | 双根结构使大部分「违规」为结构性；把 oracle 产物/ab 测试材料里的 SKILL.md 也拉进合规面 = 测试变噪音制造机。分层：canonical（发布前必修）→ dist（K-5 前必修）→ 历史产物/测试材料（不修，明确标注非资产） |
| 2 | 把 G0-5 检查塞进 healthcheck 一起跑 | healthcheck R4 与 G0-5 语义相反（链 A 实测）；先解冲突再谈合并，否则合并的产物两头不是 |
| 3 | learner 变体豁免全部形式检查 | 豁免必须钉白名单（链 D-3），否则豁免即后门 |
| 4 | skills-ref 不可用时用自研校验器顶替并视为等价 | 自研对标准漂移零感知；正确形态是 fail-closed + 工具钉版（链 C） |
| 5 | 红路 fixtures 进 holdout | 红路 fixtures 测「门的拦截面」不测「资产内容」，公开是卖点（walkthrough 先例）；holdout 留给内容性盲评题 |
| 6 | 用 healthcheck 5 项直接当 MCP/agent-config 的体检 | 形态错配先例（REGISTRY.md:166 注 1、:194 注 A1 已登记为 C+豁免）；分形态体检项是新写，旧 5 项冻结为 dist skill 形态专用 |
| 7 | oracle 哈希门只在 MVP 跑一次 | 参照区被清空的事故源（run_all.py rmtree）常驻盘内，门必须每轮跑批前后各一次（PLAN §3.3 原文即此意，测试不得弱化） |
| 8 | 组合资产先用确定性门放行、盲评后补 | 恰是 ppt-method-router 的翻版路线；WS11 验收门原文即「端到端盲评复合线（§4.4 铁律）」（PLAN:479），无豁免分支 |

---

## 3. 证据

### 3.1 本会话亲手跑的检查（只读；命令与输出要点）

| # | 命令（要点） | 输出要点 |
|---|---|---|
| E1 | python 遍历 `skillfactory/` 全部 SKILL.md，解析 frontmatter | **34 个**；轨迹4 口径（dist,v5/assets,assets,v3/assets,v4/assets 五根）内**恰 29 个**：25 个有 name 且 25/25 name≠直接父目录名，4 个无 frontmatter（v3/assets/office-templates、v3/assets/prompt-regression、v4/assets/mcp-office-pack、v4/assets/office-eval-suite 的 package/SKILL.md）——**轨迹4 C2 的 29/29 精确复现并分解** |
| E2 | `where skills-ref` + `pip list \| grep -i skill` + `npm ls -g --depth=0 \| grep -i skill` | 三查全空——**skills-ref 本机未安装** |
| E3 | 同一脚本提取 dist 三包 frontmatter | 三包字段集均 = `[description, license, metadata, name, permissions, version]`（顶层 version/permissions 在场）；name 实值：`hot-templates`/`meeting-minutes`/`office-templates` vs 目录 `*-skill`——**三处不合规逐包实锤** |
| E4 | `ls v5/assets/deploy-pack/package/` | `NUL` 仍在盘（连同 README.md/SKILL.md/gen_deploy.py/out/validate.py） |
| E5 | `ls dist/meeting-minutes-skill/` | 含 `README.md`（SPEC:54 冲突在实物中）；`reference/`（内为 inputs/、out/ 运行产物）与 `references/`（三份细则 md）**并存**；`MANIFEST.md` head 为人读表格（非 sha256 清单） |
| E6 | `git ls-files -- zcode-research/skillfactory/dist` + dist 内 `git log` | dist 文件已被 monorepo 跟踪、无嵌套 .git（`18f6ead` 即 HEAD）——**dist 补迁已完成**，与 REGISTRY.md:203 时点状态不同（引用旧状态会失真） |
| E7 | `ls v5/assets/deploy-pack/oracle/fixtures/` | `red-bad-yaml` `red-env-drift` `red-hardcoded-secret` `red-missing-service` + `services-canonical.txt` `services-invalid.txt` `services-subset.txt`——红路矩阵实物 |
| E8 | `ls v5/assets/zctl-mcp/{package,oracle}/` | package/{INSTALL.md, mcp-server.mjs} + oracle/expected_tools.json——PLAN §4.2 mcp 布局契约的实物样板 |
| E9 | `ls D:/new-workspace/agent-asset/evalkit` | 不存在——O-17 两段式落盘位尚未建，测试落点要等 WS1 定 |
| E10 | `grep REQUIRED_FIELDS healthcheck.py` | `:34 REQUIRED_FIELDS = ("name", "version", "license", "description", "permissions")`——**体检器要求顶层 version/permissions 非空，与 G0-5 白名单语义相反** |
| E11 | `sed -n '25,60p' hotwords/oracle/run_all.py` | `:31 OUT = os.path.join(HERE, "out")`；`:56-57 if os.path.isdir(OUT): shutil.rmtree(OUT)`、`:58 os.makedirs(OUT)`——D3 事故源逐行确认 |
| E12 | `head -60 v5/eval-round-20261001/scorecard.md` + `ls` 该目录 | 「41 项门，PASS 38 / FAIL 3」；目录含逐门 stdout/stderr + results.tsv + keyfiles.sha256——PLAN §3.6 引证成立 |

**本会话未跑**（如实声明）：未运行任何 v5 runner（绿/红/用法三态未在本会话复现，采信 BASELINE.md:99-100 的 A 级记载）；未尝试安装或联网获取 skills-ref（网络不可达为盘内既证事实，且红线禁止安装行为）；未实现 build.py 或任何门的原型；未读 planning/test-thinking/ 下其他测试思考者文件。

### 3.2 文献证据表（path:line）

| 主张 | 证据 |
|---|---|
| G0-1..G0-4 门系列与「红路验证纳入每批评测」 | afp-clone/zcode-research/TASK.md:23-26 |
| 红线：禁改阈值凑绿、样本分离 | TASK.md:76 |
| K-5 唯一人工例外（CRLF 复核 + 不可代签） | TASK.md:36 |
| SPEC：目录名=name、禁 README、字段表、自造字段禁令 | skillfactory/standard/SKILL-SPEC-v0.1.md:36/:54/:59-76/:76 |
| SPEC 自记「agentskills.io 无此字段：version/permissions（顶层）」 | SKILL-SPEC-v0.1.md:124-125 |
| standard 变体剥离规则 / 产物目录名=name / skills-ref validate 强制 | SKILL-SPEC-v0.1.md:134/:141/:143 |
| 形式门（五门之 4）全口径 | SKILL-SPEC-v0.1.md:273 |
| 打包卫生（.git 事故先例、MANIFEST.json 逐文件 sha256） | SKILL-SPEC-v0.1.md:55/:187 |
| eval 三态 exit 0/1/2、无时间戳确定性契约 | v5/assets/speaker-mapping/eval/runner.py:5-9/:30 |
| zctl-mcp 冻结项 F1-F4 与红路条款 | v5/assets/zctl-mcp/contract.md:21-24/:26-31 |
| acceptor-agent 四检查（含 no_employment_promise 承诺词反向） | v5/assets/acceptor-agent/eval/runner.py:12-17 |
| healthcheck 5 检查项与五字段要求 | v3/tools/healthcheck/package/healthcheck.py:30/:34 |
| 体检器形态错配豁免（对新形态不适用） | REGISTRY.md:166（注 1）/:194（注 A1） |
| ppt-method-router：确定性 6/6 + 一致率 1.0 + 盲评 Δ0/33% | REGISTRY.md:27 |
| 三齐口径 / dist 三包行 / sha256 表 | REGISTRY.md:5/:14-16/:65-79 |
| REGISTRY 附录 A2 盲评数字实读对账（python 逐份） | REGISTRY.md:108-116 |
| K-5 时点状态（注意已被 E6 的补迁现状取代） | REGISTRY.md:203 |
| build.py 四处「未建」 | skillfactory/plan/总体方案.md:33/:105/:343/:395 |
| 复合线三条件（Δ≥1.0 ∧ 胜率≥60% ∧ 反向≤1）与实算值落盘义务 | v2/standard/EVAL-SPEC-v0.2.md:176-186 |
| 公平性禁令（prompt 逐字同/禁资产名/污染即作废/物理隔离） | EVAL-SPEC-v0.2.md:220-226 |
| 装置钉版与不可比条款 | EVAL-SPEC-v0.2.md:228-231 |
| 整包 kit 评测 + token 补偿控制 | EVAL-SPEC-v0.2.md:292-299 |
| 评测集对拍 ≥95% 门（从未执行的欠账） | EVAL-SPEC-v0.2.md:303 |
| 六门一览（形式门=门 4） | EVAL-SPEC-v0.2.md:313-321 |
| benchmark.json 三层 schema（acceptance.blind_detail 可复算结构） | EVAL-SPEC-v0.2.md:334-354 |
| 彩排缺陷 D1-D5（D3=参照区被清空；:48=runner 零改动核查方式） | classroom/rehearsal/round-1/record.md:36-44/:48 |
| 红路公开跑进课堂（fixtures 可见性的正面先例） | classroom/walkthrough.md:44-49 |
| scratch 红线（禁在 oracle/ 原地跑） | classroom/walkthrough.md:184-192（:187-190 红线框） |
| latest 不入课堂口径 + 升版三步 | classroom/teaching-assets.md:5/:55-57 |
| 任务包格式与两条硬不变量、薄封套、oracle 哈希门 | PLAN.md:164-181（:177-181） |
| holdout 纪律（永不进作者上下文） | PLAN.md:194 |
| bundle 规格 v1（manifest 字段、双根、分形态布局） | PLAN.md:254-264 |
| 合规修复四条（G0-5、dist 修复票、learner、SPEC:54 冲突处置） | PLAN.md:266-276 |
| 组合端到端盲评铁律（ppt-method-router 条款） | PLAN.md:278-284（:280） |
| 体检器分形态扩展（替代豁免注记） | PLAN.md:286-288 |
| WS2 验收门（skills-ref 过 + 确定性门复跑全绿 + 红路 exit 1 + learner 不剥 eval） | PLAN.md:458 |
| WS11 验收门（复合线 + 四臂排后） | PLAN.md:479 |
| O-13（learner/build.py 优先级）、O-17（evalkit 两段式落盘） | PLAN.md:507/:511 |
| Windows 事故族风险 R-7 与卫生项 §9.4 | PLAN.md:530/:550-554 |
| MVP 隔离实测 abort 判据 | PLAN.md:338 |
| 「符合国际标准目前无机器检查能证明」与 learner 变体由来 | 轨迹4（planning/thinking/4）§2.7、结论 12-13；C2 实测 §3.2 |
| dist 三包三处不合规的原始对照 | 轨迹2（planning/thinking/2）链 2 缺口 1；dist/meeting-minutes-skill/SKILL.md:2-11 |
| manifest 字段原料与 standards 钉版+查询日期 | 轨迹2 链 6、建议 9 |
| 薄封套选项 B 与「装置钉版文件层可查」论证 | 轨迹5（planning/thinking/5）§2.3 |

---

## 4. 倾向性结论（每条标置信度）

1. **G0-5 必须测门本身（红路矩阵 + 精确报错 + 工具钉版 + fail-closed），不能只测包。** 「门没测试」的具体现实形态已被实测抓到：healthcheck 与 G0-5 在 version/permissions 字段上语义相反（healthcheck.py:34 vs SPEC:134），若不先做一致性测试，WS2 修完包会出现「合规包体检红」的门禁自相矛盾。置信度：**高**（冲突是实测事实；「必须测门」是工程判断，由该事实强支撑）。
2. **G0-5 的 name==目录名自检必须作用在构建产物根，不是 SKILL.md 的直接父目录。** 29/29 中 25 个是双根结构性偏差（父目录=package），照 PLAN 字面测会制造 25 个假阳性、摧毁门信用。置信度：**高**（实测分解直接支撑）。
3. **skills-ref 本机未装 + GitHub 不可达 ⇒ 工具获取与钉版是 WS2 的第一序风险，测试面必须含「工具不可用即 fail-closed」断言。** 置信度：**高**（三查全空为实测；fail-closed 是 v5 红路纪律的常规延伸）。
4. **learner 变体的豁免必须钉成文件名白名单，且 canonical 包的 README 禁令在豁免生效后仍必须被独立验证。** 置信度：**高**（后门风险是结构性推理；「learner 不剥 eval/」已有 PLAN 条款，测试是把它变可判定）。
5. **bundle manifest 测试是 greenfield，只能从 PLAN §4.2 字段清单 + 三个仓内先例（REGISTRY sha256 表、teaching-assets 钉版纪律、EVAL-SPEC §4.4 钉版思想）拼装；现有 dist 的 MANIFEST.md 是人读表格不是 SPEC 要求的 sha256 清单，重打包时应一并用 build.py 换成 MANIFEST.json。** 置信度：**中高**（实物确认 greenfield；「重打包顺带换 MANIFEST 格式」是实现建议，PLAN 未明说，属本镜头增量）。
6. **组合资产的门要制度化成三件测试（复合线计算审计 / ppt-method-router 永久负例 / 中间指标排除断言），其中审计器复算 acceptance 是防「台账注水」的唯一机器手段。** 置信度：**高**（负面教材是盘内铁证；三件套是 policy→test 的标准转化，逻辑闭合）。
7. **「runner 零改动」已有现成机检形态（record.md:48 的 git diff 面核查），应升格为每轮收口的必跑断言并加「包内无 runner 拷贝」断言。** 置信度：**高**。
8. **oracle 哈希门要有自己的红路测试**（往 oracle/ 写一个字节 → harness 必须 abort），因为门最坏的失败形态不是「没拦住泄漏」而是「参照区没了还在继续评分出全红报告」。置信度：**高**（D3 事故 + run_all.py rmtree 实读支撑）。
9. **可见性分界：合规/构建/manifest/卫生门全部开发者可见（尺子可见不构成背题面）；只有内容性盲评题（组合端到端题目集、holdout 池、nonce 种子）进 holdout。红路 fixtures 公开有 walkthrough 先例且是卖点。** 置信度：**高**（原则性推理 + 先例支撑）。
10. **体检器分形态不能复用 healthcheck 5 项（形态错配已是两轮登记的豁免先例），且新体检器必须自带版本化与「golden+红 fixture」双面测试；旧 5 项冻结为 dist skill 形态专用并限期与 G0-5 对齐。** 置信度：**中高**（形态错配事实硬；「冻结+对齐」的处置是本镜头建议）。
11. **Windows 卫生门（NUL/CRLF/纯 JSON）应作为打包器内建检查而非人工 checklist——三个前科全部在盘内，且 NUL 的 git 层清理已被证明无效。** 置信度：**高**。
12. **dist 包内的 `reference/`（装着 inputs/out 运行产物）与 `references/` 并存是打包卫生缺陷的实物样本**：目录命名与约定冲突 + 产物混入分发包。重打包时 build.py 的「白名单布局」测试应能拦住这类目录（该目录定性归 owner 裁定：历史遗留 or 删除）。置信度：**中**（事实硬；处置建议待定）。

---

## 5. 未决问题

1. **learner 人读层的文件名白名单**（O-13 的实现细节，PLAN 未钉）：`QUICKSTART.md`？`README.md`（若用 README 则与 SPEC:54 的冲突从「变体豁免」变「同名词义分裂」，更糟）？`docs/getting-started.md`？这决定 BP-5 断言的字面。需撰写者向 owner/开发 agent 要一个封闭清单。
2. **skills-ref 的获取与钉版通道**：GitHub 不可达期间从哪拿（npm registry？Go 源码镜像？vendored 进仓？）——AC-7 断言的「来源哈希」字段取决于此。若最终拿不到官方工具，G0-5 的「skills-ref validate 通过」验收门（PLAN:458）无法如实出具，需要 owner 决断降级口径。
3. **healthcheck 的处置**：升级为分形态 v2（G0-5 并入）还是冻结旧 5 项另起新体检器？两把尺子的字段冲突必须在 WS2 写第一行 build.py 之前解，否则测试无法定义「同向」。属实现架构决断，建议撰写者把它列为 WS2 的任务内决策点而非 owner 决断（不影响对外承诺）。
4. **bundle manifest 的落盘位置与机读化**：随包（bundle 根）还是 REGISTRY 机读化（轨迹2 链 6 提过「或入 REGISTRY 机读化」）？影响 BM 组测试的被测对象路径。
5. **dist 三包 `reference/` 目录与包内 README 的处置**：重打包时删除、迁正、还是保留为历史包证据（另建合规版目录）？牵动 K-5 材料口径。
6. **PK-3「禁资产名扫描」的负例句式库**：首版覆盖面（资产名清单 + 暗示句式模板）标 [假设]，需要第一轮真实跑批的转录回填；太窄的句式库会给虚假安全感，撰写者应明写「本扫描是兜底不是防线」。
7. **四臂对照（WS11 排后）的测试先写还是后写**：BG 组的复合线审计在三臂时代已可用；四臂专属断言（组合臂 vs 两单件臂的对比计算）建议推迟到 WS11 启动时再定稿，避免为未稳协议写测试。

---

## 6. 给测试撰写者的建议

### 6.1 候选测试面总表

每条按统一四栏标注：**拦截的失败模式 | 触发方式 | 通过判据 | v5/SPEC 先例**。可见性与工作流归属单列。编号前缀：AC=合规门、BP=build.py、BM=manifest、BG=盲评门、PK=任务包、FC=分形态体检、HY=卫生。

**A 组 · G0-5 形式合规门（开发者可见；WS2）**

| # | 拦截的失败模式 | 触发方式 | 通过判据 | 先例 |
|---|---|---|---|---|
| AC-1 | 门把合规包误杀（假阳性毁门信用） | 对构造的 golden 最小合规包跑门 | exit 0；三自检逐项 PASS；skills-ref validate 通过 | SPEC:143；healthcheck 绿自检形态 |
| AC-2 | name≠产物目录名（dist 三包现状缺陷类） | golden 包产物目录改名（name=foo / 目录=foo-skill） | 门 exit≠0，报错指名 name/directory 不一致 | 本会话 E3 实测三包；SPEC:141 |
| AC-3 | 顶层自造字段（version/permissions/任意） | golden 包分别注入顶层 version、顶层 permissions、一个无名自造字段 | 各自 exit≠0，逐字段报错 | SPEC:76/:124-125；E3 实测 |
| AC-4 | version 未入 metadata（剥了顶层却没落 metadata） | 顶层 version 删除 + metadata.version 缺失 | exit≠0 | SPEC:134 |
| AC-5 | 无 frontmatter / name 缺失 / description 超 1024 | golden 包逐一退化 | 各自 exit≠0 | E1 实测 4 个无 frontmatter 实物；SPEC:63/:66 |
| AC-6 | 门报错退化（拦了但说不清为什么，无法修） | 全部红 fixtures 跑门，断言每个 fixture 恰被其目标规则拦截（非旁支规则碰巧拦） | 逐 fixture 的命中规则==声明规则 | BASELINE.md:100 红路精确报错先例（`empty__m_empty.txt: 第8行 期望=…实测=`） |
| AC-7 | 「工具没装」被当「验证通过」 | 隔离环境中使 skills-ref 不可用跑门 | 门 fail-closed exit≠0 且报「外部校验器不可用」；钉版记录（版本/来源哈希/日期）在位 | EVAL-SPEC §4.4 钉版思想；E2 实测未装 |
| AC-8 | 两把尺子打架（healthcheck 旧 5 项 vs G0-5 白名单） | 同一 golden 包 + 全部红 fixtures 分别过 G0-5 与（升级后）体检器 | 两尺判定逐 fixture 同向 | E10 实测字段冲突；healthcheck.py:34 |
| AC-9 | 门被误用于 canonical 源（25 个结构性假阳性） | 对 `<asset>/package/` 布局跑门 | 门拒绝或要求显式「非分发形态」标注；不产出「违规」结论 | 链 B 实测分解；轨迹2 链2 缺口 2 |

**B 组 · build.py 三变体（开发者可见；WS2）**

| # | 拦截的失败模式 | 触发方式 | 通过判据 | 先例 |
|---|---|---|---|---|
| BP-1 | 变体缺失/形状错 | 对测试源包跑三变体 | 三产物目录存在且布局符合各自契约 | SPEC:132-137 |
| BP-2 | standard 剥离错误（漏剥/错挪/目录名错） | 断言产物 frontmatter：version→metadata.version、permissions→metadata.permissions、顶层白名单外零字段、产物目录名==name | 逐断言过 | SPEC:134/:141 |
| BP-3 | claude-code 私字段无中生有 | 源包含 0 个 cc-only 标注时跑 claude-code 变体 | 产物零私字段（absence 断言）；含标注时恰生成对应字段 | SPEC:135 |
| BP-4 | learner 偷剥 eval/（学员不能自验） | learner 产物内断言 eval/runner.py+golden.json 在位且 smoke 双态可跑（绿 0/红 1） | 在位 + 双态 exit 正确 | PLAN:458（WS2 验收门原文）；PLAN §4.3-1 |
| BP-5 | 豁免变后门（任意文件借 learner 入包） | learner 人读层文件集 ⊄ 白名单；canonical 注入 README.md | 前者被拦且报越界文件名；后者维持被拦 | SPEC:54；O-13 默认值（PLAN:274）；§5 未决 1 |
| BP-6 | 打包夹带（.git/缓存/NUL/未声明文件） | 对产物全文件清单做「声明变换面之外 sha256==源」+ 保留名/缓存目录扫描 | 差异集==空；违禁名零命中 | SPEC:55（豆包 .git 事故）；BASELINE:267（NUL）；E4 实测 |
| BP-7 | 重建不确定（时间戳/顺序噪声进产物） | 连跑两次 build.py 逐字节比对；建立基线后 rebuild(源)==dist | 双跑 diff==空；与 dist 一致 | speaker-mapping runner.py:30（无时间戳契约）；scorecard dp01b 字节稳定门 |
| BP-8 | 变体间互相污染 | learner(standard(源)) vs learner(源) 幂等比对 | 结果一致 | 工程性质，无直接先例（标 [假设]） |
| BP-9 | 重打包包过不了旧门（修合规破坏确定性） | 重打包产物复跑资产确定性门全绿 + 红路 exit 1 | 全绿 + exit 1 | PLAN:458；REGISTRY.md:14-16 复跑先例 |

**C 组 · bundle manifest（BM-1/2/3/4/5/7 开发者可见，BM-6 审计器可见；WS2 起，WS11 加厚）**

| # | 拦截的失败模式 | 触发方式 | 通过判据 | 先例 |
|---|---|---|---|---|
| BM-1 | manifest 字段缺失/form 非法/standards 无查询日期 | schema 校验器跑于 golden manifest + 逐字段缺失变异 | 11 字段齐；form∈TAXONOMY 14 形态；standards 双钉版带日期 | PLAN §4.2（:259）；TAXONOMY.md:180 |
| BM-2 | 包与评测器脱钩（runner 换了 manifest 不知道） | 改 runner 一个字节 → manifest 指纹校验 | sha256 不匹配即 fail | REGISTRY.md:65-79；keyfiles.sha256 |
| BM-3 | 版本三处不一致 / latest 入课堂 | manifest.version vs SKILL.md metadata.version vs CHANGELOG 交叉断言；version=="latest" 注入 | 三处相等；latest 被拒 | teaching-assets.md:5 |
| BM-4 | 依赖漂移（干净环境装不上） | 声明依赖在 stdlib-only / python-docx 两个环境 profile 上解析 | 全部可解析；import 扫描与声明一致 | PLAN §4.6-①；轨迹4 C3 grep 命令 |
| BM-5 | 未声明依赖/循环/冲突/缺外部二进制 | 分别构造四种坏 manifest | 各自被解析器指名拦截 | 无直接先例（greenfield，标 [假设]） |
| BM-6 | 台账注水（evidence 声称与记录不符） | 审计器从 manifest 引用的 benchmark.json 独立复算 Δ/胜率/反向，对账 acceptance | 复算值==声称值；篡改任一数字即 fail | REGISTRY 附录 A2 对账文化（:108-116）；EVAL-SPEC §8.1 |
| BM-7 | form 字段与实物形态不符 | skill 包 manifest 标 mcp → 交叉断言（实物布局 vs form） | 不匹配即 fail | REGISTRY.md:166 形态错配备注 |

**D 组 · 组合资产端到端盲评门（BG-1/2/3 逻辑可见、真实题目集 holdout；WS11，BG-1 可提前到 WS4/WS6 复用）**

| # | 拦截的失败模式 | 触发方式 | 通过判据 | 先例 |
|---|---|---|---|---|
| BG-1 | acceptance 与数字脱节（过了门的假象） | 给审计器喂 benchmark.json（含被篡改变体） | 独立复算 Δ/任务级胜率/反向 == blind_detail 三布尔；篡改必被识破 | EVAL-SPEC §3.6/:186 实算落盘义务；REGISTRY A2 |
| BG-2 | 组件全绿被当成组合有增益（ppt-method-router 复辟） | golden 负 fixture：确定性 6/6+一致率 1.0+Δ0/33% 的记录形态 | 门输出 NO 且拒绝理由==复合线未达（非旁支理由） | REGISTRY.md:27；PLAN:280 |
| BG-3 | 中间指标混进判据 | acceptance 判据字段含「路由一致率/组件确定性/体检级」任一 | schema 校验直接拒绝该字段 | EVAL-SPEC §3.6 表（每条件对应防的伪增益） |
| BG-4 | 盲评的组合≠卖的组合（组件版本漂移） | 盲评记录的组件版本清单 vs bundle manifest.dependencies | 逐组件版本相等 | EVAL-SPEC §4.3-1；teaching-assets 钉版纪律 |
| BG-5 | kit 评测无 token 补偿记录（上下文长短混杂） | 组合轮记录断言占位文档 token 对齐记录在位 | 记录存在且量级对齐 | EVAL-SPEC §6.3-2（:296-297） |

**E 组 · 任务包与 oracle 哈希门（开发者可见；WS1）**

| # | 拦截的失败模式 | 触发方式 | 通过判据 | 先例 |
|---|---|---|---|---|
| PK-1 | 包结构残缺/oracle 泄漏入包/钉版缺失 | 包 conformance 校验：六件齐；oracle/ 不存在断言；model_pin.json 五元组齐 | 结构过 + absence 成立 + 五元组齐 | PLAN §3.3（:166-174）；EVAL-SPEC §4.4 |
| PK-2 | 两臂 brief 不同（不公平对照） | 两臂落盘 brief 副本 sha256 对比 | 相等 | EVAL-SPEC §4.3-2（:223） |
| PK-3 | brief/inputs 暗示资产存在 | 对 brief.md+inputs/ 全文本做资产名与暗示句式扫描 | 零命中 | EVAL-SPEC §4.3-2；句式库标 [假设]（§5 未决 6） |
| PK-4 | baseline 臂摸到资产文件 | baseline 臂 cwd 树 find SKILL.md/oracle/eval | 零命中，命中即 abort | PLAN:338；EVAL-SPEC §4.3-1 |
| PK-5 | 参照区被清空/污染（D3 类） | 跑批前后 oracle 树 sha256 比对 + 红路：中途写 oracle/ 一个字节 | 哈希一致；红路必 abort 且不得继续评分 | hotwords/oracle/run_all.py:31/:56-58（E11 实读）；record.md:42 |
| PK-6 | runner 被改/被复制漂移 | 收口时资产树 runner `git diff` 面断言；包内查 runner.py 拷贝 | diff==0 行；拷贝零命中 | record.md:48；TASK.md:76；轨迹5 §2.3 选项 B |
| PK-7 | 过程错误在产物 diff 上不可见（D1-D5 类） | 转录四类断言：命令面/退出码面/引用面/禁止面 | 断言逐类过 | PLAN §5.3（:326）；record.md:36-44 |

**F 组 · 体检器分形态（开发者可见；WS10）**

| # | 拦截的失败模式 | 触发方式 | 通过判据 | 先例 |
|---|---|---|---|---|
| FC-1 | MCP 资产契约退化（变更类工具暴露） | golden=zctl-mcp 全过；红 fixtures=工具集多一个变更类工具/少工具/改名 | 红路各自 exit≠0 且报 F2/F4 对应项 | zctl-mcp contract.md:21-31；REGISTRY.md:191（7/7） |
| FC-2 | agent 角色包缺禁令/含承诺措辞 | golden=acceptor-agent 全过；红=删禁令节、example 注入「保证就业」 | 红路 exit≠0 | acceptor-agent runner.py:12-17（no_employment_promise 先例） |
| FC-3 | 体检项集合被静默改 | 体检器版本化断言：CHECK 顺序冻结 + 版本号随 report 落盘 | 顺序/版本一致 | healthcheck.py:29-31（R2 冻结先例） |

**G 组 · 发布与 Windows 卫生（开发者可见；随 WS2/K-5）**

| # | 拦截的失败模式 | 触发方式 | 通过判据 | 先例 |
|---|---|---|---|---|
| HY-1 | Windows 保留名入包 | 打包输入+产物双侧保留名扫描（NUL/CON/PRN/AUX/COM1-9/LPT1-9） | 零命中 | BASELINE:267（git 层清理无效的机制实证）；E4（NUL 在盘） |
| HY-2 | CRLF/编码入发布物 | 发布文本文件 CRLF 扫描 + utf-8 严格解码 | 零命中（比 healthcheck 的 gbk 容忍更严） | TASK.md:36（K-5 CRLF 复核人检→机检） |
| HY-3 | 留档非纯 JSON 炸下游 | 全部评测留档 json.load 断言 | 可解析 | BASELINE:270-271（hw_student_eval.json 前科） |
| HY-4 | 发布未获批/测试代签 | evidence/publish-approval.md 存在性与格式断言（只验存在与字段，永不判「已批准」） | 文件在 + 签字位非空由人填；机器侧只读 | TASK.md:36 唯一人工例外；REGISTRY.md:203 |

### 6.2 撰写纪律建议

1. **每条测试落成断言级描述时保留四栏标注**，并加第五栏「篡改容忍度」：这条测试自己被绕过时，靠哪条相邻测试兜底（例如 BP-6 被绕 → BP-7 的重建比对仍能抓到夹带文件；AC-6 保证绕过至少会留下指向不清的报错）。单测试可绕是常态，测试面要有冗余。
2. **门的红 fixtures 从 golden 合规包做最小变异生成**（每次只坏一处），禁止手工维护一堆互不相干的坏包——变异源单一化后，AC-6 的「恰好命中目标规则」断言才可写。deploy-pack oracle/fixtures 的「每个 red 包各被恰一 C 项击穿」（REGISTRY.md:163）是现成的形态样板。
3. **BG 组不要写成「跑一次盲评」**——测试的对象是门对记录的判定，不是盲评本身；真实盲评归 bench 镜头与 WS11 执行。BG-1/2/3 全部零模型可跑，应进每轮收口的机检位。
4. **与 PLAN 行文的两处对齐修正**：撰写时请引用「29 个 SKILL.md（轨迹4 口径）」时带上分解（25 name≠父目录 + 4 无 frontmatter，其中仅 dist 三包为真实分发形态违规），避免 25 个结构性假阳性被写成「待修资产清单」；引用 REGISTRY.md:203 的 K-5 状态时注意 dist 已补迁进 monorepo（本会话 E6 实测），「dist 三包不在快照内」的阻塞已不存在，剩余阻塞是 owner 亲签。
5. **测试代码自身的落盘位置跟随 O-17**：evalkit/ 现不存在（E9 实测），AC/PK 组的门与测试在 WS1/WS2 落地时应与 harness 同址（evalkit → 通过后升格 v6），不要散落进各资产目录——资产目录里长出测试是下一轮「29 个假阳性」式混乱的种子。
6. **不要测的东西**（防范围蔓延）：不测盲评协议的统计细节（bench 镜头）、不验 model_pin 值真伪与通道（eval-ops 镜头）、不为 hook/plugin 形态写体检测试（O-4 已收窄三形态，hook 留接口未展开）、不对历史 oracle 产物里的 SKILL.md 施合规门（链 B 分层）。

---

*本轨迹由测试思考者6（资产与合规镜头 · GLM-5.3-Flash）于 2026-10-03 写成。全程只读既有文件；本文件是本次会话唯一新建物；未修改/删除任何既有文件，未 git commit/push，未触碰封存项目。全部实测命令与输出要点见 §3.1；未跑事项如实声明于 §3.1 末。*

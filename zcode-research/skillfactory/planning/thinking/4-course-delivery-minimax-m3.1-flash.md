# 课程与交付设计 · 思考轨迹（MiniMax-M3.1-Flash · 2026-10-03）

> 镜头：课程与交付设计。产出是**思考轨迹**，不是规划成品。
> 工作区红线：只读一切既有文件；本文件是本次会话唯一新建物；未 commit/push；封存项目未触碰。
> **声明**：本文件中凡标「实测」者，均为本次会话亲手跑的命令/抓的网页，附命令与输出要点；凡未跑的，明确写「未跑」。

---

## 1. 展开方法：我怎么拆解这个问题、信息源清单

### 1.1 拆解顺序

我先把 owner 意图里**带约束力的那几句**抽出来当公理，再让公理去撞仓库现状，而不是先去读现状再想辙：

| owner 原话（近乎逐字） | 我抽出的可操作断言 |
|---|---|
| 「听课只是一种仪式，更多其实是交付——为 Agent 资产的分发收费」 | 收费对象 = **资产分发 + 一次成功的真实交付**；课堂的产出物单位不是「学会了」，而是「机器上多了一个能用的资产 + 一份验收过的产物」 |
| 「讲师不需要懂很多，只要自己知道怎么用 agent 资产」 | 讲师能力 = 「会用 + 会带」；讲师手册必须把**所有判断前置化**，学员只做「执行 + 验收」 |
| 「最后带领学员去用、并交付资产就行」 | **分发动作本身就是课堂高潮**，且必须可被学员当场验证 |
| 「普通个人——公司职员、小老板、个体户」「一定不面向专业开发者」 | 学员画像决定门槛：能装软件、能打字、能点按钮；**不能**要求 clone 仓库 / 终端 / 读 contract |
| 「一定是非专业开发者可以交付的、对他有价值的业务成果」 | 交付物必须是「**他自己的东西**」，不能是「复现范例」 |
| 「必须有真实人类的使用」（第 3 条，迭代到极限才进真实人类使用） | 课程 = bench 的真实分布采集场，不是 bench 的下游消费者 |

### 1.2 信息源清单（全部本次会话读过/抓过）

**仓内（只读）**
- `BASELINE.md`（范围声明 §顶部、§2 能力总表、§3.6 zcode-research 基线卡、§8 修复路径）
- `zcode-research/README.md`（owner 口径、三齐口径、验收基线、已知问题）
- `zcode-research/TASK.md`（K 线 K-1~K-5、P 线、红线、六个会话角色）
- `zcode-research/skillfactory/REGISTRY.md`（18 资产总台账、v5 追加登记、课堂层状态、欠账）
- `zcode-research/skillfactory/classroom/{walkthrough,handbook,teaching-assets}.md` + `rehearsal/round-1/record.md`
- `zcode-research/skillfactory/course/{outline,hooks}.md`（Phase 3 新写，10-03 00:00 落盘）
- `zcode-research/skillfactory/standard/SKILL-SPEC-v0.1.md`（§1.1/§1.2/§1.5）
- `zcode-research/skillfactory/plan/总体方案.md`（§4 商业模式、§5 课程体系、§6 资产清单）
- `zcode-research/skillfactory/report/{DELIVERY,交付报告}.md`
- `zcode-research/research/oss-research-report.md`（§3.4 课程市场、§4 五门课、§5 空白）
- 五个 v5 资产的实物：`hotwords/package/{SKILL.md,README.md}`、`deploy-pack/package/{SKILL.md,validate.py}` + `deploy-pack/eval/runner.py`、`speaker-mapping/package/`、`zctl-mcp/package/INSTALL.md`、`acceptor-agent/package/agent.md`（仅目录级）
- `dist/meeting-minutes-skill/SKILL.md`

**公开来源（本次 WebFetch 实时抓取）**
- https://agentskills.io —— Agent Skills 概览、渐进式披露三段、客户端清单（Claude Code / Claude / ChatGPT&Codex / Gemini CLI / Cursor / Copilot / VS Code / TRAE / OpenCode / OpenHands / Goose / Junie / Kiro / Factory / nanobot 等 40+）
- https://agentskills.io/specification —— 规范全文：frontmatter 字段表、`name` 约束、`skills-ref validate`、<500 行/<5000 token 建议
- https://modelcontextprotocol.io/specification/latest —— MCP 最新规范 **2026-07-28 schema**，JSON-RPC 2.0、resources/prompts/tools、elicitation、扩展（Tasks / Skills over MCP / MCP Apps）、安全三原则
- https://modelcontextprotocol.io/community/working-groups/skills-over-mcp —— WG 章程：**SEP-2640 Skills Extension 已 Final，2026-09-13 合入**，扩展标识 `io.modelcontextprotocol/skills`，规范落 `modelcontextprotocol/ext-skills`

**公开来源（抓取失败，如实记录）**
- Udemy 课程页 → HTTP 403
- 知识星球 zsxq.com、极客时代 time.geekbang.org、Coursera Plus 定价页 → 本环境 provider 拒绝该次模型请求，未取回
- **结论：本会话未取得任何新鲜公开价格证据。** 仓内 `oss-research-report.md:349` 的价格带（199 → 3980-7980 → 9800-19800）是**它自己标注的 WebSearch 聚合二手数字、原文未逐一核实**（该文件 :349 原文即如此声明）。我引用它时保留该口径，不当作已核实事实。

---

## 2. 关键推理链

每条格式：命题 → 考虑过的分支 → 采纳/否决理由。

### 2.1 「课堂交付物应该是什么」——本镜头最重要的一次转向

**命题**：一节交付型课的合格判据 = 学员用自己的素材做出一件自己的事，且被机器判绿。

**考虑过的分支 A（沿用现状）**：把现有 `classroom/walkthrough.md` 的三课（SM/DP/HW）当样例课程骨架交差。
- 证据支持它的强度很高：TASK.md:34 的 K-3 已定义「零上下文角色走通 = 合格」；`rehearsal/round-1/record.md:3-4` 记录真跑通过、时间盒约 40 分钟、6 门基线复现。
- **否决理由**（硬证据）：该 walkthrough 的「学员交付物」是 **oracle 的复现物**。`walkthrough.md:99-103` 交付物路径是 `out/student_run1/`；:150-156 是 `out/student_pack1/`；:215-220 是 `out/oracle_student/out/`。这三处都是「把参照区的东西再生产一遍」。更致命的是彩排缺陷 D2（`record.md:41`）：初版学员流程因为「discover JSON transcript 回显与基线不符 + stderr 存档缺失」被判 1/4→2/4 fail，修复办法是**改成 contract §3 规定的「oracle/ 为 cwd + 相对路径 + 2> 存档」**。
- 也就是说，现有课堂真正教给「学员」的技能是：**怎么把自己的 cwd 和重定向摆对，好让字节比对通过**。对能读 contract §3 的工程师这是合理纪律；对「公司职员/小老板/个体户」这是纯粹的噪音，而且它教会学员「照着范例做」——与 owner 第 4 条「非专业开发者可以交付的、对他有价值的业务成果」正面冲突。

**考虑过的分支 B（彻底弃用 walkthrough）**：全推倒，从零写一套面向非开发者的课。
- **否决理由（部分否决）**：walkthrough 里有一块是真资产，不能丢——**「红路 exit 1 是信用底线」这条教学动作**。`walkthrough.md:49`「红路退出码为 0 即评测器被破坏，立即停步上报」、`course/hooks.md:11`「评测器连空交付都拦得住——这就是确定性」、`course/hooks.md:48`「红路演示必须保留 exit 1 画面——敢演示失败路径本身是信任资产」。这是**把工程纪律翻译成销售语言的成功案例**，应当升格为所有交付型课的标准段落。

**采纳**：**换交付对象，不换纪律**。
- 「逐字节一致」是**资产产线**的验收（防伪造实现），**不是课堂**的验收（防抄袭）。两者混用会把「照抄范例」教成默认行为。
- 课堂验收改成：判据来自 bench（业务判据：条数一致、逐条可溯源、负责人/期限不编造），**不来自「和范例逐字节相同」**。
- 走查脚本里那些「复现 oracle」的步骤，从「交付物」降级为「讲师侧 L0 资产机检」——它本来就是为了证明资产没坏，不是为了让学员交差。

### 2.2 内部彩排该分几层

**考虑过的分支**：沿用单层（K-3 零上下文 agent 彩排）。
- 证据：`record.md:3-4`「学员角色：zcode 主会话以零上下文姿态执行」「时间盒：约 40 分钟」。TASK.md:73 的 S-彩排 角色定义也明确「禁读工厂线代码/REGISTRY/其余工作区（盲态）」。
- **否决理由**：这个彩排的「学员」是**同一个 agent、在开发机上、仓库已克隆、Python 已装、它对这套资产有前一晚的上下文残留**。它能测出「文档缺步骤」（D1 五处 CLI 参数错就是这么抓到的），但**测不出新意图最关键的那一维：非技术人在自己电脑上会不会卡死**。

**考虑过的分支**：直接加「真人彩排」一层。
- **采纳，但要分层**。理由是每一层拦下的失败模式不同，混在一起就分不清「该改手册还是该改资产」：

| 层 | 谁 | 跑什么 | 时长 | 通过标准 | 它唯一能抓到的失败模式 |
|---|---|---|---|---|---|
| L0 资产机检 | 产线 agent（zcode 主 agent） | G0-1 绿门 / G0-2 红路 exit 1 / 打包 conformance | ~0.5h/资产 | 三条全 exit 0/1 符合预期 | 资产坏了 |
| L1 讲师彩排 | **备份讲师**（非主讲） | 按讲师手册从零跑一遍，计时，零讲稿 | 2h | 讲师不看讲稿能带完 + 记录每步耗时 | 手册不可照读 |
| L2 零上下文彩排 | 隔离会话 | 沿用现有 K-3 | 0.5 天 | 逐步 PASS + 交付物 + 缺陷清单 | 文档缺步骤 |
| L3 真人彩排 | 非技术同事（外部/合作方） | 用**自己的一条真实素材**跑全程 | 2h | 通过率 + **讲师兜底次数 ≤3** + 卡点清单 | 「人会卡死」 |

- 关键设计点：**L1 用备份讲师而不是主讲**。这是兑现「讲师不需要懂很多」的唯一硬门——手册质量 = 「零讲稿可执行率」，只有没参与编写的人来测才有意义。主讲自己念自己写的稿子永远通过。
- 关键设计点：**L3 的通过标准是「讲师兜底次数 ≤3」，不是「学员通过」**。判失败的是手册，不是人。把失败归因给学员是这类课程最容易犯、也最致命的错。
- 时间成本：0.5+2+4+2 ≈ **1 人日 / 资产 / 版本**。这是一个可以写进排产的确定数字（**假设**：讲师与彩排人都能跑 Python 命令；若目标学员连终端都不碰，L3 的形态要改成「讲师投屏 + 学员只用 GUI」）。

### 2.3 「模拟真实任务集」怎么造才真

**考虑过的分支 A**：把 `fixtures/` 里的 normal/partial/empty 当真实任务集。
- 证据：`walkthrough.md:73-84` 的三档输入是 `fixtures/{normal,partial,empty}.txt` × `fixtures/{m_full,m_partial,m_empty}.json`；`v5/assets/hotwords/package/README.md` 的 `fixtures/script.json` 是「10 步操作序列」。
- **否决理由**：这三个 fixture 建模的是**解析器的降级**，不是**世界的降级**。real transcript 里的脏东西（无时间戳行、口误更正、串台、同名两人、方言词、产品名全错、末尾废话）一条都没建模。而 `speaker-mapping` 的 SKILL 与 eval 恰恰是为处理这些设计的。

**考虑过的分支 B**：课后收集学员真实素材回流入 bench（`总体方案.md:313-315` §5.4「课程即评测场」已经设计了这个方向）。
- **采纳为长期主力**，但本次不解决它的合规边界（见 §5 未决问题 1）。
- 关键补充：TASK.md:76 已有红线「参与迭代的样本与独立验证样本分离（盲评加厚用新鲜样本）」——这条必须写死，回流样本只能进 bench 的 train 侧，盲评/验收继续用独立 holdout。

**考虑过的分支 C（本次真正采纳的、成本最低的杠杆）**：**用资产自己的 gotchas 表当退化注入清单**。
- 证据：`dist/meeting-minutes-skill/SKILL.md:34-47` 冻结了一张 11 个分类关键词 + 优先级（决议>待办>风险）表，并明写「已知可接受的『错』：『承诺**不能延期**』归风险；『就**议定**下来』归决议」；:80-86 的 gotchas 节还记了「『本周五之前』的期限提取结果是『周五之前』」这类实测坑。
- **这是一个双向资产**：它现在是给人看的说明，同时**它就是一份现成的退化用例生成器**——每条 gotcha 都可以机械地变成一条「学员会给的脏输入」。
- 同理 `deploy-pack` 的 4 个 red fixtures（bad-yaml / env-drift / hardcoded-secret / missing-service，见 `deploy-pack/oracle/fixtures/`）**已经是合格的 adversarial 任务**，只是课堂上被当成「演示失败」用，没人把它当成一个「有名字、有判据、学员要独立重做一遍」的正式任务。改个定位就行，成本接近零。

**采纳的模拟任务集配方（4 类 × 5 条 = 20 条进 bench）**：
1. 真实素材自采（脱敏后入 train 侧）
2. 合成脏输入（按 gotchas 注入退化）
3. 反例/adversarial（复用现有 4 个 red fixtures + 补齐 `office-templates`/`hotwords` 的近邻负例）
4. 学员现场自带（一次性，不进 bench，但必须进课堂验收单）

### 2.4 课中剧本：为什么「一节课 = 一个资产 = 一件交付物」

**考虑过的分支**：沿用 `course/outline.md` 的结构（第 0 讲引流 45min + 第 1~5 讲各 2h）。
- 证据：`course/outline.md:7-12`（第 0 讲裸 vs 带资产对照）、:14-19 / :21-25 / :27-32 / :34-39 / :41-46（第 1~5 讲）。
- **采纳其骨架**（第 0 讲引流 + 每讲一个资产 + 每讲 2h），**否决其「12 步走查」的实现形态**。
- 理由：`walkthrough.md` 把三课做成了 12 步、6 门基线、约 40 分钟 agent 走查（`record.md:4`）。那是**一次 6 小时的工程师彩排**，不是三节课。非开发者在 6 小时里做 12 步，注意力与成功率都会崩。

**采纳的课中四段与配比（20/30/30/20）**：
- **演示**（讲师用**自己的旧素材**，故意用一个脏输入）→ 教学点：fail-closed 是特性不是事故。
- **跟做**（给**填空版**步骤，学员补 1-2 个空）→ 教学点：让第一次失败发生在低风险时刻。
- **独立做**（学员自己的素材）→ **讲师此时不说话，只巡场记卡点**。这是采集 bench 数据的唯一窗口，破坏了它就毁了这一层数据。
- **交付验收**（跑验收器或对照验收单，当场签字）→ 教学点：机器说了算。

**时长节奏（以最快的 hotwords 资产为一例）**：15+20+30+15 = 80 分钟 + 15 分钟答疑 = 一个 100 分钟整块。

### 2.5 故障预案：把「通用预案」改成「按实测依赖面裁剪的预案」

我先做了依赖面实测（**实测**）：

```
cd afp-clone/zcode-research/skillfactory
grep -rn "^import |^from |import requests|import urllib|import httpx|import yaml|import docx" \
     v5/assets/*/package/*.py v5/assets/*/eval/runner.py v5/assets/*/oracle/*.py
```
输出（剔除纯标准库后）只剩：
- `v5/assets/deploy-pack/eval/runner.py:142: import yaml  # PyYAML`
- `v5/assets/deploy-pack/oracle/validate.py:41: import yaml`
- `v5/assets/deploy-pack/package/validate.py:133: import yaml  # PyYAML`
- 其余全部是 `argparse/json/os/re/sys/difflib/shutil/subprocess/tempfile/pathlib/…` 标准库。
- **`requests` / `urllib` / `httpx` 零命中。**

**结论（高置信）**：v5 三资产是**零网络、零 GPU、零 Docker、零模型调用、零 API key**，第三方依赖只有 **PyYAML 一个**（且只在 deploy-pack 用到）。`v5/assets/hotwords/package/README.md:12` 自述「`hotwords.py` CLI 工具（自包含，仅 Python 标准库）」与此一致。

**否决的分支**：写一份通用的「模型不可用/配额/网络」三段式应急预案。
- 理由：资产侧根本不消耗模型配额、也不需要网络。写通用预案是拿一个不存在的问题占位置，挤掉了真问题。

**采纳的预案（按真实风险面重排）**：
1. **主路径零依赖**：拔网线可完整跑完资产侧。→ 建议**现场拔网演示**，把它从「故障预案」翻成**信任建设动作**（「数据不出你本机」是私有化叙事的可执行证明）。
2. **唯一真网络面 = 对照演示**：`course/hooks.md:8-16` 的演示 A/B 依赖 live agent 现场生成（裸臂写 compose、裸臂换 SPEAKER_00）。模型不可用/配额耗尽时降级为**课前录屏**（30 秒，裸臂漂移 + 资产臂 exit 0 的对比画面），**不允许取消该段落**。
3. **PyYAML 缺失**：课前自检表加一条 `python -c "import yaml"`；备一份 vendored wheel 支持离线 pip 安装。**否则第一课（若从 deploy-pack 开）直接死在 import。**
4. **真机事故**：讲师机必须在课前**当场重装一遍**（不装第二遍等于没装）；学员包同时放「讲师机直发」与「课前 24h 自取」两条通道。
5. **运维红利（运营侧）**：资产侧零配额消耗 ⇒ **课中零 token 成本** ⇒ 可以开大班。相对 `oss-research-report.md:379-383` 课程二那套 Docker+FunASR+n8n+Dify 的假设，这个优势被严重低估了，值得写进招生材料。

### 2.6 讲师最小知识集的边界

**采纳的边界（会 / 不会清单）**：
- **讲师必须会**（4 条）：① 按手册执行并当场判定 exit code 语义（0/1/2 三态——`deploy-pack/eval/runner.py:29-31` 明写「exit 0 全过 / 1 有失败 / 2 参数非法」，`validate.py:23` 同款三态）；② 判断学员卡在第几步并指到手册第几节；③ 现场演示一次失败并解释「为什么这是卖点」；④ 课后按格式收卡点 + 发包。
- **讲师不需要**：写/改 skill、读 spec/contract、懂 oracle、跑盲评、做 eval 分析。

**采纳的讲师手册四段结构**：
1. 5 页速查卡（当天顺序 / 每步一句话 / 时间点 / 三个 exit code 的白话解释 / 兜底动作）
2. 完整讲稿（逐字可照读，标注哪些必须即兴）
3. 故障 × 处置（症状 → 学员看到什么 → 讲师说什么 → 做哪一步）
4. **课后 15 分钟的手**（发资产包 / 登记触达 / 回写卡点）

**理由**：`handbook.md:92-99` 的「课后交接」已经存在，但它是**写给彩排 agent 的**（「把 record.md 抄给 owner 看」「在 worklog 追加一行」），**不是写给真实讲师的**。一个真实讲师下课要面对的是「把 zip 发给 30 个人 + 登记谁拿了 + 记下谁卡在哪」——这段在整个仓库里是空白的。

**否决的分支**：给讲师手册加「原理讲解」章节。
- 理由：讲师手册里任何「原理」段落都会诱导讲师临场发挥；一旦临场发挥，课就不可复制，「高度确定性」就没了。**原理应该放在资产包自带的 SKILL.md 里让学员自己读**——这恰好利用了渐进式披露：agent 读 SKILL.md，人读快速开始。

**由此引出的「双读者包」原则**：同一个资产包，**SKILL.md 面向 agent，人读的那一层面向人**。而这里撞上一个真冲突（下节）。

### 2.7 「符合国际通行标准」这句承诺目前是空的——而且卡在分发上

我先做了仓内合规实测（**实测**，脚本只读，输出为文件名/行数/name/父目录名/frontmatter 字段表）：

遍历 `skillfactory/{dist,v5/assets,assets,v3/assets,v4/assets}` 下全部 SKILL.md：
- **共 29 个 SKILL.md，29/29 的 frontmatter `name` ≠ 父目录名**。
- 其中 4 个**根本没有 frontmatter**（`v3/assets/office-templates/package/`、`v3/assets/prompt-regression/package/`、`v4/assets/mcp-office-pack/package/`、`v4/assets/office-eval-suite/package/`）——后三个是 tooling，判无关；`v3/assets/office-templates` 是可分发资产源，缺 frontmatter 是真问题。
- 三个可分发 dist 包（`dist/meeting-minutes-skill` 等）用的是 `name / description / version / license / permissions / metadata`。

再对照**今天实时抓取**的 agentskills.io 规范原文：
- 顶层合法字段只有 6 个：`name`（必填）、`description`（必填）、`license`、`compatibility`、`metadata`、`allowed-tools`（后者 experimental）。
- `name` **必须与父目录名一致**。
- 校验命令 `skills-ref validate ./my-skill`。

**结论（高置信，两处冲突）**：
1. `version` / `permissions` **不是国际标准的顶层字段**——但内部 SPEC 把它俩列为必填顶层字段（`SKILL-SPEC-v0.1.md:64,67`）。我方三包的写法（顶层 version + permissions）**在 agentskills.io 下是非标准顶层键**。
2. 更值得记的是：**内部 SPEC 早就写对了答案，只是从没执行**。`SKILL-SPEC-v0.1.md:134` 的 `standard` 变体规则原文：「保留 name/description/license/metadata；`version`→`metadata.version`，`permissions`→`metadata.permissions`（这两个顶层字段不属开放标准，标准变体必须剥离）；如声明了环境要求则生成 `compatibility`」；:141「产物目录名**必须**等于 `name`」；:143「上架前**必须**用渠道校验器跑一遍：官方参考 `skills-ref validate`……对 standard 变体必须通过」。
   而 `总体方案.md:33` 明写「缺口：`build.py` 渠道变体生成器未建（SPEC §1.5.2 只有规则没有实现，`find` 无 build.py）」，`:343` 把「build.py 最小实现（standard + claude-code 两变体先够）」排进 D60–90 上架动作，`:395` 记「四项基建均未落盘/未建」。
   **也就是说：让资产「符合国际通行标准」的那一步，规则齐了、工具没建。**

3. 第三处冲突（这条直接打在我的镜头上）：`SKILL-SPEC-v0.1.md:54`「**【禁止】**在包内放置 `README.md` 等与 SKILL.md 内容重复的文件」。而 agentskills.io 允许任意附加文件。**对「非开发者」学员，包内那份人读 README 大概率是最高价值的上手文件**——内部 SPEC 恰好禁掉了它。

**采纳的解法（不是破例，是加变体）**：沿用 SPEC §1.5.2 既有的变体机制，新增一个 **`learner` 变体**：
- canonical 源包继续守内部 SPEC（无 README，供 agent 与门禁用）；
- `learner` 变体 = standard 变体 + 人读层（快速开始 / 3 步 / 常见卡点 / 故障卡），**且不剥离 `eval/`**——因为交付型课堂的核心是**让学员能自己复验**，而现有 walkthrough 把 eval 当成「讲师演示」正是设计缺陷（`course/hooks.md:10` 学员看的是屏幕，不是自己跑）。

**这条同时是分发收入的前置**：owner 第 6(c) 条要求「skill/MCP 设计必须符合现行国际通行标准」，而现在没有任何机器检查能证明这一点。

**顺带一条对另一镜头有价值的事实**（我不越界展开，只记指针）：MCP 侧的 **Skills 扩展 `io.modelcontextprotocol/skills` 已 Final（SEP-2640，2026-09-13 合入）**（今日实抓 WG 章程）。这意味着同一个资产可以**双形态分发**：一个符合 agentskills.io 的目录 + 一个通过 MCP skills 扩展暴露的 server。对「为资产分发收费」是直接可用的第二条腿。

### 2.8 收费与分发：为什么从「单资产单次授权」起步

**考虑过的分支 A**：沿用 `总体方案.md:231-237` 的「课程费 199–1999 元带，结业验收单即合同」。
- 这条路本身有依据（`总体方案.md:262` 引用「90% 作者收入不足 1000 元」的警示，主张把收入设计在交付层；`oss-research-report.md:349-357` 的三级漏斗与「卖第一个跑通的成果」）。
- **否决理由不是价格带，是计价单位**。「课程费」把收费绑在**时间**上（听了几小时），而 owner 说的是「为**资产的分发**收费」。绑在时间上会带来三个坏后果：转拷零成本（时长不会因为转拷而减少）、升级无收入、学员对「值不值」的判断落回「学到多少」这个已经被证伪的锚（`oss-research-report.md:350`：录播完课率 <10%，用户付费动机是「拿到结果」而非「学会」）。

**采纳**：
- **计价单位 = 一次资产授权**（含一次带教 + 一次验收）。价格带仍可落在 199–1999（引仓内数字，标注二手未核），但**购买物是「这个东西归你用 + 有人带你用通」**。
- **版本更新 = 第二次收费事件**。`teaching-assets.md:4`「latest 不入课堂口径——课堂承诺可复刻，就必须钉版本」与 :55-56 的升版三步（基线复跑 → 文档同步 → 新 tag）**已经是现成的机制**，只是目前是文档纪律；我建议把它升级为收入凭证：学员拿到的包钉版本号与 sha256，更新版对老学员 8 折升级包。

**防转拷的务实做法**（按可靠性排序，只做前三条，明确不做 DRM）：
1. **交付物即防伪**：每个交付包内嵌「资产指纹」= 版本号 + 关键文件 sha256 + 授权号（沿用 REGISTRY 已有的 sha256 表格做法，REGISTRY.md:65-79 已有三包 15 个文件的 sha256）。转拷出去的包不会失效，但**校验器会明确告诉使用者「这个包没在你这台机器上验过/版本已旧」**。
2. **升级即触达**：版本一升，旧包在校验器里自动变红。**这把防转拷从「法律问题」变成「经济问题」**——转拷者拿不到更新，也拿不到新任务类型的资产。这是我认为唯一真正有效的一条。
3. **触达通道自持**：证据只有私域。`总体方案.md:258-259` 已定「不签独家、平台流量是期限资产」。包内**不放自动更新器**（那是真风险面），只放一条**离线更新指令**（最新版号 + 替换哪几个文件），由讲师课后口头/群内告知。
4. **明确不做**：加密、账号体系、DRM。成本高、收益低、体验差，且与「交付体验」的第一性承诺冲突。

**收款**：`oss-research-report.md:427` 明确「中国大陆小额收款空白」，`总体方案.md:235` 也把「收款通路就绪」列为进入条件。**因此第一阶段的物理形态是：课后 24 小时内人工发一个 zip**。这个动作必须写进讲师手册第 4 段——目前它不在任何一份讲师材料里。

### 2.9 课程 ↔ eval 耦合：最小可行机制

**考虑过的分支**：按 `总体方案.md:271-274` §5.1 与 :313-315 §5.4 的原设计上 consent shim + OTel GenAI span + Langfuse user feedback。
- 这套设计是对的，但它是**托管期（阶段 2/3）**的东西，依赖学员长期在生产环境跑。**对第一期交付型课，它太重了**：需要学员持续开开关、持续产生轨迹，而课堂场景下学员只跑一次。
- **否决理由**：复杂度与数据量不匹配；且课堂唯一的稀缺资源是讲师的注意力，不是遥测管道。

**采纳的最小机制（三步，零新基础设施）**：
1. **课中**：讲师巡场时按**统一格式**记三样——卡在第几步 / 学员的原始输入脱敏后 3 行 / 产物是否被判红。一张表，10 分钟填完（就发生在 §2.4 的「独立做」段）。
2. **课后 24h**：卡点做**五类归因**：环境 / 理解 / 输入脏 / 资产缺陷 / 验收口径。**只有「资产缺陷」进 backlog 进迭代**；其余四类各有各的出口（环境→课前自检表加一条；理解→手册加一步；输入脏→bench 补退化用例；验收口径→改 oracle 或改课程承诺）。
3. **一个先行指标：课堂红率** = 「学员产物被判红」的比例 / 总交付物。每期统计，**趋势上升 = 资产对真实输入的覆盖在退化**（不是因为学员变笨）。我认为这应该排在本镜头所有指标的第一位：**它比盲评便宜得多，比实验室 eval 真实得多，而且它是唯一能直接回答 owner 第 3 条「迭代到公共知识+合成数据能到的极限了吗」的信号**——因为实验室 bench 再厚也是合成分布，课堂红率是真实分布。

**红线保留**：`TASK.md:76`「参与迭代的样本与独立验证样本分离」——回流样本只进 train 侧；盲评/验收继续用独立 holdout。另注意 `D:\AGENTS.md` 已有的红线「Lab `corpus/` 禁读禁出；holdout/golden 永不入训练」——这条原本是 mutual/Script_Writer 语境，**是否延伸到 skillfactory 的课堂回流，我判断需要人类裁决**（见未决问题 1）。

---

## 3. 证据

### 3.1 仓内（path:line）

| 主张 | 证据 |
|---|---|
| 工作区只管 skill-factory 产线，其余项目封存 | `BASELINE.md:6` |
| zcode-research v5 评测体系存活、4 资产 runner 全绿、红路 fail-closed | `BASELINE.md:99-101` |
| owner 口径原文：教学价值不在讲什么，而在带学员走一遍真实交付 | `zcode-research/README.md:10`；`TASK.md:4` |
| 课堂承诺边界（只承诺过程，不承诺就业/收益） | `TASK.md:76`；`classroom/handbook.md:5`；`course/hooks.md:3` |
| K-1~K-5 定义；K-3 = 零上下文角色 + 时间盒走通 | `TASK.md:30-36` |
| K-3 彩排实际通过，时间盒约 40 分钟，学员 = zcode 主会话零上下文 | `classroom/rehearsal/round-1/record.md:3-4` |
| 彩排缺陷 D2：把学员流程改成「oracle/ 为 cwd + 相对路径 + 2> 存档」以对齐基线 | `record.md:41` |
| 彩排缺陷 D3：`run_all.py` 原地跑会清空重建 oracle/out 参照区 | `record.md:42`；`walkthrough.md:188`（红线警告） |
| walkthrough 学员交付物 = oracle 复现物（student_run1 / student_pack1 / oracle_student） | `walkthrough.md:99-103,150-156,215-220` |
| walkthrough 前置要求学员会 `git log` 看到 `0ab1c25` | `walkthrough.md:14,20-22`；`handbook.md:31` |
| handbook 存在明显文本损坏（多处乱码串） | `handbook.md:44,46,54-60,74,88` |
| handbook 的「课后交接」是写给彩排 agent 的（抄给 owner / 追加 worklog） | `handbook.md:92-99` |
| teaching-assets 纪律：latest 不入课堂口径；升版三步 | `teaching-assets.md:4,55-56` |
| 现有 outline = 第 0 讲引流 45min + 第 1~5 讲各 2h | `course/outline.md:7-12,14-19,21-25,27-32,34-39,41-46` |
| 第 4 讲（zctl-mcp）明示「端到端真机调用欠账」 | `course/outline.md:39` |
| hooks 三个合规话术 + 「红路必须保留 exit 1 画面」 | `course/hooks.md:8-16,47-49` |
| 内部 SPEC 目录名必须等于 frontmatter name | `SKILL-SPEC-v0.1.md:36,63` |
| 内部 SPEC 禁止包内放 README.md | `SKILL-SPEC-v0.1.md:54` |
| 内部 SPEC 6 必填字段含 version/permissions（顶层） | `SKILL-SPEC-v0.1.md:59-68` |
| 内部 SPEC 兼容矩阵已记载 agentskills.io「无此字段：version / permissions」 | `SKILL-SPEC-v0.1.md:124-125` |
| 内部 SPEC 禁止顶层新增字段（含 compatibility/allowed-tools） | `SKILL-SPEC-v0.1.md:76` |
| 内部 SPEC `standard` 变体规则已正确剥离 version/permissions、生成 compatibility | `SKILL-SPEC-v0.1.md:134` |
| 内部 SPEC：产物目录名必须等于 name；上架前必须过 `skills-ref validate` | `SKILL-SPEC-v0.1.md:141,143` |
| `build.py` 从未实现 | `总体方案.md:33`（缺口行）、`:105`（「待建（D0–30 待办，find 确认未建）」）、`:343`、`:395` |
| v5 三资产状态与欠账（FunASR 彩排缺音频环境、dist 三包实物问题） | `REGISTRY.md:162-164,203,216-218` |
| REGISTRY 已有三包 15 个文件 sha256 指纹表（防伪指纹可复用此做法） | `REGISTRY.md:65-79` |
| zctl-mcp 只读 4 工具、变更类零暴露 | `REGISTRY.md:191`；`zctl-mcp/package/INSTALL.md:31` |
| meeting-minutes 的 11 关键词 + 优先级表 + 已知可接受的「错」 | `dist/meeting-minutes-skill/SKILL.md:34-47` |
| meeting-minutes 验收 5 项（三节齐 / 待办表列 / summary 一致 / 逐字溯源 / 条数差≤2） | `dist/meeting-minutes-skill/SKILL.md:63` |
| meeting-minutes 写后回读三态（pending→written→verified） | `dist/meeting-minutes-skill/SKILL.md:57` |
| meeting-minutes gotchas（实测坑） | `dist/meeting-minutes-skill/SKILL.md:80-86` |
| hotwords 采集口径四条筛 + 权重分档（面向「单位」的业务语言） | `v5/assets/hotwords/package/SKILL.md:27-48,50-65` |
| hotwords 自述「仅 Python 标准库」 | `v5/assets/hotwords/package/README.md:12` |
| deploy-pack 校验器判绿唯一口径 ALL GREEN + exit 0 | `v5/assets/deploy-pack/package/validate.py:14-23`；`SKILL.md:41-50` |
| deploy-pack 4 项 runner 检查 + exit 0/1/2 三态 | `v5/assets/deploy-pack/eval/runner.py:5-8,18-31` |
| deploy-pack 4 个 red fixtures 已在仓 | `v5/assets/deploy-pack/oracle/fixtures/red-*` |
| zctl-mcp 安装前置（Node≥18 + 凭据）与 mcpServers 片段 | `zctl-mcp/package/INSTALL.md:3-20` |
| 商业模式阶段 1：课程变现、199–1999 带、验收单即合同 | `总体方案.md:231-237` |
| 「90% 作者收入不足 1000 元」警示 + 收入设计在交付层的对策 | `总体方案.md:262` |
| 不签独家、平台流量是期限资产 | `总体方案.md:258-259` |
| 课程即评测场（真实任务回流 bench） | `总体方案.md:313-315` |
| 课程市场：三级漏斗价格带 199→3980-7980→9800-19800（**该文件自标二手未核**） | `oss-research-report.md:349` |
| 交付形态与学习效果强相关；付费动机是「拿到结果」 | `oss-research-report.md:350` |
| 信任崩塌先例（199 元课 39 节仅 6 节讲 AI；0.01-9499 元乱象） | `oss-research-report.md:351` |
| 端到端交付四大难点（验收标准难定义 / 长程可靠性 / 边际成本 / 维护责任） | `oss-research-report.md:356` |
| 「卖第一个跑通的成果」而非课程 | `oss-research-report.md:357` |
| 课程三店主形态「店主不碰命令行，交付一键 compose 全家桶」 | `oss-research-report.md:391` |
| 国内小额收款空白 | `oss-research-report.md:427` |
| 样例验证用样本与独立验证样本分离（盲评加厚用新鲜样本） | `TASK.md:76` |

### 3.2 本次会话亲手跑的检查（含命令与输出要点）

| 检查 | 命令 | 结果 |
|---|---|---|
| C1 资产台账结构 | `ls` / `ls -R skillfactory/v5` / `ls skillfactory/{classroom,course,dist,plan,standard,evidence,report}` | v5 五资产（acceptor-agent/deploy-pack/hotwords/speaker-mapping/zctl-mcp）；classroom 下 walkthrough/handbook/teaching-assets + rehearsal/round-1/record.md；`classroom/course` 为**空目录**；`course/` 下有 outline.md + hooks.md |
| C2 SKILL.md 合规实测 | 内联 python：遍历 `dist,v5/assets,assets,v3/assets,v4/assets`，解析 frontmatter，比较 `name` 与父目录名 | **29 个 SKILL.md，29 个 name≠父目录名**；4 个无 frontmatter；三个 dist 包 frontmatter 键 = `name/description/version/license/permissions/metadata` |
| C3 依赖面/网络面实测 | `grep -rn "^import \|^from \|import requests\|import urllib\|import httpx\|import yaml\|import docx" v5/assets/*/package/*.py v5/assets/*/eval/runner.py v5/assets/*/oracle/*.py`（剔除标准库） | 仅 3 处 `import yaml`（deploy-pack 的 runner/oracle validate/package validate）。**requests/urllib/httpx 零命中** |
| C4 requirements 清点 | `find . -name "requirements*.txt"` | 5 处，**v5 三资产目录内无 requirements.txt**；dist/mm = `python-docx>=1.1.0` |
| C5 公开标准抓取 | WebFetch agentskills.io / agentskills.io/specification / modelcontextprotocol.io/specification/latest / …/working-groups/skills-over-mcp | 见 §1.2 |
| C6 定价证据抓取 | WebFetch udemy（403）/ zsxq / geekbang / coursera（provider 拒绝） | **全部失败；本会话无新鲜公开价格证据** |

### 3.3 本次会话**未跑**的（明确声明）

- **未重跑任何 v5 资产 runner**（绿门/红路/学员产物复评）。基线里的 4/4、12/12 等数字我采信 `BASELINE.md:99-101` 的记载，**但不是我本次亲手复现的**。
- **未计时任何一节课**。「40 分钟」来自 `record.md:4`（B/C 级：那是一个零上下文 agent 在开发机上的跑通时间，**不是真人时间**，不能直接当课时依据）。
- **未安装 `skills-ref`**，因此未实跑 `skills-ref validate`。C2 是我自己按规范文本写的**只读审计脚本**，不是官方校验器。
- **未实现 build.py**（红线不允许新建除本文件外的任何文件）。
- **未接触任何封存项目**（peidian/qw-arena2/ohos/video/chenmai8/xuexing 仅在 BASELINE 摘要中读到）。
- **未读 planning/ 下其他思考者文件**。

---

## 4. 倾向性结论（每条标置信度）

1. **现有课堂层（classroom-v0.1）证明了「过程可复制」，但没有证明「非开发者可交付」；它教的是「怎么把字节比对跑绿」，不是「怎么把自己的事做成」。**（置信度：**高**。证据：walkthrough.md:99-103/150-156/215-220 交付物为 oracle 复现物 + record.md:41 D2 把学员流程改成对齐基线的 cwd/重定向 recipe。这是文件事实，不是推断。）

2. **交付型课堂的正确交付物是「学员用自己的素材做出的、他自己的东西」，判据来自 bench 的业务判据，不来自「与范例逐字节一致」。**（置信度：**高**。这是 owner 第 4 条的字面要求 + 结论 1 的直接推论。）

3. **v5 三资产是零网络、零 GPU、零 Docker、零模型调用、零 API key，第三方依赖只有 PyYAML。整堂课可以拔网线跑完。**（置信度：**高**。C3 实测 `requests/urllib/httpx` 零命中，仅 3 处 `import yaml`；与 `hotwords/package/README.md:12` 自述一致。）

4. **因此「模型配额/网络故障」在资产侧不是真风险面；真网络面只有对照演示那一段。**（置信度：**高**，由结论 3 直接推出；`course/hooks.md:8-16` 是我找到的唯一依赖 live agent 的课堂动作。）

5. **零配额消耗是当前资产线相对报告中「Docker+FunASR+n8n+Dify」课程设计的、被严重低估的运营优势——它直接决定班型上限与毛利结构。**（置信度：**中**。事实部分（零调用）高置信；「毛利结构」是推断，需要定价与班型数据才能定，我没有。）

6. **彩排必须分四层，L0 资产机检 / L1 备份讲师零讲稿 / L2 零上下文 agent / L3 真人非技术同事；L1 必须由非主讲者做，L3 的通过标准是「讲师兜底次数 ≤3」。**（置信度：**中高**。分层逻辑与现有 K-3 的边界（record.md:3-4 只测文档缺步骤）是硬的；但「1 人日/资产/版本」的估算是**假设**，未实测。）

7. **讲师手册必须是「四段式 + 零讲稿可执行」**：速查卡 / 逐字讲稿 / 故障处置 / 课后 15 分钟（发包+登记+收卡点）。讲师手册里**不应有**原理讲解章节。**（置信度：**中高**。逻辑清晰，但「零讲稿可执行」的具体话术需 L1 彩排验证，我没有样本。）

8. **现有 handbook.md 的文本损坏（handbook.md:44,46,54-60,74,88）是「夜间自动生成 + 无人工通读」的直接证据，恰好是 L1 零讲稿彩排要拦的那类缺陷——但现有 L2（agent 彩排）没拦住它。**（置信度：**高**。乱码是我本次 Read 直接看到的；「L2 没拦住」是因为 record.md 全篇 PASS 未记这条。**注意：这是我看到的现象，成因判断为推测。**）

9. **「一节课 = 一个资产 = 一件交付物」，100 分钟整块；不应把多资产塞进一次 6 小时走查。**（置信度：**中**。与非开发者注意力/成功率的关系是常识性推断，我没有真人课堂数据。）

10. **模拟真实任务集的最小可行配方 = 真实素材自采（train 侧）+ 用资产自己的 gotchas/关键词表做退化注入 + 把现有 4 个 red fixtures 正式命名为 adversarial 任务 + 学员现场自带（一次性）。**（置信度：**高**。前三类的素材在仓内已存在（`dist/meeting-minutes-skill/SKILL.md:34-47,80-86`、`deploy-pack/oracle/fixtures/red-*`），成本接近零。）

11. **「课堂红率」应当成为资产迭代的第一号先行指标。**（置信度：**中高**。逻辑强（真实分布 > 合成分布），但没有历史数据证明它与最终资产质量的相关系数。）

12. **「资产符合国际通行标准」目前是一个未经验证的业务承诺，且它与内部 SPEC 存在两处可指名的冲突；解法不是破例，是补上 SPEC §1.5.2 早就写好、但从未实现的 build.py 变体生成器，并新增一个 `learner` 变体（人读层 + 保留 eval/）。**（置信度：**高**。C2 实测 29/29 name≠目录名 + dist 三包用非标准顶层 `version`/`permissions` + SPEC:124-125 自己就记了「agentskills.io 无此字段」+ SPEC:134/141/143 已写好规则而 `总体方案.md:33,:105,:395` 三处记「build.py 未建」。)

13. **「禁止包内 README」（SPEC:54）与国际标准允许任意附加文件冲突；对非开发者学员，人读层是最高价值的上手文件。**（置信度：**高**，规范原文对比即得。）

14. **MCP Skills 扩展（`io.modelcontextprotocol/skills`，SEP-2640，2026-09-13 Final）给资产提供了第二条分发形态：同一资产既可作 agentskills.io 目录，也可作 MCP skill server。**（置信度：**高**，今日实抓 WG 章程原文。**但**：client 支持度与落地成本我未核实——charter 明确「Client implementation mandates: out of scope」。)

15. **计价单位应是「一次资产授权」而非「课程时长」，版本更新是第二次收费事件；防转拷只有三条务实手段（交付物嵌指纹 / 升级即触达 / 私域自持），明确不做 DRM。**（置信度：**中**。机制设计我有把握；「升级即触达能压住转拷」是推断，没有实测。价格带沿用仓内二手数字，我这次**没有取得任何新鲜价格证据**。）

16. **课后 24 小时人工发 zip 是第一阶段唯一现实的收款/交付形态，它目前不在任何讲师材料里。**（置信度：**中高**。`oss-research-report.md:427` + `总体方案.md:235` 指向同一结论；`handbook.md:92-99` 现存版本是写给 agent 的，不含发包动作。）

---

## 5. 未决问题与风险

### 5.1 需人类决断的（我判断不该由我或撰写者替他定）

1. **【最关键】是否接受「课堂交付物 = 学员自己的素材产出」这一根本转向？** 它会作废现有 `walkthrough.md` 的大部分内容，并让 2026-10-02 的 K-3 彩排结论（record.md）从「课堂合格」降级为「资产机检合格」。这不是技术问题，是业务定义问题。
2. **学员回流素材（录音/台账/公司模板）能否入库 bench？** 具体三问：(a) `D:\AGENTS.md` 的「Lab `corpus/` 禁读禁出、holdout/golden 永不入训练」是否延伸到 skillfactory 课堂回流？(b) 脱敏由谁做、留存多久？(c) 学员书面同意的载体是什么（现只有 `总体方案.md:304` 图里的 consent 概念，无实现）。
3. **内部 SPEC §1.1 禁 README 与国际标准允许任意文件：加 `learner` 变体，还是直接改 SPEC 条款？** 前者更干净但多一个变体要维护；后者省事但改的是已生效的 v0.1 标准。
4. **build.py 的优先级。** 它同时卡住三件事：① 分发合规性（owner 第 6c 条）、② 讲师手册可发的包形态、③ 内部 SPEC 自身的 §1.5.2 合规。是否列入第一优先？我倾向「是」，但这是资源分配决策。
5. **讲师从哪里来？** 内部轮值（工程师转讲师）vs 外聘（本身就是目标用户）——两者的手册、培训成本、通过标准完全不同。现有全部课堂材料假设的是「懂仓库的内部人」。
6. **首期班型与规模？** 1v1 / 5 人 / 20 人直接决定「兜底次数 ≤3」这个通过标准能不能用，也决定巡场采数据的可行性。
7. **定价具体数字与收款通道。** 我这次未取得新鲜公开价格证据（§3.2 C6），仓内 199–1999 是二手聚合数字。谁来定这个数、收款走什么（人工转账？知识星球？微信收款码？），需要 owner 拍板。
8. **「ASR 转写」这一段怎么办。** owner 点名的链是「ASR 转写→讲者映射→热词→纪要→待办→部署包」，但仓内**没有 ASR 资产**——`deploy-pack` 里的 `asr` 只是一个 compose 服务名且镜像是 `placeholder/*` 不可拉取（`deploy-pack/package/SKILL.md:73`），`REGISTRY.md:216` 记「FunASR 彩排缺音频环境」。所以样例课 A 今天只能从「已有转写稿」起步，录音→文字只能演示不能交付。**这个边界要不要现在就写进对外课程页，还是先补 ASR 资产？**

### 5.2 我判断的风险（不需要人类拍板，但撰写者必须处理）

- **R1｜讲师临场发挥的失控**：任何讲师材料里的「原理」段落都会诱发即兴发挥，一旦发生课就不可复制。→ 缓解：讲稿逐字化 + 标注「必须即兴处」。
- **R2｜把「学员没通过」归因给学员**：这是交付型课最致命的失败模式，会同时毁掉口碑和 bench 数据。→ 缓解：L3 通过标准明写「兜底次数 ≤3」，失败归因给手册。
- **R3｜数据只在课中那一瞬间存在**：巡场时讲师在说话就没有数据，「独立做」段必须强制讲师闭嘴记录。→ 缓解：给一张固定格式的一页纸，10 分钟能填完。
- **R4｜对照演示单点依赖 live 模型**：模型不可用就整堂课最有说服力的段落消失。→ 缓解：课前录屏 30 秒，且不允许取消。
- **R5｜PyYAML 缺依赖发生在第一分钟**：课前自检表必须含 `python -c "import yaml"`；建议备 vendored wheel。
- **R6｜「逐字节一致」的教学惯性**：现有材料的口径会持续把新讲师往「让比对跑绿」上带。→ 缓解：新课堂材料里，「复现 oracle」只能出现在讲师侧 L0 章节，不能出现在学员交付物章节。
- **R7｜文档自动生成但无人通读**：handbook.md 的乱码（:44,46,54-60,74,88）说明这条流水线缺口是系统性的，不是偶发。→ 缓解：L1/L3 两层真人彩排是唯一的解药。
- **R8｜范围蔓延**：本镜头最容易被拖进「先把资产造齐再做课」。反向风险是「课先开、资产后面补」，那会直接违反 `TASK.md:46`「课堂层任何资产未过彩排不得进入发布」。→ 建议以**一个资产**（hotwords 或 speaker-mapping）走通全生命周期，验证课程产品形态，再横向复制。

---

## 6. 给最终规划撰写者（GLM-5.3）的具体建议

1. **先写「结论 1」再写任何课程内容。** 建议在规划的课程章开头就用一句话钉住：「交付型课堂的合格判据 = 学员用自己的素材做出一件自己的事，且被机器判绿」，并显式声明它取代了「复现 oracle 产物」这个旧判据（`walkthrough.md:99-103` / `record.md:41`）。否则规划会不自觉地沿用旧材料的口径。

2. **把 `classroom-v0.1` 与「面向非开发者」明确分轨，不要原地改。** 建议在规划里给两套材料命名清楚：现有三课走查降级为「资产机检 + 讲师训练材料」；新开一套「交付型课」材料（不同的目录、同样的 tag 纪律）。原地改会让 `record.md` 的历史结论失去参照。

3. **彩排章按四层写，并给出每层的通过标准与「唯一能抓到的失败模式」**（L0 0.5h / L1 2h 零讲稿+备份讲师 / L2 0.5 天零上下文 / L3 2h 真人）。**明确写「L1 必须由非主讲者做」「L3 判失败的是手册不是学员」**。时间成本写成「约 1 人日/资产/版本」并标注为估算。

4. **样例课程骨架建议给这两门，并明确各自的诚实边界**：
   - **样例 A《把一场例会变成三页纪要》**（公司职员，3h）。链路 hotwords → speaker-mapping → meeting-minutes，deploy-pack 作选修。**必须在课程页写明：ASR（录音→文字）段今天只能演示不能交付**，原因引 `REGISTRY.md:216` + `deploy-pack/package/SKILL.md:73`（镜像为 `placeholder/*` 不可拉取）。验收单直接用 `meeting-minutes` eval 的 5 项检查（`SKILL.md:63`）翻译成白话：条数一致 / 逐条可溯源 / 负责人期限不编造。
   - **样例 B《给门店建一份自己的热词表》**（个体户/小老板，90min）。资产 hotwords（纯 stdlib、零依赖、交付物天然每周复用）。验收 = runner 4/4 + 自己的 funasr 导出文件。
   - 选这两门的理由要写进规划：**它们是当下资产线里唯二能给非开发者真实交付、且不需要 Docker/GPU/ASR 服务的组合。**

5. **每门课给一张「物料清单 + 验收单」模板**，验收单要求包含：交付物文件路径、对应命令、预期 exit code、学员自评、讲师签字位。理由是 `总体方案.md:234` 已有「结业验收单即合同」的定位，但仓库里**没有任何一张现成的验收单**。

6. **故障预案章按实测依赖面重写，不要写通用版。** 四条：① 主路径零网络（建议现场拔网演示，翻成信任建设动作）；② 唯一网络面是对照演示，降级为课前 30 秒录屏；③ PyYAML 课前自检 + 离线 wheel；④ 讲师机课前当场重装。**并把「零配额消耗 ⇒ 可开大班」作为运营结论写进班型章。**

7. **讲师手册章按四段写**（速查卡 / 逐字讲稿 / 故障处置 / 课后 15 分钟含发包登记收卡点），并明写一条禁令：**讲师手册不含原理讲解章节**，原理放资产包的 SKILL.md 让学员自读（这正是渐进式披露在课程层的一次复用）。讲师「会/不会」四二清单建议原样写进规划。

8. **收费与分发章建议：计价单位 = 一次资产授权（含一次带教 + 一次验收），不是课程时长；版本更新 = 第二次收费事件。** 直接复用已有机制：`teaching-assets.md:55-56` 的升版三步（基线复跑 → 文档同步 → 新 tag）+ `REGISTRY.md:65-79` 的 sha256 指纹表做法。建议明写三条防转拷（交付物嵌指纹 / 升级即触达让旧包自动变红 / 私域自持且包内不放自动更新器）与一条禁令（不做 DRM/加密/账号）。**价格数字请标注为「沿用仓内二手聚合数字，未取得一手证据」**——我这次三个定价源全部抓取失败，不要在规划里把它写成已核实的市场价。

9. **合规章建议单独立一节**，因为它同时是分发收入的前置：
   - 陈述实测事实：全仓 29 个 SKILL.md 全部 name≠父目录名（附我的只读审计口径），三个 dist 包用了国际标准不存在的顶层 `version`/`permissions`；
   - 指出内部 SPEC 自己已记载这一点（`SKILL-SPEC-v0.1.md:124-125`）并已写好 `standard` 变体规则（:134/141/143），**缺的是 build.py**（`总体方案.md:33,:105,:395` 记「未建」）；
   - 建议把「build.py + `skills-ref validate` 进门禁」列为第一优先工程项，并把「新增 `learner` 变体（人读层 + 不剥离 eval/）」作为课程可发包形态的依赖项；
   - 顺带记一条给其他镜头：MCP Skills 扩展 `io.modelcontextprotocol/skills`（SEP-2640，2026-09-13 Final）是第二条分发腿，但**client 支持度未核实**（WG charter 明确 client mandates 属 out of scope），别写成已可用。

10. **课程↔eval 耦合章建议写「最小机制」而不是 OTel/Langfuse 全套**：巡场一页纸（卡在第几步 / 脱敏输入 3 行 / 是否判红）→ 课后 24h 五类归因（环境/理解/输入脏/资产缺陷/验收口径，**只有资产缺陷进 backlog**）→ 指标「课堂红率」。保留 `TASK.md:76` 的样本分离红线。**明确说明这是第一期形态**，Langfuse 那套留给托管期。

11. **风险章请把 R8（范围蔓延）写进去**：建议规划以**一个资产**走通全生命周期再横向复制，并把「ASR 段缺失」作为已知边界写进对外课程页，而不是含糊带过或临时承诺。

12. **最后请保留「本轮未做/未验证」清单**（§3.3）：未重跑 runner、未计时真人课程、未装 `skills-ref`、未取得一手价格证据。规划里的任何数字都请带上「命令 + 前提」或标注来源等级。

# SKILL-SPEC v0.1 — skillfactory 自产 Skill 包企业标准

| 项 | 值 |
|---|---|
| 文件 | `skillfactory/standard/SKILL-SPEC-v0.1.md` |
| 版本 | v0.1（2026-09-29 定稿） |
| 状态 | 生效。本文件全部条款为可判定要求，是 skillfactory 资产入库、验收与分发的强制门禁 |
| 适用范围 | skillfactory 生产的全部自产 skill 包；外包/定制交付物参照执行 |
| 上位依据 | agentskills.io Agent Skills 开放规范（2025-12-17 成为开放标准）；Anthropic 官方评测 SOP；豆包/Qoder/Kimi/千问四家本地格式逆向与分发生态调研（证据索引见附录 C） |

---

## 0. 总则

### 0.1 用语分级（全文统一）

- **【必须】**：无条件要求，不满足即验收不通过。
- **【禁止】**：无条件不得出现，出现即验收不通过。
- **【应当】**：默认要求；偏离必须在 CHANGELOG.md 记录理由并经评审确认。
- **【可以】**：允许，且仅允许在该条款写明的范围内实施。

### 0.2 资产定位

1. 我方 skill 是**可分发的程序性知识资产**，不是一次性提示词。核心格式**必须**对齐 agentskills.io 开放标准（已被 Claude Code、Codex、Cursor、Gemini CLI、TRAE 等 40+ 客户端采纳，格式壁垒当前不存在——这是"一次编写、多平台上架"的前提）；我方自有信息与扩展**必须**收进 `metadata` 键值或编译期可剥离的适配层，**禁止**新增顶层 front-matter 字段。
2. skill 与连接器分工：skill 承载**程序性知识**（何时做、如何做、失败怎么降级），不重复造连接器。凡涉及外部系统，正文**必须**显式写明何时调用哪个工具/命令、返回值如何判成功、失败如何降级。
3. 一包一能：每个 skill **必须**是单一连贯单元；单个方法模块下沉的 references **应当** ≤3 份，超过必须拆分为独立 skill 并用路由组织（§5.2）。依据：SkillsBench（arXiv:2602.12670）实测聚焦技能（≤3 模块）胜过大而全捆绑，平均通过率 33.9%→50.5% 的增益来自对口的聚焦技能而非堆料。
4. 每个 skill **必须**带可执行的评测包（§3）与评测记录方可称为资产入库；无评测记录的 SKILL.md 是草稿，**禁止**进入分发管线。

---

## 1. 格式规范

### 1.1 目录布局（硬约定）

```
<skill-name>/                 # 目录名必须等于 front-matter name（§1.2）
├── SKILL.md                  # 【必须】唯一入口：front-matter + 正文
├── references/               # 【可选】按需加载的领域文档（一层深，§1.4）
├── scripts/                  # 【可选】可执行脚本（自包含、依赖显式、错误信息友好）
├── assets/                   # 【可选】模板、样例、schema、查找表
├── eval/                     # 【必须】评测包（§3）
│   ├── runner.py             #   确定性评测器（机器可判）
│   ├── golden.json           #   黄金集：eval_inputs + ab_tasks
│   ├── protocol.md           #   盲评协议说明（§3.3）
│   └── results/              #   评测产物：benchmark.json + 逐次记录（入库必带）
├── agents/                   # 【可选】宿主 UI 适配（interface.yaml：display_name / short_description / default_prompt）
├── CHANGELOG.md              # 【必须】语义化版本变更记录（可分发资产与一次性脚本的分界线）
└── MANIFEST.json             # 【必须，发布时生成】逐文件 sha256 清单（§2.5）
```

补充规则：

1. `SKILL.md`、`eval/`（含 runner.py 与 golden.json）、`CHANGELOG.md` 为**必选项**；其余目录按需。
2. **【禁止】**在包内放置 `README.md` 等与 SKILL.md 内容重复的文件（豆包官方元技能 skill-creator-for-work 同样禁止冗余文件）。
3. **【禁止】**包内出现 `.git/`、`__pycache__/`、缓存、临时产物、占位空文件。豆包 106 包实测有 3 个把完整 `.git/` 打进分发 zip（如 doubao-game-designer、doubao-wealth-planning），属发布事故，不得重演（CATALOG.md:22）。

### 1.2 front-matter 字段体系

YAML front-matter **必须**位于 SKILL.md 首部并以 `---` 围栏。**必填字段 6 个**：

| 字段 | 类型 | 写法要求（可判定） |
|---|---|---|
| `name` | string | 1–64 字符；仅小写字母、数字与连字符；不得以连字符开头/结尾、不得含连续连字符；**必须与父目录名一致**；禁止 YAML 块标量、禁止路径符。语义化可读命名，**禁止** md5/hash 式命名（豆包 zip 全部 `skill-<hash>.zip` 无语义，检索全靠解包——反面教材）。 |
| `version` | string | 语义化版本 `MAJOR.MINOR.PATCH`。行为或正文变化**必须** bump 并同步 CHANGELOG.md；**禁止**非规范写法（如豆包 journal-format 的大写 `Version: 1.1.0`）。 |
| `license` | string | SPDX 许可证标识（如 `Apache-2.0`）或 `LicenseRef-<内部标识>` 或指向包内 LICENSE 文件。蒸馏自外部作品的包**必须**写明来源许可边界（§5.1）。 |
| `description` | string | 1–1024 **字符**（硬上限取各家最严值：agentskills.io 规范与千问 SkillCreator 均为 1024；Claude Code 技能列表对 description+when_to_use 在 1536 字符截断）。单行标量，**禁止** `>-`/`\|` 块标量（豆包 4 包用块标量，功能等价但徒增解析分支风险；artifact-preview 实测即用 `>-`）。三段式触发设计见 §1.3。 |
| `permissions` | list | 工具权限声明，取值枚举：`shell`（执行本地命令）/ `network`（外部网络请求）/ `fs-write`（写入交付区外的文件系统）/ `browser`（浏览器自动化）/ `user-handoff`（含登录、验证码、OTP、支付等敏感操作）。默认 `[]`。先例：豆包 byted-mediakit 系列 `permissions: [- shell]`。本字段用于评审门禁与宿主适配映射，不假设加载器消费。 |
| `metadata` | map | **平铺的 string→string 键值**（对齐 agentskills.io 类型约定）；列表值用逗号连接成字符串。自有扩展的**唯一**挂载点。 |

`metadata` 约定子键：

- 蒸馏产物**必填**：`source`（来源名称）、`source-url`、`distilled-at`（ISO 日期）。见 §5.1。
- 可选：`requires-bins`（逗号分隔的可执行依赖，如 `lark-cli,python3`；豆包 25 包 `metadata.requires.bins` 先例）、`cli-help`（逗号分隔的依赖探测命令）、`domain`、`route-to`（互导流对象清单）、`description-en`（面向海外分发的英文摘要）、`quality`（验收后由评审按 §4 结果填写）。
- **【禁止】**空值残留键（豆包 dpa-drafter 的 `metadata.dependency/python` 空值属脏字段）；**【禁止】**平铺之外再嵌套结构。

> 规范声明与实务不一致的教训：豆包官方元技能 skill-creator-for-work 在 SKILL.md:345 明文规定 front-matter "Do not include any other fields"（只准 name+description），但其官方库 30/106 个包都写了 metadata/version/permissions。我方不采取"说一套做一套"：本规范即权威，扩展统一收进 `metadata`，并在 build 变体中按渠道剥离（§1.5）。顶层只保留上表 6 个必填字段，**禁止**顶层新增任何其他字段（含 `compatibility`、`allowed-tools`、`when_to_use` 等——它们在 build 变体层生成，见 §1.5）。

### 1.3 description 触发设计（写法要求）

description 是唯一的常驻触发界面（L1 约 100 token，永不卸载），必须按**触发器**写、宁强勿弱。**必须**为三段式：

1. **能力段**：本 skill 是什么、覆盖哪些任务（清单式）。
2. **触发段**：以「当用户……时使用」句式给出正面触发条件，并内嵌**至少 3 个**具体口语触发短语；面向国内宿主**必须**含中文触发词（豆包 artifact-preview 在 description 内嵌 8 条中英触发短语，如「视觉自检」「preview pptx」，实测见其 SKILL.md:3-11）。
3. **边界段**：负面边界——「不用于 X；X 场景转交 `<对方skill-name>`」。互斥或上下游 skill **必须**在彼此 description 中互相点名导流（豆包 medical 系列互写路由构成路由网，是全库最成熟经验）。

判定规则：

- 每个触发场景**必须**能映射到 `eval/golden.json` 中至少 1 条正例或 route_to 负例（§2.1）。
- **【禁止】**把正文指令混入 description（豆包 enterprise-search 的 description 以「必须先完整读取本 skill」开头——正文内容进了元数据字段，反面教材）。
- **【禁止】**空泛触发（如「帮助用户处理文档」）与过窄单句（豆包 lark-attendance 整句仅「查询自己的考勤打卡记录」，触发面过窄，反面教材）。
- 长度：硬上限 1024 字符；低于 80 字符的 description **必须**在评审时单独说明理由。

### 1.4 渐进披露分层规则（格式红线，非建议）

豆包库实测两极分化：薄入口正文最短 363 字（doubao-game-designer，全文 23 行，74 个文件全部下沉 references/），最长单文件 51,056 字（doubao-journal-format，约 25 条边界检查全部内联——官方库自身认定的反模式）。我方规则：

1. **L1 元数据层**（常驻）：name + description，按 §1.3 写。这是唯一 always-on 界面，欠触发（undertriggering）是首要失败模式，触发短语必须具体。
2. **L2 正文层**（触发后加载）：
   - SKILL.md 正文**必须** ≤500 行，且**必须** ≤10,000 字符（约 5,000 token）。超限**必须**下沉 references/。
   - 正文只写 agent 不知道的事：项目特定流程、坑（gotchas 节**必备**）、判据。**【禁止】**「妥善处理错误」式空话条款。
   - **【应当】**学薄入口范式（game-designer：任务定义 + 每次完整读取哪份 workflow + 交付约定，三节收束）。
3. **L3 资源层**（按需加载）：
   - reference 引用**只准一层深**（SKILL.md → references/*.md；references 内部不得再引用新 reference 层级）。
   - 单份 reference 超 100 行**必须**在文件头自带目录。
   - 每处引用**必须**写明触发条件——「若 X 则读 references/Y.md」，**禁止**裸链接（"see references/" 不合格）。
   - **文档地图表【必须】**：SKILL.md 末尾放「reference 文件 × 何时读」两列表（豆包 ppt/sheet/lark-base 三包均为标配；实测 ppt SKILL.md:30-35 场景路由表）。把"什么情况读哪份"变成可查表，不靠自由发挥。
   - 超长 reference **必须**给分页续读标记（豆包 sheet 的「⏬ 未完——继续调整 offset 续读」页标）。
4. **自由度分级**：脆弱操作（格式生成、XML/二进制编辑、精确 API 调用）**必须**用固定脚本承载（低自由度）；开放性任务**可以**用文本指引（高自由度）。

### 1.5 兼容矩阵与多宿主上架

#### 1.5.1 字段兼容矩阵

（依据：agentskills.io 规范页、code.claude.com/docs/en/skills 2026-09 抓取；豆包 106 包本库 fm.json 实测统计；Qoder/Kimi/千问逆向报告 `library/qoder-kimi-qianwen.md` §4.1）

| 字段 | agentskills.io 开放标准 | Claude Code | claude.ai / Skills API | 豆包（106 包实测） | Qoder（11 包） | Kimi（7 包） | 千问（Skill 运行时） | WorkBuddy |
|---|---|---|---|---|---|---|---|---|
| `name` | 必填，1–64，`[a-z0-9-]`，=目录名 | ✓ | ✓ | 106/106 | 11/11 | 有，弱校验（允许无 frontmatter、目录名≠name） | ✓；禁块标量/路径符，非法拒收 | 纯文本形态直接兼容 |
| `description` | 必填，1–1024 | ✓（与 when_to_use 合计在列表 1536 截断） | ✓ | 106/106 | 11/11 | 有（允许缺失） | ✓；缺失则整包跳过 | 兼容 |
| `license` | 可选 | ✓ | ✓ | 9/106 | — | — | ✓ | — |
| `compatibility` | 可选，≤500 字符 | ✓ | ✓ | 3/106 | — | — | ✓ | — |
| `metadata` | 可选，str→str | ✓ | ✓ | 30/106 | — | — | ✓（snake+camel 双写） | — |
| `allowed-tools` | 可选（实验性，各端支持不一） | ✓ | 不通用 | — | — | — | ✓ | — |
| `version`（顶层） | 无此字段 | 未定义 | — | 24/106 | — | — | — | — |
| `permissions`（顶层） | 无此字段 | 未定义 | — | 5/106（全 `- shell`） | — | — | — | — |
| 各家私有扩展 | — | when_to_use / effort / context: fork / paths / hooks 等 | 仅 6 个标准字段通用 | metadata.requires.bins、cliHelp；agents/*.yaml（interface 三键） | descriptionZh 双语；catalog.v1.json 逐文件 sha256 | KIMI_SKILLS_ROOT skip-if-exists + MANAGED_OVERRIDE 名单 | Claude Code 全套扩展字段 snake/camel 双写；20MiB 安审；官方身份 errorCode=-4 保护 | Skill=纯文本提示词零代码；Expert/Connector 为平台私有层 |

#### 1.5.2 build 变体生成规则（minimal 改动上架多家）

canonical 包只写一次，由 `build.py` 生成渠道变体。核心 build **只依赖** `name`、`description`、`SKILL.md` 三要素——这是全部渠道的最大公约数。

| 变体 | 目标渠道 | 生成规则 |
|---|---|---|
| `standard`（默认） | agentskills.io / claude.ai / Skills API / Qoder / WorkBuddy | 保留 name / description / license / metadata；`version`→`metadata.version`，`permissions`→`metadata.permissions`（这两个顶层字段不属开放标准，标准变体必须剥离）；如声明了环境要求则生成 `compatibility`（≤500 字符）。 |
| `claude-code` | Claude Code / Claude 插件市场 | standard 基础上，把源码中以 `<!-- cc-only -->` 标注的可选段生成为私有增强字段（when_to_use / effort / allowed-tools / paths 等）；**无标注则不生成**，保证可剥离。 |
| `doubao` | 豆包 | standard 基础上：`metadata.requires-bins` 映射为 `metadata.requires.bins`，`cli-help` 映射为 `metadata.cliHelp`；按 `agents/` 目录原样带上 interface yaml。 |
| `qwen` | 千问 | standard 基础上按需生成 snake/camel 双写字段；zip ≤20MiB（安审门槛）。 |

通用规则：

1. 产物目录名**必须**等于 `name`；用户自装路径按宿主约定（Claude Code `~/.claude/skills/` 或项目 `.claude/skills/`；Qoder `~/.qoder-cn/skills/<kebab>/SKILL.md`；Kimi KIMI_SKILLS_ROOT）。
2. 分发 zip **必须**排除 `.git/`、缓存、临时产物，**必须**附 MANIFEST.json。
3. 上架前**必须**用渠道校验器跑一遍：官方参考 `skills-ref validate`（agentskills/agentskills 仓库）对 standard 变体必须通过。
4. **【禁止】**为单一平台做不可剥离的深度定制，除非该平台给出独家资源对价（分发调研结论：补贴期随时可能结束，平台私有能力层一律做成编译期可剥离层）。

---

## 2. 质量红线

### 2.1 可判定触发条件

1. description 中每个触发场景**必须**可判定，且映射到 golden.json 用例：正例（应触发）与近邻负例（似相关但不应触发）。
2. **【禁止】**以「相关时」「必要时」「适当情况下」等模糊措辞作为唯一触发依据。
3. eval_inputs 配比（§3.2）：正例 ≥4 条；近邻负例 ≥ 正例数的 50%（官方法：约 20 条、半正半负、60/40 train/test 防过拟合）；「相关但误导」型 adversarial 用例 ≥1 条。三类缺一即验收不通过。
4. route_to 断言**必须**同时覆盖：本 skill 应触发的正例、近邻负例中宿主**不应**触发本 skill 的情形。

### 2.2 步骤确定性

1. 每个操作步骤**必须**包含：显式命令/操作 + 显式成功判据。**【禁止】**以 shell 退出码 0 等同业务成功——豆包 ppt 实测条款：「只有 `.ok == true` 且 `.data.slide_id` 非空才能标记已写入」（skill-3f345a…/SKILL.md，权威经验第 5 条配套判据）。
2. **写后回读三态**：凡产出写入型 skill（写文件、调 API、落库），**必须**采用 `pending → written → verified` 状态机——写命令成功只能进入 `written`，服务端回读满足通过条件才可进入 `verified`（豆包 lark-base SKILL.md:33-38 实测原文条款）；存在 `pending`/`written` 项时**禁止**宣称全部完成。
3. **验收矩阵【必须】**：有外部写入的 skill **必须**含「交付物 × 必须回读的命令 × 通过条件」三列表（lark-base SKILL.md:53-64 实测表样）。
4. **脚本门卫**：脆弱操作**必须**配 lint 型校验脚本，且写明「校验不过禁止交付」（豆包 ppt 的 xml_lint.py：error_count 必须为 0，且逐页校验≠全文校验；Kimi pptx-surgical 的 prep→edit(--dry-run)→verify 三步闭环）。编辑类 skill **必须**声明操作（op）清单与数量上限（pptx-surgical 实测仅两种 op 封顶）。
5. **多轮可靠性条款【必须】**置于正文顶部：
   - MUST RELOAD：多轮对话中用户提出新指令时，第一个工具调用**必须**是重新 Read 本 SKILL.md，禁止凭上轮记忆动手（豆包 ppt SKILL.md:26 实测条款——针对上下文压缩/漂移的防线）。
   - 完整读取：技能内的文档必须完整读完，尾部有重要信息，禁止中途截断（ppt SKILL.md:19）。
   - 多附件任务**必须**建附件证据台账：每份附件登记「角色/完整读取证据/源定位/必须使用的信息/目标位置/状态或缺口」（豆包 word 的 attachment_purpose.md 机制）。

### 2.3 防幻觉条款

1. **引用来源**：正文与 references 中每个事实性断言（参数名、API 行为、数值、法条、文献结论）**必须**可回溯——包内相对路径或外部 URL；数值断言**必须**内联来源（豆包 wealth-planning evals 的 `numeric_claim_requires_inline_source` 断言即此条款的机判形式）。
2. **禁止编造参数**：调用外部 CLI/API 前，参数**必须**来自包内文档或 `--help` 实测输出；文档未覆盖的参数**禁止**使用。依赖用 `metadata.requires-bins` 声明，探测命令写进 `cli-help`。
3. **禁止凭记忆读内容**：引用文件/附件**必须**实际读取；**禁止**凭上下文记忆复述文件内容（lark-base 实测条款：命令参数「逐字使用本次返回值，不要手抄、缩写、从上下文记忆改写」）。
4. **禁止未落实的事实占位**：交付物中**禁止**存在未核实的占位事实（wealth-planning evals 的 `no_unresolved_fact_binding` 断言机判此项）。
5. **输出硬模板**：高风险输出**应当**模板化并置顶为最高优先级规则（wealth-planning「线上最高优先级规则：输出硬模板」先例）。
6. **不确定即声明**：正文**必须**含「不确定时的行为」条款——声明不知道并给出核实路径，**禁止**猜测填充。

### 2.4 错误处理要求

1. **降级链显式**：依赖缺失**必须**写明选定模式——警告降级不崩溃（artifact-preview：「Missing pieces degrade to text with a warning, never a crash」），或立即停止并报「包不完整」（mediakit-video）；二选一必须落字，**禁止**默认含糊。
2. **定向修复一次**：回读/校验不一致时，只针对失败项定向修复一次并复验；仍不满足**必须**如实报告未完成项（lark-base SKILL.md:51）。**【禁止】**循环重试、循环换身份/换参数重试（lark-base 91403 错误码条款）。
3. **敏感操作强制用户接管**：登录、验证码、OTP、支付、删除等操作**必须**显式移交用户执行，**禁止**以任何文本形式索要凭据（豆包 browser-use-automation 的 Mandatory user handoff 机制）；对应声明 `permissions: [user-handoff]`。
4. **高风险领域四件套**：医疗/金融/法律类 skill **必须**内建「硬约束清单 + 禁止项 + 免责边界 + 来源可溯」（豆包三线实证写法；如 stock-screening 禁止隐藏评分与确定性投资建议、wealth-planning `must_not_include: 保证收益`）。

### 2.5 打包与脚本安全

1. 发布包**禁止**包含 `.git/`、缓存、临时产物（豆包 3 包泄 .git 源码历史的事故不得重演）；发布前**必须**执行五步自检（skill-creator-for-work SKILL.md:351-360 同款）：SKILL.md 在位 → 资源在位 → 删占位与缓存 → 试跑 scripts → 跑校验器。
2. 发布**必须**生成 MANIFEST.json：逐文件 sha256 + 文件大小 + 总数（Qoder catalog.v1.json 模式）；分发索引沿用 `library/<来源>/CATALOG.md` 形态（名称/版本/一句话能力/结构特征/写法来源五列）。
3. `scripts/` 内代码**禁止**收集凭据、**禁止**向声明域名之外外传数据；服务端请求仅允许 http/https 且必须校验 host、拒绝环回/私有/保留地址；解析不可信 XML 前必须拒绝 DOCTYPE/ENTITY；SQL 一律参数绑定。
4. 发布渠道风险对齐：skill 含可执行代码，分发时**必须**附来源与哈希清单供买方自证安全（ClawHub 恶意 skill 事件后，「可审计的干净 skill」本身是卖点）。

---

## 3. 评价体系（每个 skill 必须捆绑 eval/）

### 3.1 确定性评测：`eval/runner.py`（机器可判）

`runner.py` **必须**满足：

1. 读取 `golden.json`，执行其中 `eval_inputs` 的全部确定性 `checks`，逐条输出 pass/fail 与证据；汇总 `pass_rate`。
2. 输出 JSON 报告；全部通过退出码 0，否则非 0。
3. 确定性：固定临时目录与随机种子；离线优先，确需外部依赖的**必须**可 mock 或在文件头显式声明。
4. 只断言可机判对象：文件存在、JSON 合法、字段值、正则匹配、数值范围、路由结果、命令退出码。**【禁止】**用确定性断言去判文风类主观质量（那是盲评臂的职责）。
5. 断言卫生：恒过断言（无信息量）**必须**剔除；恒败断言**必须**修复；with_skill 与 without_skill 双双通过的断言不计入技能价值（官方 SOP 四条 pattern 规则）。

### 3.2 黄金集：`eval/golden.json`

**必须**包含 `eval_inputs` 与 `ab_tasks` 两组，schema 如下：

```json
{
  "skill": "<name>",
  "version": "<semver，与包版本一致>",
  "eval_inputs": [
    {
      "id": "pos-001",
      "type": "positive | negative | adversarial",
      "prompt": "触发/不触发本 skill 的任务输入",
      "inputs": ["可选输入文件"],
      "route_to": "<name> 或 \"!\"" ,
      "checks": [
        {"kind": "file_exists", "value": "output/report.md"},
        {"kind": "json_valid", "value": "output/data.json"},
        {"kind": "field_equals", "path": "ok", "value": true},
        {"kind": "regex_match", "target": "output/report.md", "pattern": "..."},
        {"kind": "must_include | must_not_include", "target": "...", "value": "..."},
        {"kind": "numeric_range", "target": "...", "min": 0, "max": 100},
        {"kind": "numeric_claim_has_source", "target": "output/report.md"},
        {"kind": "command_exit", "cmd": "...", "expect": 0}
      ]
    }
  ],
  "ab_tasks": [
    {
      "id": "ab-001",
      "prompt": "盲评任务输入",
      "context_files": ["可选上下文文件"],
      "rubric": [
        {"dimension": "正确性", "weight": 4, "descriptor": "10=…；6=…；0=…"},
        {"dimension": "完整性", "weight": 3, "descriptor": "…"},
        {"dimension": "可验证性", "weight": 3, "descriptor": "…"}
      ],
      "deterministic_checks": ["可复用 eval_inputs 的 checks 子集，双臂同判"]
    }
  ]
}
```

规则：

1. `eval_inputs` 三类用例缺一不可：`positive`（应触发且做对）、`negative`（近邻不应触发——测 description 精度）、`adversarial`（相关但误导——依据 arXiv:2608.11888 实测，技能致害最大类是 Task-Implementation Fault 68.8%，即"相关但误导的流程"，仅测触发不测误导是不够的）。
2. `ab_tasks` ≥3 条；每条带 0–10 rubric（维度+权重+分档描述）；维度**必须**含正确性、完整性、可验证性。
3. `must_not_include` **必须**写入该 skill 的红线禁语（如「保证收益」「确定性投资建议」）。
4. golden.json 冻结于验收时版本；修订**必须**升 gold 版本号并在 CHANGELOG 记录、旧版归档（`eval/golden-v<N>.json`），**禁止**为让新实现通过而静默改断言。

### 3.3 有无对照盲评协议：`eval/protocol.md`

1. **两臂**：with_skill（挂载本 skill）vs without_skill（不挂载）；同一模型、同一 harness、同一 prompt 与上下文；每次运行用独立子代理保证干净上下文。
2. **baseline 选取**：全新 skill 的 baseline 臂 = without_skill；迭代修订版的 baseline 臂 = 旧版快照（`cp -r` 存档后作旧臂，官方法）。
3. **重复次数**：每条 ab_task 每臂 ≥3 次。
4. **裁判**：独立盲评裁判，**不知道**两臂来源与呈现顺序；逐维度按 rubric 打 0–10 分；LLM 裁判**必须**给出评分证据；**禁止**同情分（"PASS 要证据"）。
5. **计分**：单次加权总分 = Σ(维度分×权重)/Σ权重；`benchmark.json` **必须**记录：每臂均分±标准差、逐对胜负、token 用量与耗时均值。
6. **效率是一等指标**：with/without 的 token 比率与耗时比率**必须**记录（SWE-Skills-Bench 实测 token 开销最高 +451%；arXiv:2608.11888 实测 62.6% 失败为效率回退、Context Bloat 几乎全由强制正文造成）。

---

## 4. 验收线（资产准入 = 生产流程门禁）

以下五门**全部**通过，方可入库 `skillfactory/assets/` 并进入分发管线；该验收线同时是生产流程的强制门禁——任一门不过，**禁止**发布、**禁止**对客户交付。

1. **确定性门**：`python eval/runner.py` 退出码 0，golden.json 全部确定性检查通过。**重生成实现（重构、换实现方式、修订版）必须对同一版 golden.json 全量回归、全部通过**，方可进入盲评。
2. **盲评门**：按 §3.3 协议，treatment 均分 − baseline 均分 **≥ 1.0**（0–10 加权制），且 treatment **胜率 ≥ 60%**（胜 = 同一 ab_task 同一重复序对中 treatment 加权分严格更高；平局不计胜；总对数 = ab_tasks 数 × 每臂重复次数）。
3. **效率门**：token 比率 ≤2.0 且 耗时比率 ≤2.0（treatment/without），任一超限一票否决，无论质量分多高。
4. **形式门**：§1 全部格式检查通过——name==目录名、6 必填字段齐全、description ≤1024 且三段式、正文 ≤500 行且 ≤10,000 字符、文档地图表在位、reference 一层深、打包卫生（无 .git/缓存、MANIFEST 在位）、渠道校验器（skills-ref validate）对 standard 变体通过。
5. **断言复审门**：无恒过断言、无恒败断言、无双臂同过的无信息断言。

验收记录**必须**落盘 `eval/results/benchmark.json` + 验收单（五门逐项结论与证据），metadata.quality 由此填写。

---

## 5. 蒸馏与融合规范

### 5.1 外部知识蒸馏（paper / book / pdf → skill）

1. **来源登记**：`metadata.source`、`metadata.source-url`、`metadata.distilled-at` **必填**；`license` **必须**写明来源许可边界。蒸馏产物入库前按来源建立台账（与 CATALOG.md 索引打通）。
2. **蒸馏边界**：只抽取**方法、流程、事实与结构**；**【禁止】**复制受版权保护的表达，**【禁止】**整段复制来源文字或第三方官方文案（我方红线；引文限于合理引用范围并逐条注明出处）。K-Dense 直接 vendor anthropics/skills 的做法仅在许可明确（Apache-2.0）时允许，且**必须**保留原许可与署名。
3. **忠实性**：关键步骤与结论**必须**可回溯到来源位置（章节/页码/§）；来源中没有的补全**必须**显式标注 `[补充]` 并附独立依据，**【禁止】**把常识补全伪装成来源内容。
4. **反空话**：官方 best-practices 实证——纯靠通用知识生成的技能只会得到「handle errors appropriately」式空话；每个指令**必须**携带来源中的具体细节（参数、阈值、顺序、坑）。
5. **结构**：薄入口 + `references/` 按章节或方法分层；`gotchas` 节**必备**（来源中明示的坑 + 蒸馏验证过程中实测踩到的坑）。
6. **入库**：蒸馏产物**必须**带 `eval/results/` 评测记录并过 §4 五门，否则不算资产。

### 5.2 多方法融合大 skill 的意图路由结构

多个方法（不同的流程/范式/工具链）融合进一个 skill 时，**必须**采用路由型结构（先例：豆包 byted-mediakit-shared 纯路由入口、ppt 场景四分支、doubao-ultimate-guide 的 branches/ 总控+分支）：

1. **路由 SKILL.md 只留四件**：①意图→方法路由表；②**方法边界表**；③**移交协议**；④文档地图表（§1.4）。方法细节全部下沉 `references/<method>.md`，每方法 references ≤3 份。
2. **方法边界表【必须】**逐方法一行，列齐全：方法名 / 适用意图特征 / 输入 / 输出 / **不适用场景** / 与相邻方法的排他条件（学豆包 medical 系列互写排他与导流）。
3. **移交协议【必须】**写明：移交触发条件（何种信号转入另一方法）；移交时**必须**携带的状态（已完成步骤清单、中间产物路径、关键 ID）；移交后禁止事项（不得回退已验证步骤、不得重复询问已确认事实）。
4. **description**：按融合整体写三段式（§1.3）；负面边界中**必须**逐一写明各方法专属的转交路由。
5. **评测**：`eval_inputs` 中每个方法**必须**至少 1 条正例 + 1 条近邻负例（route_to 断言到方法粒度）；`ab_tasks` **必须**覆盖至少 1 条跨方法任务（验证移交协议）。
6. 方法数超过 4 个、或任一方法 references 超 3 份时，**必须**拆分为多个独立 skill + 一个总控路由 skill。

---

## 6. 本规范的版本与维护

1. 本规范自身的修订：新增条款升次版本号（v0.x）；改变必填字段、验收线数值等破坏性变更升主版本号（v1.0+）并在 CHANGELOG 说明迁移期。
2. 每季度复核一次：对照 agentskills.io 规范版本与各平台私有扩展演进（跟踪信号：任一大平台公布 skill 分成/数字商品政策、审核收紧、开放标准字段变更），确认 §1.5 变体规则仍成立。
3. 本规范的任何豁免**必须**书面记录于对应 skill 的 CHANGELOG 并经评审确认，豁免不构成先例。

---

## 附录 A：SKILL.md 骨架模板

```markdown
---
name: my-skill
version: 0.1.0
license: LicenseRef-skillfactory-internal
description: 〔能力段〕面向 X 的 Y，覆盖 A/B/C。〔触发段〕当用户需要 A、上传 B、要求 C 时使用；触发短语：「做X」「处理Y」「zzz」。〔边界段〕不用于 W；W 场景转交 other-skill。
permissions: []
metadata:
  source: ""            # 蒸馏产物必填
  source-url: ""        # 蒸馏产物必填
  distilled-at: ""      # 蒸馏产物必填
  requires-bins: ""     # 可选：逗号分隔
  cli-help: ""          # 可选：逗号分隔
  domain: ""
  route-to: ""
---

# my-skill

## 权威规则（置顶，编号 MUST 清单）
1. 【MUST RELOAD】多轮对话中出现新指令时，第一个工具调用必须是重新 Read 本 SKILL.md。
2. 本技能引用的文档必须完整读完，禁止中途截断。
3. 不确定时：声明不知道并按下节核实路径确认，禁止猜测填充。

## 步骤主线（每步：显式命令 + 显式成功判据；写后回读 pending→written→verified）
…

## 错误处理（降级链 / 定向修复一次 / 敏感操作移交用户）
…

## 文档地图
| 文档 | 何时读 |
|---|---|
| references/method-a.md | 若任务是 … 则必读 |
| references/gotchas.md | 交付前必读 |

## gotchas（实测踩坑，持续追加）
…
```

## 附录 B：验收检查单（生产流程执行件）

- [ ] name==目录名，`[a-z0-9-]` 合法；version 为 semver；license 在位
- [ ] description ≤1024 字符、单行标量、三段式、≥3 个触发短语、边界段含转交路由
- [ ] permissions ⊆ 枚举且与正文敏感操作一致；metadata 平铺无空值；蒸馏产物三键在位
- [ ] 正文 ≤500 行且 ≤10,000 字符；gotchas 节在位；文档地图表在位；reference 一层深且引用带触发条件
- [ ] MUST RELOAD / 完整读取 / 不确定即声明三条款在正文顶部
- [ ] 写入型步骤有回读三态与验收矩阵；脆弱操作有 lint 门卫且写明"校验不过不交付"
- [ ] 事实断言可回溯；数值断言带内联来源；无编造参数路径
- [ ] eval/ 四件齐（runner.py / golden.json / protocol.md / results/）；三类用例齐配比达标；断言卫生通过
- [ ] 盲评五门：确定性 ✓｜均分差 ≥1.0 ✓｜胜率 ≥60% ✓｜token 与耗时比率 ≤2.0 ✓｜形式门 ✓
- [ ] 打包：无 .git/缓存；MANIFEST.json 逐文件 sha256；skills-ref validate 通过

## 附录 C：证据索引

**本会话实际读取核验**（path:line 可点开复核）：

- 豆包 106 包盘点总表与统计：`skillfactory/library/doubao/CATALOG.md`（:9-22 统计；:30 artifact-preview；:33 ppt；:42 lark-attendance；:43 lark-base；:67 journal-format 反模式；:95 wealth-planning；:156 mediakit-shared 路由入口；:168 browser-use-automation；:177 enterprise-search；:181 skill-creator-for-work；:189 game-designer；:219 三代包风格）
- ppt 权威经验与 MUST RELOAD：`skillfactory/library/doubao/skill-3f345a337e8b5d02f0ab7506dcdffbfa/SKILL.md:16-27`（:26 MUST RELOAD；:19 完整读取；:32 场景路由必读分支）
- lark-base 写后回读三态与验收矩阵：`skillfactory/library/doubao/skill-30ee3da3189d08ee2d8aeebd1841ef26/SKILL.md:33-64`（:35 三态；:38 禁止 pending/written 宣称完成；:51 定向修复一次；:53-64 验收矩阵）
- game-designer 薄入口全样本：`skillfactory/library/doubao/skill-16c0c9701f05d6bff1746e22b3bb0d92/SKILL.md`（全文 23 行）
- wealth-planning 结构化断言：`skillfactory/library/doubao/skill-5e84a530ca1db13e950dbc89ee470800/evals/evals.json:1-37`（route_to / must_include / must_not_include / no_unresolved_fact_binding / numeric_claim_requires_inline_source）
- artifact-preview 触发短语、license/compatibility、块标量：`skillfactory/library/doubao/skill-cb8086694dfbc1ce1c21fab63fcc1b3b/SKILL.md:1-15`
- 豆包官方元技能 front-matter 规范声明与收尾自检：`skillfactory/library/doubao/skill-6029eb84e8a494e03cfdaf144da253e7/SKILL.md:335-345、:351-364`
- Qoder/Kimi/千问逆向：`skillfactory/library/qoder-kimi-qianwen.md`（§4.1 字段对比、§4.2 信任模型、§5 implications）

**侦察报告引用、本会话未重访**（引自任务下发的四份侦察发现及其 sources；引用时保持转述口径）：

- agentskills.io 开放规范与官方评测 SOP、best-practices；code.claude.com/docs/en/skills（Claude Code 私有字段与硬限制）；anthropic 工程博客（Skills 与 MCP 互补）
- 论文：SkillsBench arXiv:2602.12670（+16.6pp、聚焦技能优势）；SWE-Skills-Bench arXiv:2603.15401（token 最高 +451%）；arXiv:2608.11888（失败分类学：Task-Implementation Fault 68.8%、效率回退 62.6%、Context Bloat 25.3%）；arXiv:2609.02749（Repo-To-Skill 蒸馏路线）；arXiv:2608.23067（无差别注入适得其反）
- 生态与分发：anthropics/skills、VoltAgent/awesome-agent-skills、obra/superpowers、K-Dense-AI/scientific-agent-skills；WorkBuddy/Qoder/TRAE/Coze/ModelScope/MCP Registry/OpenAI Apps 分发现状（skill 平台内售卖零证据，平台政策随时可变——支撑 §1.5.2"可剥离层"与不签独家原则）

## 增补条款 A-1（2026-09-30）：接口常量全文披露

1. 凡 eval 对常量（token 名、要素名、字段名、枚举值）做逐字节或高阈值（如结构一致率阈值）比对者，该常量全集**【必须】**全文列于该资产的 `spec.md` 或 `contract.md` 附录——逐条给出字面值与语义注记，使实现者不读参照实现即可产出逐字节合规的产物。
2. **【禁止】**以「以某文件为冻结源」式引用替代披露（如仅写「token 以 gen.py builder 为准」）；指向冻结源的引用仅可作来源佐证，不得替代常量本体在规格文档中的全文在位。
3. 本案案例：hot-templates 资产重生成曾因四平台开放槽位 token 名、video 要素命名、xhs 七要素占位符、wx `total_filled_from_input` 语义只存在于 `oracle/gen.py` 而连续两轮受阻，后经雇主批准有限例外（读取 oracle 核对）方通过——本条款即该接口文档缺陷的根治。

---

*（SKILL-SPEC v0.1 完）*

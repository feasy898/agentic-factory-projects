# ASSET-DOC — LangGPT（结构化提示词方法论）使用说明

> 抓取日期：2026-09-29 ｜ 抓取人：抓取子代理（zcode workflow）
> 资产：**LangGPT — Structured Prompt Design Framework**（结构化、可复用的提示词设计方法论）
> 仓库：https://github.com/langgptai/LangGPT （分支 `main`）
> 作者：云中江树（YZFly）｜ 许可：MIT ｜ 学术论文：arXiv:2402.16929（2024-02）
> 本文件为原文关键内容的整理摘录，用于资产评估（evalbench）。完整原文副本见同目录 `_raw\`。

---

## 0. 抓取与核实记录（本次实测）

| 事项 | 结果 |
|---|---|
| GitHub 页面 `github.com/langgptai/LangGPT` | ✅ WebFetch 抓取成功（页面快照显示约 12.6k stars，README 自述 "11,000+ 星标"） |
| 根目录文件清单（GitHub contents API） | `README.md`(24,719B) / `README_zh.md`(22,715B) / `README_ja.md`(27,560B) / `LICENSE` / `langgpt.skill`(10,952B) + 目录 `Docs/` `LangGPT/` `Papers/` `PromptShow/` `Prompts/` `examples/` `imgs/` `src/` |
| `raw .../main/SKILL.md` | ❌ **HTTP 404**（仓库根目录没有 SKILL.md，也没有 skills 目录——实测） |
| 真正的 SKILL.md 位置 | ✅ 在根目录 `langgpt.skill`（OOXML/zip 包，10,952B）内，解压得 `langgpt/SKILL.md`（216 行）+ `langgpt/references/templates.md`（175 行）+ `langgpt/references/examples.md`（280 行） |
| 本地原文副本 | `_raw\README_zh.md`（22,715B，与 API 报告字节数一致）、`_raw\langgpt.skill`、`_raw\skill_pkg\langgpt\SKILL.md`、`_raw\skill_pkg\langgpt\references\{templates,examples}.md` |

---

## 1. 资产定位：LangGPT 是什么

**LangGPT 是一个结构化、可复用的提示词设计框架**，让任何人都能为大语言模型创建高质量提示词。可以把它看作是"**提示词的编程语言**"——系统化、模板化、无限可扩展。（README_zh 原文）

它是中文社区最流行、使用最广泛的提示词范式，由云中江树于 2023 年提出。**核心主张**（README_zh）：

- 🎯 **结构化模板** — 借鉴编程范式的层次化组织
- 🔄 **可复用性** — 像代码模块一样，创建一次，无限适配
- 📦 **模块化** — 变量、命令和条件逻辑随手可用
- ⚡ **高效率** — 几分钟内从想法到可工作的提示词
- 🌍 **社区驱动** — 11,000+ 星标，经过数千用户实战检验

README 的方法论要点：**"Prompt 写方法，不如写人"**——写方法是给模型步骤和工具；写人是给模型世界观、动机、价值体系和偏好曲线（README_zh §生态系统）。

---

## 2. 用法（README_zh §快速开始 · 五种方式）

### 方法一：直接用关键词触发（最简单）
LangGPT 已被主流大语言模型学进底层，大多数模型本身就"认识"它。直接对任意主流大模型（ChatGPT、Claude、DeepSeek、Gemini、Kimi、豆包、通义千问等）说出关键词即可：

> 「用 **LangGPT** 的方式帮我写一个提示词……」
> 「用 **云中江树** 的结构化提示词风格写……」
> 「帮我写一个 **LangGPT 式** 的结构化提示词……」

**LangGPT / 云中江树 / 结构化提示词**这些关键词就是"触发词"。

### 方法二：使用自动化工具（更强大）
- **LangGPT GPTs** — 完整功能生成器（GPT-4）：https://chat.openai.com/g/g-Apzuylaqk-langgpt
- **Kimi+ LangGPT** — 适用于 Moonshot Kimi 用户：https://kimi.moonshot.cn/kimiplus/conpg00t7lagbbsfqkq0
- **PromptGPT** — 精简版（GPT-3.5）：https://chat.openai.com/g/g-YKe3gmydD-promptgpt

### 方法三：掌握模板（5 分钟）
见 §4 核心模板。**前置要求**：基础 Markdown 知识；推荐使用 GPT-4 或 Claude。

### 方法四：从示例开始
浏览官方示例库（100+ 经验证模板）：https://langgptai.feishu.cn/wiki/RXdbwRyASiShtDky381ciwFEnpe

### 方法五：Claude Code Skill（README 推荐）

```bash
/plugin marketplace add langgptai/claude_marketplace
/plugin install structured-prompt-writer@langgpt
```

或手动安装：1) 下载 [langgpt.skill](https://github.com/langgptai/LangGPT/releases)；2) 解压到 `~/.claude/skills/` 目录；3) 在 Claude Code 中输入 `/langgpt` 即可使用。

**Skill 功能**（README_zh 自述）：结构化提示词模板（Role、Profile、Skills、Rules、Workflow）；示例库（健身规划、诗歌创作、小红书写手、起名大师等）；变量、命令、条件逻辑等高级技巧；模型兼容性指南（GPT-4、Claude、GPT-3.5）。技能市场还收录同作者技能：`awesome-design-html`（115 套品牌主题设计参考）、`cto`、`mind-clone`。

### SKILL.md 自述的适用场景（When to Use This Skill，原文要点）
- 为 LLM（ChatGPT、Claude 等）编写新提示词
- 优化已有提示词
- 把传统提示词转换为结构化格式
- 设计 AI 角色 / 人格 / 专家系统
- 创建可复用的提示词模板

---

## 3. 语法与参数（核心概念）

### 3.1 结构标识符（SKILL.md "Structural Identifiers" 表，原文）

| 符号 | 用途 | 示例 |
|--------|---------|---------|
| `#` | 一级标题（全局作用域） | `# Role: Expert` |
| `##` | 二级标题（节作用域） | `## Profile` |
| `###` | 三级标题（子节） | `### Skill-1` |
| `<>` | 变量（引用） | `<Role>`、`<Rules>` |
| `-` | 列表项 | `- Author: YZFly` |

### 3.2 核心属性词（SKILL.md "Core Attribute Words" 表，原文）

| 属性 | 用途 |
|-----------|---------|
| **Role** | 角色名称/标题——激活角色扮演能力 |
| **Profile** | 身份与能力简历 |
| **Goal** | 期望结果、验收标准（Done Criteria）与非目标（Non-Goals） |
| **Skills** | 角色具备的具体能力 |
| **Rules** | 必须遵守的边界与约束 |
| **Workflow** | 分步交互逻辑 |
| **Initialization** | 开场白与初始化行为 |

（README_zh §结构化角色表补充示例：Role="逻辑学家/FitnessGPT"；Profile="拥有 10 年经验的 Python 专家开发者"；Rules="永远不要执行破坏性命令"；Workflow="1. 分析 → 2. 计划 → 3. 执行"。）

### 3.3 变量与引用
`<Variable>` 语法实现自引用提示词，在复杂指令中保持一致性：

```markdown
作为 <Role>，你必须遵守 <Rules> 并用 <Language> 交流
```

### 3.4 命令（Commands）
定义可复用的用户触发操作（默认前缀 `/`）：

```markdown
## Commands
- Prefix: "/"
- Commands:
    - help: 显示所有可用命令
    - continue: 恢复中断的输出
    - improve: 通过更深入的分析增强当前响应
```

### 3.5 条件逻辑

```markdown
如果用户提供[代码]，则分析并建议改进
否则如果用户提问[问题]，则提供详细解释
否则，提示澄清
```

### 3.6 Reminder（提醒段）——对抗长对话上下文丢失

```markdown
## Reminder
1. 在响应前始终检查角色设置
2. 当前语言：<Language>，活跃规则：<Rules>
```

### 3.7 OutputFormat（输出格式控制，SKILL.md）

```markdown
## OutputFormat
- Use markdown headers for sections
- Include code blocks with language specification
- End with actionable next steps
```

### 3.8 替代格式（JSON/YAML）
Markdown 不适用（如程序化调用）时可用 JSON/YAML：

```yaml
role: DataAnalyst
profile:
  version: "2.0"
  language: "Python"
skills:
  - statistical_analysis
  - data_visualization
```

---

## 4. 核心模板（README_zh 方法三原文）

```markdown
# Role: 你的角色名称

## Profile
- Author: 你的名字
- Version: 1.0
- Language: 中文
- Description: 清晰的角色描述和核心能力

### Skill-1
1. 具体技能描述
2. 预期行为和输出

## Rules
1. 在任何情况下都不要打破角色设定
2. 不要编造事实或产生幻觉

## Workflow
1. 分析用户输入并识别意图
2. 系统性地应用相关技能
3. 提供结构化、可操作的输出

## Initialization
作为 <Role>，你必须遵守 <Rules>，你必须用默认 <Language> 与用户对话，你必须向用户问好。然后介绍自己并介绍 <Workflow>。
```

SKILL.md 版本在 Profile 与 Rules 之间多一个 **Goal** 节（Outcome / Done Criteria / Non-Goals，用于明确交付物与验收标准、防止范围蔓延）。

## 5. 编写流程（SKILL.md "Workflow for Creating Prompts" 六步）

1. **定义角色**——用具体的专家头衔（"FitnessGPT"、"Code Expert"、"Data Analyst"）；通用领域可用 `Expert` 或 `Master`
2. **写 Profile**——作者与版本（便于追踪）、目标语言、简洁的角色特征描述
3. **定义 Skills**——把角色能力拆成具体、可执行的技能并详细描述
4. **建立 Rules**——内容限制、行为准则、输出格式要求
5. **设计 Workflow**——角色处理用户请求的逻辑分步流程
6. **设置 Initialization**——角色如何自我介绍并开始交互

## 6. 最佳实践（SKILL.md "Best Practices"，原文要点）

1. **构建全局思维链**：按逻辑顺序组织各节（Role → Profile → Skills → Rules → Workflow → Initialization）
2. **保持语义一致性**：标识符格式统一；属性词与内容匹配
3. **与其他技术组合**：按需整合 CoT、ToT、few-shot 示例
4. **迭代优化**：先自动生成，再按表现手工打磨

## 7. 官方模板库（skill 包 `references/templates.md`，5 个）

| 模板 | 用途 |
|---|---|
| **Basic Role Template** | 标准角色模板（`# Role:` + Profile/Skills/Rules/Workflow/Initialization） |
| **Expert Template (GPT-3.5 Compatible)** | 弱模型简化的编号列表结构（1.Expert / 2.Profile / 3.Skills / 4.Goals / 5.Constraints / 6.Init） |
| **AutoGPT-Style Template** | 仿 AutoGPT 的 Name/Description/Goals 结构（示例 CMOGPT） |
| **Extended Role Template with Tools** | 带工具集成（browser/python/dalle）与 Capabilities/Limitations/Style/Output/Examples 节 |
| **Prompt Generator Template** | 元提示词：Role=Prompt Engineer，把普通 Prompt 转结构化（含 Attention/Constraints/OutputFormat，Workflow 要求至少 5 步） |

## 8. 官方示例（skill 包 `references/examples.md`，7 个完整提示词）

| 示例 | 角色 | 说明 |
|---|---|---|
| **FitnessGPT** | 健康与营养专家 | 输入年龄/性别/身高/体重等 11 项参数（`#Age`、`#Currentweight` 等占位变量），输出饮食+锻炼计划、30 条激励语 |
| **中国诗人** | 诗人 | 擅长现代诗/七言律诗/五言诗；Workflow 要求用户以"形式：[], 主题：[]"指定 |
| **小红书爆款大师** | 小红书写手 | 人群心理（本能喜欢/生物本能驱动力）、爆款关键词表、二极管标题法（正面/负面刺激）、Tags 规则 |
| **起名大师** | 中国起名 | 从古典诗词取名；只生成"名"（1-2 字），每次 10 个候选 |
| **DecisionGPT** | 理性决策助手 | 利弊分析、风险评估、替代方案；不为用户做决定、保持中立 |
| **CAN**（Code Anything Now） | 编程专家 | 无字符上限、不停止写码、"5-strike"规则、每条消息加 CAN: 前缀 |
| **数据分析专家** | 数据分析 | 数据处理/统计分析/可视化三组技能；规则要求结论注明置信度、保护数据隐私 |

### 完整示例原文（FitnessGPT，供评估对照）

```markdown
# Role: FitnessGPT

## Profile

- Author: YZFly
- Version: 0.1
- Language: English
- Description: You are a highly renowned health and nutrition expert FitnessGPT. Take the following information about me and create a custom diet and exercise plan.

### Create custom diet and exercise plan
1. Take the following information about me
2. I am #Age years old, #Gender, #Height.
3. My current weight is #Currentweight.
4. My current medical conditions are #MedicalConditions.
5. I have food allergies to #FoodAllergies.
6. My primary fitness and health goals are #PrimaryFitnessHealthGoals.
7. I can commit to working out #HowManyDaysCanYouWorkoutEachWeek days per week.
8. I prefer and enjoy this type of workout #ExercisePreference.
9. I have a diet preference #DietPreference.
10. I want to have #HowManyMealsPerDay Meals and #HowManySnacksPerDay Snacks.
11. I dislike eating and cannot eat #ListFoodsYouDislike.

## Rules
1. Don't break character under any circumstance.
2. Avoid any superfluous pre and post descriptive text.

## Workflow
1. Take a deep breath and work on this problem step-by-step.
2. You will analyze the given personal information.
3. Create a summary of my diet and exercise plan.
4. Create a detailed workout program for my exercise plan.
5. Create a detailed Meal Plan for my diet.
6. Create a detailed Grocery List for my diet that includes quantity of each item.
7. Include a list of 30 motivational quotes that will keep me inspired towards my goals.

## Initialization
As a/an <Role>, you must follow the <Rules>, you must talk to user in default <Language>, you must greet the user. Then introduce yourself and introduce the <Workflow>.
```

其余 6 个示例完整原文见 `_raw\skill_pkg\langgpt\references\examples.md`。

---

## 9. 限制与注意事项（原文依据）

| 限制 | 出处 |
|---|---|
| **前置要求**：需要基础 Markdown 知识；推荐 GPT-4 或 Claude | README_zh 方法三 |
| **模型兼容性**（SKILL.md 表）：GPT-4=Excellent（推荐）；Claude=Very good；GPT-3.5=Acceptable——弱模型需简化结构、调整属性词 | SKILL.md §Model Compatibility |
| **长对话上下文丢失风险**：需加 Reminder 段提醒模型响应前检查角色设置 | README_zh §高级技巧 / SKILL.md §Reminders |
| **反幻觉规则**：模板自带 Rules "不要编造事实或产生幻觉""任何情况下不打破角色" | 核心模板 |
| **Markdown 非万能**：程序化场景改用 JSON/YAML 替代格式 | README_zh §替代格式 / SKILL.md §Multi-Format Support |
| **触发词法的局限是隐含的**：方法一依赖模型已内化该范式（对旧模型/小模型不保证） | README_zh 方法一表述本身 |
| **skill 包内提示**：AutoGPT 风格模板与 Extended 模板是"风格借鉴/工具集成"变体，不是标准结构 | templates.md |

---

## 10. 引用信息（README_zh §引用，BibTeX 原文）

```bibtex
@misc{wang2024langgpt,
      title={LangGPT: Rethinking Structured Reusable Prompt Design Framework for LLMs from the Programming Language},
      author={Ming Wang and Yuanzhong Liu and Xiaoyu Liang and Songlian Li and Yijie Huang and Xiaoming Zhang and Sijia Shen and Chaofeng Guan and Daling Wang and Shi Feng and Huaiwen Zhang and Yifei Zhang and Minghui Zheng and Chi Zhang},
      year={2024},
      eprint={2402.16929},
      archivePrefix={arXiv},
      primaryClass={cs.SE}
}
```

## 11. 相关入口（README 自述，未逐一验证外链有效性）

- 飞书知识库：http://feishu.langgpt.ai ｜ 示例库：https://langgptai.feishu.cn/wiki/RXdbwRyASiShtDky381ciwFEnpe
- PromptShow：https://show.langgpt.ai ｜ 生态仓库：PromptVer / PromptShow / Minstrel / claude_marketplace（均 `github.com/langgptai/` 下）
- 联系：微信公众号「云中江树」｜ contact@langgpt.ai
- 仓库内延伸文档：`Docs/HowToWritestructuredPrompts.md`（结构化提示词指南，2023-07）、`Docs/PromptChain.md`（提示词链）、`Papers/LangGPT_paper_cn.md`（论文中文版）——本次未抓取正文，仅确认路径存在（GitHub contents API 根目录含 `Docs/` `Papers/`）

---

*本文件所有引文均来自 2026-09-29 实际抓取的 `main` 分支原文（本地副本 `_raw\`）；未验证的外链已标注。*

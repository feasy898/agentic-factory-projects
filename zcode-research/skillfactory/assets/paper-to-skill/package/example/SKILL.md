---
name: skill-authoring
version: 1.0.0
license: LicenseRef-skillfactory-internal
description: 按 Agent Skills 开放规范编写格式合规技能包的操作指南：目录结构、front-matter 六项约束、name 命名规则、正文分层与渐进披露、skills-ref 校验。当用户要新建技能包、编写或修改 SKILL.md、给技能起合法名称、或检查既有技能是否合规时使用；触发短语：「写一个技能」「新建 SKILL.md」「技能名报错」「校验技能合规」「skill 格式」。不用于把论文/官方文档/长文蒸馏成新技能（该场景转交 paper-to-skill），也不用于设计具体领域的业务逻辑。
permissions: [shell]
metadata:
  source: "agentskills.io《Specification》页 WebFetch 抓取稿（paper-to-skill/oracle/inputs/source.md）"
  source-url: "https://agentskills.io/specification"
  distilled-at: "2026-09-29"
  domain: "agent-skills"
  route-to: "paper-to-skill"
---

# skill-authoring（技能包编写指南）

> 成品声明：本文件是 paper-to-skill 方法论的示范产物——对蒸馏源 `oracle/inputs/source.md`
> 先由 `scripts/distill.py` 生成骨架，再按六步流程人工补全为成品。内容为源文本结构化摘取＋中文重写，
> 逐条标注「原文 L<行号>」（剥离源 front-matter 与头注释后的正文行号，与 `../out/outline.json` 同口径）；
> 来源中没有的补全均标 `[补充]`。本文件按资产契约放在 `example/` 下作样例；真实交付时技能目录名必须等于
> front-matter 的 name（原文 L70）。

## 权威规则（置顶）

1. 【MUST RELOAD】多轮对话中出现新指令时，第一个工具调用必须是重新 Read 本 SKILL.md，禁止凭上轮记忆动手。
2. 本指南正文必须完整读完，禁止中途截断。
3. 数值红线：本指南全部约束数值均可回溯「原文 L」标记；与来源冲突时以来源为准。
4. 不确定即声明：本指南未覆盖的字段或参数，先查来源规范页或用 `skills-ref validate` 实测，禁止编造。

## 分步方法（从零到校验通过）

1. 建目录骨架：以技能名创建目录，目录内至少含 `SKILL.md` 一个文件（原文 L12）；按需添加 `scripts/`（可执行脚本）、`references/`（按需文档）、`assets/`（模板与静态资源）子目录（原文 L216、L226、L236），完整目录树见源（原文 L14-21）。成功判据：目录名与第 3 步确定的 name 完全一致（原文 L70）。
2. 写 front-matter：`SKILL.md` 必须以 YAML frontmatter 开头、其后为 Markdown 正文（原文 L25）；必填 `name` 与 `description` 两个字段，其余字段按需（字段速查表见下节，约束出处原文 L29-36）；最小可用样例仅三行——`name`、`description` 加围栏（原文 L41-46）。
3. 定名并自查：name 为 1–64 字符，仅小写字母、数字与连字符，不得以连字符开头/结尾、不得含连续连字符，且必须与父目录名一致（原文 L66-70）；对照三个非法反例自查：大写开头（原文 L90）、首连字符（原文 L94）、连续连字符（原文 L98）。
4. 写触发描述：description 为 1–1024 字符的非空单行，写清「做什么＋何时用＋帮助识别任务的关键词」（原文 L106-108）；对照好例（原文 L114）与坏例 "Helps with PDFs."（原文 L120）自检——坏例判不出触发时机；除非确有环境要求，否则不写 compatibility 字段（原文 L164）。
5. 写正文并分层：正文无格式限制，写有助于 agent 干活的内容，建议三节——分步说明、输入输出示例、常见边界情况（原文 L202、L206-208）；主 `SKILL.md` 控制在 500 行以内（原文 L252），细节下沉到 `references/` 等文件且引用链一层为限（原文 L210、L265）；按三层渐进披露组织：元数据约 100 token 常驻、正文建议 <5000 token 触发后加载、资源文件按需读取（原文 L248-250）。
6. 校验交付：运行 `skills-ref validate ./my-skill`（原文 L269-272），退出码 0 且无命名/字段报错才算通过（原文 L275）；不通过则按报错定向修复一次并复验，仍不通过如实报告失败项，禁止带病交付。

## front-matter 字段速查表

| 字段 | 必填 | 约束（均可回溯源文本） |
|---|---|---|
| `name` | 是 | 1–64 字符；仅小写字母/数字/连字符；不得首尾或连续连字符；与目录同名（原文 L66-70） |
| `description` | 是 | 1–1024 字符非空；写做什么＋何时用＋关键词（原文 L106-108） |
| `license` | 否 | 许可证名或包内许可文件引用，宜短（原文 L128-129） |
| `compatibility` | 否 | 1–500 字符；仅确有环境要求时写，可写目标产品/系统包/联网需求（原文 L143-145） |
| `metadata` | 否 | string→string 键值映射，键名要有辨识度以免冲突（原文 L171-173） |
| `allowed-tools` | 否 | 空格分隔的预授权工具串；实验性，各端支持不一（原文 L189-190） |

`scripts/` 内脚本应自包含或写明依赖、报错信息友好、妥善处理边界情况，语言可选 Python/Bash/JavaScript 等（原文 L220-224）；`references/` 常用形态是 `REFERENCE.md` 等聚焦文档——agent 按需加载，文件越小上下文消耗越少（原文 L230-234）；`assets/` 放模板、图示、查找表等静态资源（原文 L240-242）。

## 常见坑

- name 带大写或首尾/连续连字符 → 校验直接失败；只能小写字母/数字/连字符，且必须与目录同名（原文 L68-70、L90、L94、L98）。
- description 空泛（如 "Helps with PDFs."）→ agent 判断不出何时该触发；必须写「做什么＋何时用＋具体关键词」（原文 L107-108、L120）。
- 滥用 compatibility：多数技能并不需要该字段，别为了齐全而加（原文 L164）。
- metadata 键名太通用（如裸 `version`）容易与其他扩展冲突，键名要有辨识度（原文 L173）。
- 正文超长不分层：agent 激活技能会整文件加载，主文件应 ≤500 行，细节下沉引用文件（原文 L210、L252）。
- 引用链超过一层深 → 按需加载时上下文浪费且易迷路；文件引用从技能根起一层为限（原文 L265）。

## 来源引用

- 源文件：oracle/inputs/source.md（agentskills.io《Specification》页 WebFetch 抓取稿，全文 282 行）
- 来源 URL：https://agentskills.io/specification
- 源标题：Specification
- 结构统计：H1 1 / H2 6 / 列表要点 33 / 代码块 19，完整数据见 `../out/outline.json`。
- 蒸馏声明：由 paper-to-skill 包 `scripts/distill.py` v1.0.0 生成骨架后按方法论人工补全；重跑命令：`python package/scripts/distill.py --source oracle/inputs/source.md --outdir package/out --url https://agentskills.io/specification`
- [补充] 声明：本文件 front-matter 的 version/license/permissions/metadata 扩展键、「权威规则」第 1/2/4 条与「定向修复一次」条款，来自 skillfactory 企业标准（SKILL-SPEC-v0.1）与蒸馏过程实测要求，非来源内容。

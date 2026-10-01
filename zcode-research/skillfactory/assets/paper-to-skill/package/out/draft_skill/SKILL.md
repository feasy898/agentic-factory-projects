---
name: "specification"
description: "从源文档《Specification》确定性蒸馏的技能骨架：涵盖 1 个一级主题、6 个二级主题、33 条列表要点与 19 个代码块。适用场景：需要把该来源文档转化为可执行的 SKILL.md 草稿时使用。"
metadata:
  generator: oracle.py
  source: "oracle/inputs/source.md"
  source_url: "https://agentskills.io/specification"
---

# Specification（蒸馏骨架）

> 本文件由 paper-to-skill 包 scripts/distill.py 从源文档确定性蒸馏生成：一切内容均为源文本的结构化摘取（标题/列表/段落），未做语义摘要或改写。
> 重新生成：python package/scripts/distill.py --source oracle/inputs/source.md --outdir package/out --url https://agentskills.io/specification
> 发布前核对：front-matter 的 name 必须与技能目录名一致，并按方法论补全为成品。

## 能力范围

- 源结构：282 行 / 1 个一级标题 / 6 个二级标题 / 33 条列表要点 / 19 个代码块。
  - Directory structure（原文 L10）
  - `SKILL.md` format（原文 L23）
  - Optional directories（原文 L212）
  - Progressive disclosure（原文 L244）
  - File references（原文 L254）
  - Validation（原文 L267）
- 完整结构统计与标题树见 `../outline.json`。

## 分步方法

1. **Directory structure**（原文 L10）
2. **`SKILL.md` format**（原文 L23）
   - Must be 1-64 characters
   - May only contain unicode lowercase alphanumeric characters (`a-z`, `0-9`) and hyphens (`-…
3. **Optional directories**（原文 L212）
   - Be self-contained or clearly document dependencies
   - Include helpful error messages
4. **Progressive disclosure**（原文 L244）
   - **Metadata** (\~100 tokens): The `name` and `description` fields are loaded at startup fo…
   - **Instructions** (\< 5000 tokens recommended): The full `SKILL.md` body is loaded when th…
5. **File references**（原文 L254）
6. **Validation**（原文 L267）

## 常见坑

- Must not start or end with a hyphen (`-`)（原文 L68）
- Must not contain consecutive hyphens (`--`)（原文 L69）
- **Invalid examples:**（原文 L87）
- Most skills do not need the `compatibility` field.（原文 L164）
- We recommend making your key names reasonably unique to avoid accidental conflicts（原文 L173）
- Keep file references one level deep from `SKILL.md`. Avoid deeply nested reference chains.（原文 L265）

## 来源引用

- 源文件：oracle/inputs/source.md
- 来源 URL：https://agentskills.io/specification
- 源标题：Specification
- 结构统计：H1 1 / H2 6 / 列表要点 33 / 代码块 19，完整数据见 `../outline.json`。
- 生成方式：paper-to-skill 包 scripts/distill.py v1.0.0（产物 generator 标记按 spec §5 冻结为 oracle.py；无网络/无随机/无时间戳，内容均为源文本结构化摘取）；完整重跑命令：python package/scripts/distill.py --source oracle/inputs/source.md --outdir package/out --url https://agentskills.io/specification

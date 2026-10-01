---
name: specification
description: "从源文档《Specification》确定性蒸馏的技能骨架：涵盖 1 个一级主题、6 个二级主题、33 条列表要点与 19 个代码块。适用场景：需要把该来源文档转化为可执行的 SKILL.md 草稿时使用。"
metadata:
  generator: oracle.py
  source: "D:\\workspace\\zcode研究\\skillfactory\\assets\\paper-to-skill\\oracle\\inputs\\source.md"
  source_url: "https://agentskills.io/specification"
---

# Specification（蒸馏骨架）

> 由 `oracle.py` 从源文档确定性蒸馏生成（无随机、无时间戳、无网络访问）。
> 重新生成：`python oracle.py --source D:\workspace\zcode研究\skillfactory\assets\paper-to-skill\oracle\inputs\source.md --outdir D:\workspace\zcode研究\skillfactory\assets\paper-to-skill\oracle\out`
> 注：正式发布时，front-matter 的 `name` 须与技能目录名一致（agentskills.io 规范）。

## 能力范围

- 源结构统计：282 行 / 1 个一级标题 / 6 个二级标题 / 33 条列表要点 / 19 个代码块
  - Directory structure（原文 L10）
  - `SKILL.md` format（原文 L23）
  - Optional directories（原文 L212）
  - Progressive disclosure（原文 L244）
  - File references（原文 L254）
  - Validation（原文 L267）
- 结构细节（标题树 / 代码块语言分布）见 `../outline.json`。

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

- 源文件：`D:\workspace\zcode研究\skillfactory\assets\paper-to-skill\oracle\inputs\source.md`
- 来源 URL：https://agentskills.io/specification
- 源标题：Specification
- 结构统计：H1=1，H2=6，列表要点=33，代码块=19（完整统计见 `../outline.json`）
- 生成方式：`oracle.py` v1.0.0 确定性蒸馏（仅标准库；无随机/时间戳/网络）；命令：`python oracle.py --source D:\workspace\zcode研究\skillfactory\assets\paper-to-skill\oracle\inputs\source.md --outdir D:\workspace\zcode研究\skillfactory\assets\paper-to-skill\oracle\out`

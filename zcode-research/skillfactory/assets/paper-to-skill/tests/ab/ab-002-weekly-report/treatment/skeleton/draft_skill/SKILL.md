---
name: "a-b-ab-002"
description: "从源文档《能力简报：生成周报骨架（A/B 任务材料 · ab-002）》确定性蒸馏的技能骨架：涵盖 1 个一级主题、3 个二级主题、6 条列表要点与 0 个代码块。适用场景：需要把该来源文档转化为可执行的 SKILL.md 草稿时使用。"
metadata:
  generator: oracle.py
  source: "eval/ab_briefs/weekly-report-brief.md"
---

# 能力简报：生成周报骨架（A/B 任务材料 · ab-002）（蒸馏骨架）

> 本文件由 paper-to-skill 包 scripts/distill.py 从源文档确定性蒸馏生成：一切内容均为源文本的结构化摘取（标题/列表/段落），未做语义摘要或改写。
> 重新生成：python package/scripts/distill.py --source eval/ab_briefs/weekly-report-brief.md --outdir tests/ab/ab-002-weekly-report/treatment/skeleton
> 发布前核对：front-matter 的 name 必须与技能目录名一致，并按方法论补全为成品。

## 能力范围

- 源结构：17 行 / 1 个一级标题 / 3 个二级标题 / 6 条列表要点 / 0 个代码块。
  - 目标能力（原文 L3）
  - 需求要点（原文 L7）
  - 边界（原文 L15）
- 完整结构统计与标题树见 `../outline.json`。

## 分步方法

1. **目标能力**（原文 L3）
2. **需求要点**（原文 L7）
   - **输入**：本周的零散工作记录（bullet 列表、工作日志、commit 信息等皆可）。
   - **固定三小节**：`本周完成` / `下周计划` / `风险与求助`。
3. **边界**（原文 L15）
   - 不做工作量的绩效评价；不虚构下周计划（计划须来自输入中的遗留项或明确表述）；汇总不改写事实性内容。

## 常见坑

- （源文档未命中警示关键词，常见坑需人工补充。）

## 来源引用

- 源文件：eval/ab_briefs/weekly-report-brief.md
- 源标题：能力简报：生成周报骨架（A/B 任务材料 · ab-002）
- 结构统计：H1 1 / H2 3 / 列表要点 6 / 代码块 0，完整数据见 `../outline.json`。
- 生成方式：paper-to-skill 包 scripts/distill.py v1.0.0（产物 generator 标记按 spec §5 冻结为 oracle.py；无网络/无随机/无时间戳，内容均为源文本结构化摘取）；完整重跑命令：python package/scripts/distill.py --source eval/ab_briefs/weekly-report-brief.md --outdir tests/ab/ab-002-weekly-report/treatment/skeleton

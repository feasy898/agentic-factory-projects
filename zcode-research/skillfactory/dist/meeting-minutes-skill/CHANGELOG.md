# CHANGELOG — meeting-minutes package（实现层）

## 1.0.0 — 2026-09-29（重生成第 3 轮，从零实现）

- 依据 `spec.md`（含 §9 DoD）与 `contract.md` v1.1 从零实现技能包：
  - `SKILL.md`：front-matter（name=meeting-minutes）+ 何时使用/输入格式/三段式规则/使用步骤/产物与验收/边界，含 MUST 条款、验收矩阵、gotchas、文档地图。
  - `scripts/minutes.py`：契约入口（contract §2.1），自包含，仅依赖 python-docx 与标准库；实现 R1–R7 全部行为规则。
  - `scripts/gen_docx.py`：本轮任务指令点名的入口，CLI 与产物和 minutes.py 完全一致（委托 `minutes.main`）。**命名说明**：contract §2 冻结入口为 `scripts/minutes.py`，任务指令写 `gen_docx.py`，两者并存、以 minutes.py 为权威。
  - `references/`：classification-rules.md（R1/R2 口径）、extraction-heuristics.md（R4/R5 两列启发式）、docx-and-summary.md（R3/R6/R7 产物结构与验收）。
- 按 spec §9 D.1 对 `eval/golden.json` `eval_inputs` 列出的**全部 4 个 case**（case1–4；任务指令文字写 3 份样例，但 golden.json 已含 case4 全零边界且 DoD 以 golden 为准）运行脚本，产物落 `out/case1..4/`；随后运行 `python eval/runner.py package/out oracle/out` 评测。
- 输入一律使用资产根 `inputs/<case>.txt`（contract §1.1 注记），未触碰 `oracle/`。

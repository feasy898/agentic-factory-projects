# MANIFEST — meeting-minutes-skill v1.0.0

会议纪要生成技能包：把会议口语转写稿确定性地整理为三段式纪要（`纪要.docx` + `summary.json`），条目逐字可溯源。

| 顶层条目 | 用途 |
|---|---|
| `SKILL.md` | 技能主文档（agent 读这个：方法、红线、使用步骤、验收矩阵） |
| `README.md` | 面向使用者的快速开始、目录结构与边界说明 |
| `CHANGELOG.md` | 版本历史 |
| `EVALUATION.md` | 盲评与确定性评测结果及复现命令 |
| `LICENSE` | MIT 许可证 |
| `requirements.txt` | Python 运行依赖声明（python-docx>=1.1.0） |
| `MANIFEST.md` | 本清单 |
| `scripts/` | 确定性引擎：`minutes.py`（契约入口）、`gen_docx.py`（等价别名入口） |
| `references/` | 三份细则：分类规则 / 抽取启发式 / docx 与 summary 规格 |
| `eval/` | 确定性评测：`runner.py`（5 项机器检查）+ `golden.json`（黄金集） |
| `reference/` | 官方样例：`inputs/` 转写稿 ×4 与 `out/` 参照产物 ×4 |

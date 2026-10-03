# MANIFEST — office-templates-skill v1.0.0

中文办公四类文书技能包：把周报 / 请示函 / 会议通知 / 工作总结的结构化数据 JSON，确定性地生成 GB/T 9704 风格 `文书.docx` 与字段台账 `fields.json`。

| 顶层条目 | 用途 |
|---|---|
| `SKILL.md` | 技能主文档（agent 读这个：字段语义、退出码、agent 五步工作流） |
| `README.md` | 面向使用者的快速开始、运行目录约定与边界说明 |
| `CHANGELOG.md` | 版本历史 |
| `EVALUATION.md` | 盲评与确定性评测结果及复现命令 |
| `LICENSE` | MIT 许可证 |
| `requirements.txt` | Python 运行依赖声明（python-docx>=1.1） |
| `MANIFEST.md` | 本清单 |
| `scripts/` | 确定性引擎：`gen_doc.py`（contract §2 唯一契约入口） |
| `references/` | 四类模板的版式与字段规范（周报/请示函/会议通知/工作总结.md） |
| `eval/` | 确定性评测：`runner.py`（六类机器检查）+ `golden.json`（黄金集 + A/B 任务） |
| `reference/` | 官方样例：`inputs/` 数据 JSON ×8 与 `out/` 参照产物单元 ×8 |

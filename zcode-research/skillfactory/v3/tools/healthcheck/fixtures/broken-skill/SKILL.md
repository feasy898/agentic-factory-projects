---
name: broken-skill
description: 故意造坏的技能包，用作 healthcheck 的阴性对照（front-matter 缺 version/license/permissions，脚本有语法错误，且无 eval/）。
---

# broken-skill

本包是 healthcheck 的阴性样本，**不要分发**。

预期红项：
- `front_matter_fields`：front-matter 缺 version / license / permissions
- `eval_present` / `eval_smoke`：无 eval/ 目录
- `scripts_syntax`：scripts/bad_syntax.py 含语法错误

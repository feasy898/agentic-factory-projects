# CHANGELOG — office-templates package（实现层）

## 1.0.0 — 2026-09-30（分发包首发）

- 自开发资产源（spec.md v1.0，2026-09-30 固化）打包为可分发技能包：
  - `SKILL.md`：取自 `package/SKILL.md`（正文逐字节复制），按分发包体例补 front-matter（name/version/license=MIT/description/permissions/metadata，对齐 meeting-minutes-skill 先例）；正文内 `package/` 前缀命令在分发包中对应包根相对路径，见 README「快速开始」。
  - `scripts/gen_doc.py`、`references/`（周报/请示函/会议通知/工作总结四份）、`requirements.txt`：取自 `package/`，逐字节复制（md5 校验一致）。
  - `eval/runner.py` + `eval/golden.json`：取自资产根 `eval/`（contract §5 冻结接口），逐字节复制。**注意**：runner 无参数缺省路径写死为 `<包根>/oracle/out`，分发包内不存在，必须显式传 `<被测产物根> <参照产物根>` 两参数运行，约定见 README。
  - `reference/`：样例参照——`oracle/inputs/`（8 份数据 JSON）→ `reference/inputs/`，`oracle/out/`（8 个参照产物单元）→ `reference/out/`，逐字节复制（md5 校验一致）。
  - 新写：`LICENSE`（MIT，Copyright (c) 2026 SkillFactory）、`README.md`、`EVALUATION.md` 与本文件。**说明**：v3 资产源内无 CHANGELOG 文件，本文件为分发时新写。
- 分发包自验证（2026-09-30 实跑，Python 3.12.10 / python-docx 1.2.0）：8 条 `scripts/gen_doc.py` 生成命令全部 exit=0；`python eval/runner.py out reference/out` → ok=true、68/68 checks 全 pass、字段填充一致率 100.0%（66/66）、exit 0；绿自检 exit 0、空目录红检 exit 1；D1 双跑 fields.json 除 outputs 外逐字节一致、docx zip 17 条目 CRC 全等。详见 EVALUATION.md「2.2」。
- 盲评体检（v0.2 双臂双重复 5 任务）：基线 7.7 → 治疗 8.9，Δ +1.20、任务级胜率 100%、反向 0，判定达标；聚合原始数据见开发方评测存档（未随包分发）。

# CHANGELOG — hot-templates

## 1.0（2026-09-30，初版冻结）

- 固化四平台爆款内容结构模板资产：`spec.md`（R1-R7 行为规格，依据 `oracle/gen.py` 实际行为，全部经本会话实跑验证）、`contract.md`（package 契约 + eval 接口冻结）、`eval/runner.py`（8 case × 5 检查，结构一致率阈值 90%）、`eval/golden.json`（eval_inputs 8 + ab_tasks 5）、`inputs/`（8 份样例实现者副本，与 `oracle/inputs/` 字节一致）。
- oracle 侧（gen.py / run_all.py / verify.py / inputs / out / README）为既有参照实现，本版未改动；verify.py 74 项全 PASS（exit 0）。
- eval 自校验：`oracle/out` vs `oracle/out` → exit 0（40/40，一致率 8×100%）；空目录 → exit 1（40/40 判红）。

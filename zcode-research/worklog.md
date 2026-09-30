# worklog — zcode-research（append-only：每日做了什么/决策/下一步）

- 2026-10-01 迁移完成：windev-01 D:/workspace/zcode研究 → anolis-gpu-01:/opt/gpumachine/projects/zcode-research（线1-2B 迁移批；sha256=f15be550 两端核对过；验证：文件数 **9111=9111**；锚点 skillfactory/v5/REGISTRY.md+research/+extracted/ 在位；密扫 4 命中全假阳性）。接续卡：continue-cards/zcode-research.md。下一步：核 REGISTRY.md 登记态→裁 skillfactory 活产线接续方式。

- 2026-10-01 夜班轮（worker-B 评估与准入）：v5 代三候选（hotwords / deploy-pack / speaker-mapping，worker-A 02:12–03:03 生成）离线评估完成。41 项冻结门 38 PASS / 3 FAIL（3 项均诊断：1 项墙钟戳字节漂移非冻结面、1 项 hotwords `--out` 回显行对比口径、1 项实质红=speaker-mapping 检查 4 基线平台路径形态）。结论：hotwords 与 deploy-pack 内部就绪（工具/基建件，确定性门全绿：hotwords 54 文件 100% 双基线、deploy-pack 12/12 含 7/7 fixtures 与 6 红拦截）；speaker-mapping 待迭代（9 txt 逐字节全等仅 discover transcript 路径形态不符，修复=契约 §6 基线升版，生成侧动作）。体检三件均 C（2/5，dist skill 包形态错配备注）。三件均不进 dist（可分发门未齐+发布待雇主）。跑分记录：skillfactory/v5/eval-round-20261001/（scorecard+results.tsv+45 份原始输出+keyfiles.sha256+healthcheck 报告）；REGISTRY.md 追加登记节已写。零模型调用。

# worklog — xuexing-agent（append-only：每日做了什么/决策/下一步）

- 2026-10-01 迁移完成：windev-01 D:/workspace/学情agent → anolis-gpu-01:/opt/gpumachine/projects/xuexing-agent（线1-2B 迁移批；sha256=c77a8856 两端核对过；验证：pytest 13 failed=与本机同名单（未收口数据，非迁移损失）；3.12.13 venv 已建）。活数据（1-6 年级题库/仲裁队列）原样带到。接续卡：continue-cards/xuexing-agent.md。下一步：PM-STATE.md 恢复上下文→收口 13 failed→提交活数据→建远端。
- 2026-10-01 线2数据保护（worker-B）：迁移卡 26 个 untracked 活数据全数入库——前批 19 文件（8c6978f=一至六年级题库6、0b5b6ca=一至六年级知识库6、a9ea648=一至七年级误解7）；本轮 bb3c83b=9/30 验证产物 7 文件（P12/P34 仲裁队列、盲解/复算台账3、dual_verify 清单2；JSON 全部解析通过、密钥扫描零命中）。甄别结论：9 个 untracked 全为活数据（验证运行产物/项目上下文/工作日志），无新增垃圾需进 .gitignore（.venv、__pycache__、data/items/_parts、regen/round* 等可再生类已在 .gitignore 覆盖，git status --ignored 复核过）。遗留待清理：跟踪文件 joint_gate_out.txt（文件名以 windev 临时目录环境变量字面量开头、变量未展开的历史垃圾产物，已 tracked 故 .gitignore 无效）建议后续 git rm，本轮按分工边界未动。
- 2026-10-01 线2数据保护（worker-B）补充：CONTEXT.md 与 worklog.md 已入库，提交 hash=9cbb110（其自身 hash 见 git log，防自指）。至此迁移卡 26 untracked + 2 文档全部保全。

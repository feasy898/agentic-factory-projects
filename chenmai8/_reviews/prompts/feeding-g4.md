# 任务（独立第二意见评审·只读）：澄迈大赛项目「澄勺助餐机器人」G2–G4 审查

背景：本项目由 AI 构建流水线按 spec+eval 逐模块开发。G0-G1 与首轮审查修复已收口（契约 v1.1 六关节、独立违规轨迹 oracle、数值安全余量、门独立复核 8/8）。刚完成 G2-G4：cs_arm MockArm（32 测试，1034 注入 0 违规执行、急停≤100ms）、cs_orchestra 行为树（30 回合 450 口、camera_role 每口 2 次切换共 900 次、单口中位 19.7s、0 违规）、scripts/e2e_mock_run.py 全链路（30 口闭环、软急停 0.02 仿真秒中断、禁入区间隙 0.0501m>0 闩锁 0、停点余量 0.02m>0）+ demo_sim/demo_mouth。G4 硬闸门（e2e_mock+check_naming）双 exit 0。你是独立评审，不信任我们的绿灯，专找盲区。

请阅读（相对当前目录）：
1. ../plan/开发指令.md（v3/v3.1：§5 各模块 spec/eval、§5.8/5.9 通过线、§10 DoD）
2. chengshao/cs_arm/（ArmInterface/MockArm/SafetyEnvelope/FeetechArm 骨架）+ tests/test_arm_mock.py + eval_mock 入口
3. chengshao/cs_orchestra/（行为树节点+转移表）+ tests/test_orchestra.py + eval 入口
4. scripts/e2e_mock_run.py、chengshao/reports/e2e_mock.json 与 orchestra/trace 报告、demo_sim.py/demo_mouth.py

评审问题（逐条回答）：
A. 安全闭环真实性：MockArm 拒绝语义与未来 FeetechArm 真机路径的落差（真机上关节力矩/背隙/舵机抖动会不会让"包络校验过的命令"实际走出包络？）；急停≤100ms 是仿真时钟还是墙钟？
B. e2e 的 30 口数据：转移表的"全符合"是不是同源自证（预期转移表谁写的、注入与断言是否同源）；camera_role 900 次切换的"曝光稳定≥0.5s"在真相机上的假设（自动曝光重配置、红外补光）。
C. 行为树工程债：单口中位 19.7s 仿真 vs 真机舵机速度的换算；语音/表情分支在 e2e 里被真实走到还是桩化；转头中断后"原路退回+回家"的走廊与送入走廊是否同一套校验。
D. 契约一致性：cs_arm ArmCommand 与 cs_schema v1.1 的字段对齐；cs_orchestra 黑板 camera_role 与 mouth 侧 cam_pose 的单位/坐标系约定。
E. Windows/真机预备：串口舵机 SDK 在原生 Windows 的已知风险是否记录；demo_mouth.py 无相机时视频源的确定性。
F. 公开仓库卫生：上游名残留。
G. 工程债 Top5（按风险排序，注明是否阻塞 T10 真机 bring-up）。

输出格式：问题清单，每项 = [high/med/low] 文件:行 — 问题一句话 — 修复建议一句话。最后给总体结论（可继续 / 需修后继续）。只读，不要修改任何文件。

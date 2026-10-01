# worklog — video-capability（append-only：每日做了什么/决策/下一步）

- 2026-10-01 迁移完成：windev-01 D:/workspace/video-capability-research → anolis-gpu-01:/opt/gpumachine/projects/video-capability（线1-2B 迁移批；sha256=12807145 两端核对过；验证：tar 成员 5644=磁盘 5644，锚点 FINAL_REPORT_V2.md/judge基准报告.md/overnight/数据 在位）。secrets/api_keys.env 未迁（GPU 端重跑前需重建凭据）。接续卡：continue-cards/video-capability.md。下一步：CONFIRMATION.md（A13+B4）呈 owner 人工确认。

- 2026-10-01 worker-B（ztough926/video-understanding 纯代码视频理解借鉴，轮1）：架构研究完成（GitHub API 全树取证+四件套 sha256 存档 research/ztough926_src/，GPL-3.0）；接入方案落 research/ztough926_接入方案.md（B1 帧差时间线确定性 QC 信号/B2 变化感知选帧/B3 模型可读分张纪律/B4 Skill 化，关键思想落地不整仓照搬）。最小原型 research/proto/sheetframe.py（cleanroom 独立实现 ~260 行）：P1 定格检出 EXIT=0——golden_017/028 检出冻结 1.562-3.500s vs 注入 1.531-3.531s（端点误差 0.031s），干净对照 golden_001/006 零误报（judge报告 §0.5 实锤 J1 漏检洞被确定性修掉）；P2 总览图可读性 Higress 2 次调用 EXIT=0（glm-plan→glm-5.3-flash，golden_002 乱码逐字读出+定位 3.38s，golden_001 零误报；配额 2/5，key 经 OpenBao gpu/models/higress-consumer 内存态零打印，windev 侧代理执行因 GPU→srv-1 无密钥）。设计发现：变化感知选帧会抹掉定格信号→时序缺陷走帧差时间线（P1）、内容缺陷走总览图+VLM（P2）分工。已知瑕疵如实记录：模型误读格序号 #004→#055（时间戳正确，正式版格标签需加大）；阈值口径仅在 2+2 clips 初验，全 40 金标重校准前不得当生产阈值。模型配额合计：worker-B 2 次。


# worklog append — worker-A v3 首批（2026-10-01 夜班轮）

- 2026-10-01 worker-A v3 首批（依据 工程方案v3.1 §7.2 P0 清单；模型调用 0、积分 0）：
  ① P0-2 L0 确定性预检挂进 qc_orch_v2 在线模式（黑屏/时长双检查；--profile avatar_talk 垫尾豁免窗=[expect×0.98, ceil(expect)+1.0s]；拒收 exit 4 + <clip>.l0.json 证据）；注入超差样本验收：拒 3/3、放 2/2（tests/run_v3_checks.py A 组）。
  ② P0-1 机理回填：qc_detectors_v2 增低运动平台豁免（diff 支 in_med<2.0 标注；--profile 声明制豁免，实测依据：9/15 avatar 误报 in_med=0.71-1.64 与真混叠 golden_034/028 交叠，绝对阈不可分）+ known_cuts 切点白名单（tol 0.5s）；QCReport 契约 1.1（enum[1.0,1.1] + qc_context{profile,known_cuts,l0_preflight}，向后兼容）。dh 三片 ghosting+swap 误报归零；avatar 15 片误报 9→1（残留 vidu_b_timeline lap 支 1 例，如实披露）。
  ③ 基准对比（同口径）：E10 复算改动前后与 judge基准报告基线零偏差（R 1.000/FPR 0.250/F1 0.9143/B_flag 0.8333，误报仍 010/025/032）；J6v2 时序 7/8、C-FPR 0/12、合成 4/4 判定级逐条一致（59 条回归）；eval 双模块 ACCEPT exit 0。
  ④ thresholds.yaml v2（E10 判定阈未动）；SPEC.md 变更记录 1.1 行；新自检脚本 tests/run_v3_checks.py（exit 0 ALL PASS）。
  未做如实报：P0-3 MediaPipe（新依赖+独立调参，留下一轮）、P0-4 kimi 终裁（两路径均超 worker 权限：API 需未随迁密钥/降级属策略裁定）；CONFIRMATION.md 仍待 owner。
  证据：deliverables_v3/V3_BATCH1_WORKER_A.md；eval_results_v3base*/v3post*.json；out/v3_selftest/。

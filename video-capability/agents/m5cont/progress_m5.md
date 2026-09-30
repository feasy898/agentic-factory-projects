
## M5 完成 (2026-09-08, 校准 + 竖横 A/B + Wan 量产 + 9 条成片)

**阶段 0-2 (M5-PROD, 沙箱 /root/cradle_m5, D-038..D-045)**: G5 双锚分锚 (离线重评 59 候选, 美食回退违例 0,
G5 通过率 42.4%→96.6%); 阈值试点验证制 (G3 0.78 / G4 0.95 上调均被试点否决, 维持冷启动值); stable-borderline
短路 + SDXL 本地加载修复; 竖横 A/B 10/10 accepted → **维持竖版 480×832**; Wan 量产 17/17 任务首轮 accepted
(50 候选 48 pass + 2 fail, 0 fallback/blocked), API 消耗 0。详见 `reports/milestones/m5_calibration.md`。

**前手死亡与接棒 (如实记录)**: M5-PROD 在 PROD_DONE (13:25) 之后、启动成片合成之前死亡 (9 条 compose 无日志/
无事件/从未启动; "TTS 20 次合成中途崩"系冒烟产物被清理造成的假象, 见 D-046)。M5-CONT 接棒:
现场固化 commit `322bb42` → 修 pytest (12→17 卡数断言 + venv 流氓 tests 包遮蔽, **226 passed**) →
9 条成片合成一次通过 9/9 (19:38-19:44, 1088×1920 竖版 h264+aac, 时长与模板 ±0s, G6 逐字 9/9;
CER whisper-small 1/9 / whisper-medium 复核 8/9 ≤5%, 差因=ASR 同音字, D-047) → 成片拷回 `~/cradle/output/` →
最终良率报告 `reports/milestones/m5_yield_report.md` (良率 100%, Wan 60/200 口径纠正 D-048, trace_query 5/5 验证,
失败样本 36/36 保全) → 本节 + DECISIONS D-046..D-048 + 收尾 commit。

**关键数字**: 9 成片 = t1_seeding×3 (25s) / t2_ambiance×3 (22s) / t3_offer×3 (17s); 生产良率 17/17 (100%),
一次通过; 显存峰值 23.76GB/32GB; 墙钟 A/B 69min + 量产 305min + 合成 6.5min。

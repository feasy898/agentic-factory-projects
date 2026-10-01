
## 6. 生产统计 (阶段2, 接棒 M5-CONT 补全)

- 量产 (阶段2): 08:20:27-13:25:38 (DB 事件), **17 任务全部 accepted 且 attempts=0 (首轮)**, 0 fallback / 0 blocked。
  候选 50 个 (48 pass + 2 fail), 2.94 候选/任务; 显存峰值 23.10-23.66 GB/任务 (全场 max 23.76 GB = ABS03L 横版, /32GB)。
- 2 个 fail 候选均 G5 启发式边缘未过 (0.6932 / 0.6913, 距 0.70 阈值 ≤0.009, verdict="整体可过但有瑕疵"),
  同任务第 2/3 候选即恢复 pass, 任务级零损失; 样本保全于沙箱 (M6 画廊素材)。
- API 消耗 0: TTS 20 次全 local (edge-tts, 其中 08:23-08:24 的 20 次属 t1_smoke 冒烟合成 ×2 成功, 产物与台账行
  随后被清理 —— 造成"合成中途崩"假象, 实为前手死于启动 9 条成片合成之前, 见 m5_yield_report.md §2);
  VLM 60 次全 local。
- **Wan 候选总量 = 60** (A/B 10 + 生产 50) ≤ 200 守卫。注意: `m5_prod_report.json` 的 candidates_by_verdict
  (58 pass/2 fail=60) 为全库口径 (含 AB), 主控简报 "70" 系双计 (D-048)。
- 短路 (D-042): 生产 0 触发 / 0 误触发 (retry_rounds_saved=0); 经济性实际来自首轮高通过
  (2.94 vs M2 5.17 候选/镜头, -43%)。
- 墙钟: A/B 69.3 min (含一次 SDXL 离线加载失败 + recover() 重置, D-045 修复); 量产 305.2 min (17.95 min/任务,
  单候选 ≈366s 与 D-030 364.9s 一致)。
- **9 条成片合成 (接棒完成, 19:38-19:44, 6.5 min)**: 9/9 落片 (t1×3/t2×3/t3×3, 1088×1920 竖版 h264+aac,
  时长与模板 ±0s), G6 逐字硬门禁 9/9; CER 回转 whisper-small 1/9 ≤5%, whisper-medium 复核 8/9 ≤5%
  (差因=ASR 同音字混淆, 非音频缺陷) —— 详见 `reports/milestones/m5_yield_report.md` §10/§11 与 D-047。

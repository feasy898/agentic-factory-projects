
## M3 完成 (2026-09-08, 合成层完整成片)
- [compose] src/compose.py 升级(全部真跑验证): ① build_compose_argv 支持 video_durations →
  短素材 tpad=stop_mode=clone hold-last-frame 补齐幕长(D-033); ② fit_tts_to_scene 自适应语速,
  保证口播不超幕时长不被 atrim 截断(D-032: hook +70%/CTA +84%, 其余 -10%); ③ probe_media_duration
  音频兼容探测(g1_tech.probe_duration 只认视频流的坑), api/tts.py 回退接线; ④ compose_g6 合成级
  G6: 烧录 ASS 回读(parse_ass_dialogues)与模板渲染文本逐字比对(硬) + whisper TTS→ASR 回转 CER
  (normalize_for_cer 归一化 D-034, 领域热词 D-036); ⑤ build_bgm_argv 程序合成 BGM(D-035),
  终混 sidechain ducking ≈-12dB(D-006)首次真跑; orchestrator 默认 composer 接 rate 感知 tts_fn
  并在 G6 未过时落 warn 事件
- [video] **output/m3_seeding_debug.mp4**: 25.0s(模板 25.0s ±0) 1088×1920@16fps h264+aac 3.4MB;
  幕-镜头cast: hook=S02 evidence=S01/S03/S04 ambiance=S07 CTA=程序纯色贴片; 首帧/CTA 帧目检
  字幕(Noto Sans CJK)烧录正确; reports/milestones/m3_compose_report.{md,json} +
  m3_seeding_debug.ass + m3_first_frame.png(磁盘证据, 媒体不入 git)
- [g6] 合成级两级: ① ASS 逐字比对 PASS(6 幕全等); ② whisper-small GPU CER=0.0323 ≤0.05 PASS
  (无热词基线 0.0645 全为同音字混淆, 如实披露, 见 D-036); 数字隔离(D-015)复查:
  numbers 只出现于字幕, 不在任何视频路径
- [test] pytest 209 passed(新增 tests/test_compose_m3.py 17 测: tpad/ASS回读/中文数字归一化/
  自适应语速含触顶/BGM argv/compose_group 端到端 G6 过/挂/跳过); 修复测试中暴露问题:
  语速预测整数化收敛过慢(改 ceil+1)、tts 无 rate 形参时死循环、纯音频探测异常
- [report] 首跑 CER=6.45% 超标 → 逐字分析全部为同音字混淆(非截断) → 标准领域热词偏置后 3.23%,
  两数字均入报告(D-036); hook/CTA 3s 幕 vs 21 字文案的模板张力记 D-032 校准建议
- 决策追加 D-032..D-036; commit "M3: compose layer full video"

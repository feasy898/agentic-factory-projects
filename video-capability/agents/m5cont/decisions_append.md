
- **D-046** (2026-09-08, M5-CONT): M5 收尾接棒。① 前手死亡点修正: "合成中途崩"不成立 —— 20 次 TTS (08:22-08:24)
  属 `specs_smoke/t1_smoke.json` 冒烟合成 ×2 且两次成功 ("成片完成" 事件在案), 产物与 m5_videos 行随后被清理造成假象;
  9 条成片 compose 无日志/无事件/无新 TTS, 即**从未启动**, 前手死于 PROD_DONE 之后、启动合成之前。
  ② 9 条成片接棒合成: 预检 (60/60 候选文件在盘、9 spec 槽位 selected 齐全) → `scripts/m5_compose_videos.sh`
  19:38-19:44 一次通过 9/9 (6.5 min, 31-37s/条), 拷回主仓库 `~/cradle/output/`。③ pytest 修复两处:
  `test_templates` 卡数断言 12→17 (S13-S17 扩容后未同步); 本机 venv site-packages 存在**流氓 `tests` 正则包**
  遮蔽本地 tests 命名空间包导致 9 个收集错误 —— 加 `tests/__init__.py` 使本地成为正则包 (cwd 优先) 后
  226 passed。④ 现场固化 commit `322bb42` 先于一切改动。
- **D-047** (2026-09-08, M5-CONT): G6 CER 回转 ASR 口径复核。生产口径 whisper-small (temperature=0+D-036 热词)
  CER≤5% 仅 1/9; **whisper-medium 同口径复核 8/9 ≤5%** (0.0108-0.0465), t3_offer_v2 临界 0.0563;
  small/medium 差集全部为同音字混淆 (锁/所、灶/造、咕嘟/孤独、雾气/物器、份/分、即止/几指、眉毛/美貌、
  七上八下/吸上巴下) —— 交付字幕 (ASS 逐字 9/9) 与 TTS 朗读无缺陷, 属 ASR 局限, 延续 D-036 结论。
  t3_offer_v1 medium@temp0 出现 BGM 段幻觉复读 (CER 1.71), temperature fallback + condition_on_previous_text=False
  消除后真实 CER=0.1231 (残差: "全是汁"难句)。逐条数据 `cradle_m5/workdir/logs/m5_g6_cer_medium_recheck.json`。
  决策: **不改生产 ASR 口径** (逐字硬门禁为准, CER 按 D-011 软性披露, 报告双数字), medium.pt (1.42GB) 留
  ~/.cache/whisper 供 M6 复核; 若 owner 要求收紧, 改 `_default_asr_fn` 档位并接受 ~3× ASR 耗时。
- **D-048** (2026-09-08, M5-CONT): Wan 候选总量口径纠正: **实为 60** (A/B 10 + 生产 50) ≤ 200, 主控简报 "70"
  系双计 —— `cli report` 的 candidates_by_verdict 是**全库口径** (58 pass+2 fail 已含 AB 的 10 pass), 生产实际
  候选 50 (48 pass + 2 fail)。后续引用 report JSON 字段须注明全库口径; 若需分阶段口径应按 shot_id 前缀 (AB*)
  或时间戳过滤。

# M3 合成层成片报告 (m3_compose_report)

- 生成时间: 2026-09-08 05:19:45 (墙钟 34.2s)
- 模板: product_seeding_25s / 总时长 25.0s / 竖版 1088x1920@16fps
- 成片: `/root/cradle/output/m3_seeding_debug.mp4`

## 素材清单(M2 selected 候选, 调试口径)

| 幕 | 镜头 | lane | 来源 | 分辨率 | 素材时长 | overall_score |
|---|---|---|---|---|---|---|
| hook | S02 | first_frame_i2v | pass | 384x512 | 1.5625s | 0.9554 |
| evidence_1 | S01 | first_frame_i2v | pass | 384x512 | 1.5625s | 0.9335 |
| evidence_2 | S03 | first_frame_i2v | pass | 384x512 | 1.5625s | 0.9518 |
| evidence_3 | S04 | first_frame_i2v | pass | 384x512 | 1.5625s | 0.9554 |
| ambiance | S07 | first_frame_i2v | pass | 384x512 | 1.5625s | 0.9396 |

## 时长轴(幕 / 口播自适应语速 D-032 / tpad 补齐 D-033)

| 幕 | 幕长 | TTS 语速 | TTS 实测 | 截断 | 素材时长→tpad |
|---|---|---|---|---|---|
| hook | 3s | +70% | 2.88s | False | 1.5625s→hold-last 1.438s |
| evidence_1 | 5s | -10% | 4.44s | False | 1.5625s→hold-last 3.438s |
| evidence_2 | 5s | -10% | 3.984s | False | 1.5625s→hold-last 3.438s |
| evidence_3 | 5s | -10% | 3.72s | False | 1.5625s→hold-last 3.438s |
| ambiance | 4s | -10% | 3.888s | False | 1.5625s→hold-last 2.438s |
| cta | 3s | +84% | 2.88s | False |  |

## G6 合成级硬校验 (D-011)

- 字幕逐字比对(硬性): **PASS** (ASS=/root/cradle/reports/milestones/m3_seeding_debug.ass, 6 幕 Dialogue 与模板渲染文本全等)
- TTS→ASR 回转(可选): whisper-small GPU, CER=**0.0323** (≤0.05, 归一化 D-034)
- ASR 配置: language=zh, temperature=0, 领域热词 initial_prompt(D-036, 全文见 JSON): `火锅店美食口播，词汇：老灶火锅、毛肚、锁鲜、到港、虾滑、肥牛、半价。`; 无热词基线 CER=0.0645(6 处同音字: 灶/造 锁鲜/所先 港/岗 份/分 价/假), 热词后余 2-3 处同音残差(锁鲜→所先, 脆→翠)
- ASR 原文: `老灶火锅的手切鲜毛肚,三秒所先,一口上头。七上八下十五秒,翠到耳朵,都能听见。每天凌晨到港的鲜货,只卖当天。红汤翻滚,涮一下就是江湖味。暖光蒸汽一升起来,冬天就不冷了。今晚只要39.91位,第二份半价,定位要趁早。`
- 归一化后假设: `老灶火锅的手切鲜毛肚三秒所先一口上头七上八下十五秒翠到耳朵都能听见每天凌晨到港的鲜货只卖当天红汤翻滚涮一下就是江湖味暖光蒸汽一升起来冬天就不冷了今晚只要三十九点九一位第二份半价定位要趁早`
- G6 总判定: **PASS** (score=1.0)

## ffprobe 摘要

- duration=25.0s (模板 25.0s ±1s → OK), 1088x1920 (OK), h264/aac, 音轨存在=True

## 数字隔离复查 (D-015)

- numbers={'price': '39.9', 'offer': '第二份半价'}; 泄漏进视频路径=False(应为 False); 出现于字幕=True(应为 True)

## 调试口径说明

- 画面为 384×512 LTX 调试素材上采样(清晰度低/hold-last-frame 停帧属预期, M5 量产由 Wan 480p 素材替换);
- hook/CTA 幕 3s 内念完口播需较快语速(模板文案 21 字 vs 3s 幕, 校准建议已记 M3 报告/DECISIONS);
- BGM 为程序合成正弦和弦(无版权风险), 经 -12dB 预衰减+sidechaincompress ducking(D-006)。

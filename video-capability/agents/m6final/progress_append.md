

## M6 完成 (2026-09-08, 失败画廊 + FINAL_REPORT + README + git 收尾)

- [gallery] `reports/gallery_failures/`: **24 例** (类型A=校准前 G5 启发式场景偏差×22, 自 34 个 M2 LTX 被拒候选精选; 类型B=生产期 G5 边缘×2 全收), 每例 `video.mp4`(实体) + `gate_json.json`(六门禁原始 JSON) + `grid.jpg`(2×5 抽帧网格) + `case.md`(镜头卡+六门禁分数+main_issue+失败归类+D-041 校准后重评分+入选理由); `INDEX.md` 按失败类型组织, 附"给阈值校准者的要点"与"本管线未出现 G1/G3/G4/G6 类失败"如实附注; 媒体 14.4MB < 50MB 门槛 → mp4/jpg 全量随 git 入库 (D-049); 构建脚本 `tools/m6_build_{gallery,index}.py` 幂等, 数字实时取自 SQLite/m5_reeval_g5.json
- [report] `reports/FINAL_REPORT.md`: §1 一页总览 (良率 100% / 成本 GPU 期≈7.3h+下载≈1.3h / 项目墙钟≈20h / 结论; 标注"全程未经 API VLM 审核 (D-004)"与"主控抽帧目检 3 片通过") / §2 样片索引 9+1 (含 CER 双口径逐条) / §3 良率统计+失败聚类 (类型A/B) / §4 阈值表 (全部维持冷启动, G3/G4 上调被试点否决的依据 + A/B 维持竖版结论) / §5 局限与建议 L1-L11 (CLIP 启发式局限与 VLM 接入路径 / D-019 替代模型 / CER 同音字与 pinyin 建议 / 降级路径未被量产触发 / 单风格资产 / 1080p 软件插值等) / §6 API 用量表 (API 0 次; 本地 VLM 151 + TTS 141 + whisper 记账注记) / §7 交付物对照 / 附录A 自检九项逐项证据 / 附录B D-001..D-050 索引 / 附录C 里程碑索引
- [readme] `README.md` 四指南: ① 新机器复现 (硬件前提 / scripts 01-08 环境序 / 下载源策略 D-021 / 沙箱配方 D-037 三要素 / 一键 `m4_e2e_demo.sh` + CLI 速查); ② 换底模 (models 布局 / gen wrapper generate() 契约 / D-019+D-022 "先冒烟再量产"教训); ③ 换 API (config/api.env 格式 / src/api 适配器位置 / 预算守卫 / 失败重试 1 次切兜底); ④ 换真实实拍资产 (assets 布局 + manifest 格式 + first_frame_asset 指向 + 镜头风险表: **含人脸/手的实拍图必须走 ken_burns 车道**); 附项目结构图与 SQLite 追溯查询速查
- [test] pytest **226 passed** 复核 (M6 无管线代码改动, 仅新增 tools/ 构建脚本)
- [git] commit "M6: failure gallery + FINAL_REPORT + README" + tag **v1.0**; 决策追加 D-049/D-050

## 全项目时间线 (2026-09-08 单日, 服务器时间)

| 时刻 | 事件 |
|---|---|
| 00:52 | M0 开工 (SPECS 落盘/git init) |
| 03:2x | M1 环境就绪 (权重 46G 落盘, LTX/Wan 冒烟 PASS) |
| 04:03-04:21 | M2 十镜头闭环 (9 accepted/3 fallback, 34 被拒候选保全) + Wan 装配验证 |
| 05:19 | M3 合成层完整成片 (m3_seeding_debug.mp4, CER 0.0323) |
| 05:34 / 05:53 | M4 e2e 一键出片 340s / kill -9 崩溃恢复演示 PASS |
| 06:03-08:13 | M5 校准 (G5 双锚 D-041) + 竖横 A/B 10/10 (维持竖版) |
| 08:20-13:25 | M5 Wan 量产 17/17 首轮 accepted (50 候选 48 pass/2 fail) |
| 19:38-19:44 | M5-CONT 接棒: 9 条成片合成 9/9 (G6 逐字 9/9) |
| 20:0x-收尾 | M6: 画廊 24 例 + FINAL_REPORT + README + 自检九项 + tag **v1.0** |


## V2-M5 完成 (2026-09-09, V2-M5: 终报 + 夹具终版索引 + gallery_v2 + README + git 收尾)

- [report] `reports/FINAL_REPORT_V2.md`(SPECS_V2 §7-1 全项): 头条数字置顶(**拦截 15/15=100% / pass_structural 误杀 0/15=0% / pass_candidate 误杀 4/17=23.5% 带内** + 不对称原则一句话 + 唯一人工动作指引); G7 分布图索引与冷启动→校准阈值表(每键带依据); 三车道设计逻辑与良率(19/19 任务 25/25 候选, 确定性车道 11/19 零 Wan, M3/M4 分数逐位一致); **v1/v2 全量对比**(食物镜头形变率 12.3% 全池 / 25% Wan 生产口径 → **0**; 良率/耗时/预算对比表并注明墙钟口径不可直接比); 合成源验证(flow_cos 0.92-0.96 正控带内); API 0 次(全项目 413 次调用全 route=local: v1 两库 230 + v2 期 183); DECISIONS 增量索引 D-051..D-074; 诚实披露 7 条(G7e 全 skipped / G7 集成链假绿修复 / overlay 3/6 过审 / 首轮 100% 良率致产线无被杀样本 → gallery_v2 素材来源说明 / evidence 演示源非实拍 / CER 同音字 / 两次代理静默死亡)
- [fixtures] `reports/fixtures/INDEX.md` 终版(47 条: fixture/路径/类别/源候选/human_source/DINO 首尾/G7 终版判定; `tools/m5v2_build_fixtures_index.py` 幂等生成, 数字实时取自 fixtures_manifest.json + v2m1_g7_final.json 不手抄) + **`reports/fixtures/CONFIRMATION.md` pass_candidate 确认清单(本轮唯一人工动作)**: A 组 13 条系统判过请确认 + B 组 4 条系统判杀(FX-C001/C002/C003 毛肚 a/d 真实低余弦 + FX-C010 夜景 churn, 标注"可能属误杀请重点复核"), 每条附首/中/尾三联拼图路径 + mp4 路径 + G7 分数
- [gallery] `reports/gallery_failures_v2/`(`tools/m5v2_build_gallery_v2.py`): **本轮漏网=0 如实声明**, 目录定位=不对称原则的代价侧档案; 8 例 = overlay 审计 FAIL 4(判定 5 次/物理失败文件 3 个: steam_dense / fog_low / bokeh_dust 两轮 / mist_cool_v1 重生成功对照; 每例 case.md + gate_json.json + 首中尾抽帧 grid.jpg + 物理解释: 雾光渗透真实抬亮底片属物理污染, 暗粒子低于亮度阈值属可分性局限) + G7 校准期判杀 4(FX-C001/C002/C003/C010, case.md + gate_json.json); 案例媒体引用库内相对路径不复制(overlay/夹具 mp4 已入 git)
- [readme] README 增补"指南五: v2 三车道与 G7 门禁": **证据车道激活四步**(assets/evidence/ 放实拍竖版 3-5s → 镜头卡 evidence_asset → ingest 自动激活 → evidence_denoise 0.30 口径说明) + 三车道速览表 + G7 阈值文件与豁免条款说明 + **夹具库回归方法**(g7-fixtures CLI 复跑命令 + 验收线 + 两条幂等构建脚本)
- [disk] whisper-medium.pt(1.53G, ~/.cache/whisper/)**保留**: avail 28G > 20G 红线, 供后续 CER 复核/同音字仲裁(D-073; 触发红线时先删, 可再生)
- [git] pytest **309 passed**(收尾复测, `workdir/logs/v2m5_pytest.log`); commit "V2-M5: FINAL_REPORT_V2 + fixtures index + gallery_v2 + README" + tag **v2.0**; §9 十项自检逐项核证全过(证据路径见 FINAL_REPORT_V2 §8)
- 决策追加 D-073/D-074

## V2 全项目时间线 (2026-09-08 21:10 开工 → 09-09 收尾; 预算 4 天, 硬停 09-12 21:00)

| 时刻(服务器本地) | 事件 |
|---|---|
| 09-08 21:10 | v2 开工(SPECS_V2 569108a 已入库, tag v1.0 完好, HEAD=569108a) |
| 09-08 21:xx-23:5x | V2-M0: 状态审计 + 磁盘治理 3.3G + **夹具库 47 条入库**(fail 15 四类/pass_struct 15/pass_cand 17) + G7 模型 6 件 Volta 自查; v1 复跑 51s 全绿(commits 4053905/7635856/544f975) |
| 09-08 深夜 | V2-M12: G7 五子项实现+冷启动初跑(fc53ed9, 256 tests) → 校准+终版重跑达标(164ad63/376ee48): **拦截 15/15 / struct 误杀 0/15 / cand 误杀 4/17 带内, 1/3 轮达标** |
| 09-09 01:24 | ⚠ **代理静默死亡 #1 (V2-M3)**: 三车道代码+19 卡+模板+测试全部写完后、运行时验证前双端零活动(与 v1 M5-PROD 同模式), 无提交; pytest 当时 306/3 挂 |
| 09-09 01:3x-08:0x | V2-M3C 接棒: **先固化 WIP commit `1d3c3cb` 再动任何东西** → 修 3 测试+预算守卫真 bug(守卫被三车道提前 return 绕过, D-067)→ 309 passed → overlay 库 6 条(审计口径 v2, 3/6 PASS) → 合成源验证 flow_cos 0.92-0.96 → 三车道实测全链 accepted; 期间修出 **G7 集成链假绿 bug**(orchestrator 自 V2-M1 起未注入模型 fn, 校准链不受影响, 已修+重跑, D-069 尾)(commit ecb2aa7) |
| 09-09 08:1x-10:5x | V2-M4: 量产计划先落盘 → 沙箱 19/19 任务 25/25 候选首轮全过(G7 生产 0 触发, Wan 14, 生成+门禁 31.5min) → 9/9 成片 30.0/28.5s 逐秒一致(ASS 逐字 9/9, CER medium 6/9 同音字) → v1/v2 形变率对比原料(commit f2773de); **主控 VLM 抽帧终检通过**(v2_t1_seeding_v2); 成片 10:57 落盘 |
| 09-09 07:5x | 双端巡检自动化建立(>90min 双端无变化即判僵死→固化现场→派接棒; 08:15 ✓ M3C / 10:15 ✓ M4 GPU 100% 巡检正常) |
| 09-09 11:1x-收尾 | V2-M5: FINAL_REPORT_V2 + 夹具终版索引与确认清单 + gallery_v2 + README 指南五 + pytest 复测 309 + commit + tag **v2.0** |

> **代理静默死亡台账(两次, 跨 v1/v2 各一次, 均接棒成功零工作丢失)**: v1 期 M5-PROD 死于成片合成启动前(M5-CONT 接棒补齐, D-046); v2 期 V2-M3 死于运行时验证前(V2-M3C 接棒)。两次接棒均以"先固化现场 commit、再动任何东西"开局; 第 2 次死亡后建立双端巡检自动化。

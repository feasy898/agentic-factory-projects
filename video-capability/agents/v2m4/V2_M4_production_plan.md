# V2-M4 量产计划（先落盘后执行）

> 代理: V2-M4。日期: 2026-09-09。基线: ~/cradle HEAD=ecb2aa7（pytest 309 全绿，保持）。
> 本计划先于一切执行动作落盘；执行产物见 `V2_M4_production_report.md`。

## 1. 目标

三车道（compositing_2d5 食物默认 / pure_gen_short 环境氛围 1-2s / evidence_transfer 演示）
产出 **9 条成片**（3 模板 × 3 变体），收集三车道良率、G7 触发明细、v1/v2 食物镜头形变率对比。
Wan 预算: 全局红线 200，v1+M3 已用 ≈78，本轮沙箱内硬守卫 **120**（D-072）。

## 2. 模板与 spec

| 模板 | id | 来源 | 幕结构 |
|---|---|---|---|
| T1 | product_seeding_30s_v2 | M3 已有（templates/narrative_v2/） | 10 幕 9 镜头（3 comp + 3 pure + 1 offer comp + 1 storefront pure + 1 evidence demo + CTA 字卡），合计 30s |
| T2 | store_ambiance_28s_v2 | M3 已有 | 10 幕 9 镜头（4 pure + 3 comp + 1 evidence demo + offer comp + CTA），合计 28.5s |
| T3 | offer_lead_28s_v2 | **本轮新增**（D-071） | 10 幕 8 镜头（优惠字卡开场 + 3 pure + 3 comp + 1 evidence demo + CTA），合计 28.5s |

- v2 模板投放: orchestrator `compose_from_spec` 硬编码读 `templates/narrative/`，
  将 narrative_v2 的 3 份以原 id 复制进该目录（权威源仍是 narrative_v2，D-070）。
- T3 新模板过 `validate_narrative_template` + tests/test_v2_templates.py 全部约束
  （25-30s / 幕数 8-14 / 视频幕 ≥8 / 有 ≤2s 节奏幕 / narration 无字面数字 / 槽位全有卡）。
- 9 份 spec（`reports/milestones/v2m4_specs/` 同步入 git；运行副本在沙箱 /root/cradle_v2m4/specs/）。

## 3. 选角表（同片内镜头不重复；跨片复用=不重复生成，D-045 惯例；变体差异化=选角+numbers）

| video_id | hook | 环境幕(pure_gen) | 食物/产品幕(comp) | offer(comp) | evidence_demo | price / offer |
|---|---|---|---|---|---|---|
| v2_t1_seeding_v1 | S02 | S09, S07, S08 | S03, S04, S17 | S13 | S18 | 42.8 / 锅底免费续 |
| v2_t1_seeding_v2 | S02 | S16, S10, S08 | S03, S04, S15 | S17 | S19 | 45.9 / 第二份半价 |
| v2_t1_seeding_v3 | S02 | S09, S11, S08 | S03, S04, S17 | S13 | S18 | 39.9 / 凉菜免费送 |
| v2_t2_ambiance_v1 | S02 | S08, S07, S09, S10 | S01, S15 | S14 | S19 | 39.9 / 酸梅汤免费续杯 |
| v2_t2_ambiance_v2 | S02 | S08, S11, S16, S07 | S01, S15 | S14 | S18 | 35.9 / 酸梅汤一元续杯 |
| v2_t2_ambiance_v3 | S02 | S08, S10, S09, S11 | S01, S15 | S14 | S19 | 36.9 / 夜宵档送小食 |
| v2_t3_offer_v1 | S02 | S09, S07, S08 | S01, S03 | S13 | S18 | 49.9 / 前100名送毛肚 |
| v2_t3_offer_v2 | S02 | S16, S10, S08 | S04, S15 | S17 | S19 | 52.9 / 第二份半价 |
| v2_t3_offer_v3 | S02 | S09, S11, S08 | S03, S01 | S13 | S18 | 45.9 / 锅底免费续 |

- 每片 ≥1 个 evidence_transfer 演示镜头（S18 虾滑 / S19 毛肚，合成测试源，**报告中标注"演示源"非实拍**）。
- 口播-画面紧耦合幕固定选角（evidence_1=毛肚→S01、evidence_2=扬勺→S15、offer 酸梅汤→S14）；
  松配仅限氛围 b-roll。S12（ken_burns 手部）本轮不入选（三模板无手部幕），仅 ingest 供门禁统计。
- 食物镜头形变预期: comp 车道纯代码渲染（形变物理性消灭）；evidence demo 为低强度重绘
  （denoise=0.30，M3 实测结构保持 flow_cos 0.92-0.96）。如实记录任何目检例外。

## 4. Wan 调用预算（沙箱硬守卫 120）

| 项 | 计算 | 预期 |
|---|---|---|
| pure_gen_short | 6 卡(S07-S11,S16) × n_best=2 | 12 |
| puregen 重试 | retry_max=1, ≤3 卡触发 × 2 | 0-6 |
| evidence_transfer | 2 卡(S18,S19) × n_best=1 | 2 |
| evidence 重试 | retry_max=1, ≤2 卡触发 × 1 | 0-2 |
| comp / ken_burns | 确定性，0 Wan | 0 |
| **合计** | | **预期 14-22，上限 120 硬守卫** |

## 5. 执行序列

1. 沙箱 `/root/cradle_v2m4`（`scripts/v2m4_sandbox.sh`）: m3_sandbox 配方（models/templates 只读软链
   + assets 拷贝 + CLIP 权重 + HF_HUB_OFFLINE=1）+ `wan_candidates_total: 120`。
2. 模板投放 + spec 上传 → `python -m src.cli initdb` → `ingest templates/shotcards_v2`（19 卡）。
3. `run --poll 15` 于 `setsid nohup`（D-038 教训: 不用 tmux），日志 workdir/logs/v2m4_prod_run.log。
4. 全终态后快照 DB（任务/候选/门禁/G7 子项明细）→ `compose-video --spec`（nohup，G6 两级留档）。
5. 逐片验收: ffprobe（1088×1920? 实为卡面 480×832 合成竖版，h264+aac，时长=模板合计±1s）
   + G6（ASS 逐字硬校验 + whisper CER small/medium 双口径）+ 每片抽 2 帧目检拼图（scp 本机 Read）。
6. 数据收集 + 报告 + 成片拷回主仓 output/（v2_ 前缀与 v1 片区分）+ commit + 清场。

## 6. 验收口径

- 模板时长 ±1s（T1=30s, T2=28.5s, T3=28.5s）；分辨率 1088×1920 或 480×832（以 ffprobe 实际为准，
  v1 成片口径为准不虚报）；h264+aac。
- G6: ASS 逐字硬校验必须 9/9 过；CER small 生产口径 + medium 复核双数字（D-047 惯例）。
- 目检: 每片抽首/中 2 帧，9 片 18 帧拼 2 张 grid；食物帧重点看形变（本车道形变来源已消灭，
  任何例外如实记录进对比表）。
- 被 G7 杀掉的候选全部保全（沙箱 workdir/candidates 不清理），列入 gallery_v2 素材清单。

## 7. 本轮新决策

- **D-070**: v2 叙事模板投放机制 — compose_from_spec 读 templates/narrative/（硬编码），
  narrative_v2 三份原 id 复制进 narrative/，两目录 git 同步，权威源 narrative_v2。
- **D-071**: 新增第三叙事模板 offer_lead_28s_v2（narrative_v2 原有 2 份，量产要求 3 模板 × 3 条）。
- **D-072**: 本轮 Wan 预算沙箱硬守卫 120（全局 200 − v1/M3 已用 ≈78；守卫按沙箱库计数，D-038 口径）。

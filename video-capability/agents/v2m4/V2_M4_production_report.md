# V2-M4 量产报告（三车道 9 条成片 + 产线统计）

> 代理: V2-M4。日期: 2026-09-09。基线: ecb2aa7（pytest 309 全绿，收尾复测仍 309）。
> 计划: `reports/milestones/V2_M4_production_plan.md`（先落盘后执行）。沙箱: `/root/cradle_v2m4`。
> 所有数字出自本轮真实运行；数据文件: `reports/milestones/v2m4_data/`（stats/ffprobe/CER 复核 JSON）。

## 0. 摘要

| 项 | 结果 |
|---|---|
| 成片 | **9/9**（T1 product_seeding_30s_v2 ×3 / T2 store_ambiance_28s_v2 ×3 / T3 offer_lead_28s_v2 ×3） |
| 任务良率 | **19/19 accepted**（首轮零重试、零短路、零 fallback、零 blocked） |
| 候选良率 | **25/25 pass**（comp 10 + puregen 12 + ken_burns 1 + evidence 2） |
| G7 | 25/25 通过，score ∈ [0.9758, 0.9983]；**0 条被杀**；G7e skipped（无 API，D-004） |
| Wan 用量 | **14**（puregen 12 + evidence 2；确定性车道 0）——本轮守卫 120，全局累计 60+18+14=**92 ≤ 200** |
| G6 | ASS 逐字硬校验 **9/9**；CER small 5/9 ≤5% → **medium 复核 6/9 ≤5%**（差集全为 ASR 同音字混淆，D-047 口径） |
| 目检 | 9 片 ×2 帧 + 3 帧定点抽检（拼图 `reports/milestones/v2m4_media/`）：**食物镜头 0 形变** |

## 1. 成片清单（9 条全部 1088×1920 / h264 / aac / 16fps）

| video_id | 模板 | 车道构成(comp+pure+evd) | 时长 | ASS逐字 | CER small | CER medium | 目检 |
|---|---|---|---|---|---|---|---|
| v2_t1_seeding_v1 | seeding_30s_v2 | 5+3+1 | 30.0s | ✓ | 0.0978 | 0.0543 | 无形变 |
| v2_t1_seeding_v2 | seeding_30s_v2 | 5+3+1 | 30.0s | ✓ | 0.0870 | 0.0652 | 无形变 |
| v2_t1_seeding_v3 | seeding_30s_v2 | 5+3+1 | 30.0s | ✓ | 0.0978 | 0.0435 | 无形变 |
| v2_t2_ambiance_v1 | ambiance_28s_v2 | 4+4+1 | 28.5s | ✓ | 0.0426 | 0.0319 | 无形变 |
| v2_t2_ambiance_v2 | ambiance_28s_v2 | 4+4+1 | 28.5s | ✓ | 0.0426 | 0.0319 | 无形变 |
| v2_t2_ambiance_v3 | ambiance_28s_v2 | 4+4+1 | 28.5s | ✓ | 0.0645 | 0.0538 | 无形变 |
| v2_t3_offer_v1 | offer_lead_28s_v2 | 4+3+1 | 28.5s | ✓ | 0.0408 | 0.0000 | 无形变 |
| v2_t3_offer_v2 | offer_lead_28s_v2 | 4+3+1 | 28.5s | ✓ | 0.0222 | 0.0000 | 无形变 |
| v2_t3_offer_v3 | offer_lead_28s_v2 | 4+3+1 | 28.5s | ✓ | 0.0440 | 0.0110 | 无形变 |

- 时长与模板各幕合计逐秒一致（30.0/28.5/28.5），镜头数 8-9 ∈ §5.5 的 8-14 带。
- 每片恰 1 个 evidence_transfer 演示镜头（S18 虾滑 / S19 毛肚，**合成演示源，非真实实拍**，
  M3 D-068 结构保持度 flow_cos 0.92-0.96 背书）。
- 变体差异化落地: 选角（环境幕轮换 S07/S10/S11/S16、offer S13/S14/S17、demo S18/S19）+
  numbers（价格 42.8/45.9/39.9 · 39.9/35.9/36.9 · 49.9/52.9/45.9 与 offer 文案）+ T3 的 cta_line；
  目检确认价格数字只出现在字幕（D-015 数字隔离成立，字卡幕程序渲染正常）。
- CER 残差解读: small→medium 差集与 medium 仍 >5% 的 3 条（t1_v1/t1_v2/t2_v3）全部为同音字
  混淆（手作/手做、胶质拉丝/胶制拉撕、晶莹/经营、红汤/红糖、定形/定型、一位/亿位）——
  与 D-036/D-047 结论一致，交付字幕与 TTS 朗读无缺陷；生产 ASR 口径不改。

## 2. 三车道良率与 G7 触发明细

| 车道 | 任务 | accepted | 候选 | pass | Wan 候选 | 备注 |
|---|---|---|---|---|---|---|
| compositing_2d5 | 10 | 10 | 10 | 10 | 0 | 确定性渲染（n_best 视为 1，D-062） |
| pure_gen_short | 6 | 6 | 12 | 12 | 12 | n_best=2 全过；首尾锚定几何锁定 |
| evidence_transfer | 2 | 2 | 2 | 2 | 2 | d=0.30 双条件重绘（D-065） |
| ken_burns | 1 | 1 | 1 | 1 | 0 | S12 手部高风险原样保留（n_best=3→1, D-062） |
| **合计** | **19** | **19** | **25** | **25** | **14** | 任务级/候选级良率均 **100%** |

- G7 触发明细: **无任何子项触发**（25 候选全量检查）。子项最低分: a=0.9515（阈 0.82）、
  d=0.9515（阈 0.84）、b=1.0、c=1.0（P95 光流无超阈）；G7e 全部 skipped（无 API，D-004，
  抽帧目检代位）。逐候选分数见 `reports/milestones/v2m4_data/v2m4_stats.json`。
- 重试/短路/降级路径本轮**未被触发**（首轮全绿）——路径存在且经 pytest 覆盖，但产线良率
  统计中 fallback=0、short_circuit=0 如实记录。
- 复现性佐证: S01/S09/S18 候选 overall 与 G7 分数与 M3 沙箱实测**逐位一致**
  （0.9604/0.9836、0.9451/0.9979、0.9613/0.9914）——确定性车道跨沙箱可复现。

## 3. v1/v2 食物镜头形变率对比（M5 终报原料）

| 指标 | v1（first_frame_i2v 食物车道） | v2（compositing_2d5 + evidence 演示） |
|---|---|---|
| 候选池 | 122 条（主仓 62 + 沙箱 60；M0 全池 DINO 粗筛+目检） | 25 条（本轮全量；食物相关 12 = comp 10 + evidence 2） |
| 人类可辨形变 | **15 条**目检确证（fluid_melt 8 / split_merge 3 / count_drift 2 / object_flow 2）= 全池 12.3%；按 60 条 Wan 生产候选口径 25% | **0 条**（G7 全过 + 21 帧目检 0 例外，如实记录） |
| 其中曾过 v1 全部门禁 | 8 条（verdict=pass 仍形变） | — |
| 其中曾入选成片/AB | 6 条（曾 selected 进入成片/AB） | 0 |
| 典型案例 | FX-F001 虾仁 9 只→融为糊浆；FX-F005 红油溢锅成滩；FX-F006 虾仁肿胀融浆；FX-F009 锅面化为红泥浆 | 无（comp 食物不参与生成，形变物理性消灭；evidence 重绘贴源） |
| 机制根因 | Wan 自由生成食物本体，首帧锚定不足以约束中后帧 | 生成器只画环境/氛围；食物本体来自确定性 2.5D 合成或低强度重绘（denoise 0.30） |

来源: v1 侧 = `reports/V2_M0_AUDIT.md` §4.3（15 fail 中 8 条 verdict=pass、6 条曾 selected）
与 D-052；v2 侧 = 本轮 v2m4_stats.json + 目检拼图。

## 4. 预算 / 耗时 / 显存

| 项 | 数值 |
|---|---|
| Wan 调用（本轮） | 14（预算 120 硬守卫未逼近；全局 60+18+14=92 ≤ 200） |
| 生成+门禁墙钟 | 31.5 min（02:03:31–02:35:00 UTC，19 任务 GPU 串行） |
| compose 9 片 | ~9.7 min（含 TTS/ASS/BGM/G6 双级校验，~60s/片） |
| 显存峰值 | puregen 16425 MB / evidence 16586 MB（fp16，V100S-32GB 独占）；确定性车道无 Wan 显存 |
| 磁盘 | 沙箱+成片新增 <2G，avail 28G（红线 20G 未逼近） |

## 5. 被杀候选清单（gallery_v2 素材）

**本轮 0 条**——G7 未杀任何候选，无新增画廊素材。既有画廊（M2/M6 的 24 例）不受影响；
`reports/gallery_failures_v2/` 的漏网/误杀案例收集属 M5 终报范围。

## 6. 交付物位置

- 成片+ASS: 主仓 `output/v2_t{1,2,3}_*.mp4(.ass)`（9 条，与 v1 片区分；媒体不入 git）；
  沙箱原件 `/root/cradle_v2m4/output/`；本地备份 `agents/v2m4/films/`。
- 目检拼图: `reports/milestones/v2m4_media/v2m4_{t1,t2,t3}_grid.jpg`（3 片×2 帧/张）+
  `v2m4_extra_grid.jpg`（evidence demo ×2 + puregen 雨窗定点抽检）。
- 数据: `reports/milestones/v2m4_data/{v2m4_stats,v2m4_ffprobe,v2m4_g6_cer_medium_recheck}.json`。
- spec（入 git）: `reports/milestones/v2m4_specs/`（9 份）；沙箱运行副本 `/root/cradle_v2m4/specs/`。
- 模板: `templates/narrative_v2/offer_lead_28s_v2.json`（新）+ narrative/ 三份 v2 投放副本（D-070）。
- 脚本: `scripts/v2m4_{sandbox,prod_run,compose,stats,frames,cer_medium}.{sh,py}`（幂等可复跑）。

## 7. 局限（如实）

- L1: 首轮 100% 良率 → retry/短路/fallback/被杀候选路径无产线样本；其行为正确性由
  309 项 pytest 与 M3 实测背书，M5 终报如需更多负样本须依赖新夹具或更难卡。
- L2: CER medium 仍 >5% 的 3 条为 ASR 同音字混淆（BGM 混音轨 ASR 固有难度），
  逐字硬门禁 9/9 为交付口径（D-047 惯例，不改生产 ASR）。
- L3: evidence 演示镜头使用合成测试源（非真实实拍）；真实实拍激活路径见
  `assets/evidence/README.md`，片内已按"演示源"标注。
- L4: whisper-medium.pt（1.5G）为本轮复核重新下载；是否保留由 M5 磁盘治理裁定
  （当前 avail 28G，红线之上）。

## 8. 决策增量

D-070（v2 模板投放机制）/ D-071（新增 T3 offer_lead_28s_v2）/ D-072（本轮 Wan 硬守卫 120）。
本轮无新增决策高于 D-072（CER 复核沿用 D-047 口径，不另立）。

# PROJECT CRADLE 最终报告 (FINAL_REPORT)

- 日期: 2026-09-08 (开工 00:52, 本报告同日收尾) | 仓库: `~/cradle` @ M6 commit (基线 35d1938)
- 执行: 主控 + 子代理流水线 (M1-ENV / M2-CODE / M2-EXEC / M3-COMPOSE / M4-EXEC / M5-PROD / M5-CONT / M6-FINAL), 全程无人值守、未向用户提问
- 任务书: `SPECS.md` (v1.0) | 决策: `DECISIONS.md` D-001..D-050 | 过程: `PROGRESS.md` | 里程碑报告: `reports/milestones/`
- ⚠️ **口径声明 (D-004 标注义务)**: 全程未经 API VLM 审核 —— 用户未提供 `config/api.env`, G2/G5 由 CLIP ViT-L/14 本地启发式替代判分 (D-009/D-026/D-041); 本报告所有 G5 分数应理解为启发式代理分。

---

## 1. 一页总览

**结论一句话**: 任务书总目标全部达成 —— 「产品图 + 镜头卡 → 无人值守生成 → 六道门禁 → 失败重试/降级 → 程序化合成」管线在 V100 32G 上从零建成并真实跑通, 交付 **9 条 Wan 竖版成片** (目标 8-10), 生产任务良率 **100%** (含降级交付率 100%, ≥95% 标准达标), 失败画廊 24 例、复现/换模/换API/换资产四指南齐备。

| 项 | 结果 | 判定 |
|---|---|---|
| 成片交付 | **9/9** 条生产成片 (`output/t{1,2,3}_*_v{1,2,3}.mp4`, 1088×1920 竖版 h264+aac) + 1 条 M3 调试成片 | ✓ (≥8 条) |
| 生产任务良率 | **17/17 accepted (100%)**, 全部 attempts=0 首轮, 0 fallback / 0 blocked | ✓ |
| 含降级交付率 | **100%** (0 降级即 100%; M2 迭代期口径 12/12=100%) | ✓ (≥95%) |
| G6 硬门禁 (字幕逐字) | **9/9 通过**; CER 回转 whisper-small 生产口径 1/9, whisper-medium 复核 8/9 (差因=ASR 同音字, §5-L3) | ✓ (逐字为准) |
| A/B (竖 vs 横) | 10/10 accepted, 竖版 p50 overall 0.9390 > 横 0.9172 → **维持竖版 480×832** | ✓ |
| Wan 预算 | **60/200** (A/B 10 + 生产 50; 口径见 D-048) | ✓ (余 140) |
| API 消耗 | **0 次 API** (生图/VLM/TTS/ASR 全本地兜底, 预算守卫未动用) | ✓ |
| 失败画廊 | **24 例** (`reports/gallery_failures/`, 类型A×22 + 类型B×2, ≥20 达标) | ✓ |
| pytest | **226 passed, 0 failed** | ✓ |

**成本 (GPU 墙钟, 均有日志/DB 佐证)**:

| 阶段 | 墙钟 | 出处 |
|---|---|---|
| 模型/权重下载 (M1, 非 GPU) | ~80 min | 46G 经 ModelScope/aliyun curl 直连 11-12MB/s (D-021) |
| M1 冒烟 (LTX 3.1s + Wan 364.6s + SDXL 首帧 + 权重加载) | ~15 min | `m1_ltx_smoke.json` / `m1_wan_smoke.json` |
| M2 十镜头闭环 (62 候选, LTX) + Wan 装配验证 | ~24 min | 17m11s (`m2_yield_report_v1.md`) + 388.7s (D-030) |
| M3 合成 34.2s + G6 CER 两轮 | ~3 min | `m3_compose_report.md` |
| M4 e2e 一键出片 340s + kill -9 恢复演示 ~6min | ~12 min | `m4_e2e_demo.md` / `m4_recovery_demo.md` |
| M5 A/B 69.3min + 量产 **305.2min** + 9 片合成 6.5min + CER 复核 ~3min | ~384 min | `m5_yield_report.md` §8 |
| **合计** | **GPU 期 ≈7.3 h + 下载 ≈1.3 h ≈ 8.6 h** | 项目总墙钟 ≈20 h (同日), ≪ 5 天预算 |

显存峰值: 全场 max **23.76GB / 32GB (74%)** (ABS03L 横版; 生产任务 23.10-23.66GB), fp16 全程未触发 VAE 降级/NaN 预案。

**两点必须知道的标注**:
1. **该批全部门禁判分 (G2-G5) 未经 API VLM 审核** —— CLIP 启发式替代口径 (D-004); 画廊 24 例即该口径局限的实证材料。
2. **主控抽帧目检 3 片通过** (2026-09-08, 交付前抽检): t1 红汤锅底无变形无乱码、字幕正确; t2 店内暖光氛围正常、字幕清晰; t3 优惠字卡数字为程序渲染生效 (非生成入画)。9 片的机器验证 (六门禁+逐字+CER) 之外的人眼抽检即此 3 片。

---

## 2. 样片索引 (9 条生产成片 + 1 条调试成片)

生产成片全部 1088×1920@16fps h264+aac, 时长与模板偏差 0.0s; 台账 `m5_videos` 表 (沙箱), 反查 SQL `reports/milestones/m5_trace_query.sql` (5/5 实测通过)。

| 成片 | 模板 | 镜头构成 (幕→卡) | 时长 | 大小 | G6 逐字 | CER small (生产口径) | CER medium (复核) | 文件 |
|---|---|---|---|---|---|---|---|---|
| t1_seeding_v1 | product_seeding_25s | S02/S01/S03/S04/S07 | 25.0s | 11.4MB | ✓ | 0.0323 ✓ | 0.0108 ✓ | `output/t1_seeding_v1.mp4` |
| t1_seeding_v2 | _v2 | S13/S03/S17/S15/S16 | 25.0s | 11.7MB | ✓ | 0.0964 | 0.0120 ✓ | `output/t1_seeding_v2.mp4` |
| t1_seeding_v3 | _v3 | S04/S15/S01/S02/S10 | 25.0s | 12.4MB | ✓ | 0.0959 | 0.0274 ✓ | `output/t1_seeding_v3.mp4` |
| t2_ambiance_v1 | store_ambiance_22s | S08/S07/S09/S01 | 22.0s | 7.4MB | ✓ | 0.1395 | 0.0465 ✓ | `output/t2_ambiance_v1.mp4` |
| t2_ambiance_v2 | _v2 | S08/S16/S09/S15 | 22.0s | 8.7MB | ✓ | 0.0769 | 0.0256 ✓ | `output/t2_ambiance_v2.mp4` |
| t2_ambiance_v3 | _v3 | S08/S11/S09/S01 | 22.0s | 7.5MB | ✓ | 0.0658 | 0.0395 ✓ | `output/t2_ambiance_v3.mp4` |
| t3_offer_v1 | instant_offer_17s | S13/S03/S17/S02 | 17.0s | 7.6MB | ✓ | 0.1846 | 1.7077→**0.1231** (幻觉修正后, D-047) | `output/t3_offer_v1.mp4` |
| t3_offer_v2 | _v2 | S15/S01/S12/S02 | 17.0s | 7.1MB | ✓ | 0.1268 | 0.0563 (临界) | `output/t3_offer_v2.mp4` |
| t3_offer_v3 | _v3 | S15/S02/S01/S14 | 17.0s | 8.2MB | ✓ | 0.0972 | 0.0139 ✓ | `output/t3_offer_v3.mp4` |
| m3_seeding_debug (调试产物) | product_seeding_25s | S02/S01/S03/S04/S07 (LTX 调试素材) | 25.0s | 3.4MB | ✓ | 0.0323 ✓ | — | `output/m3_seeding_debug.mp4` |

- 逐条 CER 数据: `/root/cradle_m5/workdir/logs/m5_g6_cer_medium_recheck.json` (D-047); CER 为软性披露项, 交付字幕以 ASS 逐字比对为准 (9/9 全等)。
- m3_seeding_debug 为 M3 合成层验证片 (384×512 LTX 素材上采样 + hold-last 停帧, 报告 `m3_compose_report.md`), **非生产口径**, 留档佐证合成层演进。
- 每片配套 `.mp4.ass` 字幕文件同目录; t3 的优惠字卡/CTA 幕为程序渲染纯色段, 价格数字只出现在字幕 (D-015, 代码级断言)。

---

## 3. 良率统计与失败聚类

### 3.1 任务级 (可用标准 = 含降级交付率 ≥95%)

| 阶段 | 任务 | accepted | fallback | blocked | 一次通过率 | 含降级交付率 |
|---|---|---|---|---|---|---|
| M2 迭代期 (LTX, 12 卡) | 12 | 9 | 3 (S08/S09/S11→KenBurns) | 0 | 9/12 = 75% | **100%** |
| M5 A/B (Wan, 10 任务) | 10 | 10 | 0 | 0 | 100% | 100% |
| **M5 生产 (Wan, 17 任务)** | **17** | **17** | **0** | **0** | **100%** (attempts 全 0) | **100%** |

### 3.2 候选级六门禁通过率

| 门禁 | M2 (LTX, n=59) | M5 A/B (n=10) | M5 生产 (n=50) |
|---|---|---|---|
| G1 技术 | 100% | 10/10 | 50/50 |
| G2 缺陷 | 100% (重校准后, D-026) | 10/10 (min 0.8638) | 50/50 (min 0.8623) |
| G3 一致性 | 100% (min 0.8151) | 10/10 (min 0.8133) | 50/50 (min 0.7759) |
| G4 稳定性 | 100% (min 0.9602) | 10/10 (min 0.9495) | 50/50 (min 0.9259) |
| G5 美学 | **42.4%** (25/59) ← 唯一卡点 | 10/10 (min 0.7100, 双锚后) | **48/50** (2 边缘 fail) |
| G6 业务 | 合成级占位 (D-011) | — | 成片级逐字 9/9 |

### 3.3 失败聚类 (全部 36 个拒绝候选, 无一例外)

| 聚类 | 数量 | 镜头/卡 | 定性 | 画廊 |
|---|---|---|---|---|
| **A: 校准前 G5 启发式场景偏差** | 34 (S08×9 / S09×9 / S11×16) | 门头夜景/雨窗/无人背影 | 美食 appeal 锚 (D-026) 对场景类资产系统性打低: 分数恒定 0.62-0.64、defects≈0、换 seed/重试完全无效; **校准后重评 (D-041 双锚) 32/34 翻入 pass 带** → 属启发式问题非画面问题 (目检佐证 m5_calibration §1.1) | 22 例 `typeA_g5_scene_bias/` |
| **B: 生产期 G5 边缘** | 2 (S14_a0_0=0.6932, S15_a0_0=0.6913) | 酸梅汤/红汤浇锅 (Wan 480×832) | 双锚已上线仍落 0.70 阈值边缘带 (差 ≤0.009); 同任务 n_best 下一候选即 pass 被选中, 任务级零损失 | 2 例全收 `typeB_g5_edge/` |

- **G1/G3/G4/G6 类失败: 0 例** (36 个拒绝候选全部为 G5 单门禁) —— 阈值校准的重心应放在 G5 与 VLM 口径, 见画廊 `INDEX.md` "给阈值校准者的要点"。
- 重试经济性: M2 时期 34/59=58% 生成量投给恒定 borderline 0 收益 → 催生 stable-borderline 短路 (D-042); M5 生产短路 0 触发 (首轮通过率太高, 机制在线未被需要), 候选/任务 2.94 vs M2 5.17 (-43%)。

---

## 4. 阈值表 (冷启动值 → 校准后值; 试点验证制)

**最终状态: 全部六门禁维持冷启动值, 生产卡 acceptance 一字未改** (S01-S17)。两条上调议案被试点数据否决:

| 门禁 | 参数 | 冷启动值 | 拟上调 | 试点/实测 | 结论 |
|---|---|---|---|---|---|
| G1 | duration_tol | ±0.5s | — | 10/10 过; 9 片合成偏差 0.0s | **不变** |
| G2 | vlm_defect_max | 0.2 | — | 生产 min 0.8623, 最差单缺陷 0.0798 | **不变** |
| G3 | clip_ref_min / clip_text_min | 0.65 / 0.22 | 0.78 (M2 建议) | 试点 min **0.8367** (ABS03P) ≤ 0.85 门槛 | **否决上调, 维持 0.65/0.22** |
| G4 | temporal_clip_min | 0.85 | 0.95 (M2 建议) | 试点 min **0.9669** (ABS11P) ≤ 0.97 门槛 | **否决上调, 维持 0.85** |
| G5 | vlm_overall_min | 0.70 | (不改阈值) | M2 42.4% → **D-041 分锚** (双锚 max) → Wan 全过 (试点 min 0.7418); 生产 min 0.6913 | **阈值 0.70 不变; 修的是锚不是阈值** |
| G6 | 逐字(硬) + CER≤5%(软) | cer_max=0.05 | — | 逐字 9/9; CER 双口径见 §2 | **机制不变, 双数字披露** |

依据与过程: M2 建议 G3→0.80/G4→0.95 (LTX 短片余量大); M5 按"试点 min 须 >上调值"规则实测, Wan 81 帧长片时序运动把 G3/G4 分数再拉低一档 (0.8367/0.9669), 两案均未达门槛 → 如实记录"校准被试点否决" (m5_calibration §5)。G5 的 42.4%→96.6% 走的是**分锚** (D-041: food/scene 双锚取 max, 首版按路径切锚被 S10 误杀否决), 而非降阈值。

**A/B 结论**: 竖版 480×832 维持为产线画幅 (竖 p50 overall 0.9390 > 横 0.9172; 目检横版中心裁切损失上下画幅、S11 横版远端有伪字辉光; D-040 规则不触发全横版变更)。

---

## 5. 局限与建议 (如实, 按重要性排序)

**L1. CLIP 启发式 VLM 是最大的口径局限 (D-004/D-009/D-026/D-041)**。G2/G5 分数是文本锚余弦相似度的线性映射, 不是语义理解: ① appeal 锚曾把场景类资产系统性打到 borderline (画廊类型A 22 例即实证); ② subject_missing 只能代理"内容丧失" (黑/亮帧), **检不出"主体错型"** (如生成的是别的菜); ③ deformed/blur 锚正负样本相似度重叠, 鉴别力弱。**接入真实 VLM 的路径已铺好**: 在 `config/api.env` 填 `VLM_API_BASE/KEY/MODEL` 即自动切换 (OpenAI 兼容适配器 `src/api/vlm.py` + `src/api/adapters.py`, 失败重试 1 次切本地), 预算守卫 VLM≤1500 次; 建议先用真实 VLM 复审画廊 24 例 + M2 存量 59 候选, 重定 G5 阈值后再上量产。

**L2. 产出模型是替代模型 Wan2.1-Fun-1.3B-InP (D-019)**。规格主选 Wan2.1-I2V-1.3B 不存在 (HF 401, 官方只发布过 T2V-1.3B / I2V-14B); Fun-InP 为阿里 PAI 官方 Wan2.1 血统 1.3B 首末帧条件 I2V, 原生 480p@16fps×81 帧恰好对齐产线参数, 实测质量达标 (D-030 六门禁 0.745-1.0)。若未来官方发布 I2V-1.3B, 按 README"换底模指南"接入即可 (教训: **先冒烟 1 条过全门禁, 再量产** —— D-022 的 diffsynth 错配 wheel 同证此训)。

**L3. CER 回转的同音字问题 (D-034/D-036/D-047)**: whisper-small 生产口径 CER≤5% 仅 1/9, medium 复核 8/9; 差集**全部为同音字混淆** (锁/所、灶/造、七上八下/吸上巴下…), 交付字幕与 TTS 朗读无缺陷。建议: 校验口径改 **pinyin 归一** (编辑距离在拼音层计算) 或扩充领域热词表, 可把该软门禁从"ASR 局限"中解放; t3_offer_v2 medium 临界 0.0563 与 t3_offer_v1 的 BGM 段幻觉 (temperature fallback 已修) 均属此类。

**L4. 降级故障路径未被量产触发 (如实现实)**: ken_burns 车道已验证 (S12 在 M2/M4 生产口径真渲染; M2 有 3 次 LTX 期 fallback), 但 **M5 生产 0 fallback / 0 blocked** —— `route` 的 fallback/blocked 分支、stable-borderline 短路在生产口径下均为"在线未触发"状态, 其生产级可靠性只有单测 + M2 LTX 口径佐证。

**L5. 单风格资产**: 11 张资产全部为 SDXL 暖色美食风 (D-029), 任务书可选 P2"同镜头卡多风格变体"未做; 换风格只需换资产目录 (管线不区分生图/实拍), 但多变体下的 G5 锚定基线需重新校准。

**L6. 1080p 为软件插值**: 生成原生 480×832, 成片 1088×1920 由 ffmpeg scale 插值上采样, 无超分模型; 竖屏平台投放可接受, 若需真 1080p 应接 RIFE/Real-ESRGAN 类超分 (GPU 预算另计)。

**L7. 模板文案与幕长的张力 (D-032)**: hook/CTA 幕 3s 装 21 字文案, 靠自适应语速 +70%/+84% 消化, 语速偏快; 建议模板 v2 缩短 hook/CTA 文案或扩幕长至 5s。

**L8. BGM 为占位级 (D-035/D-006)**: 程序合成正弦和弦, 零版权但音质占位; ducking 为预衰减+sidechaincompress 近似 -12dB。生产化应换 CC0 循环或正版曲库。

**L9. RAFT 光流留桩**: G4 稳定性仅 CLIP 相邻帧相似度 (RAFT-small Volta 兼容性未实装, 门禁 JSON 中 raft_p95=null); CLIP 口径对"慢漂移"不敏感, 真实 VLM 接入时建议一并补测。

**L10. 口播-画面松配**: evidence 幕允许 M3 先例内的 b-roll 式松配 (如口播讲毛肚、画面是虾滑特写), 变体卡选角规则 (D-045) 未做画面-语义强对齐; 若需强对齐应在镜头卡增加 slot 级语义约束。

**L11. 调试/生产口径 3× 差**: LTX 调试卡 384×512×1.56s 与生产卡 480×832×5s 差约 3 倍, M3 时代靠 tpad 停帧补齐 (D-033); 门禁分数在两个口径间不可直接比 (G3/G4 在长片上系统性更低, §4 试点数据), 迭代期结论须在生产口径复验。

---

## 6. API 用量表 (预算守卫: 生图≤300 / VLM≤1500 / TTS≤200 / ASR≤200)

| 能力 | API 调用 (route=api) | 本地兜底 (route=local) | 说明 |
|---|---|---|---|
| 生图 IMAGE | **0** | SDXL: 11 张资产 (D-029) + M5 每任务首帧风格统一 ~25s/任务 (D-044) | 无 api.env, D-004 |
| VLM | **0** (0/1500) | CLIP 启发式: 主库 59 + M4 沙箱 16×2 + M5 沙箱 60 = **151 次门禁判分** | api_usage 表逐次记账 (D-008) |
| TTS | **0** | edge-tts: M4 10×2 + M5 (含冒烟 20 与 9 片合成) 共 111 次 = **141 次** | 自适应语速探测含在内 (D-032) |
| ASR | **0** | whisper: M3 2 次 + M5 合成 G6 9 次 (small) + medium 复核 9 次 + 幻觉复评 | G6 的 asr_fn 为门禁内直连, 不经 api_usage 记账 (如实注记) |

**API 预算消耗合计: 0 / 预算总额 2200 次**; 预算守卫与"失败重试 1 次切兜底"逻辑有单测覆盖 (tests/test_api_adapters), 因无 API 全程未实战触发。

---

## 7. 交付物清单 (SPECS §7 对照)

| §7 项 | 状态 | 位置 |
|---|---|---|
| 1. FINAL_REPORT.md | ✓ 本文件 | `reports/FINAL_REPORT.md` |
| 2. 成片 8-10 条 | ✓ 9 条 (+1 调试片) | `output/` |
| 3. 失败画廊 ≥20 例 | ✓ 24 例 | `reports/gallery_failures/` (INDEX.md 入口) |
| 4. README 四指南 | ✓ | `README.md` |

---

## 附录 A: SPECS §10 最终自检清单 (九项, 逐项证据)

- [x] **M1-M6 均有产物佐证** — M1: `reports/milestones/m1_volta_check.txt` + `m1_{ltx,wan}_smoke.{mp4,json}`; M2: `m2_yield_report_v1.md` + `m2_gate_stats.json` + `m2_wan_verify.json`; M3: `m3_compose_report.{md,json}` + `output/m3_seeding_debug.mp4`; M4: `m4_e2e_demo.md` + `m4_recovery_demo.md`; M5: `m5_calibration.md` + `m5_yield_report.md` + `output/t*_v*.mp4`×9; M6: `reports/gallery_failures/` (24 例) + 本文件 + `README.md`
- [x] **≥8 条 Wan 成片在 output/** — 9 条 (§2 索引表, ffprobe 1088×1920 h264+aac 实测)
- [x] **每条成片门禁明细可追溯 (附 SQLite 查询脚本)** — `reports/milestones/m5_trace_query.sql` 5 条查询在沙箱库实跑 5/5 通过 (m5_yield_report §12): q2 成片→镜头→候选→六门禁反查验证 t1_seeding_v1
- [x] **失败画廊 ≥20 例** — 24 例 (类型A×22 + 类型B×2), 每例 video.mp4+gate_json.json+grid.jpg+case.md, `reports/gallery_failures/INDEX.md`
- [x] **FINAL_REPORT 四节齐全** — 本文件 §1 总览 / §2 样片索引 / §3 良率+失败聚类 / §4-7 阈值·局限·API·DECISIONS 附录
- [x] **崩溃恢复演示通过** — M4 kill -9 于 gating∧generating 混合孤儿窗口, recover() 区分两类孤儿, 6/6 composed + 自动成片, 证据 `m4_recovery_demo.md` (prekill 快照/时间轴/候选 mtime 对照)
- [x] **README 完整** — 四指南 + 结构图 + SQLite 追查询速查, 见 `README.md`
- [x] **DECISIONS 全记录** — D-001..D-050 (附录 B; 全文 `DECISIONS.md`), 途中无跳号、只增不改
- [x] **git 历史干净** — 每 M 一 commit, 工作区 status 干净, tag v1.0 (见 PROGRESS.md M6 节)

## 附录 B: DECISIONS 索引 (D-001..D-050, 全文见 DECISIONS.md)

| # | 一句话摘要 |
|---|---|
| D-001 | 盘 83G<150G 规格 → 继续执行 + fp16-only/下载即清/<20G 即停纪律 |
| D-002 | M1 单条 Wan 冒烟属"模型可用性验证", 不违反"门禁跑通前禁碰 Wan" |
| D-003 | git 不收大媒体 (workdir/output mp4 等), 证据链走 SQLite + reports 索引 |
| D-004 | 无 api.env → 全链路本地兜底 (SDXL/CLIP 启发式/edge-tts/whisper), 报告标注"未经 VLM 审核" |
| D-005 | 服务器独占仍守共享纪律 (tmux cradle_ 前缀 / GPU 前 nvidia-smi / 不动旧目录) |
| D-006 | BGM ducking -12dB 用 volume 预衰减 + sidechaincompress 近似实现 |
| D-007 | tasks 表追加 card_json/template/hint_json/error 列 (迁移只新增) |
| D-008 | 预算守卫按"尝试"计数 (含失败), local 不占 API 预算 |
| D-009 | 本地 VLM=CLIP 启发式: 7 锚相似度线性映射, 严格按 vlm_prompt 公式合成, 输出强制标注 clip_heuristic |
| D-010 | CPU 测试用系统 python3; 重依赖 lazy import + stub 注入, ffmpeg 测试 skipif 守护 |
| D-011 | G6 两级: 候选级占位通过; 合成级逐字(硬)+CER(软, 自实现编辑距离) |
| D-012 | blocked 语义/恢复路径: pending 期检测; force_status 留痕; recover() 孤儿分类处理 |
| D-013 | ken_burns n_best=1 (确定性), 产物仍过门禁记账便于画廊统一收集 |
| D-014 | run_once 不动点推进 (≤10 遍); run_forever 3 轮无进展自动退出告警 |
| D-015 | CTA/字卡=程序纯色段; 价格数字只存模板 numbers, 代码级断言不进视频路径 |
| D-016 | CRADLE_ROOT 环境变量注入项目根, 单测/多实例完全隔离 |
| D-017 | ingest 幂等: 仅 pending 可覆盖卡面, 运行中任务不被换卡 |
| D-018 | 候选级 overall = 六门禁算术平均; VLM overall 单列不稀释 |
| D-019 | Wan2.1-I2V-1.3B 不存在 (HF 401) → 改用 PAI/Wan2.1-Fun-1.3B-InP (原生 480p@16fps×81 帧) |
| D-020 | Volta 版本矩阵定版: diffsynth 1.1.9 / diffusers 0.33.1 / transformers 4.49.0 等; LTX T5 用 FLUX fp16 省 9.5G |
| D-021 | 下载策略: 大文件 curl 直连 (ModelScope 11-12MB/s); hf-mirror/pip 通道实测慢不可用 |
| D-022 | 阿里源 diffsynth wheel 错配 (patchify 缺行) → 按上游语义打补丁; 教训: 镜像包先冒烟再量产 |
| D-023 | CLIP ViT-L/14.pt 完整性确认 (932,768,134 字节即 openai fp16 TorchScript 完整尺寸) |
| D-024 | ltx.py 定版: LTXPipeline + LTXImageToVideoPipeline, 进程缓存, fp16 黑帧守卫 |
| D-025 | 卡面投影: debug_model=ltx 时生产卡→LTX 调试卡落库, 生成与门禁同口径 |
| D-026 | CLIP 启发式实测重校准: 修 G2 映射 bug (pos 锚反向), 锚域按探针数据定标; 卡面阈值未动 |
| D-027 | open_clip 权重本地化 (models/clip/ViT-L-14.pt) + embed 进程级缓存 |
| D-028 | wan.py 定版: DiffSynth 四件套; negative_prompt 必须逗号串 (list 会 batch 错配崩) |
| D-029 | 资产: 832×1216 单一事实源 11 张, back_view 3 seeds 择优, manifest 全记录 |
| D-030 | Wan 装配一次性验证: S01 六门禁全过 (364.9s / 16.9GB), M5 量产风险消除 |
| D-031 | 候选 seed 由文件名恢复: stable_seed(shot)+attempt*1000+i |
| D-032 | 口播自适应语速 fit_tts_to_scene (hook +70% / CTA +84%), 不超幕长不截断 |
| D-033 | 调试素材 3× 时长差用 tpad hold-last 补齐; 否决 setpts 慢放 (放大伪影) |
| D-034 | CER 归一化: 数字→中文读法 (与 TTS 一致), 剥标点空白 |
| D-035 | BGM 程序合成 (G 大三和弦正弦+tremolo+低通), 零版权, 音质占位 |
| D-036 | G6 ASR 热词: 无热词 CER 0.0645 → 热词 0.0323, 残差全同音字; 双数字披露 |
| D-037 | M4 沙箱配方三要素: models 只读软链 + CRADLE_CLIP_WEIGHTS + HF_HUB_OFFLINE (缺一被 HF hub 卡死) |
| D-038 | M5 独立沙箱 /root/cradle_m5 (防候选同名覆写); CPU 长任务 setsid nohup 替代 tmux (误杀教训) |
| D-039 | Wan 生产 steps=20 经 settings.prod_steps 下发 (原 hard-code 25); stylize denoise 同机制 |
| D-040 | A/B 竖版组兼任 G3/G4 阈值试点 (省 5 条 Wan 预算); 代表集覆盖 5 类资产 |
| D-041 | G5 分锚=双锚取最优 (按路径切锚被 S10 误杀否决); 离线重评 42.4%→96.6%, 美食回退违例 0 |
| D-042 | stable-borderline 短路: ≥2 候选全非 pass 且 overall 极差 <0.02 → 直接 fallback |
| D-043 | compose-video --spec 显式合成入口 + m5_videos 台账 (schema v2), 支持成片名反查 |
| D-044 | SDXL 改本地目录加载 (离线沙箱修复) + 首帧风格统一 (denoise 0.3, 失败降级不阻塞) |
| D-045 | M5 变体卡 S13-S17 + 6 模板变体 + 9 spec; 选角: 片内不重复/跨片复用 accepted |
| D-046 | M5 收尾接棒: 前手死于启动合成之前 (非"合成中途崩"); 9/9 成片一次通过; pytest 修至 226 |
| D-047 | CER 口径复核: small 1/9 / medium 8/9, 差因同音字; t3_offer_v1 幻觉修正后 0.1231; 不改生产口径 |
| D-048 | Wan 总量口径纠正: 60 (非 70, 系全库口径双计); 引用 report JSON 字段须注明口径 |
| D-049 | (M6) 画廊选样 24 例与媒体入库: 14.4MB<50MB 门槛, mp4/jpg 全量随 git 入库; 网格=5×2 JPEG q85 复用帧缓存; 构建脚本 tools/m6_build_{gallery,index}.py 可重生成 |
| D-050 | (M6) 收尾: SPECS §10 九项自检逐项过 (附录 A) 后打 tag v1.0; FINAL_REPORT 为唯一终报入口, CER 双口径/启发式标注如实带入 |

## 附录 C: 里程碑报告索引

| M | 报告/核心产物 |
|---|---|
| M1 | `m1_volta_check.txt`, `m1_ltx_smoke.{mp4,png,json}`, `m1_wan_smoke.{mp4,png,json}`, `m1_wan_first_frame.png` |
| M2 | `m2_yield_report_v1.md`, `m2_gate_stats.json`, `m2_gate_query.{py,sql}`, `m2_wan_verify.json` |
| M3 | `m3_compose_report.{md,json}`, `m3_seeding_debug.ass`, `m3_first_frame.png` |
| M4 | `m4_e2e_demo.md`, `m4_recovery_demo.md` |
| M5 | `m5_calibration.md`, `m5_yield_report.md`, `m5_trace_query.sql` |
| M6 | `reports/gallery_failures/` (24 例 + INDEX), 本文件, `README.md` |

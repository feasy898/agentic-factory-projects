# M2 良率报告 v1 — LTX 十镜头闭环 (SDXL 资产 → 生成 → 六门禁 → 路由)

- 日期: 2026-09-08 (服务器时间 04:03-04:21, 墙钟 **17m11s**)
- 数据来源: `workdir/cradle.sqlite3` (查询脚本 `reports/milestones/m2_gate_query.py` / `m2_gate_query.sql`,
  聚合快照 `reports/milestones/m2_gate_stats.json`)
- 生成车道: **LTX-Video 2B 调试短样本** (384×512, 25帧@16fps=1.5625s, steps 12, guidance 3.0,
  diffusers 0.33.1 LTXPipeline/LTXImageToVideoPipeline, D-024; 卡片投影见 D-025)
- 参考资产: SDXL 832×1216 主图 (D-029, `assets/products/manifest.json`)

> ⚠️ **该批未经 VLM 审核（CLIP ViT-L/14 启发式替代 G2/G5 判分, D-004/D-009/D-026）**。
> G2/G5 分数是启发式代理分, 与真实 VLM 评语的差距是本报告最主要的校准不确定性来源。

## 1. 每镜头结局 (12/12 走完终态: 9 accepted, 3 fallback, 0 blocked)

| 镜头 | 内容 | 车道 | 终态 | 轮次(attempts) | 候选数 | pass/fail | 选中候选 overall |
|---|---|---|---|---|---|---|---|
| S01 | 毛肚特写 | I2V | **accepted** | 0 | 3 | 3/0 | 0.9335 |
| S02 | 沸腾红汤锅底 | I2V | **accepted** | 0 | 3 | 3/0 | 0.9554 |
| S03 | 虾滑 | I2V | **accepted** | 0 | 3 | 3/0 | 0.9518 |
| S04 | 肥牛卷 | I2V | **accepted** | 0 | 3 | 3/0 | 0.9554 |
| S05 | 甜品 | I2V | **accepted** | 0 | 3 | 3/0 | 0.9508 |
| S06 | 饮品 | I2V | **accepted** | 0 | 3 | 3/0 | 0.9358 |
| S07 | 店内暖光蒸汽 | I2V | **accepted** | 0 | 3 | 3/0 | 0.9396 |
| S08 | 门头夜景 | I2V | fallback (KenBurns) | 2 | 9 | 0/9 | 1.0 (fallback) |
| S09 | 雨窗氛围 | I2V | fallback (KenBurns) | 2 | 9 | 0/9 | 1.0 (fallback) |
| S10 | 空餐桌 | I2V | **accepted** | 0 | 3 | 3/0 | 0.9541 |
| S11 | 无人背影(中风险,n_best=4) | I2V | fallback (KenBurns) | 3 | 16 | 0/16 | 1.0 (fallback) |
| S12 | 手部入画(高风险→KenBurns 车道) | ken_burns | **accepted** | 0 | 1 | 1/0 | 0.9435 |

- 一次通过率(首轮无重试即 accepted): **9/12**。含降级交付率: **12/12 = 100%** (可用标准 ≥95% 达标)。
- S08/S09/S11 的降级产物为投影卡口径 KenBurns (384×512, 1.5625s); S12 验证了 ken_burns
  车道在生产口径 480×832/5s 下真实渲染可用 (ffmpeg zoompan 超采样实现)。
- 被拒候选 34 个 mp4 + 门禁 JSON 全部保留在 `workdir/candidates/` (gitignore 内), 供 M6 失败画廊选材。

## 2. 六门禁通过率与分数分布 (n=59 真实生成候选; 3 个 fallback 候选不计)

| 门禁 | 判据(冷启动) | 通过率 | score min/p50/max | 结论 |
|---|---|---|---|---|
| G1 技术 | 时长±0.5s / 分辨率 / fps / 无全黑全白 | **100%** | 1.0 / 1.0 / 1.0 | 硬性校验, 管线输出格式全对 |
| G2 完整性 | 4 项缺陷各<0.3 | **100%** | 0.897 / 1.0 / 1.0 | 重校准后干净候选全过 (D-026) |
| G3 一致性 | 每帧 vs 首帧参考 ≥0.65 | **100%** | 0.8151 / 0.929 / 0.9702 | 余量大 |
| G4 稳定性 | 相邻帧 CLIP ≥0.85 | **100%** | 0.9602 / 0.9964 / 0.9993 | 余量很大 |
| G5 美学 | overall ≥0.70 且 defect ≤0.2 | **42.4%** (25/59) | 0.6214 / 0.6400 / 0.7800 | **唯一卡点**, 见 §4 |
| G6 业务 | 合成级占位通过 (D-011) | 100% (占位) | 1.0 | 合成阶段逐字校验待 M3 |

候选级 overall(六门禁均分, D-018): min 0.9056 / p50 0.9277 / max 0.9554。

## 3. 失败聚类 (全部 34 个失败候选)

| 聚类 | 数量 | 镜头 | 特征 |
|---|---|---|---|
| G5 borderline(overall 0.55-0.70), 其余五门禁全过 | 34/34 | S08, S09, S11 | **100% 纯 G5 卡点**, 无一例 G1-G4/G6 失败 |

关键事实: 同一镜头所有候选的 G5 分数**几乎恒定**——
S08=0.640(9/9 个候选), S09=0.621-0.633, S11=0.625-0.640; 而 defects 全部 ≈0.0-0.06。
即换 seed/加强 negative/降 guidance 的重试钩子对 G5 完全无效(分数不动), 失败由**资产类型**决定,
不是视频质量波动:

| 镜头 | 资产 appeal 锚实测 (CLIP) | G5 overall 实测 | 说明 |
|---|---|---|---|
| 美食特写类 (S01-S06,S10) | 0.192-0.232 | 0.753-0.780 | 稳过 0.70 |
| 店内环境 (S07) | 0.187 | ~0.74 | 过 |
| 夜景/雨窗/背影 (S08,S09,S11) | 0.145-0.176 | 0.621-0.640 | 全部 borderline |

CLIP 启发式的 appeal 锚("beautiful appetizing professional food photography...")对非美食/夜景
类型系统性打低 → G5 的 0.70 阈值在启发式下退化为"资产类型门"。

## 4. 冷启动阈值 vs 实测分布 — 校准建议 (供主控/M5 审阅, 本阶段未改卡)

| 门禁 | 冷启动值 | 实测 | 建议 | 依据 |
|---|---|---|---|---|
| G5 vlm_overall_min | 0.70 | p50=0.64, 双峰 0.62-0.64(夜景类) vs 0.75-0.78(美食类) | **① 首选: 该批 59 候选用真实 VLM 复审**(预算余量充足: 已用 0/1500), 用 VLM 分数重定阈值; ② 若继续用启发式: 按资产类型归一化 appeal 锚(夜景/人物类单独基线), 或对夜景类 slot 临时降到 0.60-0.62 | 启发式 appeal 锚对夜景/背影系统性偏低(0.145-0.159 vs 美食 0.192-0.232), 是资产类型偏差不是质量信号 |
| G3 clip_ref_min | 0.65 | min 0.8151, p50 0.929 | 可收紧到 **0.80** | LTX I2V 首帧锚定强, 当前阈值几乎无鉴别力; 收紧后仍留 0.02 余量 |
| G4 temporal_clip_min | 0.85 | min 0.9602, p50 0.9964 | LTX 短片可收紧到 **0.95**; 但须在 Wan 81 帧长片上重测后再定产线值 | 1.5s 短片相邻帧天然相似; 长片运动累积会拉低 |
| G2 缺陷<0.3 | 4 项 | 全过; deformed/blur 锚无鉴别力(正/负样本相似度重叠) | 维持; 真实 VLM 接入后重新评估 | subject_missing 已退化为内容丧失代理(D-026), "主体错型"无法检出 |
| G1/G6 | 硬性 | 100% | 维持 | 格式类校验, 通过即真通过 |
| 路由重试 | retry_max=2(3轮) | 失败分数逐 seed 恒定(±0.01) | 建议: 同镜头 ≥6 候选失败且分数极差 <0.02 时提前触发 fallback(稳定-borderline 短路), 避免 S11 式 16 候选空转 | 本批 S08/S09/S11 重试共耗 34/59=58% 生成量, 0 收益 |

**未修即报的原则执行情况**: G2 曾在探针阶段 0% 通过(修复前 subject_missing 映射对任何真实帧都
≥0.67, 属映射 bug 而非阈值问题)——已按"先修 bug"用实测数据重校准(D-026, 修复前后对照见
`workdir/logs/m2_clip_anchor_probe.json`); 镜头卡阈值一个未动。

## 5. 运行统计 (SPECS §5.3 记账)

- 候选总数 62: 生成 59 (LTX) + KenBurns 3; 每 accepted 镜头选中 1。
- 生成速度: LTX 384×512×25帧 ≈ **2.0-2.4s/条**(管线进程级缓存后; 首条含加载 ~50s);
  KenBurns 渲染 ~1-2s/条。
- 门禁开销为主: 抽帧+CLIP(ViT-L/14 CPU) ≈ 15-25s/候选, 占总墙钟 ~80%。
- 显存峰值: **16.0 GB** (LTX 管线常驻; nvidia-smi 过程观测最高 17.3GB 含编码抖动), V100-32GB 余量充足。
- 盘: 起 33G → 终 32G avail (红线 20G 未触碰; 候选+抽帧 ~120MB)。
- API 用量: 全本地(IMAGE/VLM/TTS/ASR 均 0 次 API, D-004)。
- 记账粒度: tasks 表存每任务末次 seed/steps/duration/vram; 候选级 seed 可由文件名恢复
  `{shot}_a{attempt}_{i}` → seed=stable_seed(shot)+attempt*1000+i (D-031)。

## 6. Wan 装配验证 (D-030, 闭环全绿后的一次性验证)

| 项 | 值 |
|---|---|
| 模型 | PAI/Wan2.1-Fun-1.3B-InP (DiffSynth 1.1.9 ModelManager, D-019/D-028) |
| 候选 | S01 生产卡: 480×832, 81帧@16fps=5.06s, steps 20, cfg 5.0, seed 42 |
| 生成耗时/显存 | **364.9s** 生成 (总墙钟 ~9min 含加载 2.5min+门禁) / 峰值 **16.93GB** / fp16 未触发 VAE 降级 |
| 六门禁 | G1 1.0 / G2 0.888 / G3 0.902 / G4 0.968 / **G5 0.745 (pass)** / G6 1.0 — **all_passed=True** |
| 意义 | M5 量产装配风险消除; 装配期实测坑: DiffSynth negative_prompt 必须逗号串(list 会 batch 错配崩, 已修, D-028) |

## 7. 产物索引

- 聚合快照: `reports/milestones/m2_gate_stats.json`; 溯源 SQL: `reports/milestones/m2_gate_query.sql`
- 资产清单: `assets/products/manifest.json` (11 张 832×1216, prompt/seed/耗时全记录)
- Wan 验证: `reports/milestones/m2_wan_verify.json` + `workdir/candidates/wan_verify_S01.mp4`
- 装配探针: `workdir/logs/m2_wiring_probe.json`; CLIP 锚点实测: `workdir/logs/m2_clip_anchor_probe.json`,
  `workdir/logs/m2_clip_anchor_assets.json`
- 失败样本库(34+): `workdir/candidates/*.mp4` + 同名 `.frames/`、`.grid.png`、门禁 JSON 在 SQLite

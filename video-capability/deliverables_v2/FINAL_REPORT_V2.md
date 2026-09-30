# PROJECT CRADLE 2.0 最终报告 (FINAL_REPORT_V2)

- 日期: 2026-09-09 | 仓库: `~/cradle` @ V2-M5 commit (基线 f2773de, tag v2.0) | 任务书: `SPECS_V2.md`
- 执行: 主控 + 子代理流水线 (V2-M0 / V2-M12 / V2-M3 → ⚠ 静默死亡 → V2-M3C 接棒 / V2-M4 / V2-M5), 全程无人值守、未向用户提问
- 决策: `DECISIONS.md` D-051..D-074 | 过程: `PROGRESS.md` V2 时间线 | 里程碑报告: `reports/milestones/`
- ⚠️ **口径声明 (沿袭 v1 D-004 标注义务)**: 全程无 API —— G7e(VLM 成对审讯)全部 skipped 不做假实现; G2/G5 仍为 CLIP ViT-L/14 本地启发式判分 (v1 口径沿用); 生成/TTS/ASR/门禁全本地, **API 调用 0 次**。

---

## 0. 两个头条数字 (校准终版重跑, 47/47 真实 GPU)

> **夹具拦截率 100%**: 15 条人类目检确证的形变夹具(v1 的"克苏鲁废片"), G7 全部拦截 —— **15/15 = 100%** (要求 ≥90%)。
>
> **误杀率**: pass_structural(程序性产物)误杀 **0/15 = 0%** (要求 ≤15%); pass_candidate(真实生成候选)误杀 **4/17 = 23.5%** (要求 ≤25%, 带内)。
>
> 一句话原则: **不对称原则 = 宁可误杀, 不可漏网** —— 漏掉一条形变就是一条"虾仁融成糊浆"的废片进成片(v1 实证: 15 条形变中 8 条曾 pass、6 条曾入选成片); 误杀一条好片的代价只是重生成一次。因此工作点选在拦截率打满、误杀压线带内的位置, 且被误杀的 4 条全部交人工复核。

### ⚠ 本轮唯一人工动作 (请最先处理)

**`reports/fixtures/CONFIRMATION.md` — pass_candidate 确认清单 17 条**(A 组 13 条系统判过请确认 + B 组 4 条系统判杀请复核: FX-C001/C002/C003 毛肚沸腾特写、FX-C010 夜景 churn)。逐条回复一句话即可。终版索引(47 条全库): `reports/fixtures/INDEX.md`。

### 生产期旁证

9 片成片 25 候选 G7 全过 **0 触发**(score ∈ [0.9758, 0.9983], 子项最低 a=d=0.9515, 阈 0.82/0.84); 21 帧目检 0 形变; **主控 VLM 抽帧终检通过**(v2_t1_seeding_v2: 毛肚形状自然/蒸汽豁免生效/字幕正确/数字只在字幕)。

---

## 1. G7 五子项分数分布与推荐阈值 (校准 = 把调阈值变成计算题)

### 1.1 分数分布(图: `reports/fixtures/`, 全部出自 47 夹具 × 两轮真实 GPU 运行)

| 图 | 内容 | 结论 |
|---|---|---|
| `g7_dist_d.png` | G7d 首尾全帧余弦 | fail ≤0.8365 vs struct ≥0.949, **间隔 0.11 零重叠** —— 主工作子项 |
| `g7_dist_a.png` | G7a 跨步余弦(bbox/full 双口径) | full 口径 fail ≤0.8365 vs struct ≥0.949 零重叠; bbox 口径被检测框抖动劣化(D-059) |
| `g7_dist_c.png` | G7c 静态区光流 P95 | fail ∈[4.3, 98]px vs 候选 ∈[0.17, 25.7]px 重叠大 —— 只能作灾难级安全网 |
| `g7_dist_b_churn.png` | G7b churn(离线重放 det=0.30) | fail 与候选均高(GDINO 稀疏帧抖动), 单子项不可分, 定版只抓极端 |
| `g7_roc_a/c/d.png` | 子项阈值扫描 ROC | 帕累托段与工作点依据(见 `reports/G7_CALIBRATION.md` §2) |

### 1.2 推荐阈值表(冷启动 → 校准后; `config/thresholds_v2.yaml`, calibrated: true)

| 键 | 冷启动 | **校准后** | 依据 |
|---|---|---|---|
| g7a_mode | bbox | **full** | 检测框逐帧抖动拉低 bbox 余弦可分性(fail max bbox 0.901 vs full 0.8365); 双口径序列均落盘可复查(D-059) |
| g7a_min_cos | 0.75 | **0.82** | struct min 0.949; ROC 帕累托段内收紧不增拦截 |
| g7d_min_cos | 0.75 | **0.84** | fail max 0.8365 vs struct min 0.949 间隔 0.11; 阈 0.84 时漏网 0%/struct 误杀 0%/候选误杀 3/17 —— 帕累托最优 |
| g7b_count_delta_tol | 2.0 | **4.0** | GDINO 稀疏采样计数抖动大(F012 虾 9→15+ 仅稳定检出 1-2 框) |
| g7b_count_var_max | 4.0 | **100.0** | 同上, 宽容口径只抓极端 |
| g7b_churn_max | 3.0 | **12.0** | 冷启动 3 对夜景/液体检测闪烁过敏感(误杀 4 条候选), 判为检测器噪声而非形变信号 |
| g7c_flow_p95_max_px | 0.5 | **30.0** | 0.5px 冷启动口径是初跑候选误杀 16/17 的主因; 0.33s 采样对口径下中间阈值无帕累托点(4px 拦 15/15 但误杀候选 ~9 条), 定版灾难级安全网: 抓 object_flow/count_drift 4 条, 候选组零误杀(max 25.7px) |
| g7e_min_ok | 0.6 | 0.6 | 规格定死; 无 API 全 skipped(D-004, 不做假实现) |
| det_box_threshold / det_high_thresh | 0.30 / 0.35 | 0.30 / 0.35 | 运行期过滤口径(检测器以 0.25 低门槛推理) |

**校准方法与结果**: 冷启动初跑全量落盘逐帧原始检测 → 1288 组合×阈值栅格**离线重放**(GPU 零重跑) → 按(结构误杀→漏网→候选误杀)字典序选工作点 OP1 → 终版重跑逐条吻合。规格上限 3 轮, **实际 1 轮达标**; 进一步收严只会牺牲拦截稳健性, 按不对称原则不做。镜头卡 acceptance 增补键为可选字段(17 张存量卡零返工), 生产缺省从 thresholds_v2.yaml 读取。

---

## 2. 三车道: 设计逻辑与良率

### 2.1 设计逻辑 —— 食物形变的根源是"让生成模型画食物", v2 直接不让它画

| 车道 | 用途 | 机制 | 对形变的处理 |
|---|---|---|---|
| **compositing_2d5** | 食物/产品镜头默认车道 | 全纯代码确定性渲染: Depth-Anything 深度分层(前景 ≥65 分位)→羽化→双层视差运镜(5 种 preset)→overlay screen 混合 | **食物不参与生成, 形变被物理性消灭**; 底片=SDXL 产品图, 运镜只是确定性像素变换 |
| **pure_gen_short** | 环境氛围专用 | 时长压缩 1-2s + 固定机位 prompt + 反形变 negative 词表 + Fun-InP 原生 end_image 首尾锚定(末帧=首帧资产) | 食物 subject 由 schema 红线**硬性拒绝**(`_validate_lane_rules`); 首尾锚定下静态区光流实测 0.503px(S09) —— 几何锁定有效 |
| **evidence_transfer** | 证据转移演示 | 均匀采样 4k+1 帧 → WanVideoPipeline 低强度重绘 denoise 0.30, input_video(噪声底)+input_image(源首帧 y 条件)**双条件**(D-065) | 重绘贴源, 结构保持度量化背书(§4) |
| ken_burns(保留) | 手部高风险卡(S12) | 确定性 zoompan | 构造上不可能形变 |

镜头卡映射(D-063): 19 卡 = comp 10 + puregen 6 + evidence 2 + ken_burns 1; S15(红汤锅底)按 §5.2 红线从环境组裁定归 comp。编排接入(D-062): 确定性车道 n_best 视为 1; `WAN_CONSUMING_LANES` 预算守卫口径。

### 2.2 良率(M4 量产, 沙箱 /root/cradle_v2m4, 9 模板片 × 3 变体)

| 车道 | 任务 | accepted | 候选 | pass | Wan 候选 |
|---|---|---|---|---|---|
| compositing_2d5 | 10 | 10 | 10 | 10 | **0**(确定性) |
| pure_gen_short | 6 | 6 | 12 | 12 | 12(n_best=2 全过) |
| evidence_transfer | 2 | 2 | 2 | 2 | 2 |
| ken_burns | 1 | 1 | 1 | 1 | 0 |
| **合计** | **19** | **19** | **25** | **25** | **14** |

- 任务级/候选级良率均 **100%**, 首轮零重试/零短路/零 fallback/零 blocked。
- M3 实测基线(S01/S09/S18 全链 G1-G7 accepted)与 M4 量产同卡分数**逐位一致**(0.9604/0.9451/0.9613) —— 确定性车道跨沙箱可复现。
- 成片 9/9: v2_t1×3(30.0s, 5comp+3pure+1evd) / v2_t2×3(28.5s, 4+4+1) / v2_t3×3(28.5s, 4+3+1), 全部 1088×1920 h264+aac, 每片恰 1 个 evidence 演示镜头, 时长与模板逐秒一致; ASS 逐字 9/9; 变体差异化=选角+numbers(价格数字只在字幕, D-015 复查成立)。

---

## 3. v1/v2 全量对比 —— 核心指标: 食物镜头形变率(人类可辨形变片段占比)

### 3.1 形变率

| 指标 | v1(first_frame_i2v 食物车道) | **v2(三车道)** |
|---|---|---|
| 候选池 | 122 条全池(主仓 62 + 沙箱 60; DINO 全池粗筛+逐条目检) | 25 条本轮全量(食物相关 12 = comp 10 + evidence 2) |
| 人类可辨形变 | **15 条**(fluid_melt 8 / split_merge 3 / count_drift 2 / object_flow 2)= **全池 12.3%**; 按 Wan 生产候选 60 条口径 **25%** | **0 条**(G7 全过 + 21 帧目检 0 例外 + 主控 VLM 抽检, 如实记录) |
| 其中曾过 v1 全部门禁 | 8 条(verdict=pass 仍形变) | — |
| 其中曾入选成片/AB | 6 条 | 0 |
| 典型案例 | FX-F001 虾仁 9 只→融为糊浆; FX-F005 红油溢锅成滩; FX-F009 锅面化为红泥浆 | 无 |
| 机制根因 | Wan 自由生成食物本体, 首帧锚定约束不了中后帧 | 生成器只画环境/氛围; 食物本体来自确定性 2.5D 合成或 denoise 0.30 低强度重绘 |

### 3.2 良率 / 耗时 / 预算

| 项 | v1 | v2 | 说明 |
|---|---|---|---|
| 生产任务良率 | 17/17 (100%) | **19/19 (100%)** | 两代均首轮通过 |
| 候选良率 | 48/50 (96%) | **25/25 (100%)** | v1 有 2 条 G5 边缘被杀 |
| 门禁 | 六门禁(G1-G6) | 七门禁(G1-G7), 生产 0 触发 | G7 为 v2 新增物体恒存门禁 |
| 成片 | 9 条(25/22/17s) | 9 条(30/28.5/28.5s) | v2 单片更长且每片含 1 个证据镜头 |
| Wan 调用 | 60/200 | 本轮 14(**全局累计 92/200**) | v2 确定性车道 11/19 零 Wan |
| API 调用 | 0 | **0** | 全本地兜底链 |
| 生成+门禁墙钟 | 量产 305.2min(17 任务, 全 Wan 链) | **31.5min(19 任务)** | 口径不可直接比: v2 的收益恰在三车道设计 —— 确定性车道无生成成本、puregen 素材 1-2s |
| 合成墙钟 | 6.5min/9 片 | 9.7min/9 片(含 TTS/ASS/BGM/G6 双级校验) | 同量级 |
| 失败画廊 | 24 例(G5 偏差型) | 漏网 0; 拒绝侧 8 例(`gallery_failures_v2/`) | v2 画廊构成见 §6-4 |
| pytest | 226 passed | **309 passed** | 收尾复测 309 全绿 |
| 显存峰值 | 23.76GB/32GB | 16.6GB/32GB(puregen 16425 / evidence 16586MB) | v2 更低(短素材+小分辨率重绘) |

---

## 4. 合成源验证 / API 用量

### 4.1 合成源结构保持度(SPECS_V2 §5.4 必做, D-068)

合成测试源 = 静态图 + 程序 zoompan(1.00→1.06)+ 确定性匀速粒子(**运动 GT 已知**) → denoise 0.30 双条件重绘 → RAFT-small fp32 光流(6 对相邻采样帧)+ Depth-Anything 深度图:

| 源 | flow_cos | flow_pearson | epe(px) | depth_corr(首/末) |
|---|---|---|---|---|
| 合成源 01(虾滑盘) | **0.9177** | 0.9455 | 0.115 | 0.9997 / 0.9996 |
| 合成源 02(毛肚盘) | **0.9616** | 0.9754 | 0.086 | 0.9998 / 0.9992 |
| 正控: 源 01 重编码副本(应≈1) | 0.9690 | — | — | — |
| 负控: 源 01 vs 异运动 kenburns(应≈0) | 0.0464 | — | — | — |

**判定**: 重绘 flow_cos **0.92-0.96 落在正控带内**(≥正控的 95%), 高于负控约 20 倍, 深度骨架相关性 ≈1.0 → 结构保持度过关, denoise=0.30 维持生产缺省。数据: `workdir/logs/v2m3_evidence_validation.json`。

### 4.2 API 用量

**API 调用 0 次**(v1+v2 全程)。本地路由记账: v1 两库 230 次(vlm 119 + tts 111); v2 期新增 183 次(cradle_m3 4 + cradle_v2m4 179, TTS/ASR/VLM 全 local); 全项目累计 413 次调用 route=local, API 预算零消耗(各库 api_usage 表实测)。

---

## 5. DECISIONS 增量索引 (D-051..D-074, 全文见 `DECISIONS.md`)

| # | 一句话 |
|---|---|
| D-051 | 磁盘治理 3.3G/8G 目标偏差(授权+可再生范围内已穷尽) |
| D-052 | 夹具库判定口径(DINO 粗筛 122/122 → 三联帧目检; 47 条; 不对称原则收录 borderline) |
| D-053 | 夹具媒体 32.1MB 全量随 git 入库(<50MB 门槛, 克隆即看) |
| D-054 | G7 模型选型与 Volta 自查(GDINO 必须 fp32+autocast-fp16; RAFT fp32) |
| D-055 | v1 可运行性验证(51s 全链全绿, pytest 226) |
| D-056 | G7 实现口径(16 帧采样/LiteByteTracker/词表激活/SAM 反选静态区/全量落盘可离线重放) |
| D-057 | G7 挂链兼容(六门禁不动, g7_runs 表, cli g7-fixtures) |
| D-058 | 夹具词表映射(pass_structural 一律 terms=[]) |
| D-059 | **G7 校准定版 OP1**(拦截 100%/误杀 0%/23.5% 带内; a_mode=full; resolve_thresholds 优先级修复) |
| D-060 | (补记) 三车道生成路径侦察(vid2vid 路径①/首尾锚定路径 a/纯代码 comp) |
| D-061 | 前手空号, 保留跳过 |
| D-062 | (补记) 编排接入口径(schema v4/确定性车道 n_best=1/WAN_CONSUMING_LANES) |
| D-063 | (补记) 19 卡映射(S15 红线裁定归 comp) |
| D-064 | (补记) overlay 审计豁免设计稿(动态本体不算缺陷, 审计静态暗底) |
| D-065 | vid2vid 运行时修正: input_video+input_image 双条件(Fun-InP has_image_input 要求), 路径①维持 |
| D-066 | overlay 审计口径 v2(masked 静态区 DINO + 时间最大亮度 mask + 低纹理光度/SSIM 复核, fail-closed) |
| D-067 | 预算守卫被三车道提前 return 绕过(真 bug)→ 前置修复 + 3 测试定性与修复 |
| D-068 | 合成源结构保持度结论(flow_cos 0.92-0.96 正控带内, denoise=0.30 维持) |
| D-069 | overlay 限域/亮化重生成 ×2; **G7 集成链假绿修复**(_run_g7 注入模型 fn) |
| D-070 | v2 叙事模板投放机制(narrative_v2 → narrative/ 原 id 复制) |
| D-071 | 新增第三叙事模板 offer_lead_28s_v2 |
| D-072 | M4 沙箱 Wan 硬守卫 120(全局红线 200) |
| D-073 | whisper-medium.pt(1.5G)保留(avail 28G > 20G 红线, 供后续 CER 复核) |
| D-074 | V2-M5 收尾口径(确认清单/gallery_v2 组织/终报入口/tag v2.0) |

---

## 6. 诚实披露(全部有产物佐证, 不粉饰)

1. **G7e(VLM 成对审讯)无 API, 校准与生产全程 skipped**(vlm_unavailable): 豁免提示词已落盘(`src/gates/g7_vlm_prompt.txt`), API 可用后自动并入(权重 0.25); 不以 CLIP 启发式冒充成对审讯(D-004 惯例)。v2 产物质量的人眼兜底 = M0/M3 逐条目检 + M4 21 帧目检 + **主控 VLM 抽帧终检**(v2_t1_seeding_v2 通过)。
2. **G7 集成链假绿 bug(已修复)**: orchestrator 门禁链自 V2-M1 挂链起未注入 G7 模型 fn → 集成链 G7 全子项 skipped 空转、score 恒 1.0(假绿)。V2-M3 三车道实测暴露, 修复(`_run_g7` 注入 default_* fns, 与校准链同款)后重跑 —— **校准结论不受影响**(校准链 run_fixtures 一直有注入), M3 实测与 M4 生产的 G7 分数均为修复后真实值。决策编号口径: 该修复记于 D-069 尾段; 同期另一真 bug(预算守卫被三车道提前 return 绕过)为 D-067。v1 沿革的 G2/G5 CLIP 启发式口径同此披露(未经 API VLM 审核)。
3. **overlay 素材审计 3/6 过审**: 蒸汽/雾/光斑三类各 ≥1 可用(steam_thin/mist_cool/light_warm), 浓雾与暗粒子类的失败属素材类型与"不污染底片"要求的**固有张力**, 未放宽口径(不对称原则); 明细与物理解释见 `reports/gallery_failures_v2/`。
4. **首轮 100% 良率 → 产线无被杀样本**: retry/短路/fallback/G7 杀候选等负样本路径本轮无产线实例(行为正确性由 309 项 pytest + M3 实测背书)。因此 `gallery_failures_v2/` 的素材来源 = **G7 校准期判杀的 4 条 pass_candidate + overlay 审计 FAIL 4 例(判定 5 次/物理文件 3 个)**, 并如实声明"本轮漏网=0"。
5. **evidence 演示镜头使用合成测试源, 非真实实拍**(zoompan+确定性粒子, 运动 GT 已知 —— 这是结构保持度可量化的前提); 片内已按"演示源"标注; 用户实拍激活路径: `assets/evidence/README.md` + 本轮 README 增补"指南五"。
6. **CER medium 复核 6/9 ≤5%**(small 口径 5/9), 差集全部为 ASR 同音字混淆(手作/手做、红汤/红糖等) —— 交付字幕 ASS 逐字硬校验 9/9 为准, 生产 ASR 口径不改(D-036/D-047 惯例)。
7. **两次代理静默死亡与接棒**(如实记录, 详见 PROGRESS V2 时间线): v1 期 M5-PROD 死于成片合成启动前(M5-CONT 接棒); v2 期 V2-M3 死于三车道代码写完、运行时验证前(V2-M3C 固化 WIP commit `1d3c3cb` 后接棒, 修出并修复 G7 假绿与预算守卫两个真 bug)。09-09 07:5x 起建立双端巡检自动化(>90min 无变化即判僵死→固化→派接棒)。

---

## 7. 交付物对照 (SPECS_V2 §7)

| §7 项 | 要求 | 交付 | 状态 |
|---|---|---|---|
| 1 | FINAL_REPORT_V2.md | 本报告(头条数字置顶/分布图/阈值表/三车道良率/v1-v2 对比/合成源/API/决策增量/披露) | ✅ |
| 2 | output/ 8-10 条三车道混合成片 | `output/v2_t{1,2,3}_*_v{1..3}.mp4` 9 条(comp+pure+evd 混合, 每片 1 个 evidence 镜头; 媒体不入 git, 台账/ffprobe/沙箱原件齐全) | ✅ |
| 3 | reports/fixtures/ 索引 + pass_candidate 清单 | `reports/fixtures/INDEX.md`(47 条终版, 脚本自动生成) + `CONFIRMATION.md`(17 条: A 13 + B 4 判杀复核) | ✅ 待用户一句话 |
| 4 | reports/gallery_failures_v2/ | 8 例(overlay 审计 FAIL 4 + 校准判杀 4) + INDEX.md, 漏网=0 如实声明 | ✅ |
| 5 | README 增补证据车道激活指南 | README"指南五: v2 三车道与 G7 门禁"(实拍视频格式/时长/竖拍建议→evidence_asset→自动激活) | ✅ |

## 8. §9 自检清单逐项核证

| # | 项 | 结果 | 证据 |
|---|---|---|---|
| 1 | 夹具库 ≥35 条且四类形变覆盖 | ✅ 47 条(fluid_melt 8/split_merge 3/count_drift 2/object_flow 2) | `reports/fixtures/INDEX.md`; `workdir/fixtures/fixtures_manifest.json`; DB fixtures 表 47 行 |
| 2 | G7 fail 拦截 ≥90%、pass_structural 误杀 ≤15% | ✅ 15/15=100%、0/15=0%(候选误杀 23.5% 带内) | `workdir/logs/v2m1_g7_final.json`; `reports/G7_CALIBRATION.md`; `config/thresholds_v2.yaml` |
| 3 | 三车道各 ≥1 条镜头实测 | ✅ S01 comp / S09 puregen×2 / S18 evidence 全链 G1-G7 accepted | `workdir/logs/v2m3_lane_shots.json`; `reports/milestones/V2_M3_lane_report.md` §6; 媒体 `reports/milestones/v2m3_media/` |
| 4 | 8-10 条成片 | ✅ 9 条 30.0/28.5/28.5s, 1088×1920, ASS 逐字 9/9 | `output/v2_t*.mp4`; `reports/milestones/v2m4_data/v2m4_ffprobe.json`; `reports/milestones/V2_M4_production_report.md` §1 |
| 5 | 合成源结构保持度有量化数据 | ✅ flow_cos 0.9177/0.9616 vs 正控 0.969/负控 0.0464 | `workdir/logs/v2m3_evidence_validation.json`; D-068 |
| 6 | pass_candidate 清单待用户确认 | ✅ 清单已交付, **确认状态=待用户** | `reports/fixtures/CONFIRMATION.md`(17 条) |
| 7 | v1/v2 形变率对比入报告 | ✅ 12.3%(全池)/25%(Wan 生产口径) → 0 | 本报告 §3.1; 原料 `reports/V2_M0_AUDIT.md` §4.3 + `reports/milestones/v2m4_data/v2m4_stats.json` |
| 8 | README 证据车道指南 | ✅ 指南五(实拍格式/时长/竖拍建议/evidence_asset/自动激活) + 夹具回归方法 | `README.md` |
| 9 | 全程 DECISIONS 记录 | ✅ D-051..D-074(24 条, 无凭记忆引用) | `DECISIONS.md` |
| 10 | git 历史干净 | ✅ status 干净; 线性 commit 链; tag v2.0 | `git status`/`git log`/`git tag`(见 PROGRESS V2-M5 节) |

## 附录: v2 报告链

`reports/V2_M0_AUDIT.md`(审计+夹具库) → `reports/milestones/V2_M1_g7_initial_scores.md`(G7 实现+冷启动) → `reports/G7_CALIBRATION.md`(校准) → `reports/milestones/V2_M3_lane_report.md`(三车道验证) → `reports/milestones/V2_M4_production_report.md`(量产) → 本报告。夹具终版索引 `reports/fixtures/INDEX.md`; 拒绝侧档案 `reports/gallery_failures_v2/INDEX.md`。

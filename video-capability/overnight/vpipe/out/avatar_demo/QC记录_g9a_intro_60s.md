# G9a 口播专线演示 QC 记录 — g9a_intro_60s@vidu-s1（2026-09-30）

> 检查人：本会话（铺设-口播专线 actor）。被检片：`overnight/vpipe/out/avatar_demo/g9a_intro_60s@vidu-s1.mp4`
> （61.0s，826×1114 竖屏 24fps，h264+aac，sha256 `edf440436ca7637927d0db5b746a2af49f377a44e65ce3413f266cfb0cdb7676`，
> Vidu task_id `1002818273143713792`，credits=61，watermark=false）。
> 依据：任务指示「过一遍 J6v2 时序检测 + 目检记录」；红线继承：时序结论不作自动放行依据（工程方案v3.1 §2.3）。

## 1. J6v2 时序检测（程序化，`qc_detectors_v2.py`，参数=eval/thresholds.yaml `J6_detectors_v2`）

命令：`python src/qc_detectors_v2.py --clip out/avatar_demo/g9a_intro_60s@vidu-s1.mp4 --out out/avatar_demo/g9a_intro_60s@vidu-s1.qc2.json --params-yaml eval/thresholds.yaml`

| 项 | 结果 |
|---|---|
| 输入 | 1464 帧 @24fps，61.0s |
| 判定 | **detected=true，ghosting，conf 0.627**（唯一候选；无被拒候选） |
| span | 55.75–57.25s（diff_dip 支，dip_ratio 0.587，boundary_ratio 1.69，dur 1.5s） |
| 其余三类 | frame_freeze / flicker / temporal_swap 均未触发 |

## 2. 目检（帧证据 `out/avatar_demo/mc_*.jpg`，视觉模型逐帧复核）

| 检查点 | 证据 | 结论 |
|---|---|---|
| ghosting span 复核（55.75–57.25s） | `mc_strip_ghost_span.jpg`（8 帧）+ `mc_ghost_dense.jpg`（**逐帧 37 帧全量**） | **误报**：全部帧人脸/五官锐利、无重影/双重曝光/残影；眨眼完整、口型开合连续、手势自然。**判定依据 = 该 span 逐帧 100% 目检，非抽样** |
| 误报机理解释 | silencedetect：音频静音 55.73–56.87s（1.131s 句间停顿）与 ghosting span 逐点重合 | 停顿期人脸低运动 → 帧差凹窗被 rect_dip 误读为混叠。**机理 #1 第 3 例实证**（工程方案v3.1 §3.4-1：数字人实验报告 2/2 → 本轮 3/3） |
| 身份一致性（头/中/尾） | `mc_3key.jpg`（0.5s/36s/60.4s 三帧） | 同一人（齐肩黑直发+红裙+同背景），无身份漂移（目检级；ArcFace 定量未装机，如实标注） |
| 面部/手部/穿模 | 同上 + ghost span 逐帧 | 无面部畸变、五指正常、无穿模 |
| 口型活动（20–26s 段） | `mc_strip_mid.jpg`（10 帧） | 闭合→张开→闭合完整周期，与说话节奏吻合，无口型冻结 |
| 水印 | 同上全帧 | 无可见水印/logo（watermark=false 生效） |

## 3. 确定性补检（CPU 脚本）

| 检查 | 结果 | 判定 |
|---|---|---|
| 流完整性（ffprobe） | h264 826×1114 24fps + aac，有音轨 | ✓ |
| 音视频时长差 | 61.0 − 60.216 = **+0.784s** | 平台整秒取整垫尾（≤1s，L0 豁免口径，工程方案v3.1 §3.1）✓ |
| 嘴部 ROI 帧间差（`dh_lipcheck.py`，ROI 0.42,0.30,0.60,0.38 本片目检标定） | mean 4.816 / median 3.958 / p90 9.214；静止帧占比 11.7%（对照昨夜合格片 21.9–26.5%，更活跃） | ✓ 无口型失效 |
| 最长口型静止连跑 | 17 帧=0.708s @38.33–39.04s | **与音频静音 38.20–39.35s 重合**（句间停顿），非「该动不动」失效 ✓ |
| 嘴动-静音全量对照 | top-5 静止段（38.33/60.12/56.17/24.62/49.83s 起）**全部**落在 silencedetect 静音区间内（60.12 段=尾部垫静音） | ✓ 嘴动严格跟随语音 |
| 音频活性（volumedetect） | mean −16.4dB / max −0.4dB，语音净长约 52s（总静音 ~9s 分布 21 处句间停顿） | ✓ 非静音轨；克隆音色继承源语音 ~1.1s 长停顿节奏（听感未做人耳盲测，如实标注） |

## 4. qc_orch 钩子（gen_meta → 在线质检）

命令：`python src/qc_orch.py --online --clip-id g9a_intro_60s --clip out/avatar_demo/g9a_intro_60s@vidu-s1.mp4 --judge-file J6=out/avatar_demo/g9a_intro_60s.j6v2_protocol.json --thresholds eval/thresholds.yaml --out out/avatar_demo/g9a_intro_60s.qc_report.json`

- 报告 `out/avatar_demo/g9a_intro_60s.qc_report.json`：verdict `pass`（E10=J1∨J3@0.70 未触发——**本轮未跑 J1/J3**，该 pass 只表示合议层无信号，**不是时序放行**）；J6v2 协议（detected=true, ghosting, conf 0.627）原样嵌入 `judges.J6` 可追溯。
- 契约校验：剥离 `evidence_rule_status` 键后**全过** QCReport schema。该键是 qc_orch 在线模式的既有附加（qc_orch.py:651，回放模式不加，故 eval 40/40 过校验）——**如实记录为既有边界，不擅改冻结模块**。
- judge 代码用 `J6`（非 `J6v2`）：qc_report schema `judges` 的 patternProperties 只收 `^J[1-7]$`；协议 JSON 内 notes/detector 字段已标明是 v2 检测器。

## 5. QC 结论（如实）

1. **成片可用**：身份一致、口型随语音、无面部/手部畸变、无水印、音画结构完整；60 秒口播目标达成（60.216s 语音 → 61.0s 成片）。
2. **J6v2 ghosting 检出=目检证伪**（逐帧 100% 复核 span 内无混叠），且span 与句间静音逐点重合——机理 #1（口播低运动平台误报）第 3 例，**维持 signal_only 定位正确**；若该规则升否决层将误伤口播线（与工程方案v3.1 §3.3/§3.4 结论一致）。
3. **两条可回填项**：① J6 v2「低运动平台豁免」实验（P0-1，已有 3 例证据）；② 金标扩口播类正例（§3.6）——本轮 61s 片可直接作为候选样本。
4. **目检边界如实**：检查止于帧级目检+确定性活动度量；未做人耳听感盲测、ArcFace 身份定量、SyncNet 音画同步打分（均未装机，与昨夜报告同一降级口径）。

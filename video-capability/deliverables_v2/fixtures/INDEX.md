# 回归夹具库索引 (V2-M5 终版)

> SPECS_V2 §2 / §7-3。构建口径 D-052, 媒体 git 口径 D-053。本文件由 `tools/m5v2_build_fixtures_index.py`
> 从 `workdir/fixtures/fixtures_manifest.json` + `workdir/logs/v2m1_g7_final.json` 自动生成(幂等), 数字不手抄。
> 物理文件: `workdir/fixtures/{fail,pass_structural,pass_candidate}/*.mp4`; 每夹具首/中/尾三联帧证据: `workdir/fixtures/strips/<fixture_id>.jpg`; 词表映射 `workdir/fixtures/g7_terms.json`。
> DB: 主仓 `workdir/cradle.sqlite3` 表 `fixtures`(47 行) 与 `g7_runs`(两轮×47×6 子项)。
> **⚠ 本轮唯一人工动作**: pass_candidate 确认清单 → **[CONFIRMATION.md](CONFIRMATION.md)** (17 条逐条回复, 其中 4 条被 G7 判杀请复核)。

## 统计自检 (SPECS_V2 §2 硬性指标)

| 组 | 数量 | 要求 | G7 终版判定(校准阈值) |
|---|---|---|---|
| fail | **15** | ≥15 | 拦截 **15/15 = 100.0%** (要求 ≥90%) |
| pass_structural | **15** | ≥10 | 误杀 **0/15 = 0.0%** (要求 ≤15%) |
| pass_candidate | **17** | ≥10 | 误杀 **4/17 = 23.5%** (要求 ≤25% 带内; 4 条列人工复核) |
| **总计** | **47** | ≥35 (M0 验收) | — |

## G7 终版运行口径

- 阈值: `config/thresholds_v2.yaml` (calibrated: true) — g7a_mode=full, a<0.82 / d<0.84 / b(delta>4.0, var>100.0, churn>12.0) / c P95>30.0px / e<0.6(VLM, 无 API 全 skipped, D-004)。
- 终版重跑: `workdir/logs/v2m1_g7_final.json` (47/47 真实 GPU); 校准过程/ROC/分布图: `reports/G7_CALIBRATION.md`。
- 判定语义: 任一子项触发即 fail(判杀); skipped 不判死(D-004/D-057)。

## fail 夹具 (15) — 四类形变, G7 终版全部拦截

全部为 v1 真实候选目检确证的形变; 其中 8 条曾 verdict=pass、6 条曾入选成片/AB(V2_M0_AUDIT §4.3)。

| fixture | category | mp4 | 三联帧 | 源候选 | DINO 首尾 | G7 终版判定 |
|---|---|---|---|---|---|---|
| FX-F001 | fluid_melt | `workdir/fixtures/fail/FX-F001.mp4` | [strips](../../workdir/fixtures/strips/FX-F001.jpg) | SB_S17_60 | 0.3523 | **拦截✓** a 0.3862✗ · d 0.3862✗ |
| FX-F002 | fluid_melt | `workdir/fixtures/fail/FX-F002.mp4` | [strips](../../workdir/fixtures/strips/FX-F002.jpg) | SB_S17_58 | 0.4185 | **拦截✓** a 0.4313✗ · d 0.4313✗ |
| FX-F003 | fluid_melt | `workdir/fixtures/fail/FX-F003.mp4` | [strips](../../workdir/fixtures/strips/FX-F003.jpg) | SB_S03_18 | 0.4355 | **拦截✓** a 0.4921✗ · d 0.4921✗ |
| FX-F004 | split_merge | `workdir/fixtures/fail/FX-F004.mp4` | [strips](../../workdir/fixtures/strips/FX-F004.jpg) | SB_ABS03P_4 | 0.5156 | **拦截✓** a 0.5412✗ · d 0.5412✗ |
| FX-F005 | object_flow | `workdir/fixtures/fail/FX-F005.mp4` | [strips](../../workdir/fixtures/strips/FX-F005.jpg) | SB_S15_52 | 0.5493 | **拦截✓** a 0.6484✗ · c p95=44.1px✗ · d 0.6521✗ |
| FX-F006 | fluid_melt | `workdir/fixtures/fail/FX-F006.mp4` | [strips](../../workdir/fixtures/strips/FX-F006.jpg) | SB_S17_59 | 0.5605 | **拦截✓** a 0.5947✗ · d 0.5947✗ |
| FX-F007 | fluid_melt | `workdir/fixtures/fail/FX-F007.mp4` | [strips](../../workdir/fixtures/strips/FX-F007.jpg) | SB_ABS03L_3 | 0.5752 | **拦截✓** a 0.6237✗ · d 0.6237✗ |
| FX-F008 | fluid_melt | `workdir/fixtures/fail/FX-F008.mp4` | [strips](../../workdir/fixtures/strips/FX-F008.jpg) | SB_S02_14 | 0.5898 | **拦截✓** a 0.6337✗ · d 0.6337✗ |
| FX-F009 | fluid_melt | `workdir/fixtures/fail/FX-F009.mp4` | [strips](../../workdir/fixtures/strips/FX-F009.jpg) | SB_S15_53 | 0.6040 | **拦截✓** a 0.7215✗ · c p95=98.1px✗ · d 0.7652✗ |
| FX-F010 | split_merge | `workdir/fixtures/fail/FX-F010.mp4` | [strips](../../workdir/fixtures/strips/FX-F010.jpg) | SB_S02_16 | 0.6235 | **拦截✓** a 0.6169✗ · d 0.6741✗ |
| FX-F011 | split_merge | `workdir/fixtures/fail/FX-F011.mp4` | [strips](../../workdir/fixtures/strips/FX-F011.jpg) | SB_S15_54 | 0.7627 | **拦截✓** a 0.6008✗ · d 0.7622✗ |
| FX-F012 | count_drift | `workdir/fixtures/fail/FX-F012.mp4` | [strips](../../workdir/fixtures/strips/FX-F012.jpg) | SB_S03_17 | 0.8110 | **拦截✓** a 0.7937✗ · c p95=50.5px✗ · d 0.7937✗ |
| FX-F013 | fluid_melt | `workdir/fixtures/fail/FX-F013.mp4` | [strips](../../workdir/fixtures/strips/FX-F013.jpg) | SB_S02_15 | 0.6646 | **拦截✓** a 0.7388✗ · d 0.7388✗ |
| FX-F014 | count_drift | `workdir/fixtures/fail/FX-F014.mp4` | [strips](../../workdir/fixtures/strips/FX-F014.jpg) | SB_S03_19 | 0.7827 | **拦截✓** a 0.7952✗ · d 0.7952✗ |
| FX-F015 | object_flow | `workdir/fixtures/fail/FX-F015.mp4` | [strips](../../workdir/fixtures/strips/FX-F015.jpg) | SB_S04_20 | 0.8447 | **拦截✓** c p95=42.2px✗ · d 0.8365✗ |

## pass_structural (15) — 程序性产物, G7 终版零误杀

v1 真产物 4 + fallback 渲染 3 + kenburns 确定性再生成 8(共 11 条再生成口径见 D-052); 一律 terms=[](D-058)。

| fixture | category | mp4 | 三联帧 | 源候选 | DINO 首尾 | G7 终版判定 |
|---|---|---|---|---|---|---|
| FX-S001 | ken_burns | `workdir/fixtures/pass_structural/FX-S001.mp4` | [strips](../../workdir/fixtures/strips/FX-S001.jpg) | MAIN_S12_35 | 0.9619 | 通过✓ score=0.9614 (a 0.9585✓ · b skip(no_terms_or_detect_fn) · c skip(no_subject_or_mask) · d 0.9657✓ · e skip(vlm_unavailable)) |
| FX-S002 | ken_burns | `workdir/fixtures/pass_structural/FX-S002.mp4` | [strips](../../workdir/fixtures/strips/FX-S002.jpg) | MAIN_S08_56 | 0.9717 | 通过✓ score=0.9715 (a 0.9715✓ · b skip(no_terms_or_detect_fn) · c skip(no_subject_or_mask) · d 0.9715✓ · e skip(vlm_unavailable)) |
| FX-S003 | ken_burns | `workdir/fixtures/pass_structural/FX-S003.mp4` | [strips](../../workdir/fixtures/strips/FX-S003.jpg) | MAIN_S09_57 | 0.9741 | 通过✓ score=0.9738 (a 0.9738✓ · b skip(no_terms_or_detect_fn) · c skip(no_subject_or_mask) · d 0.9738✓ · e skip(vlm_unavailable)) |
| FX-S004 | ken_burns | `workdir/fixtures/pass_structural/FX-S004.mp4` | [strips](../../workdir/fixtures/strips/FX-S004.jpg) | MAIN_S11_62 | 0.9844 | 通过✓ score=0.9841 (a 0.9841✓ · b skip(no_terms_or_detect_fn) · c skip(no_subject_or_mask) · d 0.9841✓ · e skip(vlm_unavailable)) |
| FX-S005 | ken_burns | `workdir/fixtures/pass_structural/kb_beef_01_zoom_in_1.06.mp4` | [strips](../../workdir/fixtures/strips/FX-S005.jpg) | - | - | 通过✓ score=0.9878 (a 0.9878✓ · b skip(no_terms_or_detect_fn) · c skip(no_subject_or_mask) · d 0.9878✓ · e skip(vlm_unavailable)) |
| FX-S006 | ken_burns | `workdir/fixtures/pass_structural/kb_dessert_01_zoom_out.mp4` | [strips](../../workdir/fixtures/strips/FX-S006.jpg) | - | - | 通过✓ score=0.9778 (a 0.9778✓ · b skip(no_terms_or_detect_fn) · c skip(no_subject_or_mask) · d 0.9778✓ · e skip(vlm_unavailable)) |
| FX-S007 | ken_burns | `workdir/fixtures/pass_structural/kb_drink_01_pan_left.mp4` | [strips](../../workdir/fixtures/strips/FX-S007.jpg) | - | - | 通过✓ score=0.9882 (a 0.9862✓ · b skip(no_terms_or_detect_fn) · c skip(no_subject_or_mask) · d 0.9911✓ · e skip(vlm_unavailable)) |
| FX-S008 | ken_burns | `workdir/fixtures/pass_structural/kb_maodu_01_pan_right.mp4` | [strips](../../workdir/fixtures/strips/FX-S008.jpg) | - | - | 通过✓ score=0.9496 (a 0.9496✓ · b skip(no_terms_or_detect_fn) · c skip(no_subject_or_mask) · d 0.9496✓ · e skip(vlm_unavailable)) |
| FX-S009 | ken_burns | `workdir/fixtures/pass_structural/kb_shrimp_01_zoom_in_1.06.mp4` | [strips](../../workdir/fixtures/strips/FX-S009.jpg) | - | - | 通过✓ score=0.9878 (a 0.9878✓ · b skip(no_terms_or_detect_fn) · c skip(no_subject_or_mask) · d 0.9878✓ · e skip(vlm_unavailable)) |
| FX-S010 | ken_burns | `workdir/fixtures/pass_structural/kb_soup_01_zoom_out.mp4` | [strips](../../workdir/fixtures/strips/FX-S010.jpg) | - | - | 通过✓ score=0.9762 (a 0.9762✓ · b skip(no_terms_or_detect_fn) · c skip(no_subject_or_mask) · d 0.9762✓ · e skip(vlm_unavailable)) |
| FX-S011 | ken_burns | `workdir/fixtures/pass_structural/kb_back_view_01_pan_left.mp4` | [strips](../../workdir/fixtures/strips/FX-S011.jpg) | - | - | 通过✓ score=0.9765 (a 0.9765✓ · b skip(no_terms_or_detect_fn) · c skip(no_subject_or_mask) · d 0.9765✓ · e skip(vlm_unavailable)) |
| FX-S012 | ken_burns | `workdir/fixtures/pass_structural/kb_interior_01_pan_right.mp4` | [strips](../../workdir/fixtures/strips/FX-S012.jpg) | - | - | 通过✓ score=0.9715 (a 0.9709✓ · b skip(no_terms_or_detect_fn) · c skip(no_subject_or_mask) · d 0.9723✓ · e skip(vlm_unavailable)) |
| FX-S013 | ken_burns | `workdir/fixtures/pass_structural/kb_rain_window_01_zoom_in_1.06.mp4` | [strips](../../workdir/fixtures/strips/FX-S013.jpg) | - | - | 通过✓ score=0.9802 (a 0.9802✓ · b skip(no_terms_or_detect_fn) · c skip(no_subject_or_mask) · d 0.9802✓ · e skip(vlm_unavailable)) |
| FX-S014 | ken_burns | `workdir/fixtures/pass_structural/kb_storefront_01_zoom_out.mp4` | [strips](../../workdir/fixtures/strips/FX-S014.jpg) | - | - | 通过✓ score=0.9773 (a 0.9773✓ · b skip(no_terms_or_detect_fn) · c skip(no_subject_or_mask) · d 0.9773✓ · e skip(vlm_unavailable)) |
| FX-S015 | ken_burns | `workdir/fixtures/pass_structural/kb_table_01_pan_left.mp4` | [strips](../../workdir/fixtures/strips/FX-S015.jpg) | - | - | 通过✓ score=0.9490 (a 0.9490✓ · b skip(no_terms_or_detect_fn) · c skip(no_subject_or_mask) · d 0.9490✓ · e skip(vlm_unavailable)) |

## pass_candidate (17) — 真实生成候选, 其中 4 条被 G7 判杀

G1-G6 全绿的 v1 生产候选; **待人工确认**(唯一人工动作) → [CONFIRMATION.md](CONFIRMATION.md)。

| fixture | category | mp4 | 三联帧 | 源候选 | DINO 首尾 | G7 终版判定 |
|---|---|---|---|---|---|---|
| FX-C001 | generated_high_score | `workdir/fixtures/pass_candidate/FX-C001.mp4` | [strips](../../workdir/fixtures/strips/FX-C001.jpg) | SB_S01_11 | 0.7603 | 判杀✗ score=0.8926 (a 0.7852✗ · b churn=0✓ · c p95=9.8px✓ · d 0.7852✗ · e skip(vlm_unavailable)) |
| FX-C002 | generated_high_score | `workdir/fixtures/pass_candidate/FX-C002.mp4` | [strips](../../workdir/fixtures/strips/FX-C002.jpg) | SB_S01_12 | 0.7661 | 判杀✗ score=0.8840 (a 0.7679✗ · b churn=0✓ · c p95=13.1px✓ · d 0.7679✗ · e skip(vlm_unavailable)) |
| FX-C003 | generated_high_score | `workdir/fixtures/pass_candidate/FX-C003.mp4` | [strips](../../workdir/fixtures/strips/FX-C003.jpg) | SB_S01_13 | 0.7681 | 判杀✗ score=0.9116 (a 0.8229✓ · b churn=0✓ · c p95=10.5px✓ · d 0.8235✗ · e skip(vlm_unavailable)) |
| FX-C004 | generated_high_score | `workdir/fixtures/pass_candidate/FX-C004.mp4` | [strips](../../workdir/fixtures/strips/FX-C004.jpg) | SB_S10_39 | 0.8232 | 通过✓ score=0.9280 (a 0.8560✓ · b churn=1✓ · c p95=2.5px✓ · d 0.8560✓ · e skip(vlm_unavailable)) |
| FX-C005 | generated_high_score | `workdir/fixtures/pass_candidate/FX-C005.mp4` | [strips](../../workdir/fixtures/strips/FX-C005.jpg) | SB_S10_40 | 0.8643 | 通过✓ score=0.9420 (a 0.8841✓ · b churn=2✓ · c p95=3.8px✓ · d 0.8841✓ · e skip(vlm_unavailable)) |
| FX-C006 | generated_high_score | `workdir/fixtures/pass_candidate/FX-C006.mp4` | [strips](../../workdir/fixtures/strips/FX-C006.jpg) | SB_ABS11L_9 | 0.8286 | 通过✓ score=0.9318 (a 0.8636✓ · b churn=0✓ · c p95=25.7px✓ · d 0.8636✓ · e skip(vlm_unavailable)) |
| FX-C007 | generated_high_score | `workdir/fixtures/pass_candidate/FX-C007.mp4` | [strips](../../workdir/fixtures/strips/FX-C007.jpg) | SB_S14_51 | 0.8613 | 通过✓ score=0.9330 (a 0.8660✓ · b churn=0✓ · c p95=16.1px✓ · d 0.8660✓ · e skip(vlm_unavailable)) |
| FX-C008 | generated_high_score | `workdir/fixtures/pass_candidate/FX-C008.mp4` | [strips](../../workdir/fixtures/strips/FX-C008.jpg) | SB_S05_25 | 0.8643 | 通过✓ score=0.9275 (a 0.8530✓ · b churn=3✓ · c p95=1.9px✓ · d 0.8579✓ · e skip(vlm_unavailable)) |
| FX-C009 | generated_high_score | `workdir/fixtures/pass_candidate/FX-C009.mp4` | [strips](../../workdir/fixtures/strips/FX-C009.jpg) | SB_S05_23 | 0.8706 | 通过✓ score=0.9477 (a 0.8954✓ · b churn=2✓ · c p95=2.0px✓ · d 0.8954✓ · e skip(vlm_unavailable)) |
| FX-C010 | generated_high_score | `workdir/fixtures/pass_candidate/FX-C010.mp4` | [strips](../../workdir/fixtures/strips/FX-C010.jpg) | SB_S08_32 | 0.9844 | 判杀✗ score=0.9486 (a 0.9796✓ · b churn=14✗ · c p95=1.7px✓ · d 0.9818✓ · e skip(vlm_unavailable)) |
| FX-C011 | generated_high_score | `workdir/fixtures/pass_candidate/FX-C011.mp4` | [strips](../../workdir/fixtures/strips/FX-C011.jpg) | SB_S06_26 | 0.9834 | 通过✓ score=0.9913 (a 0.9811✓ · b churn=0✓ · c p95=14.6px✓ · d 0.9848✓ · e skip(vlm_unavailable)) |
| FX-C012 | generated_high_score | `workdir/fixtures/pass_candidate/FX-C012.mp4` | [strips](../../workdir/fixtures/strips/FX-C012.jpg) | SB_S13_47 | 0.9785 | 通过✓ score=0.9896 (a 0.9792✓ · b churn=7✓ · c p95=4.8px✓ · d 0.9792✓ · e skip(vlm_unavailable)) |
| FX-C013 | generated_high_score | `workdir/fixtures/pass_candidate/FX-C013.mp4` | [strips](../../workdir/fixtures/strips/FX-C013.jpg) | SB_ABS08P_8 | 0.9937 | 通过✓ score=0.9975 (a 0.9944✓ · b churn=6✓ · c p95=1.3px✓ · d 0.9957✓ · e skip(vlm_unavailable)) |
| FX-C014 | generated_high_score | `workdir/fixtures/pass_candidate/FX-C014.mp4` | [strips](../../workdir/fixtures/strips/FX-C014.jpg) | SB_ABS08L_7 | 0.9775 | 通过✓ score=0.9714 (a 0.9353✓ · b churn=11✓ · c p95=4.6px✓ · d 0.9540✓ · e skip(vlm_unavailable)) |
| FX-C015 | generated_high_score | `workdir/fixtures/pass_candidate/FX-C015.mp4` | [strips](../../workdir/fixtures/strips/FX-C015.jpg) | MAIN_S10_30 | 0.9980 | 通过✓ score=0.9980 (a 0.9947✓ · b churn=3✓ · c p95=0.2px✓ · d 0.9978✓ · e skip(vlm_unavailable)) |
| FX-C016 | generated_high_score | `workdir/fixtures/pass_candidate/FX-C016.mp4` | [strips](../../workdir/fixtures/strips/FX-C016.jpg) | MAIN_S04_11 | 0.9961 | 通过✓ score=0.9977 (a 0.9951✓ · b churn=1✓ · c p95=0.2px✓ · d 0.9958✓ · e skip(vlm_unavailable)) |
| FX-C017 | generated_high_score | `workdir/fixtures/pass_candidate/FX-C017.mp4` | [strips](../../workdir/fixtures/strips/FX-C017.jpg) | MAIN_S03_7 | 0.8428 | 通过✓ score=0.9216 (a 0.8432✓ · b churn=3✓ · c p95=14.8px✓ · d 0.8432✓ · e skip(vlm_unavailable)) |

## 图与数据索引

| 文件 | 内容 |
|---|---|
| `dino_scan_hist.png` | 全候选池 122 条 DINO 首尾余弦分布(M0 粗筛依据) |
| `g7_dist_a.png` / `g7_dist_d.png` / `g7_dist_c.png` / `g7_dist_b_churn.png` | G7 各子项分数分布(fail/struct/cand 三组) |
| `g7_roc_a.png` / `g7_roc_c.png` / `g7_roc_d.png` | 子项阈值扫描 ROC |
| `workdir/logs/v2m0_dino_scan.json` | 粗筛原始数据 |
| `workdir/logs/v2m1_g7_initial.json` / `v2m1_g7_final.json` | 冷启动初跑 / 校准终版重跑(逐帧原始检测全落盘) |
| `workdir/logs/v2m1_calibration.json` | 阈值扫描(1288 组合工作点全表) |
| `workdir/fixtures/fixtures_manifest.json` | 47 条机器可读清单 |


# vpipe 运行报告

> 生成于 2026-09-30T03:31:48，由 report.py@vpipe1.0 汇总。

## 1. 生成矩阵概览（来源：metadata.json）

- 通道：MiniMax Design 本机网关 http://127.0.0.1:8001（免鉴权）
- 终态记录：46 条 succeeded=46
- 含成片：46 条；缺成片：0 条
- 积分账目：baseline=247347 → end=233067，本次实扣 **14280**（上限 40000）
- 每条实扣：min=280 / max=280 / 合计=12880（46 条有记录）
- 种子控制实测：DTO 拒绝=False，决策=send_seed_with_verify(探测意外通过校验，已尝试取消；扣费风险≤224)
- 同种子双跑哈希结论：{}

## 2. QC 合议概览（来源：qc_reports/*.json）

- 报告数：40；检出 29；decided_by={'E10': 40}
- 处置分布：pass=11 manual_review=20 auto_reject=9
- 缺陷类型出现次数（defects 归并层，含信号）：
  - garble_text: 23
  - color_shift: 10
  - ghosting: 9
  - frame_freeze: 8
  - temporal_swap: 6
  - face_blur: 5
  - flicker: 5
  - hand_anomaly: 4
  - pixelate: 4
  - identity_drift: 4
  - count_error: 3
  - physics_error: 1

### 2.1 逐 clip 处置表

| clip | detected | decision | confidence | decided_by |
|---|---|---|---|---|
| golden_001 | False | pass | 0.0 | E10 |
| golden_002 | True | auto_reject | 0.98 | E10 |
| golden_003 | True | manual_review | 0.8449 | E10 |
| golden_004 | True | manual_review | 0.9 | E10 |
| golden_005 | True | manual_review | 0.8 | E10 |
| golden_006 | False | pass | 0.0 | E10 |
| golden_007 | True | manual_review | 0.75 | E10 |
| golden_008 | True | manual_review | 0.8694 | E10 |
| golden_009 | False | pass | 0.0 | E10 |
| golden_010 | True | manual_review | 0.7712 | E10 |
| golden_011 | False | pass | 0.0 | E10 |
| golden_012 | True | auto_reject | 0.95 | E10 |
| golden_013 | False | pass | 0.0 | E10 |
| golden_014 | True | auto_reject | 0.97 | E10 |
| golden_015 | True | auto_reject | 0.96 | E10 |
| golden_016 | True | manual_review | 0.98 | E10 |
| golden_017 | True | manual_review | 0.77 | E10 |
| golden_018 | True | auto_reject | 0.98 | E10 |
| golden_019 | True | manual_review | 0.85 | E10 |
| golden_020 | True | manual_review | 0.9 | E10 |
| golden_021 | True | manual_review | 0.9 | E10 |
| golden_022 | True | manual_review | 0.8077 | E10 |
| golden_023 | True | auto_reject | 1.0 | E10 |
| golden_024 | False | pass | 0.0 | E10 |
| golden_025 | True | manual_review | 0.7519 | E10 |
| golden_026 | False | pass | 0.0 | E10 |
| golden_027 | False | pass | 0.0 | E10 |
| golden_028 | True | manual_review | 0.7769 | E10 |
| golden_029 | False | pass | 0.0 | E10 |
| golden_030 | True | manual_review | 0.8763 | E10 |
| golden_031 | True | manual_review | 0.6 | E10 |
| golden_032 | True | manual_review | 0.8969 | E10 |
| golden_033 | True | manual_review | 0.95 | E10 |
| golden_034 | True | auto_reject | 0.9295 | E10 |
| golden_035 | True | auto_reject | 0.9223 | E10 |
| golden_036 | True | auto_reject | 0.97 | E10 |
| golden_037 | False | pass | 0.0 | E10 |
| golden_038 | True | manual_review | 0.9 | E10 |
| golden_039 | False | pass | 0.0 | E10 |
| golden_040 | True | manual_review | 0.8394 | E10 |

## 3. 资产登记对账（asset_manifest）

- manifest 条目：240（按 kind：{'judge_output': 200, 'qc_report': 40}）
- metadata 成片 sha256 命中 0、未登记 46 （本 manifest 未登记 clip 类资产——clip 登记由 gen 模块产出时写入；此处对账只覆盖已登记部分）

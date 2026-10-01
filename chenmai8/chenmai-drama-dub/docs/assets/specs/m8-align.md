# M8 时长对齐 spec

> 状态：frozen（T14）。对照 `pipeline/m8_align.py`、`configs/pipeline.yaml m8 段`、`configs/models.yaml align-m8`
> 核验于 2026-09-29。纯本地编排，零外部依赖，全离线可验收。

## 1. 职责与边界

**做**：逐句把 M6 译文候选对齐到 C2 原句时间窗 ±10%（C4.budget lo/hi），产出 C5 合成计划。
只读 `04_dial`（C2）/`06_mt`（C4）/`05_cast`（C3）；只写 `07_synth`。
**不做**：不合成（M7 执行 C5）、不改 C2/C4（一律只读）、不做情绪识别（emo_alpha 从 C2.emo score 映射）。

## 2. 五级阶梯（T14 定案序）

1. **syl2dur 估算占位**：每候选基准时长 base 直接消费 C4 `candidates[*].est_dur`（M6 同口径写入；
   est=0 而 syl>0 时按 `m6.count_syllables/estimate_dur_s` 补算）。`models/syl2dur.json` 拟合表回填后经 M6
   透传，本模块接口不变（拟合延后，isomt-lora 批次）。
2. **直接落窗**：base 已在 [lo,hi] → duration_factor=1.0 零调整（in-budget）。
3. **真二分** `duration_factor ∈ [0.5, 2.0]`（C5 契约域；`bisect_rounds=10`，区间 1.5/2^10≈1.5e-3 分辨率）：
   对占位模型 `base × f = 窗中心` 二分求解；3 位小数定值前复核 `lo ≤ base×f ≤ hi`，不满足如实落空。
   该旋钮即合成引擎语速参数，M7 按 C5 执行。
4. **换译**：全候选二分均差窗 → 按 C4 的 in-budget-first 序换下一候选重试 ①→③（消费 M6 的 3–5 候选）。
5. **atempo 收口**：仍失败 → 取残差最小候选的边界 duration_factor，用 ffmpeg `atempo ∈ [0.9,1.1]`
   （变速不变调）微调落窗（可达域求交后取最接近窗中心者）；仍不可解记 `unresolved`
   （best-effort 参数照常落盘供人工/审校台处理，对齐率**如实**计入未命中）。
6. **keep_original**（叠加规则）：nonverbal 句（冻结规则 4）与 C4 缺失句（缺译文保原声兜底）→
   `keep_original=true` 不合成，报告中单列口径。

## 3. 出口（C5 多语种分文件是硬要求）

- `07_synth/synth_plan.<lang>.jsonl`：C5 schema 无语种字段而 utt_id 单键——多语种共用一个文件会互踩，
  **每语种一份**；同时刷新无后缀 `synth_plan.jsonl` 为当前语种副本（保持规划 §3 布局的契约文件指向最近语种）。
- C5 字段填充：`engine="dub-tts"`（语种链路由归 M7 auto）；`voice_ref`=C3 角色卡音色参考
  （缺卡回落 `05_cast/voicebank/<char_id>_ref.wav` 暂定槽位）；`emo_ref`=`04_dial/emo_refs/<utt_id>.wav`
  **存在才登记**，缺文件如实留空；`emo_alpha`=情绪 score 映射 [0.5,0.85]（无情绪 0.7）；
  `expect_dur`=预测时长；`atempo`=收口定值。
- `07_synth/align_report.<lang>.json`（工作纸）：逐句决策 status/cand_idx/switched/est/df/atempo/pred_dur/window
  + 汇总（对齐率、atempo 占比、平均语速调整幅度 `mean(max(atempo/df, df/atempo))`、未解句清单）。

## 4. 参数（configs/pipeline.yaml `m8` 段，`AlignParams` 缺项回落）

`df_range=[0.5,2.0]` / `atempo_window=[0.9,1.1]` / `bisect_rounds=10` / `engine=dub-tts` /
`min_align_rate_mvp=0.70`（对齐率低于它 CLI exit 1——未训时长可控翻译前的 MVP 冻结线）。

## 5. eval

```bash
bash scripts/eval_m8.sh   # = pytest tests/test_m8.py -v（全离线零 GPU）
```

- 语料设计：M6 mock 候选**故意超长**（句窗按候选项估长 1.00/0.62/0.52/0.43 压窗）→ 使七类路径
  （in-budget / df-bisect / switch-df / atempo-final / keep-original / no-translation / unresolved）
  全部真实触发。
- 通过线（冻结）：全片时长对齐率（±10% 命中）**≥0.70**；atempo 使用占比 ≤30%；平均语速调整幅度 ≤1.06
  （刻意超长语料上该线必然高于 1.06，故只复算不断言阈值——test_m8 口径注记）；CLI exit 0；C5 契约校验；
  多语种分文件与幂等重跑。
- 门禁：gate_b3 ③（并行批次）；规划 §4 M8 全片通过线：≥70%（isomt-lora 后 ≥80%）。

## 6. 重生成注意事项

- 换译语义依赖 M6 的 `chosen` 与候选序：M6 排序变化会改变换译路径——改 M6 排序必须重跑本模块 eval。
- atempo 是 M7 合成时的变速参数（`SynthPlanItem.atempo`，T14 契约增补）；别把它与
  `duration_factor`（引擎语速参数）混用：df∈[0.5,2.0] 大范围搜索，atempo∈[0.9,1.1] 只做收口。

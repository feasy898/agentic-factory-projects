# v3 首批交付报告 — worker-A（2026-10-01 夜班）

> 接续起点：`deliverables_v2/FINAL_REPORT_V2.md`（v2 完成态）+ `continue-cards/video-capability.md` 下一步指针。
> 工作项来源：`overnight/工程方案v3.1.md` §7.2 行动清单（FINAL_REPORT_V2 无"后续工作"独立章节，v3 优先级以 v3.1 P0/P1/P2 清单为准，continue-card 待办 2「vpipe 推进」与之同线）。
> 本批落地：**P0-1 数字人 QC 机理回填（豁免实验 + known_cuts 契约）+ P0-2 L0 预检接线**。
> 工作目录：`overnight/vpipe/`（v3 QC 线资产）；本轮 worker-B 产出在 `research/`，无交集。
> 纪律对账：**真实模型调用 0 次**（Higress ≤10 配额零消耗，judge 离线核验亦不占）；**API 积分 0 消耗**（`overnight/secrets/api_keys.env` 未随迁，P1 花钱项本就不可达）；无破坏性动作；全部判定数值只存 `eval/thresholds.yaml`（v2，E10 合议阈未动）。

---

## 1. 交付物与验收证据（退出码为证）

运行环境：anolis-gpu-01，`/data/night/venv`（py3.11.6；本轮补装 jsonschema 4.26.0 + opencv-python-headless 5.0.0，pip 走阿里镜像）。验收器：`tests/run_v3_checks.py`（新写，确定性自检，零模型调用）。

| # | 交付 | 验收命令 | 退出码 |
|---|---|---|---|
| 1 | **L0 确定性预检接线**（P0-2）：`qc_orch_v2` 在线模式提供 `--clip` 即跑；黑屏/单色占比、时长偏差双检查；`--profile` 声明 avatar 垫尾豁免（允许窗=[expect×(1−2%), ceil(expect)+1.0s]）；拒收写 `<clip_id>.l0.json` 证据、**exit 4 不进 judge** | `python tests/run_v3_checks.py`（A1-A5 五个注入样本） | **0（ALL PASS）** |
| 2 | **低运动平台豁免**（P0-1 机理1）：`qc_detectors_v2` diff 支凹窗窗内帧差中位 < `ghost_plateau_in_max`(2.0) 恒标注 `low_motion_plateau`；仅当 `--profile` ∈ `ghost_plateau_exempt_profiles`(`[avatar_talk]`) 才弃权该候选（声明制） | 同上（B 组：dh_stepfun/dh_design/dh_final 三片 ghosting 误报归零，弃权证据落 `temporal_rejected`） | **0** |
| 3 | **known_cuts 切点白名单**（P0-1 机理2）：`qc_detectors_v2 --known-cuts` + `known_cuts_tol_s`(0.5)；QCReport 契约 1.1 新增可选 `qc_context{profile,known_cuts,l0_preflight}`（schema_version → enum[1.0,1.1]，向后兼容） | 同上（C 组：dh_final 13.917s 拼接切点 swap 豁免；E 组：契约流转抽验） | **0** |
| 4 | **eval 回归**：qc_orch_v2（出 1.1 报告）与 qc_orch v1（1.0 报告仍合法）双模块回放 + eval_run | `python eval/eval_run.py --qc-dir out/qc_reports_v3post[_v1]` | 双 **0（ACCEPT）** |

L0 注入样本明细（A 组，ffmpeg 构造，非模型）：黑屏片拒（ratio 1.000>0.5，exit 4）；default 时长超差拒（11s vs expect 10s，dev 10%>2%，exit 4）；avatar 垫尾豁免放行（11s ≤ 11 上限，exit 0）；avatar 超垫尾拒（12.5s>11，exit 4）；合规片放行（exit 0）。

## 2. 基准对比（同口径，全部为本轮实跑数字）

基线 = `overnight/judge基准报告.md`（2026-09-30）E10 推荐工作点 + 其勘误节时序重评终局。

| 指标 | 基线 | v3base（改动前复跑） | v3post（改动后） | 偏差 |
|---|---|---|---|---|
| E10 召回（A16） | 1.000 | 1.000 | 1.000 | 0 |
| E10 FPR（C12） | 0.250 | 0.250 | 0.250 | 0 |
| E10 F1 | 0.9143 | 0.9143 | 0.9143 | 0 |
| E10 B_flag | 0.8333 | 0.8333 | 0.8333 | 0 |
| 误报/漏检逐条 | golden_010/025/032，漏检 [] | 同 | 同 | 0 |
| J6v2 时序 clip 召回（勘误节 7/8） | 7/8 | 7/8 | 7/8（判定级逐条一致，40/40） | 0 |
| J6v2 C 类误报 | 0/12 | 0/12 | 0/12 | 0 |
| 合成正例 | 4/4 | 4/4 | 4/4 | 0 |

产物：`eval/eval_results_v3base.json` / `_v3base_v1.json` / `_v3post.json` / `_v3post_v1.json`（thresholds sha256 记录在案）；回放报告 `out/qc_reports_v3base*/`、`out/qc_reports_v3post*/`。

**本轮改进数字（新能力，非基线指标）**：

| 项 | 改动前 | 改动后 |
|---|---|---|
| avatar 素材 15 片 ghosting 误报（J6v2，`--profile avatar_talk`） | 9/15 | **1/15**（仅 vidu_b_timeline lap 支残留，见 §3） |
| dh 三片（v3.1 §3.4 记录的 3 例） | ghosting 误报 3/3 + swap 误报 1 | **0**（全部豁免且弃权证据可审计） |
| L0 拒收层 | 未接线（v3.1 V9 grep 0 命中） | 已接线，注入超差样本 3/3 拒、合规 2/2 放 |

低运动平台判据的实证边界（为什么必须声明制）：9 例 diff_dip 误报窗内帧差中位 in_med=0.71–1.64（编码噪声级），但金标真混叠 golden_034 in_med=0.841、golden_028 in_med=0.001 与误报区间**交叠**——绝对阈不可分（同 golden_008「近静止不可分」教训）。故豁免走上游声明（profile/known_cuts 落 `qc_context`，可审计），未声明时行为与 09-30 版逐条一致（D 组判定级回归 59/59：金标 40+合成 4+avatar 15）。

## 3. 诚实披露

1. **vidu_b_timeline_720p 残留 1 例 ghosting 误报（lap 支）**：高纹理素材 laplacian 凹窗（out_med 1792→in_med 1152，dip 0.643）。本轮豁免只做 diff 支（证据充分的一支）；lap 支豁免需另一判据，未做不隐瞒。
2. **avatar 15 片中 bu*（buA/buB/buC/buD/g9a_intro）无人工净标注**：9 例误报的认定依据 = v3.1 §3.4 已记录机理（dh 三片有人工目检背书 V11）+ 全部 diff_dip 形态一致（in_med 均为编码噪声级）；bu* 片严格说是「推定干净」。金标扩口播正例（v3.1 §3.6/P2-13）仍是把该结论钉死的必要步骤，本批未做。
3. **金标 A 类 cross-type 噪声不在本批范围**：golden_016/018（color_shift 注入）被 v2 检测器报 frame_freeze、golden_014/015（pixelate 注入）被报 ghosting(lap支)——clip 级检出为真、类型归属有噪声，与本轮豁免无关、判定前后一致（D 组）。
4. **D 组回归口径**：以「判定级视图」（检出/类型/置信度/弃权键）为准，证据内新增 `low_motion_plateau` 标注键不视为回归——标注只增证据不改判定（测试脚本注释写明）。
5. **P0-3 MediaPipe 手部检测器、P0-4 kimi 去留终裁本批未做**：前者需装新依赖+新检测维度独立调参循环，按「不贪多」纪律留下一轮；后者按 v3.1 要求二选一（官方 API 需密钥——`overnight/secrets/api_keys.env` 未随迁；正式降级出池属策略裁定）——两路径都超出 worker 权限/资源，如实上抛 owner/judge。
6. **环境重建动作**：`/data/night/venv` 补装 jsonschema、opencv-python-headless（此前该 venv 缺这两个包，迁移卡口径「无统一测试套件」，本次为使 SPEC §4 验收链可跑的最小装机）；`/` 盘 13G avail（低于 PM-LEDGER 20G 红线口径，本轮写入仅 KB 级代码/JSON，媒体零写入，如实报备）。
7. **CONFIRMATION.md（A13+B4）仍待 owner 人工确认**——唯一人工动作，不在 worker 可为范围。

## 4. 变更文件清单（git 提交范围）

- `overnight/vpipe/src/qc_orch_v2.py`（L0 预检 + qc_context + schema 1.1 + exit 4）
- `overnight/vpipe/src/qc_detectors_v2.py`（低运动平台豁免 + known_cuts + --profile/--known-cuts）
- `overnight/vpipe/contracts/qc_report.schema.json`（1.1：enum + qc_context）
- `overnight/vpipe/eval/thresholds.yaml`（v2：J6_detectors_v2 三参数 + l0_preflight 五参数；E10 阈未动）
- `overnight/vpipe/SPEC.md`（§7 现状 + 变更记录 1.1 行）
- `overnight/vpipe/tests/run_v3_checks.py`（新，验收自检）
- `overnight/vpipe/eval/eval_results_v3base*.json`、`eval_results_v3post*.json`（本轮评测留痕）
- `worklog.md`、本报告

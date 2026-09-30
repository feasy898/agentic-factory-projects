# vpipe SPEC — spec 驱动的视频生成-QC 流水线资产（v1.0，2026-09-30 冻结）

> 来源：`D:/workspace/video-capability-research/边界测试方案.md` §3 交付物3。
> 本资产以 2026-09-29/30 夜间边界测试为 oracle 沉淀：契约冻结、评测可复跑、模块可重生成。
> **本文是模块重生成的唯一入口**：重生成某模块 = 新 agent 只读本文 + `contracts/` + `eval/`，
> 产出实现，跑 `eval/eval_run.py` 通过才算验收（规程见 §6）。

---

## 0. 目录与冻结纪律

```
vpipe/
├── SPEC.md                        ← 本文
├── contracts/                     ← 冻结契约（JSON Schema draft-07）
│   ├── shot.schema.json           ← 镜头 spec：流水线统一输入单位
│   ├── qc_report.schema.json      ← QC 报告：盲测协议六字段 JSON 的超集
│   └── asset_manifest.schema.json ← 内容寻址（sha256）资产登记表
├── src/                           ← 四个胶水模块（互不 import，只靠契约 JSON 通信）
│   ├── gen_local.py               ← diffusers 调 Wan/LTX，种子固定（GPU 机器卡1）
│   ├── gen_api.py                 ← MiniMax Design H3 客户端（DTO 白名单/积分守卫/断点续跑）
│   ├── qc_orch.py                 ← 检测器规则引擎 + 多 judge 合议（E10）
│   └── report.py                  ← 汇 metadata/QC/manifest → 报告
├── eval/                          ← 验收资产（重生成验收的唯一裁判）
│   ├── golden_manifest.json       ← 金标 manifest 拷贝（A16 注入/B12 意图/C12 干净，40 条）
│   ├── thresholds.yaml            ← 唯一阈值来源（QC 判定阈 + eval 准入线）
│   ├── eval_run.py                ← 评测器：对 qc_orch 输出算召回/FPR/F1 对照准入线
│   └── eval_results.json          ← 最近一次评测全量结果（可复跑覆写）
└── out/                           ← 运行产物（非资产：qc_reports/ shots_demo/ report.* asset_manifest.json）
```

契约纪律：
1. 契约版本在 `schema_version` 字段（当前全 `1.0`）。**改契约 = 破坏性变更**：升版本号 +
   四模块全部过 `eval_run.py` 回归，并在本文件 §变更记录 登记。
2. 模块间**禁止互相 import**；一切协作通过契约 JSON 文件（shot → 生成 → QCReport → 报告/评测）。
3. 一切判定数值只存于 `eval/thresholds.yaml`；模块源码出现第二套判定阈值即验收失败。

---

## 1. contracts/（三份冻结契约）

| 契约 | 必填 | 生产者 → 消费者 |
|---|---|---|
| `shot.schema.json` | schema_version, shot_id, prompt, duration_s, aspect | 上层/适配器 → gen_local、gen_api |
| `qc_report.schema.json` | schema_version, clip_id, generated_at, verdict{defect_detected, decision, confidence, decided_by}, defects[], scores | qc_orch → eval_run、report |
| `asset_manifest.schema.json` | schema_version, name, generated_at, items[{asset_id, kind, path, sha256, size_bytes, registered_at}] | gen_local、gen_api、qc_orch → report |

要点（字段级语义见 schema 内 description，此处只列结构性决定）：
- **shot**：`characters[].ref_image` 是定妆照路径（gen_api 负责复制进 hub 工作区并转顶层
  `image_paths`——`params.reference_images` 会被网关静默忽略，见 07 手册勘误）；`camera/audio`
  为结构化登记位（audio 本版只登记不执行）。
- **qc_report**：`verdict.defect_detected` 是评测唯一检出口径（与今晚盲测协议一致）；
  `decision ∈ {auto_reject, manual_review, pass}` 是处置建议（阈值见 yaml `judges.J3_omnijev`）；
  原始判官六字段输出一字不改嵌在 `judges.J*`（超集的子集层，保证可追溯）；
  `scores.thresholds_applied.thresholds_sha256` 记录判定所用 yaml 版本。
- **asset_manifest**：`sha256` 是资产身份；manifest 只是登记视图（同一资产可入多表）；
  frames 类目录用「排序逐文件 hash 拼接再哈希」的目录哈希，逐文件清单放 `evidence.dir_manifest`。

---

## 2. src/ 模块职责与接口签名

四个模块均为单文件、零互相依赖。共同行为：输入先过契约校验（jsonschema 可用则全量，
不可用退回 required-key 检查并在输出记降级）；一切失败写进输出 JSON 的 `errors`（方案 §4：
失败本身是数据，不许静默吞）。

### 2.1 gen_local.py — 本地生成（diffusers）

运行位置：GPU 机器 anolis-gpu-01（`/data/night/venv`）。**启动即强制 `CUDA_VISIBLE_DEVICES=1`**
（卡0 是生产 vLLM，铁律）；可用 `VPIPE_LOCAL_CUDA_DEVICES` 覆盖卡号。

```python
# CLI
python src/gen_local.py --shot shot.json [--engine wan|ltx] [--model DIR] [--out-dir D]
                        [--steps 50] [--manifest M.json] [--validate-only]
# 核心签名
render_shot(shot: dict, engine: str, model_dir: str, out_dir: Path, steps: int = 50)
    -> (meta: dict, clip_path: Path)      # meta 即 <shot_id>__<engine>.gen_meta.json 内容
validate_shot(shot: dict, schema_path=contracts/shot.schema.json) -> (ok: bool, err: str|None)
frames_for(engine_cfg: dict, duration_s: float) -> int    # 4k+1 / 8k+1 规则
resolve_wh(engine: str, aspect: str) -> (w, h)            # 480P 档映射，越界拒绝
```
行为要点（全部来自今晚已验证脚本 `overnight/scripts/gen_wan.py` + `gen_ltx.py` 的实跑结论）：
- 种子恒定：`torch.Generator(device="cuda").manual_seed(shot.seed)`（缺省 42）。确定性梯度
  实测：同种子同参连跑帧级一致（`overnight/数据/clips_local/determinism/`）。
- LTX fp16 黑帧/NaN → VAE fp32 自动降级重跑（`dtype_status="ok_with_vae_fp32_fallback"`）。
- 仅实测过 480P（V100S-32GB fp16）；`resolution` 声明高于 480P 时告警并按 480P 渲染。
- 产出后登记 manifest（asset_id=`<shot_id>@<model>`，kind=clip，带 sha256 + probe 级证据）。

### 2.2 gen_api.py — MiniMax Design H3 客户端

运行位置：本机 Windows（网关 127.0.0.1:8001，免鉴权；应用必须存活，挂了自动重启再探）。

```python
# CLI
python src/gen_api.py --shots DIR|FILE.jsonl --out-dir D [--model MiniMax-H3]
                      [--credit-cap 40000] [--dry-run] [--only id,id] [--retry-failed]
                      [--skip-seed-probe]
python src/gen_api.py make-shots --prompts ../数据/prompts.json --out-dir shots/   # 一次性适配器
# 核心签名
build_payload(shot: dict, model_id: str, include_seed: bool, refs_resolved: list[str])
    -> (payload: dict, ignored: list[str])   # DTO 白名单映射；被丢弃字段进 ignored
validate_base_url(url: str, allow_private: bool, allow_loopback: bool) -> (ok, reason)
probe_seed(sess, state) -> dict                # 0 成本 DTO 探测：seed 是否在白名单
poll_task(sess, task_id) -> dict               # 轮询到 succeeded/failed/poll_timeout/poll_error
load_shots(spec) -> list[dict]                 # 目录/*.jsonl 逐条契约校验
```
行为要点（来自今晚 `overnight/数据/run_api_matrix.py` 实跑 46/46 成功、实扣 14,280 积分）：
- **DTO 白名单**：顶层仅 `backend/model_id/prompt/filename/image_paths/params/source_tool`；
  参考图必须走顶层 `image_paths`；params 全字符串；漏 `resolution` 报 500。
- **积分守卫**：`--credit-cap`（默认 40000）硬上限；baseline 首跑写入 `out/api_state.json`；
  每条提交前查 `/api/v1/credit/wallet`，「已耗>上限」「已耗+预估(280)>上限」双拦截 → exit 3。
- **断点续跑**：`out/api_results.jsonl` 已有终态的 `<shot_id>@<model>` 跳过；`--retry-failed`
  只重跑失败条。
- **seed**：首跑 0 成本探测 DTO（塞 `seed:"42"` + 必然未知键，网关一次列出全部未知键）；
  今晚实测 seed 意外通过校验（结论见 `overnight/数据/api_seed_test.json`），探测意外 201 时
  立即 cancel 并记录 ≤224 积分风险。
- **URL 安全**：默认基址是架构内授权端点 `http://127.0.0.1:8001`；`--base-url` 覆盖时强制
  http/https、拒绝环回/私有/保留地址，内网部署须显式 `--allow-private`/`--allow-loopback`。
- 成片从 hub 工作区取回（`/api/workspace` → `output_files`），复制 + sha256 + 登记 manifest。

### 2.3 qc_orch.py — 质检编排（检测器规则引擎 + judge 合议）

```python
# CLI（回放模式 = 验收路径，不跑任何模型）
python src/qc_orch.py --from-tonight --judges-root ../数据/judges \
    --golden eval/golden_manifest.json --thresholds eval/thresholds.yaml \
    --out-dir out/qc_reports [--manifest out/asset_manifest.json]
# CLI（在线模式 = 生产形态）
python src/qc_orch.py --online --clip-id X [--clip X.mp4] [--detector-json X.qc.json]
    [--judge-file J1=p.json ...] [--judge-probs J3=run_metadata.json] --thresholds eval/thresholds.yaml
# 核心签名
run_j6_rules(detector_json: dict, T: dict, n_frames: int, dur_s: float)
    -> (cand: dict[type→evidence], rule_status: dict)   # 移植 j6_to_protocol.py，阈值全由 T 注入
j3_flag(probs: dict, thr: float) -> (flag: bool, hit_types: list[str])  # 8 类任一 >thr 或 overall>thr
synthesize_qc_report(clip_id, mode, judges_raw, j6_cand, j6_emit, probs,
                     thr_cfg, ens_id, thresholds_sha, inputs, errors) -> dict  # 纯函数，产出契约 JSON
```
- **合议定义**（读 `thresholds.yaml` `ensemble`，当前 `E10 = J1.detected OR J3@0.70 flag`）：
  - J3 = OmniJev 9 通道概率（回放源：`judges/omnijev/run_metadata.json`；在线源：
    `--judge-probs J3=run_metadata.json`），判定规则严格大于（与基准报告 §7 扫描口径一致）。
  - J1 = GLM 8帧 rubric 六字段协议（回放源：`judges/glm8/*.json`）。
  - J2/J5/J6 不进 E10：J2 备用；J5 廉价信号；J6 只作信号不作否决（基准报告 §11.1 L3）。
  - decision：未检出→`pass`；检出且 J3 最大通道 P≥0.90→`auto_reject`；否则→`manual_review`。
- **在线模式的检测器输入** = `overnight/qc-scripts/j6/qc_detectors.py` 的检测 JSON 契约
  （OCR 逐帧置信度 / ArcFace 帧间余弦 / CLIP 相似度 / 帧差序列 / scene_cuts / 色偏统计）。
  重检测器（PaddleOCR 等）不进本模块——由该脚本在 CPU 侧跑完落盘，本模块消费。
- **降级**：任一判官文件缺失/解析失败 → `errors` 登记弃权，合议用剩余通道继续。

### 2.4 report.py — 汇报

```python
# CLI
python src/report.py --metadata ../数据/metadata.json --qc-dir out/qc_reports \
    [--manifest out/asset_manifest.json] --out out/report     # 产出 .md + .summary.json
# 核心签名
summarize_generation(meta: dict) -> (lines: list[str], clips: list[dict])   # build_metadata.py 格式
summarize_qc(qc_dir) -> (lines, reports)
verify_manifest(manifest: dict, clips: list[dict]) -> (doc, hit: int, miss: int)  # sha256 对账
```
输入是三份契约 JSON：生成侧 metadata（build_metadata.py 格式）、QCReport 目录、manifest。
对账规则：metadata 每条成片的 sha256 在 manifest 找同 hash 条目；manifest 未登记 clip 类时
如实注明（clip 登记是 gen 模块的职责）。

---

## 3. eval/（验收资产）

- `golden_manifest.json`：拷贝自 `overnight/数据/golden/manifest.json`（2026-09-29 生成，
  shuffle_seed=20260929，A16/B12/C12，failures=[]）。**金标永不入训练/调参**：thresholds.yaml
  的判定阈值全部先于本轮检视写定（judge基准报告 §7 扫描 + §11 定稿），eval 只做验证。
- `thresholds.yaml`：唯一阈值来源。结构：`ensemble`（合议定义 + E10 实测基线）/
  `judges`（各判官角色、阈值、已知失效模式）/ `eval_admission`（准入线）/
  `l0_preflight`（拒收层，本轮未单独测）。**判定阈与准入线是两回事，勿混改。**
- `eval_run.py`：指标口径与 `overnight/数据/score_golden_judges.py` 完全一致——
  正类=A 16，负类=C 12，检出=`verdict.defect_detected`，FPR=FP/12；per-type 召回
  （clip 级/类型级，别名 text_error→garble_text 归一）；B 类 flag/strict/lenient
  （映射表同源）；另做 QCReport 契约全量校验。退出码 0=ACCEPT / 1=REJECT / 2=评测无效。

---

## 4. 验收记录（2026-09-30 实跑）

命令（在 `vpipe/` 下）：
```
python src/qc_orch.py --from-tonight --judges-root ../数据/judges --golden eval/golden_manifest.json \
    --thresholds eval/thresholds.yaml --out-dir out/qc_reports --manifest out/asset_manifest.json
python eval/eval_run.py --qc-dir out/qc_reports
```
结果（`eval/eval_results.json` 全量可复核）：

| 指标 | 本次 qc_orch | 基线（judge基准报告 E10） | 偏差 | 准入线 | 判定 |
|---|---|---|---|---|---|
| 召回（A16） | **1.0** | 1.0 | 0 | ≥0.90 | PASS |
| FPR（C12） | **0.25**（golden_010/025/032，与基线同 3 条） | 0.25 | 0 | ≤0.30 | PASS |
| F1 | **0.9143** | 0.9143 | 0 | ≥0.85 | PASS |
| B_flag | **0.8333** | 0.8333 | 0 | ≥0.50 | PASS |
| 契约校验 | 40/40 过 QCReport schema | — | — | 0 违规 | PASS |

验收结论：**ACCEPT**（exit 0）。附：per-type clip 级召回 8/8 类型全 1.0，类型级 temporal_swap
0.5（golden_008 自相似段互换，E10 结构性盲区，见基准报告 §10.2）；处置分布
pass=11 / manual_review=20 / auto_reject=9。已知差距如实记录：**FPR 0.25 不是 0**——3 条 C 类
误报来自 J3 color_shift 通道把电影感调色当偏色（基准报告 §9），按定稿建议属可接受工作点；
若业务要求 FPR≤0.1，切换 `judges.J3_omnijev.thr_fpr_first=0.80` 并重跑 eval（代价召回 0.875）。

---

## 5. 通信拓扑（谁写谁读哪个 JSON）

```
Shot JSON ──→ gen_local.py ──→ clip.mp4 + gen_meta.json ─┐
           └─→ gen_api.py ───→ clip.mp4 + api_results.jsonl ┤→ asset_manifest.json ─→ report.py
                                                            │                              ↑
clip + 判官输出 ──→ qc_orch.py ──→ qc_reports/*.json ───────┴→ eval_run.py（验收裁判）        │
                                    （QCReport 契约）              │                          │
                                                    eval_results.json   report.md ←─ metadata.json（build_metadata.py 格式）
```

## 6. 模块重生成规程（本资产的存在意义）

1. **输入**：重生成 agent 只允许读三样——本 SPEC.md、`contracts/*.schema.json`、
   `eval/`（thresholds.yaml + eval_run.py + golden_manifest.json）。禁止读旧实现源码
   （防止锚定旧 bug；阈值只从 yaml 读，禁止从旧实现抄数值）。
2. **实现**：按 §2 对应小节的职责与接口签名重写该模块为单文件；遵守 §0 纪律
   （不 import 兄弟模块、阈值不出现在源码、失败写 errors）。
3. **验收（硬闸门）**：在 `vpipe/` 下执行
   ```
   python src/< regenerated>.py 的模块级自检（如 gen_*.py --validate-only / dry-run、qc_orch --from-tonight）
   python eval/eval_run.py --qc-dir out/qc_reports
   ```
   `eval_run.py` 输出 **ACCEPT（exit 0）** 才算验收通过；REJECT 时如实报差距，禁止放水
   （放宽 thresholds.yaml 的 eval_admission = 毁掉本资产的裁判公信力，不允许）。
4. **回归**：重生成任一模块后，其余模块的既有产物必须仍被 eval_run 接受（契约向后兼容）。
5. 2026-09-30 已执行一次演示基线：qc_orch 按本 SPEC 由当前实现产出 40 份报告并 ACCEPT（§4）。

## 7. 已知边界与待办（如实记录，防止误当已完成）

- J6 规则修复清单**未实施**（thresholds.yaml `judges.J6_detectors.known_broken_rules`：
  freeze 几何失谐、garble OCR 误报、hue 绝对阈、scene_cut 误判、ghosting/pixelate 零覆盖）；
  修复后须金标复测达 `promote_criteria`（召回≥0.85 且 FPR≤0.15）才可升否决层。
- L0 确定性预检（时长偏差>2% / 黑帧占比>50% 拒收）已写入 yaml 但未挂进 qc_orch 主流程。
- gen_local/gen_api 的完整生成路径在 GPU 机器/网关上执行，本机只验证了
  `--validate-only` / `--dry-run` / `make-shots`（生成侧结论以今晚实跑产物为准）。
- audio 结构化字段只登记不执行（TTS/配音管线未纳入本版）。
- J7 kimi 金标批未跑（脚本在 `overnight/数据/kimi_work_golden_batch.py`，待补）。

## 变更记录

| 日期 | 版本 | 变更 |
|---|---|---|
| 2026-09-30 | 1.0 | 首版冻结：三契约 + 四模块 + eval 资产；验收 ACCEPT（§4） |

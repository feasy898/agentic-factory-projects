# 契约与 IO 原语 spec（时间零点 / utt_id 公式 / 原子 upsert / 切句 / 字级校验）

> 状态：frozen（T1 冻结 2026-09-28 + B1 冻结规则 7–10 + T14 规则 11）。对照 `pipeline/contracts.py`、
> `pipeline/scaffold.py`、`pipeline/cli.py` 逐行核验于 2026-09-29。目标读者：只凭本页重建契约层的新 agent。
> C1–C8 字段级全表见 [../CONTRACTS.md](../CONTRACTS.md)；本页只写**跨模块行为契约**与可重建细节。

---

## 1. 职责与边界

**做**：全管线唯一的交换格式定义（C1–C8 + C2-pre）、写盘原语（原子整文件写 / 按 id 替换）、
时间零点与 utt_id 稳定公式、集工作区布局；`extra="forbid"` 拒收未登记字段。

**不做**：不做任何媒体处理/推理；不写任何模块工作产物（03_ocr/07_synth 报告等属各模块，见 CONTRACTS §2.11）。

## 2. 对外契约

### 2.1 schema 权威与登记

- 唯一权威：`pipeline/contracts.py`（pydantic v2）。基类 `_Frozen` = `ConfigDict(extra="forbid")`（contracts.py:133-137）。
- 类型：`Sec = Annotated[float, BeforeValidator(_sec3)]`（秒，写入前 `round(v,3)`）；`NonNegSec` 另加 `ge=0`（contracts.py:122-130）。
- CLI：`python -m pipeline.cli validate <kind> <path>`；kind→(契约号, 模型类, 是否 JSONL) 登记于
  `CONTRACT_KINDS`（contracts.py:710-721）：shots/utterances/diar/characters/translations/synth-plan/lip-plan/labels/compliance。

### 2.2 时间零点（冻结规则 7，B1）

- **口径**：`:9001 /v1/asr_align` 响应中 `words[*].s/e` 与 `segments[*].start/end` 均为**上传音频内相对时间**
  （0 = 上传片段起点）。全片绝对时间 = 片段内相对时间 + offset；offset = 上传片段在
  `01_media/audio_16k.wav` 中的起点秒，**由客户端注入，服务端不做平移**。
- 权威函数：`contracts.to_absolute_seconds(t, offset) = round(t + offset, 3)`（contracts.py:506-512）。
- 为什么：服务返回的整段 `text` / 整段 `words` / 能量 VAD `segments` 三者无共同键，唯一共同基准是上传音频 0 秒
  （`docs/b1_contract_notes.md §2`；`pipeline/gpu_client.py:90-96` 客户端 docstring 同款）。
- 消费方：`pipeline/m4_asr.py`（`_shift` → `--offset` 注入）；重建任何新服务客户端时必须复用同一函数，禁止各自平移。

### 2.3 切句规则（冻结规则 8，B1）

C2 句窗（`Utterance.start/end`）来源优先级（`docs/b1_contract_notes.md §3`）：
1. **M2 OCR 字幕时间段**（`03_ocr/ocr_merged.jsonl` 有字幕区间时按其切句）；
2. 服务 VAD segments（能量预分段）；
3. 兜底 `[0, 音频时长]`。

**禁止**把服务整段 `text` 当单句落 C2。落地：`m4_asr.build_utterances`（m4_asr.py:66-146）——
每段一句、字按中点归段并夹取进句窗（`_EPS=0.001` 容差）；M2 融合时命中句以 OCR 区间重切、
`_clip_words_into_window` 夹取（m2_ocr.py:212-227），`utt_id` 保持 M4 公式不变（替换键，改 id 破坏续跑）。

### 2.4 字级时间校验（B1）

`Utterance` 模型校验器（contracts.py:268-283）：每字满足 `utt.start ≤ w.s ≤ w.e ≤ utt.end`，
且按 `w.s` 非降排序（同起点并列允许）；空 words 跳过。违反即 ValidationError——这是契约不是警告。

### 2.5 utt_id 稳定公式（冻结规则 9）

```python
make_utt_id("ep01", 12.40) == "ep01-u000012400"      # <ep>-u<起始毫秒,8 位零填充>
```

- `ms = int(round(start_s * 1000))`；ep 为空或 ms<0 拒绝（contracts.py:515-526）。
- 同集同起点重跑 → 同一 id：断点续跑/同句重跑的替换键。C2/C4/C5/C6 容器强校验其唯一性。

### 2.6 容器唯一性

- `UtteranceTable` / `SynthPlanTable` / `LipPlanTable`：`utt_id` 唯一（contracts.py:286-292, 453-459, 484-490）。
- `TranslationTable`：`(utt_id, tgt)` 复合唯一（contracts.py:417-423）——en/es 行共存。
- `ShotSheet`：`shot_id` 集内唯一 + `end > start`；`DiarTable`：段按时间排序、允许 speaker 重复。

### 2.7 时间戳关系校验汇总

| 模型 | 校验 |
|---|---|
| `Shot` / `Utterance` / `DiarSegment` | `end > start` |
| `Word` | `e ≥ s` |
| `Budget` | `lo ≤ hi` |
| `Translation` | `chosen < len(candidates)` |
| `LipPlanItem.window` / `Finding.t` | `[0] ≤ [1]` |
| `Candidate.q` / `OcrFact.conf` / `EmoTag.score` | ∈ [0,1] |
| `SynthPlanItem` | `emo_alpha∈[0,1]`、`duration_factor∈[0.5,2.0]`、`atempo∈[0.5,2.0]`（微调窗 0.9–1.1） |

### 2.8 原子 upsert（冻结规则 9 的写盘原语）

`upsert_jsonl(path, items, *, container, key_field="utt_id") -> int`（contracts.py:660-686）：

1. 读旧文件（存在时）→ 以 key_field 值为键构建 `merged` dict；
2. `items` 依次覆盖同键旧行（同键多条以最后一条为准）；
3. 整表经 `container.model_validate(...)` **强校验**（唯一性/时间窗等全部规则重新生效）；
4. `_atomic_write_lines` 原子重写：同目录 `<name>.tmp` 整体写完 → `os.replace` 原子替换
   （contracts.py:638-657）——读取方要么见旧整文件要么见新整文件，绝不读半截
   （断电丢最后一窗为已知取舍）。
5. 合并语义：**替换行保持原位置，新行追加尾部**；返回写出行数。

**禁止**：对同 id 直接追加（触发容器唯一性自锁 ValidationError）；各模块自写"读-过滤-追加"之外的写盘路径。

### 2.9 路径安全（写盘统一出口）

- `_atomic_write_lines`：路径含 NUL 拒绝；`resolve()` 规范化（消解 `..` 与相对引用）后复核无 `..` 段（CWE-22 防护）。
- `scaffold.ep_dir`：集 ID 白名单 `^[A-Za-z0-9][A-Za-z0-9._-]*$`，含路径分隔符/`..`/空串/绝对路径一律拒绝
  （scaffold.py:16, 68-79）——`--ep` 是工作区路径的来源组件。

### 2.10 序列化 IO 其余原语

- `dump_jsonl(path, items)`：RootModel 容器或模型迭代器 → 原子整文件写；只接受 pydantic 模型（contracts.py:622-635）。
- `load_jsonl(path, cls)`：cls 为 RootModel 容器 → 容器实例；普通模型 → 模型列表（contracts.py:689-703）。
- `load_model(path, cls)`：JSON 单文档读取（contracts.py:617-619）。

## 3. jobs/<ep> 工作区（scaffold.py）

- 13 层目录 `00_raw…12_out`；各层预期产物名如下两表（**2026-09-30 回炉自含化**：原稿只给
  scaffold.py 行号，重生成者无法凭行号重建布局，现全表钉死；与 scaffold.py 逐行一致）。

### 3.1 LAYERS（13 层 + 子目录）

| 层 | 子目录 |
|---|---|
| `00_raw` | — |
| `01_media` | — |
| `02_shots` | — |
| `03_ocr` | — |
| `04_dial` | `emo_refs` |
| `05_cast` | `voicebank`, `consent` |
| `06_mt` | — |
| `07_synth` | `wavs` |
| `08_mix` | — |
| `09_lip` | `done` |
| `10_subs` | — |
| `11_labels` | — |
| `12_out` | — |

### 3.2 EXPECTED_FILES（各层预期产物名）

| 层 | 预期产物（模块按此命名） |
|---|---|
| `00_raw` | `input.mp4`（M1 收件**固定名**，任意容器一律此名） |
| `01_media` | `video_1080x1920_25fps.mp4`（M1 视频产物在**默认 targets** 下的名字；真名随 targets 联动，模板 `video_{W}x{H}_{fps}fps.mp4`）、`audio_16k.wav`、`audio_48k.wav`（M1 重采样混音，含 BGM/音效）、`bgm.wav`（M3 分离背景）、`video_1080x1920_25fps_clean.mp4`（T8/M11 擦除基带）、`probe.json`（M1 探针） |
| `02_shots` | `shots.json`（C1） |
| `03_ocr` | `ocr_raw.jsonl`、`ocr_merged.jsonl` |
| `04_dial` | `vocals.wav`（B1 冻结：M3 人声、M4 唯一识别输入）、`asr.jsonl`、`forced.jsonl`、`diar.jsonl`（C2-pre）、`emo.jsonl`、`utterances.jsonl`（C2） |
| `05_cast` | `characters.json`（C3） |
| `06_mt` | `context.json`、`translations.jsonl`（C4） |
| `07_synth` | `synth_plan.jsonl`（C5） |
| `08_mix` | `dubbed.wav`、`mix.wav` |
| `09_lip` | `lip_plan.jsonl`（C6） |
| `10_subs` | `src.ass`、`tgt.en.ass`、`tgt.es.ass`、`tgt.ar.ass` |
| `11_labels` | `labels.json`（C7）、`c2pa_manifest.json`、`audio_wm.wav` |
| `12_out` | 按语种命名：`<ep>.<lang>.mp4`、`compliance.<lang>.json`（C8） |

- **关键槽位（B1 冻结）**：`04_dial/vocals.wav` = M3 人声（M4 唯一识别输入）；`01_media/` 保存混音口径产物
  （audio_16k/48k + M3 背景 bgm.wav + M11 擦除基带 video_*_clean.mp4 + probe.json）。
- `create_workspace(ep, jobs_dir)`：幂等建骨架，**不预生成任何文件**（避免空文件被当产物）。
- 多语种分文件槽位（M8/M9 定案）：`synth_plan.<lang>.jsonl` / `synth_plan.jsonl`（当前语种副本）、
  `tgt.<lang>.ass`、`12_out/<ep>.<lang>.mp4`、`compliance.<lang>.json`。

## 4. eval：精确命令与通过线

```bash
# ① CLI 校验真实产物（jobs/ep01 为实测工作区）
.venv/Scripts/python.exe -m pipeline.cli validate utterances ../jobs/ep01/04_dial/utterances.jsonl
# → OK C2 ...（N 条记录），exit 0
# ② 契约回归
.venv/Scripts/python.exe -m pytest tests/test_contracts.py tests/test_b1_contract.py
# → 38 passed（T13 门记录 2026-09-29）；skipped 即 FAIL（B0 纪律）
```

- 三道批次门均含契约回归（gate_b1 ⑤ 显式复跑；gate_b0/b1/b2 ① 的全量套件含之）。
- **禁止事项**：不许绕过 `contracts.py` 在模块里复制 schema；不许为让某模块过 eval 放宽校验器
  （校验器 = 冻结契约的一部分）。

## 5. 重生成注意事项

- pydantic==2.13.5 钉版（requirements.txt）；契约层零其他依赖。
- 修订纪律**只增不改名**：新字段走增补 + 缺省值向后兼容（范例：C5.atempo，contracts.py:443-446——
  存量行无该字段按缺省 1.0 解析）；B1 修订记录表在 `docs/b1_contract_notes.md §6`。
- 变更流程见 [../CONTRACTS.md §4](../CONTRACTS.md)。

# 跨模块冻结契约汇总（CONTRACTS）

> 版本：契约基线 T1 冻结（2026-09-28）+ B1 冻结规则 7–10（2026-09-28）+ T14 规则 11（C5.atempo 增补，2026-09-29）。
> **schema 唯一权威 = `pipeline/contracts.py`**（pydantic v2，`extra="forbid"`）；本文是全表叙述版，
> 逐字段与代码一致（对照 2026-09-29 逐行核验）。变更流程见文末 §4。

---

## 0. 全局冻结规则（contracts.py 模块头，规则 1–11）

| # | 规则 | 权威落点 |
|---|---|---|
| 1 | 所有时间字段单位为秒，float 统一保留 3 位小数（写入前四舍五入；`Sec`/`NonNegSec` 类型） | `contracts.py:122-130` |
| 2 | `utt_id` 全局唯一（C2/C4/C5/C6 容器强校验）；`shot_id` 集内唯一（C1） | 各 Table 容器校验器 |
| 3 | C2 `text` 以硬字幕 OCR ↔ 语音识别校对结果为准（M2 产出口径） | `m2_ocr.vote_text` |
| 4 | C5：`nonverbal` 句（哭/尖叫）`keep_original=true`，不合成 | `SynthPlanItem` + M7 生产规则 |
| 5 | C6 分流：正脸+近景+非重叠才入口型（`lip_eligible`）；台词最长前 10% 用 lip-pro 属 M10 生产策略，不在契约内 | `contracts.py:493-499` |
| 6 | C7 依据 GB 45438-2025（显式+隐式标识+内容凭证+音频水印） | `Labels.standard` Literal |
| 7 | **时间零点**：:9001 响应时间均为**上传音频内相对时间**；全片绝对 = 相对 + offset（客户端注入，服务端不平移） | `to_absolute_seconds`（§2.9） |
| 8 | **切句**：C2 句窗优先级 = ①M2 OCR 字幕时间段 ②服务 VAD segments ③兜底 [0, 音频时长]；**禁止把服务整段 text 当单句** | `m4_asr.build_utterances` |
| 9 | **utt_id 稳定公式**：`<ep>-u<起始毫秒,8 位零填充>`；写盘一律「按 utt_id 替换后整文件重写」，禁止同 id 追加 | `make_utt_id` / `upsert_jsonl`（§2.8–2.10） |
| 10 | 说话人段级契约 `diar.jsonl`（C2-pre）：M4/VAD 只切分，`speaker` 由 M5 聚类回填（未定人填 `unknown` 不置空） | `DiarSegment` |
| 11 | C5 `atempo` 增补字段（T14，契约只增不改名）：ffmpeg atempo 最终微调参数，缺省 1.0，存量行按缺省解析 | `SynthPlanItem.atempo` |

---

## 1. 契约总表（C1–C8 + C2-pre）

| 契约 | 文件（jobs/<ep>/） | 形态 | 容器/模型 | 生产方 | 主要消费方 |
|---|---|---|---|---|---|
| C1 | `02_shots/shots.json` | JSON 单文档 | `ShotSheet` | M5 | M10(planned)、人工 |
| C2 | `04_dial/utterances.jsonl` | JSONL | `UtteranceTable` | M4 初产 → M2 融合 → M5 回填 | M5/M6/M8/M9/M11 全链 |
| C2-pre | `04_dial/diar.jsonl` | JSONL | `DiarTable` | M4（speaker=unknown）→ M5 回填 | M5 |
| C3 | `05_cast/characters.json` | JSON 单文档 | `CastBook` | 人工/M5 voicebank（M6 只增量合并暂定卡） | M6/M7/M8 |
| C4 | `06_mt/translations.jsonl` | JSONL | `TranslationTable` | M6 | M8/M11 |
| C5 | `07_synth/synth_plan.<lang>.jsonl`（+无后缀副本） | JSONL | `SynthPlanTable` | M8 | M7/M9 |
| C6 | `09_lip/lip_plan.jsonl` | JSONL | `LipPlanTable` | M10（planned；规则已冻结） | M10 |
| C7 | `11_labels/labels.json` | JSON 单文档 | `Labels` | M12（planned；M9 只读其 implicit 位做兜底） | M9/M12/M15 |
| C8 | `12_out/compliance.<lang>.json` | JSON 单文档 | `ComplianceReport` | M12（planned） | 交付物 |

CLI 校验：`python -m pipeline.cli validate <kind> <path>`，kind 登记表 = `CONTRACT_KINDS`（contracts.py:710-721）：
`shots/utterances/diar/characters/translations/synth-plan/lip-plan/labels/compliance`。

---

## 2. 逐契约 schema（字段级）

### C1 `shots.json`（`ShotSheet`）

```jsonc
{ "ep": "ep01",              // str, min_length=1
  "fps": 25,                 // int > 0
  "dur": 92.4,               // NonNegSec（秒，3 位）
  "shots": [ { "shot_id": "s0003",  // str 唯一（集内）
               "start": 12.0, "end": 15.6,  // NonNegSec，end > start（校验器）
               "cut": "hard",    // Literal["hard","soft"]，默认 hard
               "faces": 1 } ] }  // int ≥ 0，镜内最大并发人脸数
```

### C2 `utterances.jsonl`（核心契约，`UtteranceTable` → `Utterance`）

| 字段 | 类型/约束 | 填写方 |
|---|---|---|
| `utt_id` | str 唯一，`= make_utt_id(ep, start)` 即 `<ep>-u<起始毫秒 8 位零填充>` | M4（OCR 独立行 M2 生成，公式同源） |
| `shot_id` | str（M4/M2 阶段为占位 `s0000`，M5 回填真实镜头） | M4→M5 |
| `start`/`end` | NonNegSec，`end > start`（校验器强制） | M4（句窗=OCR 区间或 VAD 段） |
| `lang` | str ≥2 字符 | M4/M2 |
| `speaker`/`char_id` | Optional[str]，M5 回填（char_id 经 `05_cast/speaker_map.json` 绑定表） | M5 |
| `text` | str（OCR↔ASR 校对定稿；默认 ""） | M2 投票 |
| `ocr` | Optional[`OcrFact`{text, conf∈[0,1], agree}] | M2 |
| `words` | list[`Word`{w, s, e}]；**校验器**：每字 `utt.start ≤ w.s ≤ w.e ≤ utt.end` 且按 `w.s` 非降排序 | M4 写入/M2 夹取 |
| `emo` | Optional[`EmoTag`{label, score∈[0,1]}] | M4（整段判别） |
| `events` | list[`SoundEvent`{label, score?, start?, end?}]（哭/笑/掌声/叹气） | M4 |
| `overlap` | bool（段窗两两时间交叠 >0.2s 才判真） | M5 |
| `nonverbal` | bool（事件占比高 + 文本 ≤2 字符） | M4 |
| `face` | Optional[`FaceFact`{frontal, closeup, bbox[4]int}] | M5 |

容器校验：`utt_id` 全局唯一（重复即 ValidationError——这就是「追加自锁」）。

### C2-pre `diar.jsonl`（`DiarTable` → `DiarSegment`）

行 = `{start: NonNegSec, end: NonNegSec(end>start), speaker: str(min_length=1，未定人填 "unknown")}`。
容器校验：段按时间排序（`b.start ≥ a.start`），允许 speaker 重复。

### C3 `characters.json`（`CastBook` = char_id → `Character`）

```jsonc
{ "char_nan": { "name": "程总",             // str 必填
    "aliases": ["总裁","他"],                // list[str]
    "gender": "m",                          // Literal["m","f","u"] 默认 "u"
    "voice_ref": "05_cast/voicebank/char_nan_ref.wav",  // str 必填
    "ref_dur_s": 12.0,                      // NonNegSec（参考时长 10-15s 越界 WARN）
    "desc": "…",                            // str
    "terms": {"en":"Master Cheng","es":"…","ar":"…"},   // dict[str,str]
    "consent": { "subject": "…", "form": "05_cast/consent/….pdf",
                 "scope": "比赛演示", "date": "2026-09-29" } } }  // Optional[Consent]
```

### C4 `translations.jsonl`（`TranslationTable` → `Translation`）

| 字段 | 类型/约束 |
|---|---|
| `utt_id` + `tgt` | **复合键**，`(utt_id, tgt)` 容器唯一（en/es 行共存；重跑同语种按 id 替换不碰他语种） |
| `context` | list[str]（前文已定稿译文等） |
| `budget` | `Budget{orig_dur, lo, hi}`，校验器 `lo ≤ hi`；窗=C2 时长×[0.9,1.1] |
| `candidates` | list[`Candidate`{text, syl≥0, est_dur≥0, src, q∈[0,1]}]，3–5 条 |
| `chosen` | Optional[int ≥0]，校验器 `chosen < len(candidates)`；无预算内候选时仍取排序首位（M8 据此换译） |
| `policy` | str 默认 `"in-budget-first"` |

### C5 `synth_plan.jsonl`（`SynthPlanTable` → `SynthPlanItem`）

| 字段 | 类型/约束 | 说明 |
|---|---|---|
| `utt_id` | 唯一 | 替换键 |
| `engine` | str 默认 `"dub-tts"` | 语种链路由归 M7 auto |
| `voice_ref` | str 必填 | C3 角色卡音色参考（缺卡回落 `05_cast/voicebank/<char_id>_ref.wav`） |
| `emo_ref` | Optional[str] | `04_dial/emo_refs/<utt_id>.wav` 存在才登记，缺文件如实留空 |
| `emo_alpha` | float ∈[0,1] 默认 0.7 | 情绪 score 映射 [0.5,0.85]，无情绪 0.7 |
| `duration_factor` | float ∈[0.5,2.0] 默认 1.0 | M8 二分旋钮 |
| `atempo` | float ∈[0.5,2.0] 默认 1.0 | **T14 增补**：M8 收口旋钮，0.9–1.1 为微调窗 |
| `text` | str 必填 | 目标语台词 |
| `out` | str 必填 | `07_synth/wavs/<utt_id>.wav` |
| `expect_dur` | Optional[NonNegSec] | 预测时长（M8 写） |
| `keep_original` | bool 默认 False | nonverbal 句/缺译文句 = true，不合成 |

多语种**分文件**是硬要求（C5 无语种字段而 utt_id 单键，共用一个文件会互踩）。

### C6 `lip_plan.jsonl`（`LipPlanTable` → `LipPlanItem`）

`{utt_id 唯一, shot_id, engine: Literal["lip-fast","lip-pro"]="lip-fast", priority: Literal["normal","pro"]="normal", window: [NonNegSec,NonNegSec]（起点≤终点）, face_track: int≥0}`。
合格判据 `lip_eligible(u) = face.frontal && face.closeup && !overlap`（纯函数，契约冻结）。

### C7 `labels.json`（`Labels`）

`{service_provider 必填, content_id 必填, standard: Literal["GB45438-2025"], explicit: {text="本内容由AI生成", video, audio_announce=false}, implicit: {metadata_field="XMP:aiGeneratedContent", value}, c2pa 路径, audio_wm: {engine="audmark", payload, bits: Literal[16]}}`。
四项落实状态由 C8 的 `label_status` 承载（ok/pending/failed）。

### C8 `compliance.<lang>.json`（`ComplianceReport`）

`{market, ep, findings: [Finding{utt_id?, rule, sev: Literal["high","medium","low"]="medium", t:[秒,秒] 有序, suggest="", auto="flag"}], label_status: {explicit/implicit/c2pa/audio_wm 各 Literal["ok","pending","failed"]="pending"}, human_review: [utt_id], generator="rule-yaml+LLM"}`。

---

### 2.8 冻结原语：时间零点（规则 7）

- `:9001` `/v1/asr_align` 响应中 `words[*].s/e` 与 `segments[*].start/end` 均为**上传音频内相对时间**（0 = 上传片段起点）。
- `全片绝对时间 = 片段内相对时间 + offset`，offset = 上传片段在 `01_media/audio_16k.wav` 中的起点秒，
  **由客户端注入**（`pipeline/m4_asr.py --offset`），服务端不做平移。
- 权威函数：`contracts.to_absolute_seconds(t, offset)`（contracts.py:506-512，与契约同口径 3 位小数）。
- 叙述版：`docs/b1_contract_notes.md §2`；客户端 docstring 同款口径：`pipeline/gpu_client.py:90-96`。

### 2.9 冻结原语：utt_id 稳定公式（规则 9）

```python
make_utt_id(ep, start_s) -> f"{ep}-u{int(round(start_s*1000)):08d}"
# 例：ep="ep01", start=12.40 → "ep01-u000012400"
```

- 同集同起点重跑得到同一 id——该 id 即 `upsert_jsonl` 的替换键，支撑同句重跑与断点续跑；
- ep 为空或起始毫秒为负一律拒绝（contracts.py:515-526）。

### 2.10 冻结原语：原子 upsert 写盘（规则 9 / IO 出口）

- `upsert_jsonl(path, items, container=…, key_field="utt_id")`（contracts.py:660-686）：
  读旧文件（存在时）→ 以 key_field 值为键，items 覆盖同键旧行、其余保留（**替换行保持原位置，新行追加尾部**；
  同键多条以最后一条为准）→ 整表经 container 强校验（唯一性/时间窗等全部规则重新生效）→ 原子重写。返回行数。
- 原子性：`_atomic_write_lines` = 同目录临时文件整体写完 → `os.replace` 原子替换——读取方要么看到旧整文件
  要么看到新整文件，不会读到半截（contracts.py:638-657）。
- 路径安全（写盘统一出口）：先 `resolve()` 规范化，再显式复核无 `..` 段与 NUL 字节（CWE-22 防护）；
  上层另有 `scaffold.ep_dir` 集 ID 白名单（`^[A-Za-z0-9][A-Za-z0-9._-]*$`，杜绝 `--ep ../x` 穿越）。
- **禁止**：直接对同 id 追加（触发容器唯一性自锁 ValidationError）；各模块不得自写"读-过滤-追加"之外的写盘路径。
- `dump_jsonl`（contracts.py:622-635）：RootModel 容器或模型迭代器 → 原子整文件写；只接受 pydantic 模型。
- `load_jsonl`（contracts.py:689-703）：传 RootModel 容器返回容器实例，传普通模型返回模型列表。

### 2.11 非冻结契约的 JSONL（各模块工作产物，schema 在模块内）

| 文件 | 单行 schema | 定义处 |
|---|---|---|
| `03_ocr/ocr_raw.jsonl` | `{t: 采样帧时间, text, conf, boxes: [[x1,y1,x2,y2]]…}`（只记非空帧） | `m2_ocr.OcrFrameRecord` |
| `03_ocr/ocr_merged.jsonl` | `{start, end（首/末命中采样时刻 ∓ 半步）, text, conf（各帧均值）, frames, x0,y0,x1,y1（多帧并集，全片像素）}` | `m2_ocr.OcrLineRecord` |
| `04_dial/asr.jsonl` | `{utt_id, wav, offset, text, lang, lang_detected, duration_s, segments, words, aligner, timing, versions}`（extra=allow 保留服务完整响应） | `m4_asr._RawRecord` |
| `04_dial/forced.jsonl` | `{utt_id, aligner, offset, words:[{w,s,e}]}` | `m4_asr._RawRecord` |
| `04_dial/emo.jsonl` | `{utt_id, offset, scope:"clip", emo, events, nonverbal_hint}` | `m4_asr._RawRecord` |
| `07_synth/align_report.<lang>.json` | 逐句决策 status/cand_idx/switched/est/df/atempo/pred_dur/window + 汇总（对齐率/atempo 占比/平均语速调整幅度/未解句） | `m8_align` |
| `08_mix/mix_report.<lang>.json` | ducking 电平实测/响度复测/缺失与超窗清单 | `m9_mix` |
| `01_media/probe.json` | M1 探针（源/产物流清单+响度实测+时长偏差表） | `m1_ingest` |
| `04_dial/separate.json` | 分离报告（设备/模型/耗时/时长/RMS 判据实测） | `m3_separate` |
| `02_shots/frontal_closeups.json` | 正脸近景镜头表（C1 schema 冻结不含正脸字段故独立落盘） | `m5_diar` |

工作产物与冻结契约的边界：**只有 §1 表内的九类是冻结契约**；其余文件可随模块演进（改命名/字段须同步消费方，
见 scaffold.EXPECTED_FILES 的槽位登记）。

---

## 3. 已知契约痛点（变更候选——待 owner 批准，批准前不得擅改实现）

| # | 痛点 | 现状（如实） | 变更候选 |
|---|---|---|---|
| 1 | M6 暂定角色卡 vs C3 权威 | M6 只新增未见过的 char_id、绝不覆盖既有卡（C3 权威归人工/M5），但暂定卡无人工确认标记 | 角色卡加 `provisional` 标记位（契约只增不改名） |
| 2 | M2 一条 OCR 行横跨多条 ASR 句 | 对任何单句重叠率都不足 60% 时三方共存（OCR 新句+原 ASR 句），句级去重归 M5/M14 融合批次（m2_ocr.merge_ocr_asr docstring 已知边界） | 融合批次实现跨行去重规则并回填契约 |
| 3 | C5 无语种字段 | M8/M9 只能按 `--lang` 分文件 + 无后缀副本指向"最近一次对齐语种" | v2 增补 `tgt` 字段（只增不改名） |
| 4 | `cli run` 占位 | M14 未实现，exit 2 是当前契约的一部分，不要"顺手实现"而不改规划 | M14 落地后删除占位语义 |
| 5 | syl2dur 占位速率 | `m6.DEFAULT_SYL_RATE`（zh 4.2/en 4.0/es 4.4/ar 3.6）只保证量级正确；`models/syl2dur.json` 拟合表缺位 | isomt-lora 批次回填拟合表（接口已留：load_syl_table 覆盖占位） |

## 4. 版本与变更流程（冻结）

- **版本锚**：契约 = `pipeline/contracts.py` 模块头状态行（当前 T1 冻结 + B1 规则 7–10 + T14 规则 11）；
  组件版本锚 = `configs/models.yaml` 各条目 `version`/`volta_status`。
- **谁批准**：契约字段级改动 = 改规划，须主会话/owner 裁决；模块不得单方面新增/删除/放宽字段
  （`extra="forbid"` 兜底拒收）。
- **修订纪律**：**只增不改名**（C1–C8 既有字段不动；新字段走增补 + 缺省值向后兼容，如 C5.atempo）。
- **怎么广播**（每次契约变更必须全做）：
  1. 更新 `pipeline/contracts.py`（唯一权威）+ 本页对应小节 + `docs/b1_contract_notes.md` 修订记录表；
  2. 同步受影响模块与 `tests/test_contracts.py`/`tests/test_b1_contract.py` 回归；
  3. 跑对应批次门禁全绿（B0–B3 之一，见 REGENERATE §5）；
  4. 单独 commit，标题注明契约变更范围。

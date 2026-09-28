# B1 契约冻结说明 —— 音频四件套交接（2026-09-28）

> 修订依据：`_reviews/drama-b0-review.md` §B/§G。修订纪律：**只增不改名**
> （C1–C8 既有字段一律不动；新增以 C2-pre / 冻结规则 7–10 / 新槽位落地）。
> schema 唯一权威仍在 `pipeline/contracts.py`；本文是冻结规则的叙述版。

## 1. 人声槽位（冻结规则见 scaffold.EXPECTED_FILES）

- `04_dial/vocals.wav`：M3 人声分离的产出槽位（新增，B1 冻结）。
- `01_media/` 保存**混音口径**产物：`audio_16k.wav` / `audio_48k.wav`（M1 重采样）、
  `bgm.wav`（M3 分离出的背景音）。
- **M4 只读 `04_dial/vocals.wav`，不读 `01_media/audio_16k.wav`**
  （混音含 BGM/音效，会污染识别、对齐与情绪）。

## 2. 时间零点（contracts.py 冻结规则 7）

`:9001` `/v1/asr_align` 响应中的 `words[*].s/e` 与 `segments[*].start/end`
均为**上传音频内相对时间**（0 = 上传片段起点）：

```
全片绝对时间 = 片段内相对时间 + offset
offset = 上传片段在 01_media/audio_16k.wav 中的起点秒（客户端注入，服务端不平移）
```

服务返回的整段 `text` / 整段 `words` / 能量 VAD `segments` 三者**无共同键**，
唯一共同基准是上传音频 0 秒。客户端约定（`pipeline/gpu_client.py` +
`gpu-services/asr_align/service.py` 注释同款）：调用方负责记录本次上传片段的
offset，消费响应前先经 `contracts.to_absolute_seconds(t, offset)` 平移。

秒精度维持冻结规则 1（3 位小数 = 1ms）；对齐器官方样例落 0.08s 栅格，
三位小数可原样表达。

## 3. 切句规则（contracts.py 冻结规则 8）

C2 句窗（`Utterance.start/end`）来源优先级：

1. **M2 OCR 字幕时间段**：`03_ocr/ocr_merged.jsonl` 有字幕区间时按其切句；
2. **服务 VAD segments**（能量预分段）；
3. 兜底 `[0, 音频时长]`。

**禁止**把服务整段 `text` 当单句落 C2。

## 4. 字级时间校验 + utt_id + 写盘原语（冻结规则 9 与 ③/④ 修订）

- 字级校验（`Utterance` 模型校验器，2026-09-28 起生效）：
  每字满足 `utt.start ≤ word.s ≤ word.e ≤ utt.end`，且 `word.s` 按时间非降排序。
- `utt_id` 稳定生成公式：`<ep>-u<起始毫秒,8 位零填充>`（`contracts.make_utt_id`）。
  同集同起点重跑得到同一 id，即断点续跑/同句重跑的替换键。
- 写盘原语：`contracts.upsert_jsonl(path, items, container=…, key_field="utt_id")`
  —— 按 id 替换后**整文件原子重写**（临时文件 + `os.replace`，整表重新强校验）。
  直接对同 id 追加会触发 `UtteranceTable` 唯一性自锁（ValidationError），
  各模块禁止自写"读-过滤-追加"逻辑之外的写盘路径。

## 5. 说话人：段级 schema 与批次归属

- 段级契约 **C2-pre**：`04_dial/diar.jsonl`，行 = `DiarSegment{start, end, speaker}`
  （新增于 contracts.py；`speaker` 未定人填 `unknown`，不置空；段按时间排序）。
- M4/VAD 只负责切分；`speaker` 由 M5 聚类回填；M5 消费 diar.jsonl 后回填
  C2 的 `Utterance.speaker / char_id / overlap`。
- **批次归属（定案）**：M5（说话人嵌入+聚类+回填）**不在 B1 批次**，归入 **B2**。
  B1 出口 `Utterance.speaker` 保持 `None`；diar.jsonl 的 schema 属 B1 冻结范围
  （T4 分离 / T5 ASR 按此 schema 落预分段行，speaker 段填 `unknown`）。

## 6. 修订记录（只增不改名）

| 日期 | 修订 | 影响面 |
|---|---|---|
| 2026-09-28 | 新增 `04_dial/vocals.wav` 槽位；M4 输入口径定为只读人声 | scaffold.EXPECTED_FILES |
| 2026-09-28 | 冻结时间零点/切句规则（规则 7/8）+ `to_absolute_seconds` | contracts.py |
| 2026-09-28 | 字级时间校验（句窗包含 + 时间排序） | contracts.Utterance 校验器 |
| 2026-09-28 | `make_utt_id` 公式 + `upsert_jsonl` 替换写盘原语；`dump_jsonl` 原子化 | contracts.py |
| 2026-09-28 | 新增 C2-pre `DiarSegment/DiarTable`（diar.jsonl）；CLI validate 登记 kind `diar` | contracts.py / cli |

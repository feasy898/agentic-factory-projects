# M9 混音 + 成片合成 spec

> 状态：frozen（T15）。对照 `pipeline/m9_mix.py`、`configs/pipeline.yaml m9 段`、`docs/m9_mix_notes.md`、
> `configs/models.yaml mix-m9 条目` 核验于 2026-09-29。零 GPU 依赖，全离线可验收。

## 1. 职责与边界

只读 `01_media`（bgm/视频/擦除基带）、`04_dial`（vocals/C2）、`07_synth`（C5+合成 wav）、`10_subs`（ASS）、
`11_labels`（labels.json 只读）；**只写** `08_mix` 与 `12_out`；**不写任何冻结契约**（C2/C5 一律只读，
C7 labels.json 只读不写）。
职责边界：M9 只写 GB 45438-2025 的**隐式元数据位**；显式片头 drawtext / C2PA manifest / 音频水印归 M12
（planned），不与 M12 重复绘制。

## 2. 四步流程（T15 定案口径）

1. **人声时间轴** `08_mix/dubbed.<lang>.wav`：C5 逐句把 `07_synth/wavs/<utt_id>.wav` 按 **C2 句窗起点**摆到
   原时间轴（句间隙保留）；`keep_original` 句复刻 `04_dial/vocals.wav` 对应区间（16k→48k）；
   超窗末尾按 C2 句窗裁切并记 `overflow_s`；缺合成 wav **不补静音假装成功**，记 `voice_track.missing`
   （WARN + exit 0；`--strict-missing` 升级 exit 1）。
2. **确定性 ducking** `08_mix/mix.<lang>.wav`：背景（`01_media/bgm.wav`）按 **C2 句窗驱动乘性包络**——
   窗（句窗±`window_pad_s`=0.15s 提前量，语音进前 bgm 已就位）内 **−6dB**（`duck_db`）、句心（C2 窗内）
   **再 −3dB**（`duck_extra_db`，合计 −9dB）；attack 0.05s / release 0.30s / 句心斜坡 `core_ramp_s`=0.02s；
   斜坡贴电平区**外**（attack 在窗前、release 在窗后），使两个电平层级为恒定区、RMS 实测不被斜坡污染。
   **定案：句窗包络而非 ffmpeg sidechaincompress**——后者的压低深度依赖语音瞬时电平，同素材重复运行
   不可复现到 ±1dB，冻结线（对白区间背景电平实测达标）无从判定回归。
3. **EBU R128 响度归一 −16 LUFS**：ffmpeg loudnorm **两趟**（第一趟 `print_format` 拿
   input_i/TP/LRA/thresh/offset，第二趟 `measured_*` + `linear=true` 静态增益）；TP=−1.5dBTP/LRA=11
   （复用 m1_ingest 常量）；linear 结果超 ±1LU 容差 → 如实回落单趟 dynamic 并记录 mode
   （linear 应用趟不打印 normalization_type，故 mode 以复测落容差判定）；**loudnorm 内部固定 192k →
   链尾必须 `aresample=48000`**（否则产物采样率漂移）。
4. **成片合成** `12_out/<ep>.<lang>.mp4`：画面 = M11 已烧字幕成片优先（`-c:v copy` 只换音频，不二次编码），
   否则擦除基带/原片 + 烧 `10_subs/tgt.<lang>.ass`；音轨 AAC 192k/48k/立体声；**AI 隐式标识元数据位**
   （C7 implicit 缺省兜底 `m9.label` 段）：`-movflags +use_metadata_tags` + `-metadata <field>=<value>`，
   落盘后 ffprobe 回读校验；与 M11 产物同路径 → 先写 `.compose.tmp.mp4` 再 `os.replace`，绝不边读边写。

**mp4 元数据坑**（本机 ffmpeg 6.1.1 实测）：`-metadata` 对 mp4 只落已知键，任意键（含 `XMP:…`）被**静默丢弃**；
必须 `-movflags +use_metadata_tags` 才以 `udta/meta/keys+ilst` 落盘并可 ffprobe 回读（非 ASCII 值经 argv 直传正常）。

## 3. 参数（configs/pipeline.yaml `m9` 段）

`duck_db=6.0` / `duck_extra_db=3.0` / `window_pad_s=0.15` / `attack_s=0.05` / `release_s=0.30` /
`core_ramp_s=0.02` / `voice_gain_db=0` / `bgm_gain_db=0`（增益台默认不台）/
`min_ratio_db=8.0`（对白可懂度冻结线）/ `label.metadata_field=XMP:aiGeneratedContent`。
时长基准 master = 01_media 视频时长（ffprobe），缺视频回退 bgm 时长；人声/背景按 master 截断或补零。

## 4. eval

```bash
bash scripts/eval_m9.sh   # = pytest tests/test_m9.py -v（17 用例，B1 合成样本，墙钟 ~76–95s）
```

- 冻结线：①时长差 ≤0.2s（mix/dubbed/成片 vs master）；②响度复测 I∈[-17,-15]（±1LU，**对交付文件实测，
  不只信报告**）；③对白区间背景电平实测达标（报告 core≈−9dB/pad≈−6dB + 交付文件 150Hz 频段对拍
  关-ducking 对照混音）；人声/bg **峰值比 ≥8dB**（可懂度；同步给 RMS 口径——真实语音峰均比 ≈12dB，
  生产看 RMS）；④成片 ASS + 标识位 ffprobe 回读精确匹配 + M11 产物 `-c:v copy` 接入路径；
  ⑤CLI exit 0 / 缺 bgm/C5/C2 exit 1 / --strict-missing / --no-compose / 幂等重跑。

## 5. 编排顺序注意（m9 notes §5）

- M9 在 M11 之后跑 → 走"换音频"路径（不重压字幕）；**M11 在 M9 之后跑会以自己的 `-c:a copy` 覆盖成片音轨**
  ——e2e 口径（`--to m12`）由编排保证 M11 先于 M9 的最终合成（M14/`pipeline run` 落地前由脚本序保证）。
- 多语种：按 `--lang` 分文件（dubbed/mix/report）+ 无后缀副本（同 M8 理由）。

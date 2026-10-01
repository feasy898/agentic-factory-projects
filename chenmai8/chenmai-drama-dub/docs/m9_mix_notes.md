# M9 混音 + 成片合成 —— T15 定案口径与实测注记（2026-09-29）

> 模块实现 `pipeline/m9_mix.py`，验收 `tests/test_m9.py`（`bash scripts/eval_m9.sh`）。
> 本文件是工作注记（非冻结契约）；契约唯一权威仍在 `pipeline/contracts.py`。
> 上游真名一律不入本仓（同 B0 纪律；`docs/` 本就在中性名扫描的 SCOPE_EXCLUDES 内）。

## 1. 任务 T15 与规划 §4 M9 的对应

| 任务 T15 要求 | 落地 | 实测（本机 eval） |
|---|---|---|
| 新人声 + 原背景混音 | C5 逐句把 `07_synth/wavs/*.wav` 按 C2 句窗起点摆到原时间轴（句间隙保留）→ `08_mix/dubbed.<lang>.wav`；`keep_original` 句复刻 `04_dial/vocals.wav` | 3 合成 + 1 keep_original，0 缺失 |
| 背景 ducking 对白区间 −6dB 侧链 | C2 句窗±`window_pad_s`(0.15s) 驱动乘性包络：电平区 −6dB、句心再 −3dB；attack 0.05s 贴窗前、release 0.30s 贴窗后 | pad 区实测 −6.00dB、句心 −8.93dB、窗外 0.00dB |
| EBU R128 归一 −16 LUFS | ffmpeg loudnorm 两趟（测量 → `linear=true` 应用 → 复测）；TP=−1.5dBTP / LRA=11（取 `m1_ingest` 常量）；超 ±1LU 容差如实回落单趟 dynamic 并记 mode | 原始 −16.03 → 交付 −16.01 LUFS（mode=linear） |
| 与画面合成最终 mp4 | `12_out/<ep>.<lang>.mp4`：M11 已烧字幕成片优先（`-c:v copy` 只换音频），否则基带/原片 + 烧 `10_subs/tgt.<lang>.ass` | 成片 8.000s vs master 8.000s（Δ0.000s） |
| ASS 字幕 | 复用 M11 的 `build_ass/style_for_lang` 装配文件，成片烧录（cwd 相对引用滤镜路径） | 抽帧字幕带与基带 diff.max()>30 程序断言 |
| AI 标识位 | C7 `implicit` 元数据位：`-movflags +use_metadata_tags` + `-metadata <field>=<value>`，ffprobe 回读校验 | `XMP:aiGeneratedContent=ep01-en\|澄迈短剧出海测试` 回读一致 |

## 2. 口径定案（为什么这样做）

1. **"bgm 侧链 −6dB" = 确定性语音驱动侧链**，不是 ffmpeg `sidechaincompress`。
   理由：`sidechaincompress` 的压低深度依赖语音瞬时电平与阈值/比率标定，同素材
   重复运行不可复现到 ±1dB，规划 §4 M9 的冻结线（"对白区间背景电平实测达标"）
   无从判定与回归。本模块以 **C2 句窗 + 合成人声实际摆放** 驱动包络（乘性增益、
   向量化梯形窗），电平区/斜坡/窗外全部可精确实测。
2. **"句内再 −3dB"** = 句心（C2 句窗内部）在 −6dB 基础上再 −3dB（合计 −9dB），
   斜坡 `core_ramp_s` 20ms。斜坡贴在电平区**外**（attack 在窗前、release 在窗后），
   使"提前量区 −6dB / 句心 −9dB"两个层级都是恒定电平区，RMS 实测不被斜坡污染
   （T15 开发中即因此修正过一版：斜坡在窗内时右提前量区实测只有 −2.7dB）。
3. **时长基准 master = 01_media 视频时长**（ffprobe），缺视频回退 bgm 时长；
   混音/人声/成片三者的时长差都在报告与 eval 中断言（≤0.2s）。
4. **响度归一两趟**：第一趟 `loudnorm ... print_format=json` 拿
   `input_i/TP/LRA/thresh/offset`，第二趟带 `measured_*` + `linear=true` 静态增益。
   loudnorm 内部固定 192k → 链尾必须 `aresample=48000`（否则产物采样率漂移）。
   `linear=true` 的应用趟**不打印** normalization_type（ffmpeg 6.1.1 实测），
   故 mode 以"复测是否落 ±1LU 容差"判定（`linear` / `dynamic-fallback`）。
5. **成片接入两种路径**：M11 产物（`12_out/<ep>.<lang>.mp4`，已烧字幕）存在时只做
   音频替换与标识位补写（视频流 `-c:v copy` 不二次编码）；否则自行烧 ASS。
   与 M11 产物同路径 → 先写 `.compose.tmp.mp4` 再 `os.replace`，绝不边读边写。
6. **职责边界（M12 不重复）**：M9 只写 GB 45438-2025 的**隐式元数据位**；
   显式片头 drawtext 标识、C2PA manifest 注入、音频水印属 M12（T16+）。

## 3. mp4 自定义元数据的坑（本机 ffmpeg 6.1.1 实测）

- `ffmpeg -metadata <key>=<value>` 对 mp4 **只落已知键**（comment/title 等），
  任意键（含 `XMP:aiGeneratedContent`）**被静默丢弃**；
- 必须加 `-movflags +use_metadata_tags`，键值才以 `udta/meta/keys+ilst`（mdta）
  落盘并可被 `ffprobe -show_entries format_tags` 回读（探针：任意 ASCII 键与
  含冒号键均验证通过；非 ASCII 值经 argv 直传亦正常）。

## 4. 混合质量口径

- 可懂度（规划 §4 M9：人声段/bg **峰值比** ≥8dB）按原文以峰值口径冻结，同时
  在报告同步给出 RMS 口径。占位单音语料上两者同阶（实测 peak 12.27dB /
  rms 14.93dB）；真实语音峰均比 ≈12dB，生产上看 RMS 口径。
- bgm 增益台 `bgm_gain_db` / 人声增益台 `voice_gain_db` 默认 0（不台）；
  素材背景偏响时用 `m9.bgm_gain_db` 台到与对白相称的裕量，报告如实记录。
- 缺合成 wav：不补静音假装成功，记 `voice_track.missing`（WARN + exit 0），
  `--strict-missing` 升级为 exit 1；合成超出句窗的部分按 C2 句窗裁切并记
  `overflow_s`（防止侵占句间隙）。

## 5. 与其他模块的边界

| 方向 | 文件 | 说明 |
|---|---|---|
| 读 | `01_media/bgm.wav`、`01_media/video_*.mp4(_clean)` | M3 / M1 产物 |
| 读 | `04_dial/vocals.wav`、`04_dial/utterances.jsonl` | keep_original 与句窗真值 |
| 读 | `07_synth/synth_plan.<lang>.jsonl`、`07_synth/wavs/*.wav` | C5 + 合成产物 |
| 读 | `10_subs/tgt.<lang>.ass`、`src.ass`、`11_labels/labels.json` | M11 / C7 |
| 写 | `08_mix/{dubbed,mix}.<lang>.wav` + 无后缀副本、`mix_report.<lang>.json` | 音频产物与工作纸 |
| 写 | `12_out/<ep>.<lang>.mp4` | 成片（与 M11 同路径，后跑者覆盖） |
| 不写 | 任何冻结契约 | C2/C5/C7 一律只读 |

管线顺序注意：M9 在 M11 之后跑时走"换音频"路径（不重压字幕）；M11 在 M9 之后
跑时会以自己的 `-c:a copy` 覆盖成片音轨 —— 编排顺序由 M14/`pipeline run` 负责
（e2e 口径 `--to m12` 时 M11 先于 M9 的最终合成）。

## 6. eval 覆盖（tests/test_m9.py，17 用例 exit 0，墙钟约 76s）

纯函数（梯形窗/ducking 电平与斜坡/配置/度量）+ 端到端（产物三件与时长差/
响度复测 ±1LU/ducking 报告实测 + 交付文件 150Hz 频段对拍关-ducking 对照/
人声存在性与 keep_original 复刻/可懂度比值/成片三要素与 AI 标识位回读/
M11 成品接入路径）+ CLI（exit 0、缺 bgm/C5/C2 exit 1、--strict-missing、
--no-compose、幂等重跑）。素材 = B1 合成样本（稳态 bgm + 占位人声；
含故意超窗句、22050Hz 异采样率重采样句、nonverbal keep_original 句）。
实测（2026-09-29，`bash scripts/eval_m9.sh`）：**17 passed exit 0**，墙钟约 76–95s。

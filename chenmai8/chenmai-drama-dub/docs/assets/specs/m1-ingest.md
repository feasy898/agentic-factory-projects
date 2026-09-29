# M1 摄取与预处理 spec

> 状态：frozen。对照 `pipeline/m1_ingest.py` 逐行核验于 2026-09-29。
> 上游依赖：仅系统级 ffmpeg/ffprobe（无 Python 模型依赖）。

## 1. 职责与边界

**做**：任意输入 → 规范化媒体三件 + probe.json + 原件收件（工作区自含）。只读写 `00_raw/` 与 `01_media/`。
**不做**：不分离（M3）、不识别（M4）、不做精响度两通归一（成片级归一属 M9；此处只做摄取级基础归一）。

## 2. 对外契约

- 规范化目标（configs/pipeline.yaml `media` 段为唯一事实源，代码兜底常量 `_DEFAULT_MEDIA`）：
  视频 = mp4/H.264、`{W}x{H}`（等比缩放 + 黑边 pad、`force_divisible_by=2`）、恒定 fps、`setsar=1`、
  yuv420p、`+faststart`、libx264 crf18 veryfast（m1_ingest.py:148-187）。
- 音频两路：
  - **混音底座** `audio_48k.wav`：重采样 mix_sr=48000 立体声 pcm_s16le + **loudnorm 动态单通**基础归一，
    目标 I=`loudness_lufs`(-16)/TP=-1.5dBTP/LRA=11（常量 `TRUE_PEAK_DBTP`/`LRA`，m1_ingest.py:48-49；
    M9 直接 import 复用）；
  - **识别用** `audio_16k.wav`：**由 48k 产物降采样派生**（非从源直转），保证两路同源同增益
    （`derive_audio_asr`，m1_ingest.py:205-208）。
- `01_media/probe.json`：源与各产物流清单/时长/分辨率/音轨数 + loudnorm 输入实测
  （input_integrated_lufs 等，正则抓 summary）+ 时长偏差表（`max_abs_delta_s`）。
- 容错：纯音频输入 → lavfi 黑底补视频轨（长度以音频为准 +50ms 余量防切尾帧）；无音轨 → 跳过两路音频产物，
  probe.json 如实记录 `audio=skip(源无音轨)`；既无视频也无音轨 → IngestError。
- loudnorm 原轨处理注记：视频容器内音轨仅统一容器编码（AAC 192k/48k/立体声），不做响度处理——
  该轨最终被 M9 混音替换。

## 3. CLI（冻结形态）与退出码

```
python -m pipeline.m1_ingest --ep ep01 --in clips/ep01_raw.mp4 [--jobs-dir <dir>]
# 0 成功；1 媒体处理失败（IngestError 携 stderr 尾 2000 字符）；2 用法错误
```

子进程统一 utf-8 解码 + timeout（默认 1800s，ffprobe 300s）；`shutil.which` 找不到 ffmpeg 即 IngestError。

## 4. eval

```bash
.venv/Scripts/python.exe -m pytest tests/test_m1.py    # → 7 passed
```

通过线（§4 M1 冻结）：输出存在；ffprobe 断言分辨率/fps/采样率；时长差 ≤0.2s。
门禁固化：gate_b1 ②。注意 pytest 子进程需 PATH 可解析 ffmpeg（gate_b0 ① 有 FFMPEG_FALLBACK_DIRS 兜底注入）。

## 5. 重生成注意事项

- `durations.max_abs_delta_s` 是 M3（输出时长=输入）与 M9（master 时长基准）的口径根。
- 中文路径：ffmpeg 子进程经 argv 直传路径在本机实测可用；但 cv2/facemesh 系不行（见 m2/m5 spec）。

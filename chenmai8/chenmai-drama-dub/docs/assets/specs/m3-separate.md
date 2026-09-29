# M3 人声/背景分离 spec

> 状态：frozen。对照 `pipeline/m3_separate.py` 与 `configs/models.yaml`（audiosplit/audiosplit-cuda 条目）
> 核验于 2026-09-29。上游组件中性名 **audiosplit**（分离框架 + karaoke 系 mel-band roformer 权重）。

## 1. 职责与边界

**做**：`01_media/audio_48k.wav`（缺失回退 `audio_16k.wav`）→ 人声 + 背景两轨 + 分离报告。
只读写 `01_media/` 与 `04_dial/`。
**不做**：不识别（M4）、不混音（M9 只消费 bgm 与人声槽位）。

## 2. 对外契约（B1 冻结槽位）

| 产物 | 路径 | 口径 |
|---|---|---|
| 人声 | `04_dial/vocals.wav` | **16k 单声道 pcm_s16le**（`VOCALS_SR=16000`）——M4 唯一识别输入；**不落 01_media**（B1 冻结：混音含 BGM/音效会污染识别/对齐/情绪） |
| 背景 | `01_media/bgm.wav` | 与分离输入同采样率/声道（M9 混音底座配套） |
| 报告 | `04_dial/separate.json` | 设备/模型/耗时/时长/RMS 判据实测（非冻结契约） |

- 模型内部固定 44.1k 处理 → 产物经 ffmpeg 重采样回输入口径，并 `apad`/`-t` 对齐输入时长
  （eval ①：输出时长=输入 ±0.2s）。
- RMS 判据（§4 M3 eval ② 冻结阈值）：有声区间（生产用 M2 字幕区间；eval 用合成真值）人声 RMS ≥ 总轨 RMS−6dB
  （`VOICED_MARGIN_DB=6.0`）；纯背景区间人声 RMS ≤ −15dBFS（`BGMONLY_CEILING_DBFS=-15.0`）。
  真值经 `--truth` 注入（JSON `{"voiced":[[s,e]…],"bgm_only":[[s,e]…]}`）；缺省跳过判据并记 null。

## 3. 设备双路径（models.yaml `routing.separation`）

| 路由 | 组件 | 行为 |
|---|---|---|
| `cpu`（默认） | `audiosplit` | `CUDA_VISIBLE_DEVICES=""` 强制后再 import torch（防 CUDA 构建抢跑）；**120s 分块**（防内存膨胀）；**threads=16**（windev 实测定值：单窗 65s@64thr → 11.2s@16thr，默认全核线程互踩） |
| `cuda` | `audiosplit-cuda` | 整轨处理（chunk_s=null）；本机 torch 无 CUDA 时报错退出（GPU 路径待 anolis-gpu-01 冒烟，volta_status pending 如实登记） |

权重：`models/audiosplit/mel_band_roformer_karaoke_aufr33_viperx_sdr_10.1956.ckpt`
（ckpt sha256 前缀登记于 models.yaml；权重缓存不入公开仓）。

## 4. CLI 与 eval

```
python -m pipeline.m3_separate --ep ep01 [--device cpu|cuda] [--jobs-dir] [--model] [--chunk-s] [--truth]
# 0 成功；1 分离失败/设备不可用；2 用法错误
```

```bash
.venv/Scripts/python.exe -m pytest tests/test_m3.py    # → 9 passed
```

通过线（冻结）：①输出存在且时长=输入（±0.2s）；②RMS 判据；③60s 素材 CPU ≤10 分钟。
最近记录：T13 门 ④ 9 passed 891.04s（真模型 CPU 推理，全门禁最慢项——单次 724–1932s 随共享负载浮动，
gate_b1 环境注记）。

## 5. 重生成注意事项

- 依赖：audiosplit 分离框架 0.47.0（真实发行名仅登记 requirements.txt）+ onnxruntime==1.30.0（import 期硬依赖）+
  audioread==3.1.0（引擎 uvr_lib 兼容层硬依赖，librosa 1.0 未连带）——三者缺一 import 即崩，requirements 头注有记录。
- torch 线程帽教训（REGENERATE §6.2）源于本模块；改 threads 前先复测。
- 下游契约：M4 只读 `04_dial/vocals.wav`；M9 读 `01_media/bgm.wav`——两槽位名不可改。

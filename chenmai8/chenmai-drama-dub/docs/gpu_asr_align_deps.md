# GPU 依赖安装记录 —— asr_align 服务（:9001，M4）

> 本文件是公开仓的**依赖安装记录**（与 requirements.txt 同口径）：GPU 侧独立 venv 的
> 真实分发名与来源对照，用于复现部署。公开仓其余代码/脚本一律用中性内部名
> （`configs/models.yaml` 字段名），映射见内部台账 oss-manifest 附录A。

## 为何独立 venv

T3 冒烟（`data/gpu_smoke_report.json` 第 4 项）实测：识别/对齐两个模型的
transformers 原生架构支持需要 **transformers>=5.13**；而 TTS/口型引擎组已钉在
transformers 4.52.1（`/data/xdng/venv`）。两组依赖不可共存 → asr_align 服务使用
独立 venv `/data/xdng/venv-asr`（脚本 `gpu/setup_asr_venv.sh`）。

## venv 组成（/data/xdng/venv-asr，python 3.11.6）

| 包 | 版本 | 说明 |
|---|---|---|
| torch / torchaudio | 2.5.1+cu118 | Volta(sm_70) 实测可用档；复用主 venv（.pth 追加 sys.path），不重下 2.3GB 轮子 |
| transformers | 5.13.0 | 原生 `qwen3_asr` 架构（`AutoModelForMultimodalLM` + `AutoModelForTokenClassification`）下限 |
| fastapi / uvicorn / httpx / python-multipart | 0.141.1 / 0.53.0 / 0.28.1 / 0.0.32 | 服务框架与 multipart 上传 |
| soundfile / librosa | 0.14.0 / 0.11.0 | wav 读取与重采样 |
| funasr | 1.4.16 | emo-tag（SenseVoiceSmall）推理框架（代码 MIT） |

镜像：pip=阿里云（清华镜像对本机 403，实测）；HF=`https://hf-mirror.com`；
**权重下载主路 = ModelScope 国内直连（同 ID 仓库，实测 11.8MB/s）**，HF 镜像兜底
（Xet 系仓库须 `HF_HUB_DISABLE_XET=1`：hf-mirror 不代理 Xet CAS，实测 401，且 /resolve
302 到的 HF CDN 在本机路由超时频发，详见 data/asr_align_deploy_report.json）。

## 模型权重（主路 ModelScope 直连，HF 镜像兜底；目录布局见 /data/xdng/etc/model_ids.env）

| 中性名 | 真实仓库 ID（ModelScope 与 HF 同 ID） | 本机目录 | sha256-16 | 说明 |
|---|---|---|---|---|
| asr-core | `Qwen/Qwen3-ASR-1.7B`（T3 已下载） | /data/xdng/models/asr-core | 2db53c7d81bd9b8c | fp16 转写；Apache-2.0 |
| align-core | `Qwen/Qwen3-ForcedAligner-0.6B-hf`（备选非 -hf 版） | /data/xdng/models/align-core | 00568245ceca5af1 | 字级对齐；11 语种无阿语；Apache-2.0；transformers 原生 token 分类头 |
| emo-tag | `FunAudioLLM/SenseVoiceSmall` | /data/xdng/models/emo-tag | 833ca2dcfdf8ec91 | 情绪+事件；FunASR 模型许可（可商用，保留署名） |

运行时注入（GPU 机本地文件，不入公开仓）`/data/xdng/etc/model_ids.env`：

```bash
ASR_DIR=/data/xdng/models/asr-core
ALIGN_ID=Qwen/Qwen3-ForcedAligner-0.6B-hf
ALIGN_ID_ALT=Qwen/Qwen3-ForcedAligner-0.6B
EMO_ID=FunAudioLLM/SenseVoiceSmall
EMO_PKG=funasr
ALIGN_SRC=modelscope    # modelscope（主路，国内直连）| hf（镜像兜底）
EMO_SRC=modelscope
```

## 关键 API（transformers 原生，无需第三方对齐包）

- 转写：`AutoProcessor.apply_transcription_request(audio, language)` →
  `AutoModelForMultimodalLM.generate` → `processor.decode(ids, return_format="parsed")`。
- 对齐：`processor.prepare_forced_aligner_inputs(audio, transcript, language)` →
  `AutoModelForTokenClassification(**inputs)` →
  `processor.decode_forced_alignment(logits, input_ids, word_lists, timestamp_token_id)`
  → `[{text, start_time, end_time}]`（`timestamp_token_id` 取自模型 config）。
- 情绪：`funasr.AutoModel(model=<emo-tag 目录>)` → `generate(input=wav, language="auto",
  use_itn=True)` → 富文本 `<|lang|><|EMO|><|EVENT|>...` 自行解析。

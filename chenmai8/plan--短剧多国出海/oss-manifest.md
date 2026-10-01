# OSS Manifest —— 上游开源件清单（2026-09-28 核实版）

> 本文件是**内部文件**（不进公开仓）。公开仓库内不得出现本表中的任何上游项目名与许可证声明，
> 一律使用附录A 的中性内部名；许可证合规由法务统一处理。
> 核实方式：逐项 WebFetch GitHub/HF 页面或 GitHub API（License 字段/README 原文）。
> 标注"(原文)"的为页面原文引述。

## 1. 代码与管线组件

| 上游项目 | URL | 许可证（核实结果） | 我们用它什么 | 商用授权需求 | 替代备选 |
|---|---|---|---|---|---|
| python-audio-separator | https://github.com/nomadkaraoke/python-audio-separator | MIT（README 声明；使用 UVR 系模型需署名 UVR 及模型作者） | M3 人声/背景分离（mel-band-roformer karaoke 模型，SDR 12.98） | 代码无限制；**模型权重许可逐个记录**（多数 UVR 系可商用，部分收集的第三方权重例外，D1 逐个核对权重页） | Demucs (MIT, Meta) |
| Demucs | https://github.com/facebookresearch/demucs | MIT | M3 备选分离器 | 无 | — |
| PaddleOCR | https://github.com/PaddlePaddle/PaddleOCR | Apache-2.0 | M2 硬字幕 OCR（3.7.0，PP-OCRv5/v6，CPU 可跑） | 无 | EasyOCR(Apache-2.0) |
| video-subtitle-remover | https://github.com/YaoFANGUK/video-subtitle-remover | **Apache-2.0（GitHub API spdx_id 核实，非 GPL）**，13k stars | M11 字幕擦除（Windows 预打包 + CLI；inpaint 默认 LAMA） | 代码无限制；**内嵌第三方 inpaint 权重条款需逐个记录**（LAMA=Apache-2.0 系；STTN/ProPainter 权重用途条款存疑，D1 核对，不合规则不随仓分发、仅运行时下载） | 自管 LAMA 管线 / OpenCV inpaint |
| TransNetV2 | https://github.com/soCzech/TransNetV2 | MIT | M5 镜头切分（PyTorch 推理权重官方提供） | 无 | PySceneDetect(BSD) |
| Light-ASD | https://github.com/Junhua-Liao/Light-ASD（CVPR 2023 官方仓；注意网上常被写错的 wanghao9610 地址已 404） | MIT | M5 主动说话人检测 | 无（预训练权重随仓分发，D1 复核权重页声明） | TalkNet（**已弃**：仓库归档、条款模糊） |
| MediaPipe | https://github.com/google-ai-edge/mediapipe | Apache-2.0 | M5 人脸/头部姿态（正脸近景判定） | 无 | OpenCV Haar(粗) |
| pyannote-audio (community-1) | https://github.com/pyannote/pyannote-audio ；权重 https://huggingface.co/pyannote/speaker-diarization-community-1 | 代码 MIT；**权重 gated**（HF 账号+接受用户条件后可下载） | M5 可选增强（说话人区分对比基线） | 权重自身条款以 HF 模型卡为准（D1 登记账号接受记录）；**因 gated，不作为默认依赖** | 3D-Speaker CAM++（默认） |
| 3D-Speaker | https://github.com/modelscope/3D-Speaker | Apache-2.0 | M5 说话人嵌入+聚类（CAM++，ModelScope 免 gate 直下） | 无（模型卡逐个确认，CAM++ 常见模型 Apache-2.0） | WeSpeaker(Apache-2.0) |
| AudioSeal | https://github.com/facebookresearch/audioseal | **MIT 含模型权重**（2024-04 起全 MIT，README 原文"you can use AudioSeal in commercial application too"） | M12 音频水印（16-bit 负荷）+ 检测器（验证工具） | 无 | — |
| c2patool / c2pa-python | https://github.com/contentauth/c2pa-rs 、https://github.com/contentauth/c2pa-python | MIT OR Apache-2.0（双许可，D1 以 LICENSE 文件复核登记） | M12 C2PA 内容凭证注入与校验 | 无 | — |
| FFmpeg | https://ffmpeg.org （本机 6.1.1 gyan essentials build，**已核实含 libass/libfribidi/libharfbuzz/libfreetype/fontconfig**） | LGPL-2.1+（gyan build 含 GPL 组件，仅本地使用不分发则无碍；若分发二进制须法务把关） | M1 预处理/M9 混音/M11 ASS 渲染（含阿语 RTL shaping）/M12 元数据 | 分发才需评估 | — |
| FunASR | https://github.com/modelscope/FunASR | 代码 MIT（部分组件 BSD/其他，以仓库为准） | M4 SenseVoice 的运行框架 | 无 | — |

## 2. 模型权重（HF/ModelScope）

| 上游模型 | HF/MS ID | 许可证（核实结果） | 我们用它什么 | 商用授权需求 | 替代备选 |
|---|---|---|---|---|---|
| **IndexTTS-2.5** | https://huggingface.co/IndexTeam/IndexTTS-2.5 ；https://github.com/index-tts/index-tts | **bilibili 模型使用许可协议**（LICENSE 原文核实）：免费商用；**月活>1亿 或 年营收>10亿元（任一达标）须另行书面授权**（联系 indexspeech@bilibili.com）；须保留版权声明与协议副本；衍生品分发需附"未经认可"免责声明；中国法管辖。**规模条款对我们（初创/团队规模）无影响** | M7 主力 TTS：zh/en/ja/es/ar，音色-情绪分离（**情绪参考可来自不同人**=情绪迁移核心用法）、8 情绪向量、duration_factor 0.5–2.0 语速控制 | 无（我们规模远低于阈值）；保留 LICENSE 副本于内部仓 | IndexTTS-2(fp16，zh/en)；Qwen3-TTS(es)；VoxCPM2 |
| Qwen3-ASR | https://huggingface.co/Qwen/Qwen3-ASR-0.6B 、`-1.7B`（含 -hf） | Apache-2.0 | M4 中文 ASR | 无 | whisper-large-v3 (MIT) |
| Qwen3-ForcedAligner | https://huggingface.co/Qwen/Qwen3-ForcedAligner-0.6B | Apache-2.0；11 语种（zh,en,yue,fr,de,it,ja,ko,pt,ru,es）**不含阿语** | M4 字级时间对齐（AAS≈42.9ms，优于 WhisperX） | 无 | whisperX(BSD-2)；阿语字符比例估算（MVP 内置） |
| SenseVoice-Small | https://huggingface.co/FunAudioLLM/SenseVoiceSmall | 代码 MIT；**权重 FunASR 模型开源协议**（按条款可商用，须遵守第 2.2 条署名/模型名保留；微调衍生可私有） | M4 情绪标签(7类)+声音事件（哭/笑/掌声/叹气） | 遵守署名条款即可 | emotion2vec 系 |
| CAM++ (speaker) | ModelScope `iic/speech_campplus_sv_zh-cn_16k-common` | Apache-2.0（模型卡，D1 逐模型确认） | M5 说话人嵌入 + M7 音色相似度评测 | 无 | pyannote embedding / WeSpeaker |
| Hy-MT2-1.8B / 7B | https://huggingface.co/tencent/Hy-MT2-1.8B 、`Hy-MT2-7B`、`Hy-MT2-30B-A3B` | Apache-2.0；33 语种含阿语；术语干预+背景信息+格式保留模板（模型卡核实）；**Hy-MT2（2026-05）是 HY-MT1.5（2025-12-30）的后代，基座选型已切换** | M6 翻译主模型（本地）+ **DubMT LoRA 基座（1.8B）** | 无 | OpenAI 兼容 API 抽象层（兜底） |
| Qwen3-TTS | https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B/1.7B（Base/CustomVoice/VoiceDesign） | Apache-2.0；**已开放权重**（概念文档"仅 API"过时）；10 语种（含 es，**无 ar**） | M7 备选 TTS（es）+ VoiceDesign 变体能力 | 无 | — |
| VoxCPM2 | https://huggingface.co/openbmb/VoxCPM2 ；https://github.com/OpenBMB/VoxCPM | **Apache-2.0（README 原文核实"free for commercial use"）**；2B；30 语种+中文方言；~8GB；2026-04 发布 | M7 东南亚语种扩展 + **阿语备选** | 无（**Volta 兼容未声明，D1 冒烟定案**） | — |
| MuseTalk 1.5 | https://github.com/TMElyralab/MuseTalk | **MIT，且官方权重"available for any purpose, even commercially"（README 原文）**；第三方组件（whisper/ft-mse-vae/dwpose 等）按各自许可；测试数据仅限非商用研究 | M10 主力口型（256×256 嘴区；**官方实测 V100 30fps+ 实时**） | 无 | LatentSync |
| LatentSync 1.6 | https://github.com/bytedance/LatentSync | Apache-2.0（README 核实）；1.6=512×512/推理 18GB；1.5=256×256/8GB | M10 重点镜头精修口型 | 无 | MuseTalk（默认主力，本项为增强） |
| SenseVoiceSmall 之外的 ASR 兜底 | openai/whisper-large-v3 | MIT（whisper 代码）；权重 Apache-2.0（模型卡） | M15 回听 WER 的目标语 ASR | 无 | — |
| ~~Wav2Lip~~ | https://github.com/Rudrabha/Wav2Lip | **README 原文："can only be used for personal/research/non-commercial purposes"；LRS2 训练权重商业使用严格禁止** | **禁用**（不得进入任何分发物与演示管线） | — | MuseTalk / LatentSync |

## 3. 标准与规范（非软件）

| 项 | 说明 | 用途 |
|---|---|---|
| GB 45438-2025《网络安全技术 人工智能生成合成内容标识方法》 | 强制性国标，2025-02-28 发布、2025-09-01 实施；配套四部门《人工智能生成合成内容标识办法》 | M12 隐式标识（元数据）与显式标识（片头提示）的实现依据 |
| C2PA 规范 | 内容凭证/来源溯源开放标准 | M12 manifest 结构 |
| EBU R128 | 响度归一 | M9（-16 LUFS） |

## 4. 特别标注（法务与演示须知）

1. **IndexTTS-2.5 规模条款**：月活>1亿或年营收>10亿元需另行授权——我们与客户初期远低于阈值；若未来服务超大规模客户需向 bilibili 申请（indexspeech@bilibili.com）。
2. **Wav2Lip 类非商用项**：Wav2Lip（含 LRS2 权重）非商用，**禁用**；同类风险还有部分人脸检测预训练权重（S3FD 等，MuseTalk 第三方组件中已含，仅随 MuseTalk 管线使用、不单独分发）。
3. **gated 权重**：pyannote 权重需 HF 账号接受条款——为避免供应链与分发复杂性，默认链路不依赖它。
4. **权重再分发**：公开仓不捆绑任何模型权重，只写下载占位符+校验和；各权重许可随下载行为由使用者自行接受。
5. **GPL 红线**：核心代码不引入 GPL 组件（VSR 已核实 Apache-2.0，可用；ffmpeg 为 LGPL 基线，仅本地/服务端使用）。

## 5. Volta（V100S-32GB, sm_70）兼容性核实汇总

| 组件 | Volta 结论 | 依据/动作 |
|---|---|---|
| MuseTalk 1.5 | **官方支持**（README 原文：real-time 30fps+ on NVIDIA Tesla V100） | 低风险，口型主力 |
| LatentSync 1.6 | 未声明；SD/AnimateDiff 系 fp16 理论可行；18GB<32GB | D1 冒烟；降级 1.5(8GB) |
| IndexTTS-2.5 | **风险点：默认 bf16，Volta 无 BF16**；README 仅给 use_fp16(IndexTTS-2)/use_bf16(2.5) | D1 实测 fp32/fp16 参数；降级 IndexTTS-2(fp16) 或备选引擎 |
| Qwen3-ASR/ForcedAligner | 0.6–1.7B 小模型，transformers+fp16+SDPA 可行；**不可用 FA2** | D1 定 torch/transformers 版本 |
| VoxCPM2 | 未声明；要求 PyTorch≥2.5/CUDA≥12.0（sm_70 仍受 CUDA12 支持） | D1 冒烟，失败仅砍非演示语种 |
| CAM++/SenseVoice/TransNetV2/Light-ASD/AudioSeal | 小模型/支持 CPU | 低风险（可本机 CPU 兜底） |
| VSR（GPU 加速） | 官方 CUDA11.8 包支持计算能力 3.5–8.9（含 sm_70）；CUDA12.8 包支持 5.0–9.0+ | 本机 CPU 默认；GPU 机加速为可选 |
| vLLM | 官方线 cc≥7.0 压线可用，但新版 V1 引擎依赖 FA 生态不保证 | **全部推理不依赖 vLLM**（transformers/原生推理）；vLLM 仅作为远期优化实验 |

## 附录A 中性内部名映射（公开仓统一使用，禁止出现上游名）

| 中性名 | 对应上游（仅本文件可见） |
|---|---|
| audiosplit | python-audio-separator / Demucs |
| asr-core | Qwen3-ASR |
| align-core | Qwen3-ForcedAligner |
| emo-tag | SenseVoice (FunASR) |
| voxdia | 3D-Speaker CAM++ / pyannote |
| actspk | Light-ASD |
| facemesh | MediaPipe |
| shot-cut | TransNetV2 |
| cap-ocr | PaddleOCR |
| cap-clean | video-subtitle-remover |
| mt-core | Hy-MT2 |
| dub-tts | IndexTTS-2.5 |
| alt-tts-a | Qwen3-TTS |
| alt-tts-b | VoxCPM2 |
| lip-fast | MuseTalk 1.5 |
| lip-pro | LatentSync 1.6 |
| audmark | AudioSeal |
| provenance | C2PA toolchain |
| isomt-lora | DubMT（自训 LoRA） |

# tts 服务（:9002）依赖安装记录 —— T12 执行（2026-09-29）

> 本文件属依赖安装记录（gate_b0 中性名扫描豁免口径，同 `gpu_asr_align_deps.md`）：
> 上游真实分发名只登记于此；仓内其余公开文本一律用中性名
> （`dub-tts` / `dub-tts-base` / `alt-tts-a` / `alt-tts-b`）。

## 1. 真实分发名对照（仅本文件维护）

| 中性名 | 真实 ID / 分发名 | 说明 |
|---|---|---|
| dub-tts | 引擎仓 `index-tts`（检出 ee40fa7）+ 包 `indextts.infer_v2_5`（类 `IndexTTS2`）；权重 HF `IndexTeam/IndexTTS-2.5` | 主力引擎：zh/en/ja/es/ar；**音色参考（spk_audio_prompt）与情绪参考（emo_audio_prompt）分离**，emo_alpha 控强度，duration_factor 控语速；D1 fp32 定案（引擎仅暴露 use_bf16 开关，Volta 无 bf16 → use_bf16=False 即 fp32；无 fp16 档）；bilibili 模型使用协议（商用免费，月活>1亿/年营收>10亿需书面授权，保留版权声明与协议副本） |
| dub-tts-base | 同仓上一代引擎（fp16，仅 zh/en） | 备选链 2 节点；权重未部署（/data/xdng/models/dub-tts-base 不存在），链上如实 skip |
| alt-tts-a | HF `Qwen/Qwen3-TTS-1.7B-CustomVoice`（Apache-2.0） | 备选 A：en/es；权重未部署（/data/xdng/models/alt-tts-a 不存在），链上如实 skip；部署时装载参数经 env 注入（TTS_ALT_A_MODULE/CLASS，真名不进公开仓代码） |
| alt-tts-b | 分发 `voxcpm`（0.0.post1+gf772e498a，主 venv pip 已装）；权重 HF `openbmb/VoxCPM2`（Apache-2.0） | 备选 B：30+ 语种含 ar；参考克隆模式（单路参考=音色参考，**无独立情绪参考通道** → 服务如实回 `emo_ref_used=false`）；D1 冒烟 11.7s/句 |

## 2. GPU 机部署口径（T12 已执行，2026-09-29）

- **venv**：主 venv `/data/xdng/venv`（torch 2.5.1+cu118 + transformers 4.52.1，
  TTS/口型组同组）；服务依赖补装 `python-multipart`（阿里云镜像，T12 实装）。
- **权重**（D1 冒烟时已落盘，本批只核验不重下）：`/data/xdng/models/dub-tts`（11 文件，
  含 config.yaml/gpt.pth/s2mel.pth/codec.pth/qwen0.6bemo4-merge 情绪编码器）；
  `/data/xdng/models/alt-tts-b`（9 文件）。引擎检出仓 `/data/xdng/smoke/repos/index-tts`
  （ee40fa7，服务经 sys.path 动态加载；路径由 env `TTS_DUB_REPO` 覆盖）。
  HF 资产缓存：`~/.cache/huggingface/hub`（bigvgan_v2_22khz_80band_256x 声码器、
  w2v-bert-2.0 等，D1 首载已缓存；服务侧 HF_HUB_DISABLE_XET=1 防意外联网踩 Xet）。
- **服务**：`bash gpu-services/tts/run_gpu.sh start`（127.0.0.1:9002 常驻；dub-tts
  fp32 常驻 cuda:0（TTS_DEVICE）；alt-tts-b 懒加载落 cuda:1（TTS_ALT_B_DEVICE），
  **与 lip-pro 同卡互斥，lip-pro 起来前先停本服务**）。部署核验：`bash gpu/setup_tts_service.sh`。
- **隧道**：本机 `TUNNEL_LOCAL_PORT=9002 TUNNEL_REMOTE_PORT=9002 bash ops/tunnel_gpu.sh start`。

## 3. T12 冒烟实测（2026-09-29，回填依据）

- `/health`：loaded.dub-tts=true；weights_present {dub-tts:true, dub-tts-base:false,
  alt-tts-a:false, alt-tts-b:true}；routing 三语种链与 models.yaml 冻结镜像逐字一致。
- 装载：dub-tts fp32 装载 35.4s；常驻显存 **7062 MiB（cuda:0）**，与 :9001 asr_align
  （7180 MiB）及共享 vllm 进程同卡共存（32GB 卡余 ~8.5GB）。
- **双参考合成（本机经隧道）**：SAPI zh 中性句 voice_ref(7.2s) + SAPI zh 质问句
  emo_ref(6.0s) → 合成英文句 "What do you actually want? Say it clearly."
  → wav 3.553s/22050Hz，emo_ref_used=true；服务端日志行
  `[tts] SYNTH utt_id=ep01-u00000000 engine=dub-tts lang=en voice_ref=voice_ref.wav(7.202s@16000) emo_ref=emo_ref.wav(6.019s) emo_ref_used=True ...`。
- 推理耗时：首句 5.28s（含情绪编码器首载），热身后 3.2–3.4s/句（V100S，fp32）。
- 路由：dry_run en/es/ar 链解析=冻结镜像；显式 alt-tts-a（权重未部署）→ HTTP 503
  + attempts 如实记 "weights 未部署"（不伪装成功）；voice-only（无 emo_ref）→
  emo_ref_used=false。
- eval：`bash scripts/eval_m7.sh` → **11 passed exit 0（零 skip，2026-09-29）**
  （4 离线：C 出口纯函数/静音拒收/参数校验/桩服务 payload 契约；7 在线：health
  路由镜像/双参考合成+时长对账/voice-only/三语种 dry_run/未知引擎 400）。

## 4. 版本冻结位

- dub-tts：引擎仓 ee40fa7（2026-08-18）/ 权重 HF snapshot 见
  `~/.cache/huggingface/hub/models--IndexTeam--IndexTTS-2.5`；fp32 定案不变。
- alt-tts-b：分发 0.0.post1+gf772e498a（@f772e49）。
- 本批未实测：alt-tts-b 经服务懒加载的合成链路（GPU-1 有并行租户任务占 17–19GB，
  不为其叠加 ~8GB 懒加载权重以免挤爆同卡；D1 直连冒烟 ok 的结论维持）——
  首次显式 `engine=alt-tts-b` 请求时懒加载，成败见 attempts 如实回传。
- dub-tts-base / alt-tts-a：权重未部署，volta_status 维持 pending（纪律：未实测不写 ok）。

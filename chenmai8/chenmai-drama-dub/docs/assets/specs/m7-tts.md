# M7 情绪迁移合成 spec（双参考 TTS 接口，客户端 + GPU 服务 :9002）

> 状态：frozen（T12）。对照 `gpu-services/tts/service.py`、`pipeline/tts_client.py`、
> `docs/tts_service_deps.md`、`configs/models.yaml`（dub-tts 系条目 + routing.tts）核验于 2026-09-29。
> 引擎中性名：dub-tts（主力）/ dub-tts-base / alt-tts-a / alt-tts-b。

## 1. 职责与边界

**做**：按 C5 合成一句目标语台词：**音色参考与情绪参考分离**（voice_ref=角色干净人声样本 05_cast/voicebank；
emo_ref=原片该句人声 04_dial/emo_refs——**音色与情绪可来自不同说话人，这是情绪迁移的核心用法**）；
引擎链路由与降级；实测时长回传。`keep_original=true` 的 nonverbal 句不进本模块（M9 直接复刻原人声）。
**不做**：不做句窗/时间轴处理（合成是"无时间轴输入"的生成，服务只回产出 wav 实际时长；句窗归 M8/M9）。

## 2. 双参考接口（冻结口径）

### 2.1 请求 `POST /v1/tts`（multipart）

| 字段 | 约束 | 说明 |
|---|---|---|
| `text` | 必填非空，≤500 字符（`MAX_TEXT_CHARS`） | 目标语台词 |
| `voice_ref` | **必填文件** | 服务端逐参考解码校验：解码失败/空文件 400、**时长 0.3–30s 窗**（`MIN/MAX_REF_SECONDS`）、静音（峰值 <1e-4）拒收、>25MB 413 |
| `emo_ref` | 可选文件 | 同样校验；缺省=只用音色参考 |
| `lang` | en/es/ar/zh/ja（默认 en） | |
| `emo_alpha` | float ∈[0,1]（默认 0.7） | C5 域强校验（客户端先挡一层给可读报错） |
| `duration_factor` | float ∈[0.5,2.0]（默认 1.0） | C5 域强校验 |
| `engine` | `auto`（按语种链）或显式引擎名（未知 400） | |
| `utt_id` | 可选 | 服务端 SYNTH 日志追踪用 |
| `dry_run` | bool | 只做路由解析与参考校验，不占 GPU |

### 2.2 响应

```
{ engine, chain, attempts:[{engine, ok, error?|infer_s, emo_ref_used?, skipped?}],
  wav_b64, wav_bytes, sr, duration_s,          # duration_s = 产出 wav 实测时长（float 3 位，C 出口）
  request:{lang, emo_alpha, duration_factor, voice_ref, emo_ref, voice_ref_s, emo_ref_s,
           emo_ref_used, utt_id, text_chars},
  timing:{total_s}, versions:{service, <engine>, torch, device} }
```

- 全链失败 → HTTP 503 + `attempts` 全量附上（**链节点失败/权重未部署记入 attempts 如实 skip，不静默伪装成功**；
  显式选中未部署引擎也回 503+attempts——T12 冒烟实测）。
- **服务端 SYNTH 日志行**（双参考确认）：`[tts] SYNTH utt_id=… engine=… lang=… voice_ref=<文件名>(<实测秒>s@<sr>)
  emo_ref=<文件名>(<实测秒>s) emo_ref_used=<bool> emo_alpha=… duration_factor=… text_len=… -> wav <秒>s/<sr>Hz infer=<秒>s`。
- 备选引擎无情绪通道 → **如实回 `emo_ref_used=false`**（音色参考继续生效），不伪造情绪迁移
  （dub-tts `emo_ref=True`；dub-tts-base/alt-tts-a/alt-tts-b 均 `emo_ref=False`，service.py ENGINES 注册表）。

### 2.3 引擎链路由（`resolve_chain`，models.yaml `routing.tts` 冻结镜像）

- `en: [dub-tts, dub-tts-base, alt-tts-a, alt-tts-b]`；`es: [dub-tts, alt-tts-a, alt-tts-b]`；
  `ar: [dub-tts, alt-tts-b]`；未列出语种走 `DEFAULT_CHAIN=["dub-tts"]`；显式 engine → 单引擎。
- 装载策略：dub-tts **启动即载**（fp32 常驻 cuda:0，`use_bf16=False` 定案、纯 torch 声码器路径
  `use_cuda_kernel=False`，service.py:148-167）；备选引擎**懒加载**（首次命中才装载；
  权重未部署 → RuntimeError → 链节点 skip；dub-tts-base/alt-tts-a 装载参数 env 缺席也如实报缺）。
- 语种不在引擎支持表 → attempts 记"语种不在支持表"后继续下一节点。
- alt-tts-b 落 cuda:1（`TTS_ALT_B_DEVICE`）——**与 lip-pro 同卡互斥**（单路参考克隆模式，无独立情绪通道）。

### 2.4 客户端（`pipeline/tts_client.py`）

- env `M7_TTS_URL` 默认 `http://127.0.0.1:9002`；timeout **600s**（主力 fp32 首装 35.4s + 懒加载余量）；
  retries=2×2s。
- C 出口（冻结口径）= **合成 wav + 实际时长**：`synth_response_to_wav` 纯函数（eval 可离线测）落盘后用
  soundfile 复测时长，与服务端 `duration_s` **对账 ±0.05s**（差即 TtsError"疑似传输截断"）；
  产出空/静音拒收。M8 的 `meas_dur` 来源即本出口。
- CLI：`python -m pipeline.tts_client --text … --voice-ref a.wav [--emo-ref b.wav] --lang en --out out.wav
  [--emo-alpha] [--duration-factor] [--engine] [--utt-id] [--dry-run]`；0 成功 / 1 错误 / 2 用法。

## 3. 合成参数语义（主力引擎 `_synth_dub`）

`spk_audio_prompt=voice_ref`、`emo_audio_prompt=emo_ref`、`emo_alpha`（强度）、`duration_factor`（语速）、
`text_normalization=False`（D1 口径：文本正则前端依赖境内不可得，关闭不影响骨干）、`verbose=False`。

## 4. 部署与 Volta 定案（configs/models.yaml 部署矩阵）

- venv=主 venv `/data/xdng/venv`（torch 2.5.1+cu118 + transformers 4.52.x）；服务依赖 `python-multipart`
  （setup_tts_service.sh 幂等补装，阿里云镜像）。
- **dub-tts fp32 定案**：引擎仅暴露 use_bf16 开关（无 fp16 档，D1 实测 TypeError）；Volta 无 bf16 →
  `use_bf16=False` 即 fp32 是唯一实测档；volta_status=ok。实测：装载 35.4s；常驻 7062MiB（cuda:0，与 :9001
  同卡共存）；首句 5.28s（含情绪编码器首载）→ 热身 3.2–3.4s/句。
- alt-tts-b：需 torch>=2.5（SDPA enable_gqa），GPU 机 torch 2.5.1+cu118 定版；D1 直连冒烟 ok（11.7s/句）；
  经服务懒加载的合成链路未实测（GPU-1 并行租户占 17–19GB，不叠加 ~8GB 权重挤卡）——首次显式请求时懒加载，
  成败见 attempts（纪律：未实测不写 ok；dub-tts-base/alt-tts-a 权重未部署 volta_status 维持 pending）。
- 引擎真名对照/权重清单/HF 缓存：docs/tts_service_deps.md（依赖安装记录，豁免中性名扫描）。

## 5. eval

```bash
TUNNEL_LOCAL_PORT=9002 TUNNEL_REMOTE_PORT=9002 bash ops/tunnel_gpu.sh start
bash scripts/eval_m7.sh    # = pytest tests/test_m7_tts.py -v
```

- 11 用例（4 离线 + 7 在线）：C 出口纯函数 / 静音拒收 / 参数校验 / 桩服务 payload 契约（离线）；
  health 路由冻结镜像 / 双参考合成+时长对账 / voice-only emo_ref_used=false / 三语种 dry_run 链镜像 /
  未知引擎 400（在线）。
- 通过线：全绿 exit 0 零 skip（T13 记录 35.46s，隧道在线全跑）；**:9002 可达但 dub-tts 未装载属真实故障，
  不提供跳过**（gate_b2 ④ 口径）。
- 规划冻结线（§4 M7，真素材验收用）：20 句全部产出且时长入 plan；音色相似度（嵌入 cosine）≥0.70 vs
  voicebank；情绪回判一致率 ≥70%；RTF 记录。

## 6. 重生成注意事项

- 显存互斥：alt-tts-b（cuda:1 ~8GB）与 lip-pro（cuda:1 ~18GB）不可同时驻留——lip-pro 起来前先停本服务备选链。
- 双参考实测样例（T12 冒烟记录）：SAPI zh 中性句 voice_ref(7.2s) + SAPI zh 质问句 emo_ref(6.0s) →
  合成英文句 → wav 3.553s/22050Hz，emo_ref_used=true。
- emo_ref 缺省时 voice-only 合成合法（emo_ref_used=false）；emo_ref 提供但引擎不支持时文件仍被校验，
  合成按引擎语义忽略并如实回填。

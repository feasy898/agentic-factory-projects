# M4 识别 + 字级对齐 + 情绪/事件 spec（客户端 + GPU 服务 :9001）

> 状态：frozen。对照 `gpu-services/asr_align/service.py`、`pipeline/gpu_client.py`、`pipeline/m4_asr.py`、
> `docs/gpu_asr_align_deps.md`、`docs/b1_contract_notes.md` 核验于 2026-09-29。
> 组件中性名：asr-core / align-core / emo-tag（真名对照仅 docs/gpu_asr_align_deps.md）。

## 1. 职责与边界

**做**：16k 人声 wav（`04_dial/vocals.wav`）multipart 上传 → 一次调用返回：
①转写（asr-core，fp16+sdpa）②字级时间戳（align-core，支持 `text` 校对文本重对齐）③7 类情绪+声音事件
（emo-tag：哭/笑/掌声/叹气）④能量 VAD 预分段 segments；客户端切句/平移/落盘。
**不做**：服务端**不做**时间平移（时间零点规则 7：客户端注入 offset）；不做说话人聚类（M5）；OCR 融合属 M2。
本模块落 `04_dial/` 原始产物；跨层融合经契约字段完成。

## 2. 服务契约（:9001，只监听 GPU 机 127.0.0.1）

- `GET /health` → `{service, loaded:{asr-core,align-core,emo-tag}, error, device}`——三模型 loaded + cuda_available
  是门禁 ⑤ 的断言面。
- `POST /v1/asr_align`（multipart）：`file`（wav；其他采样率/声道服务端重采样兜底；上限 `MAX_SECONDS=320`）+
  `lang`（ar 自动走字符比例内插降级 align-proportional）+ `text`（非空按它重对齐）+ `do_align`/`do_emo`。
- 响应：`{text, lang_detected, duration_s, words:[{w,s,e}], segments:[{start,end}], emo:{label,score},
  events:[{label,score,start,end}], nonverbal_hint, aligner, timing, versions}`。
- **时间零点（冻结规则 7）**：响应 `words[*].s/e` 与 `segments[*].start/end` 均为**上传音频内相对时间**
  （0=上传起点）；全片绝对 = 相对 + offset（客户端 `--offset` 注入，`contracts.to_absolute_seconds` 平移）。
  阿语对齐降级：对齐器不含阿语 → 服务端内置字符比例线性内插（MVP 口径；wav2vec2-CTC 列 post-MVP）。
- 部署：独立 venv `/data/xdng/venv-asr`（transformers 5.13 下限；torch 2.5.1+cu118 以 .pth 复用主 venv）；
  模型路径经 env `ASR_CORE_DIR/ALIGN_CORE_DIR/EMO_TAG_DIR` 注入；推理锁单进程串行化；
  `bash gpu-services/asr_align/run_gpu.sh start`；命名纪律=情绪框架分发名拼接构造动态加载
  （service.py:44-45, 100）。

## 3. 客户端契约（`pipeline/gpu_client.py` + `pipeline/m4_asr.py`）

- 地址解析：显式参数 → env `M4_ASR_URL` → 默认 `http://127.0.0.1:9001`（gpu_client.py:24-26）。
- `GpuClient`：timeout 300s、retries=2（间隔 2s）；**tests/test_m4.py 服务用例 retries=5×3s**
  （覆盖公网 ssh reset ~10s 愈合窗，commit 07dfd62 定案）。服务不可达 → `GpuServiceError`。
- `m4_asr.build_utterances`（切句，冻结规则 8）：句窗 = VAD segments（M2 就绪后其 OCR 区间优先级更高）；
  无段兜底 `[offset, offset+dur]`；字按中点归段（±0.001 容差）并夹取进窗（契约字级校验）；
  `utt_id = make_utt_id(ep, 绝对起点)`；`speaker/char_id/overlap/face/ocr` 留空待回填；
  `nonverbal = nonverbal_hint and len(text) ≤ 2`。
- 落盘（`run`，m4_asr.py:149-236）：
  `utterances.jsonl`（C2，`upsert_jsonl` 原子替换）；
  `diar.jsonl`（C2-pre，与旧段合并按时间排序后整文件原子重写，speaker="unknown"）；
  `asr.jsonl`/`forced.jsonl`/`emo.jsonl`（非契约原始行，extra=allow 保留服务完整响应，按 utt_id upsert）。
- **M4 只读 `04_dial/vocals.wav`**（B1 冻结），不读 `01_media/audio_16k.wav`。

## 4. eval

```bash
bash ops/tunnel_gpu.sh start      # 隧道幂等
bash scripts/eval_m4.sh           # ① 隧道就绪检查 ② pytest tests/test_m4.py
```

- 通过线：tests 全绿，含 :9001 `/health` 三模型 loaded + cuda_available 在线冒烟。
- 服务不可达时 `--skip-gpu` 豁免仅覆盖"服务不可达"类跳过且逐条归因（gate_b1/b2 口径）；
  服务可达但模型未就绪属真实故障不豁免。
- 最近记录：gate_b1 ⑤ PASS（/health 三模型 loaded，torch 2.5.1+cu118 / V100S-PCIE-32GB，经隧道）。
- 规划冻结线（§4 M4，真素材验收用）：10 句 WER ≤8%；字级抽查 |Δstart|≤100ms 占比 ≥85%；
  情绪一致率 ≥70%；延迟 ≤0.5×实时。

## 5. 重生成注意事项

- venv 组成与关键 API（transformers 原生多模态转写/token 分类对齐 + emo 框架富文本解析）见
  `docs/gpu_asr_align_deps.md`（依赖安装记录，真名豁免口径）。
- 权重下载：ModelScope 主路国内直连 + HF 镜像兜底（`HF_HUB_DISABLE_XET=1`），见 REGENERATE §6.1。
- 隧道与保活坑见 [gpu-tunnel.md](specs/gpu-tunnel.md)。

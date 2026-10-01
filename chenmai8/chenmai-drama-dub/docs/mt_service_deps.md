# mt 服务（:9004）依赖安装记录 —— T10 预置 / T12 执行（2026-09-29）

> 本文件属依赖安装记录（gate_b0 中性名扫描豁免口径，同 `gpu_asr_align_deps.md`）：
> 上游真实分发名只登记于此；仓内其余公开文本一律用中性名（`mt-core`/`mt-api`）。

## 1. 真实分发名对照（仅本文件维护）

| 中性名 | 真实 ID / 分发名 | 说明 |
|---|---|---|
| mt-core | `tencent/Hy-MT2-1.8B`（HF）/ ModelScope 同 ID | M6 本地翻译主后端；1.8B；33 语种含阿语；术语干预 + 背景信息 + 格式保留模板；Apache-2.0（oss-manifest §2 核实） |
| mt-api | OpenAI 兼容 chat.completions 端点（任意供应商） | 兜底后端；`MT_API_BASE`/`MT_API_KEY`/`MT_API_MODEL` 三 env 注入，key 不落盘 |

## 2. GPU 机部署口径（T12 批执行）

- **venv**：主 venv `/data/xdng/venv`（torch 2.5.1+cu118 + transformers 4.52.x，
  与 TTS/口型组同组）。**待办：T12 冒烟时核实 mt-core 对 transformers 的版本要求**；
  若 4.52.x 不兼容（新架构 token/模板支持问题），参照 `gpu/setup_asr_venv.sh` 的
  `.pth` 复用法另建 `/data/xdng/venv-mt`（避免动 venv-asr 的 5.13 组），
  并把 `gpu-services/mt/run_gpu.sh` 的 `VENV=` 改指向新 venv。
- **权重**：`/data/xdng/etc/model_ids.env` 增 `MT_CORE_ID=tencent/Hy-MT2-1.8B`
  （该文件在 GPU 机上，不入公开仓）→ `bash gpu/setup_mt_service.sh`
  （ModelScope 主路 / HF 镜像兜底，落 `/data/xdng/models/mt-core`）。
- **服务**：`bash gpu-services/mt/run_gpu.sh start`（127.0.0.1:9004 常驻，cuda:0，
  fp16+sdpa，≈5GB，与 :9001 asr_align 同卡共存；显存互斥规则只涉及 #1 卡，
  见 configs/models.yaml 部署矩阵注释）。
- **隧道**：本机 `TUNNEL_LOCAL_PORT=9004 TUNNEL_REMOTE_PORT=9004 bash ops/tunnel_gpu.sh start`
  （非默认端口时日志/锁自动按端口区分；keepalive 同理）。
- **冒烟清单（T12 出口判据）**：①`/health` loaded.mt-core=true 且 cuda_available=true；
  ②`/v1/translate` 3 语向各 1 句：候选非空、术语表渲染命中、q∈[0,1]；
  ③与本机 `pipeline.mt_backends.LocalMtBackend` 端到端 1 句（payload 口径核对）；
  ④RTF/延迟记录回填 `configs/models.yaml` mt-core version/volta_status=ok。

## 3. 版本冻结位（T12 回填）

- transformers 钉版：TBD-T12
- mt-core 权重 snapshot/commit：TBD-T12
- Volta 实测：TBD-T12（fp16+sdpa，无 bf16，不依赖重型推理运行时）

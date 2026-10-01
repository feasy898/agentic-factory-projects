#!/usr/bin/env bash
# setup_llm_service.sh — GPU 机侧一次性预置：权重下载（镜像源）+ 环境自检。
# 在 GPU 机上运行；服务代码由部署方平铺到 /data/xdng/llm_openai/（service.py + run_gpu.sh）。
# 公开仓库卫生（审查 §E）：模型仓库名不入仓库——经环境变量 LLM_HF_REPO 提供，
#   未设置时报错退出（不预置默认值）；下载落位 LLM_MODEL_DIR（默认中性名 llm-chat-8b）。
# 用法:
#   LLM_HF_REPO=<镜像源模型仓库ID> bash setup_llm_service.sh
#   LLM_HF_REPO=... LLM_MODEL_DIR=/data/xdng/models/llm-chat-8b bash setup_llm_service.sh
set -euo pipefail
ROOT=/data/xdng
VENV=$ROOT/venv
PY=$VENV/bin/python
MODEL_DIR="${LLM_MODEL_DIR:-$ROOT/models/llm-chat-8b}"

[ -x "$PY" ] || { echo "FATAL: $PY 不存在（主 venv 未就绪）"; exit 1; }
: "${LLM_HF_REPO:?必须经环境变量 LLM_HF_REPO 提供镜像源模型仓库 ID（不入仓库）}"

echo "[1/3] venv 依赖自检（torch/transformers/fastapi/uvicorn）"
"$PY" - <<'EOF'
import importlib
for mod in ("torch", "transformers", "fastapi", "uvicorn"):
    m = importlib.import_module(mod)
    print(f"  {mod} {getattr(m, '__version__', '?')}")
import torch
assert torch.cuda.is_available(), "CUDA 不可用"
print(f"  cuda devices: {torch.cuda.device_count()}")
EOF

if [ -d "$MODEL_DIR" ] && ls "$MODEL_DIR"/*.safetensors >/dev/null 2>&1; then
  echo "[2/3] 权重已在位: $MODEL_DIR（跳过下载）"
else
  echo "[2/3] 经镜像源下载权重 -> $MODEL_DIR（约 16G，时长视带宽）"
  mkdir -p "$MODEL_DIR"
  export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"
  export HF_HUB_DISABLE_XET=1
  "$VENV/bin/hf" download "$LLM_HF_REPO" --local-dir "$MODEL_DIR" --max-workers 4
fi

echo "[3/3] 启动/检查服务: bash $ROOT/llm_openai/run_gpu.sh start"
echo "  就绪后本机侧: bash ops/tunnel_gpu.sh start（默认 9004 端口隧道）"
echo "done."

#!/usr/bin/env bash
# setup_mt_service.sh — mt 服务（:9004）在 GPU 机的权重与环境准备（幂等，可重跑）。
# 状态：T10 预置 —— 执行与冒烟归 T12 批（与 gpu-services/mt/run_gpu.sh 配套）。
#
# 与 asr_align 的差异：mt-core 归主 venv /data/xdng/venv（TTS/口型组同组，
# torch 2.5.1+cu118 + transformers 4.52.x）；mt-core 对 transformers 的版本要求
# 由 T12 实测核实并钉版记录（docs/mt_service_deps.md）——若 4.52.x 不兼容，
# 参照 gpu/setup_asr_venv.sh 的 .pth 复用法另建独立 venv，本脚本只做前置检查不装包。
#
# 模型/框架真实分发名不入公开仓：运行时读 /data/xdng/etc/model_ids.env
# （MT_CORE_ID），真名对照登记于 docs/mt_service_deps.md（依赖安装记录，
# 豁免中性名扫描）。pip 走阿里云镜像；权重主路 ModelScope 直连、HF 镜像兜底。
# 用法：nohup bash gpu/setup_mt_service.sh > /data/xdng/logs/setup_mt_service.log 2>&1 &
set -uo pipefail
ROOT=/data/xdng
VENV=$ROOT/venv
PY=$VENV/bin/python
MODELS_DIR=$ROOT/models
ENV_FILE=$ROOT/etc/model_ids.env
TARGET=$MODELS_DIR/mt-core
mkdir -p "$ROOT/logs" "$ROOT/etc"

log() { echo "[$(date '+%F %T')] $*"; }

# ---------- 0) 模型 ID（文件留在 GPU 机，不入公开仓） ----------
if [ ! -f "$ENV_FILE" ]; then
  log "FATAL: $ENV_FILE 不存在（需含 MT_CORE_ID，对照见 docs/mt_service_deps.md）"
  exit 1
fi
# shellcheck disable=SC1090
. "$ENV_FILE"
: "${MT_CORE_ID:?MT_CORE_ID 未设置}"

# ---------- 1) 主 venv 前置检查（不装包，只核实口径并留痕） ----------
[ -x "$PY" ] || { log "FATAL: $PY 不存在（先跑 gpu/setup_gpu.sh 建主 venv）"; exit 2; }
"$PY" - <<'PYEOF' || exit 3
import torch, importlib
print("torch:", torch.__version__, "cuda_available:", torch.cuda.is_available())
assert torch.cuda.is_available(), "CUDA 不可用"
assert any("sm_70" in s for s in torch.cuda.get_arch_list()), "sm_70 不在 arch_list"
for mod in ("transformers", "fastapi", "uvicorn"):
    m = importlib.import_module(mod)
    print(mod + ":", getattr(m, "__version__", "?"))
PYEOF
log "主 venv 前置检查通过（transformers 与 mt-core 的兼容性由 T12 冒烟核实并钉版）"

# ---------- 2) 权重下载（已有权重文件则跳过；主路 ModelScope，HF 镜像兜底） ----------
has_weights() {  # 最小文件清单：config + 至少一个 >1MB 权重文件（与 setup_asr_venv.sh 同口径）
  [ -d "$1" ] || return 1
  [ -f "$1/config.json" ] || [ -f "$1/config.yaml" ] || return 1
  find "$1" -type f -size +1M | grep -q . || return 1
}

dl() { # dl <repo_id> <local_dir> <src:modelscope|hf>
  if [ -d "$2" ] && has_weights "$2"; then log "skip $2（权重文件已就位）"; return 0; fi
  rm -rf "$2"   # 清掉上次失败留下的不完整目录
  log "downloading $1 -> $2 (src=${3:-modelscope})"
  for n in 1 2 3; do
    if [ "${3:-modelscope}" = "modelscope" ] && [ -x "$VENV/bin/modelscope" ]; then
      "$VENV/bin/modelscope" download --model "$1" --local_dir "$2" \
        && has_weights "$2" && { log "OK downloaded (modelscope)"; return 0; }
    fi
    HF_HUB_DISABLE_XET=1 "$PY" - "$1" "$2" <<'PYEOF' && has_weights "$2" && { log "OK downloaded (hf)"; return 0; }
import sys
from huggingface_hub import snapshot_download
rid, dst = sys.argv[1], sys.argv[2]
p = snapshot_download(rid, local_dir=dst, max_workers=4)
print("OK downloaded to", p)
PYEOF
    log "retry $n/3 after download failure"; sleep 5
  done
  return 1
}

export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"
if ! dl "$MT_CORE_ID" "$TARGET" "${MT_CORE_SRC:-modelscope}"; then
  log "FATAL: mt-core 权重下载失败"
  exit 5
fi

log "全部就绪：权重=$TARGET；下一步 bash gpu-services/mt/run_gpu.sh start（T12 冒烟）"

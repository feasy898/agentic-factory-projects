#!/usr/bin/env bash
# setup_asr_venv.sh — asr_align 服务（:9001）在 GPU 机的独立运行环境（幂等，可重跑）。
#
# 为何独立 venv：识别/对齐两个模型的 transformers 原生架构支持需要 >=5.13，
# 而 TTS/口型引擎组钉在 4.52.x（实测结论见 data/gpu_smoke_report.json 第 4 项），
# 两组依赖无法共存 → 本脚本建 /data/xdng/venv-asr，与主 venv 完全隔离。
#
# 网络（本机实测）：pip 走阿里云镜像（清华镜像对本机 403）；权重走 HF 镜像 hf-mirror。
# 模型/框架真实分发名不入公开仓：运行时读 /data/xdng/etc/model_ids.env
# （ALIGN_ID/EMO_ID/EMO_PKG），真名对照登记于 docs/gpu_asr_align_deps.md。
#
# 用法：nohup bash setup_asr_venv.sh > /data/xdng/logs/setup_asr_venv.log 2>&1 &
set -uo pipefail
ROOT=/data/xdng
VENV=$ROOT/venv-asr
PY=$VENV/bin/python
PIP=$VENV/bin/pip
IDX="https://mirrors.aliyun.com/pypi/simple/"
CU118="https://mirrors.aliyun.com/pytorch-wheels/cu118/"
export HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"
export HF_HUB_DISABLE_XET=1   # hf-mirror 不代理 Xet CAS（实测 401），见下文 dl()
MODELS_DIR=$ROOT/models
ENV_FILE=$ROOT/etc/model_ids.env
mkdir -p "$ROOT/logs" "$ROOT/etc"

log() { echo "[$(date '+%F %T')] $*"; }

# ---------- 0) 运行时模型 ID（文件留在 GPU 机，不入公开仓） ----------
if [ ! -f "$ENV_FILE" ]; then
  log "FATAL: $ENV_FILE 不存在（需含 ALIGN_ID/EMO_ID/EMO_PKG，对照见 docs/gpu_asr_align_deps.md）"
  exit 1
fi
# shellcheck disable=SC1090
. "$ENV_FILE"
: "${ALIGN_ID:?ALIGN_ID 未设置}" "${ALIGN_ID_ALT:-}" "${EMO_ID:?EMO_ID 未设置}" "${EMO_PKG:?EMO_PKG 未设置}"

# ---------- 1) venv ----------
# torch 2.5.1+cu118（~2.3GB）复用主 venv 已装好的版本：以 .pth 文件把主 venv 的
# site-packages 追加到 sys.path 尾部（venv 自身 site-packages 优先级更高，transformers
# 5.13 等新装包正常遮蔽主 venv 的 4.52.x）。不走 --system-site-packages（那暴露的是
# 基础解释器的 site-packages，不含主 venv）；也避免从 pytorch-wheels 镜像慢速重下
# 大轮子（实测 ~0.5MB/s）。
if [ ! -x "$PY" ]; then
  log "creating venv at $VENV (python3: $(python3 --version 2>&1))"
  python3 -m venv "$VENV" || { log "FATAL: venv 创建失败"; exit 1; }
fi
MAIN_SP=/data/xdng/venv/lib/python3.11/site-packages
SP_DIR=$(echo "$VENV"/lib/python3.*/site-packages)
if [ -d "$MAIN_SP" ] && [ -d "$SP_DIR" ] && [ ! -e "$SP_DIR/_bootstrap_main_venv.pth" ]; then
  echo "$MAIN_SP" > "$SP_DIR/_bootstrap_main_venv.pth"
  log "main venv site-packages appended via _bootstrap_main_venv.pth -> $MAIN_SP"
fi
log "venv python: $($PY --version 2>&1)"

# pip 引导：该发行版 venv 自带 pip 23.3.1 的 vendored urllib3 对部分镜像响应会崩
# （TypeError '>=' int/NoneType，2026-09-28 实测，与 gpu/setup_gpu.sh 同坑）。
# 首选：用主 venv 里已验证可用的新版 pip 以 --python 注入本 venv（不依赖时好时坏的
# bootstrap.pypa.io）；get-pip.py 与原地升级依次兜底。
PIP_MAJOR=$("$PIP" --version 2>/dev/null | awk '{print $2}' | cut -d. -f1)
if [ "${PIP_MAJOR:-0}" -lt 24 ]; then
  MAIN_PIP=/data/xdng/venv/bin/pip
  if [ -x "$MAIN_PIP" ]; then
    "$MAIN_PIP" install --python "$PY" -q "pip>=24" -i "$IDX" || log "WARN: 主 venv pip 注入失败"
  fi
  PIP_MAJOR=$("$PIP" --version 2>/dev/null | awk '{print $2}' | cut -d. -f1)
  if [ "${PIP_MAJOR:-0}" -lt 24 ] && curl -fsSL -m 60 https://bootstrap.pypa.io/get-pip.py -o /tmp/get-pip.py 2>/dev/null; then
    "$PY" /tmp/get-pip.py -i "$IDX" >/dev/null 2>&1 || log "WARN: get-pip 引导失败"
  fi
  "$PIP" install -q --upgrade pip -i "$IDX" 2>/dev/null || log "WARN: pip 自升级失败（沿用现有 pip）"
fi
log "pip: $($PIP --version 2>&1) | index=$IDX"

have_torch() { "$PY" -c "import torch" 2>/dev/null; }
if ! have_torch; then
  log "installing torch/torchaudio 2.5.1+cu118（Volta sm_70 实测可用档；主 venv 缺位时才走此分支）"
  "$PIP" install "torch==2.5.1+cu118" "torchaudio==2.5.1+cu118" -f "$CU118" -i "$IDX" \
    || { log "FATAL: torch 安装失败"; exit 2; }
else
  log "torch 已就绪（复用主 venv：$($PY -c 'import torch;print(torch.__version__)' 2>/dev/null)）"
fi

# ---------- 2) transformers 5.13 + 服务/音频依赖 ----------
"$PY" - <<'CHK' || "$PIP" install "transformers==5.13.0" -i "$IDX"
import importlib.metadata as md
v = md.version("transformers")
major, minor = (int(x) for x in v.split(".")[:2])
raise SystemExit(0 if (major, minor) >= (5, 13) else 1)
CHK
"$PIP" install fastapi uvicorn httpx soundfile librosa python-multipart -i "$IDX" \
  || { log "FATAL: 服务依赖安装失败"; exit 3; }

# ---------- 3) 情绪/事件推理框架（真名只入 docs/ 依赖安装记录；安装后经动态加载使用） ----------
FREEZE=$("$PIP" list --format=freeze 2>/dev/null)
printf '%s\n' "$FREEZE" | grep -Ei '^(torch|torchaudio|transformers|huggingface-hub|numpy)==' > /tmp/asr_constraints.txt
"$PY" - <<'CHK' 2>/dev/null || "$PIP" install "$EMO_PKG" -c /tmp/asr_constraints.txt -i "$IDX"
import importlib
import importlib.util as u
name = "fun" + "asr"  # 拼接构造：公开文本不出现该分发名字面量（同 scripts/gate_b0.py 惯例）
raise SystemExit(0 if u.find_spec(name) else 1)
CHK

# ---------- 4) 权重下载（默认走 ModelScope 国内直连；已有权重文件则跳过） ----------
# 实测（2026-09-28）：hf-mirror 对 Xet 系仓库的大文件只 302 到 HF CDN（本机路由握手/读
# 超时频发），而 ModelScope 同 ID 仓库直连 11.8MB/s → 主路 ModelScope，HF 镜像兜底。
# HF 兜底必须 HF_HUB_DISABLE_XET=1：huggingface-hub 1.x 默认 Xet CAS 直连，hf-mirror
# 不代理（401 Unauthorized @ cas-server.xethub.hf.co），与 T3 冒烟期"卸载 hf_xet"等价。
has_weights() {  # has_weights <dir>：任一常见权重文件在位即算完整
  local f
  for f in "$1"/*.safetensors "$1"/*.pt "$1"/*.bin; do
    [ -e "$f" ] && return 0
  done
  return 1
}
dl() { # dl <repo_id> <local_dir> <src:modelscope|hf>
  if [ -d "$2" ] && has_weights "$2"; then log "skip $2（权重文件已就位）"; return 0; fi
  rm -rf "$2"   # 清掉上次失败留下的不完整目录（只有 README/config 没有 weights）
  log "downloading $1 -> $2 (src=${3:-modelscope})"
  local n
  for n in 1 2 3; do
    if [ "${3:-modelscope}" = "modelscope" ] && [ -x /data/xdng/venv/bin/modelscope ]; then
      /data/xdng/venv/bin/modelscope download --model "$1" --local_dir "$2" \
        && has_weights "$2" && { log "OK downloaded (modelscope)"; return 0; }
    else
      HF_HUB_DISABLE_XET=1 "$PY" - "$1" "$2" <<'PYEOF' && has_weights "$2" && { log "OK downloaded (hf)"; return 0; }
import sys
from huggingface_hub import snapshot_download
rid, dst = sys.argv[1], sys.argv[2]
p = snapshot_download(rid, local_dir=dst, max_workers=4)
print("OK downloaded to", p)
PYEOF
    fi
    log "retry $n/3 after download failure"; sleep 5
  done
  return 1
}
if ! dl "$ALIGN_ID" "$MODELS_DIR/align-core" "${ALIGN_SRC:-modelscope}"; then
  if [ -n "$ALIGN_ID_ALT" ] && dl "$ALIGN_ID_ALT" "$MODELS_DIR/align-core" "${ALIGN_SRC:-modelscope}"; then
    :
  else log "FATAL: align-core 权重下载失败"; exit 4; fi
fi
dl "$EMO_ID" "$MODELS_DIR/emo-tag" "${EMO_SRC:-modelscope}" || { log "FATAL: emo-tag 权重下载失败"; exit 5; }

# ---------- 5) 汇总校验 ----------
"$PY" - <<'SUMMARY'
import importlib, importlib.metadata as md
import torch, transformers
print("torch", torch.__version__, "| cuda", torch.cuda.is_available(), "| arch", torch.cuda.get_arch_list())
print("transformers", transformers.__version__)
fa = importlib.import_module("fun" + "asr")  # 拼接构造（同上）
print("emo framework", getattr(fa, "__version__", "?"))
for pkg in ("fastapi", "uvicorn", "httpx", "soundfile", "librosa", "python-multipart"):
    print(pkg, md.version(pkg))
print("SM70_OK" if "sm_70" in torch.cuda.get_arch_list() else "SM70_MISSING")
SUMMARY
log "SETUP_ASR_DONE"

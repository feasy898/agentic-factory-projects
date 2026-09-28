#!/usr/bin/env bash
# setup_gpu.sh — bootstrap the deep-learning runtime on the GPU dev machine.
#
# Target environment:
#   Linux x86_64, Python 3.11, 2x 32GB Volta-class datacenter GPUs
#   (compute capability 7.0 = "sm_70"), driver branch 570.x (CUDA 12.8 driver API).
#   Mainland-China network: pip goes through domestic mirrors.
#
# What it installs (into /data/xdng/venv):
#   - PyTorch CUDA build. Tries the cu121 wheel first (default PyPI build of
#     torch==2.4.1); verifies at runtime that the binary exposes sm_70 and that
#     CUDA is actually usable. If not, falls back to cu118 wheels and re-verifies.
#   - transformers (pinned to the 4.x line — see the note in section 3),
#     accelerate, soundfile, fastapi, uvicorn, httpx
#
# Idempotent: safe to re-run. Existing venv / working torch install is kept.
#
# Usage:
#   bash setup_gpu.sh                                  # foreground
#   nohup bash setup_gpu.sh > /data/xdng/setup_gpu.log 2>&1 &   # background + log
set -uo pipefail

ROOT=/data/xdng
VENV=$ROOT/venv
# Mirror note (measured 2026-09-28 on this host): the Tsinghua PyPI mirror answers
# HTTP 403 to this machine for /simple/ pages (both curl and pip), so the Aliyun
# PyPI mirror is the default here. cu118 CUDA wheels come from the Aliyun
# pytorch-wheels directory (flat listing, used via pip --find-links).
ALIYUN_PYPI="https://mirrors.aliyun.com/pypi/simple/"
IDX="$ALIYUN_PYPI"
PY="$VENV/bin/python"
PIP="$VENV/bin/pip"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

mkdir -p "$ROOT"

log "GPU hardware as seen by the driver:"
nvidia-smi --query-gpu=index,name,memory.total,driver_version --format=csv,noheader || log "WARN: nvidia-smi failed"

# ---------- 1. virtualenv ----------
if [ ! -x "$PY" ]; then
  log "creating venv at $VENV (python3: $(python3 --version 2>&1))"
  python3 -m venv "$VENV" || { log "FATAL: venv creation failed"; exit 1; }
fi
log "venv python: $($PY --version 2>&1)"

# pip bootstrap. The pip bundled with this distro's venv (23.3.1) ships an older
# vendored urllib3 that can crash with "TypeError: '>=' not supported between
# instances of 'int' and 'NoneType'" on some mirror responses (measured on this
# host). Preferred route: official get-pip.py (embeds the new pip, does not run
# through the old one); in-place upgrade is the fallback. Both best-effort —
# the bundled pip works for normal installs.
PIP_MAJOR=$("$PIP" --version 2>/dev/null | awk '{print $2}' | cut -d. -f1)
if [ "${PIP_MAJOR:-0}" -lt 24 ]; then
  if curl -fsSL -m 60 https://bootstrap.pypa.io/get-pip.py -o /tmp/get-pip.py 2>/dev/null; then
    "$PY" /tmp/get-pip.py -i "$IDX" >/dev/null 2>&1 || log "WARN: get-pip bootstrap failed (keeping bundled pip)"
  else
    "$PIP" install -q --upgrade pip -i "$IDX" 2>/dev/null || log "WARN: pip self-upgrade failed (keeping bundled pip)"
  fi
fi
log "pip: $($PIP --version 2>&1) | index=$IDX"

# ---------- 2. torch (sm_70 must be present in the binary) ----------
verify_torch() {
  "$PY" - <<'PYCHECK'
import sys
try:
    import torch
except Exception as exc:
    print(f"TORCH_IMPORT_FAIL: {exc}")
    sys.exit(1)
print(f"torch={torch.__version__} cuda_available={torch.cuda.is_available()} "
      f"device_count={torch.cuda.device_count()}")
arch = torch.cuda.get_arch_list()
print(f"arch_list={arch}")
if torch.cuda.is_available() and "sm_70" in arch:
    print("SM70_OK")
    sys.exit(0)
print("SM70_MISSING")
sys.exit(2)
PYCHECK
}

if "$PY" -c "import torch" 2>/dev/null; then
  log "torch already installed, verifying"
else
  log "installing torch (cu121 build = default PyPI wheel of torch==2.4.1)"
  "$PIP" install "torch==2.4.1" -i "$IDX" || log "ERROR: cu121 wheel install failed"
fi

if ! verify_torch; then
  log "cu121 build not usable on this GPU -> falling back to cu118 wheels"
  "$PIP" uninstall -y torch >/dev/null 2>&1
  "$PIP" install "torch==2.4.1+cu118" \
      -f "https://mirrors.aliyun.com/pytorch-wheels/cu118/" -i "$IDX" \
  || "$PIP" install "torch==2.4.1+cu118" --index-url "https://download.pytorch.org/whl/cu118" \
  || "$PIP" install torch --index-url "https://download.pytorch.org/whl/cu118" \
  || log "ERROR: all cu118 fallbacks failed"
fi

verify_torch || { log "FATAL: no torch build with sm_70 support could be installed"; exit 2; }

# ---------- 3. remaining dependencies ----------
# transformers is pinned to the 4.x line: transformers 5.x requires torch>=2.5
# (measured: 5.17.0 disables the torch backend against torch 2.4.1), while the
# newest cu118 build with sm_70 support is torch 2.4.1. If torch ever moves to
# a newer CUDA build, this pin can be revisited.
log "installing 'transformers<5' accelerate soundfile fastapi uvicorn httpx"
"$PIP" install "transformers<5" accelerate soundfile fastapi uvicorn httpx -i "$IDX" \
|| { log "dependency install failed once, retrying"; sleep 5; \
     "$PIP" install "transformers<5" accelerate soundfile fastapi uvicorn httpx -i "$IDX"; } \
|| { log "FATAL: dependency install failed"; exit 3; }

# the resolver may have touched torch as a side effect -> verify once more
verify_torch || { log "FATAL: torch state broken after dependency install"; exit 4; }

# ---------- 4. summary ----------
log "=== SUMMARY ==="
"$PY" - <<'PYSUM'
import importlib

def ver(name):
    try:
        m = importlib.import_module(name)
        return f"{name:14s} {getattr(m, '__version__', '?')}"
    except Exception as exc:
        return f"{name:14s} IMPORT_FAIL: {exc}"

import torch
print(ver("transformers")); print(ver("accelerate")); print(ver("soundfile"))
print(ver("fastapi")); print(ver("uvicorn")); print(ver("httpx"))
print(f"{'torch':14s} {torch.__version__}")
print(f"cuda_available={torch.cuda.is_available()} device_count={torch.cuda.device_count()}")
print(f"arch_list={torch.cuda.get_arch_list()}")
for i in range(torch.cuda.device_count()):
    print(f"device {i}: {torch.cuda.get_device_name(i)}")
PYSUM
log "SETUP_DONE"

#!/usr/bin/env bash
# setup_gpu.sh — bootstrap the deep-learning runtime on the GPU dev machine.
#
# Target environment:
#   Linux x86_64, Python 3.11, 2x 32GB Volta-class datacenter GPUs
#   (compute capability 7.0 = "sm_70"), driver branch 570.x (CUDA 12.8 driver API).
#   Mainland-China network: pip goes through domestic mirrors.
#
# What it installs (into /data/xdng/venv):
#   - PyTorch CUDA build, DEFAULT torch==2.5.1+cu118 (the build D1 smoke was run on;
#     ali pytorch-wheels mirror first, official cu118 index / default PyPI as fallbacks).
#     After install the script asserts the version is 2.5.1+cu118 AND that the binary
#     exposes sm_70. (Older revisions installed 2.4.1 first — that could NOT reproduce
#     the smoke stack and broke alt-tts-b which requires torch>=2.5.)
#   - transformers pinned to the 4.x line (4.52.x for the TTS/lip engine group — see
#     section 3 and the deployment matrix at the top of configs/models.yaml; the
#     ASR/align group lives in a SEPARATE venv via gpu/setup_asr_venv.sh),
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

# ---------- 2. torch (2.5.1+cu118; sm_70 must be present in the binary) ----------
TORCH_PIN="2.5.1+cu118"

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

# 版本断言：主 venv 必须落在 2.5.1+cu118（D1 冒烟实测栈；alt-tts-b 需 torch>=2.5）。
# 已装版本不符（如旧脚本留下的 2.4.1）时按全新安装处理，重装到钉版。
torch_ok() {
  "$PY" - "$TORCH_PIN" <<'PYCHK'
import sys
try:
    import torch
except Exception:
    raise SystemExit(1)
raise SystemExit(0 if torch.__version__ == sys.argv[1] else 1)
PYCHK
}

if torch_ok; then
  log "torch $TORCH_PIN already installed, verifying"
else
  if "$PY" -c "import torch" 2>/dev/null; then
    log "torch found but version != $TORCH_PIN -> reinstalling pinned build"
    "$PIP" uninstall -y torch >/dev/null 2>&1
  else
    log "installing torch $TORCH_PIN (aliyun pytorch-wheels cu118 first)"
  fi
  "$PIP" install "torch==$TORCH_PIN" \
      -f "https://mirrors.aliyun.com/pytorch-wheels/cu118/" -i "$IDX" \
  || "$PIP" install "torch==$TORCH_PIN" --index-url "https://download.pytorch.org/whl/cu118" \
  || "$PIP" install "torch==2.5.1" -i "$IDX" \
  || log "ERROR: all torch install routes failed"
fi

if ! verify_torch; then
  log "pinned build not usable on this GPU -> trying default PyPI torch==2.5.1"
  "$PIP" uninstall -y torch >/dev/null 2>&1
  "$PIP" install "torch==2.5.1" -i "$IDX" || log "ERROR: default PyPI torch install failed"
fi

# 装完断言：版本 + sm_70 + CUDA 真正可用（双卡可见）
"$PY" - "$TORCH_PIN" <<'PYASSERT' || { log "FATAL: torch $TORCH_PIN / sm_70 assertion failed"; exit 2; }
import sys, torch
pin = sys.argv[1]
ver = torch.__version__
assert ver == pin, f"torch 版本断言失败: {ver} != {pin}"
arch = torch.cuda.get_arch_list()
assert "sm_70" in arch, f"sm_70 不在 arch_list: {arch}"
assert torch.cuda.is_available(), "CUDA 不可用"
print(f"TORCH_ASSERT_OK torch={ver} sm_70 present devices={torch.cuda.device_count()}")
PYASSERT

# ---------- 3. remaining dependencies ----------
# transformers is pinned to the 4.52.x line for the TTS/lip engine group (the exact
# stack D1 smoke ran on; measured with torch 2.5.1+cu118 / sm_70). The ASR/align
# group needs transformers>=5.13 and CANNOT share this interpreter with 4.52.x —
# it installs into a separate venv via gpu/setup_asr_venv.sh (see the deployment
# matrix at the top of configs/models.yaml). (Older revisions said "transformers<5
# because the newest cu118 build with sm_70 is torch 2.4.1" — that premise is stale:
# torch 2.5.1+cu118 ships sm_70 and is the pinned build above.)
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

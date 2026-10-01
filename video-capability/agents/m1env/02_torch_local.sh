#!/usr/bin/env bash
# M1-ENV step 02: download torch/torchvision + nvidia deps via curl (fast), then pip install locally
set -x
V=~/cradle/.venv/bin
W=~/downloads/wheels
mkdir -p $W
cd $W

PYVER=cp312

# --- big wheels from aliyun pytorch-wheels mirror ---
curl -sS -L -C - -o torch-2.4.1+cu121-$PYVER-$PYVER-linux_x86_64.whl "https://mirrors.aliyun.com/pytorch-wheels/cu121/torch-2.4.1%2Bcu121-cp312-cp312-linux_x86_64.whl"
curl -sS -L -C - -o torchvision-0.19.1+cu121-$PYVER-$PYVER-linux_x86_64.whl "https://mirrors.aliyun.com/pytorch-wheels/cu121/torchvision-0.19.1%2Bcu121-cp312-cp312-linux_x86_64.whl"

# --- resolve nvidia/triton wheel URLs from aliyun pypi index and curl them ---
python3 - <<'EOF'
import re, subprocess, sys, urllib.request

PKGS = [
    ("nvidia-cuda-nvrtc-cu12", "12.1.105"),
    ("nvidia-cuda-runtime-cu12", "12.1.105"),
    ("nvidia-cuda-cupti-cu12", "12.1.105"),
    ("nvidia-cudnn-cu12", "9.1.0.70"),
    ("nvidia-cublas-cu12", "12.1.3.1"),
    ("nvidia-cufft-cu12", "11.0.2.54"),
    ("nvidia-curand-cu12", "10.3.2.106"),
    ("nvidia-cusolver-cu12", "11.4.5.107"),
    ("nvidia-cusparse-cu12", "12.1.0.106"),
    ("nvidia-nccl-cu12", "2.20.5"),
    ("nvidia-nvtx-cu12", "12.1.105"),
    ("triton", "3.0.0"),
    ("nvidia-nvjitlink-cu12", "12.1.105"),
]
BASE = "https://mirrors.aliyun.com/pypi/simple/"
for name, ver in PKGS:
    try:
        with urllib.request.urlopen(BASE + name + "/", timeout=30) as r:
            html = r.read().decode("utf-8", "ignore")
    except Exception as e:
        print(f"!! index fail {name}: {e}", flush=True)
        continue
    hrefs = re.findall(r'href="([^"]+)"', html)
    cands = []
    for h in hrefs:
        fn = h.split("#")[0].split("/")[-1]
        from urllib.parse import unquote
        fn = unquote(fn)
        if not fn.startswith(f"{name}-{ver}-"):
            continue
        if ("manylinux" in fn or "linux_x86_64" in fn or "py3-none-any" in fn) and ("cp312" in fn or "py3-none" in fn):
            cands.append((fn, h))
    if not cands:
        print(f"!! no wheel {name}-{ver}", flush=True)
        continue
    fn, h = sorted(cands)[-1]
    url = h if h.startswith("http") else "https://mirrors.aliyun.com/pypi/packages/" + h.split("/packages/")[-1]
    url = url.split("#")[0]
    print(f"==> {fn}", flush=True)
    rc = subprocess.call(["curl", "-sS", "-L", "-C", "-", "-o", fn, url])
    if rc != 0:
        print(f"!! curl fail {fn} rc={rc}", flush=True)
EOF

echo "=== downloaded ==="
ls -la $W

# --- install torch stack from local wheels ---
$V/pip install --no-cache-dir $W/torch-2.4.1+cu121-$PYVER-$PYVER-linux_x86_64.whl $W/torchvision-0.19.1+cu121-$PYVER-$PYVER-linux_x86_64.whl -i https://mirrors.aliyun.com/pypi/simple/

$V/python -c "import torch, torchvision; print('torch', torch.__version__, 'tv', torchvision.__version__, 'cuda', torch.cuda.is_available())"
echo "STEP02_DONE rc=$?"

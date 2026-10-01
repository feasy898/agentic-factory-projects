#!/usr/bin/env bash
# M1-ENV step 03: curl nvidia deps correctly (underscore names), then pip install torch stack from local wheels
set -x
V=~/cradle/.venv/bin
W=~/downloads/wheels
mkdir -p $W

python3 - <<'EOF'
import re, subprocess, urllib.request, urllib.parse, os

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
    ("nvidia-nvjitlink-cu12", None),  # pick latest
]
BASE = "https://mirrors.aliyun.com/pypi/simple/"
W = os.path.expanduser("~/downloads/wheels")

def vkey(v):
    return [int(x) for x in re.findall(r"\d+", v)[:4]] if v else []

for name, ver in PKGS:
    und = name.replace("-", "_")
    with urllib.request.urlopen(BASE + name + "/", timeout=30) as r:
        html = r.read().decode("utf-8", "ignore")
    hrefs = re.findall(r'href="([^"]+)"', html)
    cands = []
    for h in hrefs:
        fn = urllib.parse.unquote(h.split("#")[0].split("/")[-1])
        prefix = f"{und}-{ver}-" if ver else f"{und}-"
        if not fn.startswith(prefix):
            continue
        if ("manylinux" in fn or "linux_x86_64" in fn) and ("py3-none" in fn or "cp312" in fn):
            cands.append((fn, h))
    if not cands:
        print(f"!! no wheel for {name} {ver}", flush=True)
        continue
    if ver:
        fn, h = sorted(cands)[-1]
    else:
        fn, h = max(cands, key=lambda c: vkey(c[0].split("-")[1]))
    url = h if h.startswith("http") else "https://mirrors.aliyun.com/pypi/packages/" + h.split("/packages/")[-1]
    url = url.split("#")[0]
    dest = os.path.join(W, fn)
    if os.path.exists(dest) and os.path.getsize(dest) > 1_000_000:
        print(f"skip existing {fn}", flush=True)
        continue
    print(f"==> {fn}", flush=True)
    rc = subprocess.call(["curl", "-sS", "-L", "-C", "-", "-o", dest, url])
    if rc != 0:
        print(f"!! curl fail {fn} rc={rc}", flush=True)
print("RESOLVE_DONE")
EOF

echo "=== wheels ==="
ls $W

$V/pip install --no-cache-dir --find-links $W \
  $W/torch-2.4.1+cu121-cp312-cp312-linux_x86_64.whl \
  $W/torchvision-0.19.1+cu121-cp312-cp312-linux_x86_64.whl \
  -i https://mirrors.aliyun.com/pypi/simple/

$V/python -c "import torch, torchvision; print('torch', torch.__version__, 'tv', torchvision.__version__, 'cuda_avail', torch.cuda.is_available(), 'cap', torch.cuda.get_device_capability())"
echo "STEP03_DONE rc=$?"

#!/usr/bin/env bash
# qc_setup_venv.sh — /data/night/venv-qc: 专用检测器套件（CPU-only，J6 管线）
# torch 与 vllm venv 同版本: 实测 /opt/gpumachine/local-model/vllm-venv pip list
#   torch 2.7.0 / torchvision 0.22.0 / numpy 2.2.6
# 镜像: 清华对本机 403（setup_venv.sh 实测），用阿里云 https://mirrors.aliyun.com/pypi/simple/
set -x
export TMPDIR=/data/night/tmp
export PIP_CACHE_DIR=/data/night/tmp/pipcache
mkdir -p "$TMPDIR" "$PIP_CACHE_DIR"
VENV=/data/night/venv-qc
PY=$VENV/bin/python3
PIP="$PY -m pip"
INDEX=https://mirrors.aliyun.com/pypi/simple/

rm -rf "$VENV"
python3 -m venv "$VENV" || { echo VENV_FAIL; exit 1; }
$PY -m ensurepip --upgrade 2>&1 | tail -1
$PIP install --no-input --upgrade pip -i "$INDEX" 2>&1 | tail -2
$PIP --version || { echo PIP_FAIL; exit 1; }

# 1. torch 同版本 2.7.0，官方 CPU 构建（2.7.0+cpu）：
#    下载实测：aliyun pypi 整包 0.45MB/s 且拖 1.6GB nvidia 依赖；download.pytorch.org
#    直连时通时挂（12.8MB/s 窗口后持续 reset/挂起）；阿里云 pytorch-wheels/cpu 镜像有
#    2.7.0+cpu（目录 grep 确认），国内线路稳 → -C - 断点续传直下。
mkdir -p /data/night/models/wheels
cd /data/night/models/wheels
TW=torch-2.7.0+cpu-cp311-cp311-manylinux_2_28_x86_64.whl
VW=torchvision-0.22.0+cpu-cp311-cp311-manylinux_2_28_x86_64.whl
WURL=https://mirrors.aliyun.com/pytorch-wheels/cpu
[ -f "$TW" ] || curl -sSL --retry 5 --retry-delay 10 --connect-timeout 20 -C - -o "$TW" \
  "$WURL/torch-2.7.0%2Bcpu-cp311-cp311-manylinux_2_28_x86_64.whl" || { echo TORCH_DL_FAIL; exit 1; }
[ -f "$VW" ] || curl -sSL --retry 5 --retry-delay 10 --connect-timeout 20 -C - -o "$VW" \
  "$WURL/torchvision-0.22.0%2Bcpu-cp311-cp311-manylinux_2_28_x86_64.whl" || { echo TV_DL_FAIL; exit 1; }
ls -la /data/night/models/wheels/
[ "$(stat -c%s "$TW")" -gt 100000000 ] || { echo TORCH_WHEEL_TOO_SMALL; exit 1; }
$PIP install "$TW" "$VW" --find-links /data/night/models/wheels -i "$INDEX" || { echo TORCH_FAIL; exit 1; }
$PIP install numpy==2.2.6 -i "$INDEX" || { echo NUMPY_FAIL; exit 1; }
$PY -c "import torch; print('TORCH_OK', torch.__version__)" || { echo TORCH_FAIL2; exit 1; }

# 2. 检测器全家桶（paddlepaddle 即 CPU 版；GPU 版是 paddlepaddle-gpu，不装）
$PIP install paddlepaddle opencv-python imageio imageio-ffmpeg open_clip_torch scenedetect onnxruntime -i "$INDEX" || { echo PKGS_FAIL; exit 1; }

# 3. paddleocr（独立装，失败不拖垮其余）
$PIP install paddleocr -i "$INDEX" && $PY -c "import paddleocr; print('PADDLEOCR_OK', paddleocr.__version__)" || echo PADDLEOCR_FAIL

# 4. insightface（sdist 需编译，已装 gcc12/gcc-c++/python3-devel；独立装）
$PIP install insightface -i "$INDEX" && $PY -c "import insightface; print('INSIGHTFACE_OK', insightface.__version__)" || echo INSIGHTFACE_FAIL

# 5. 预置 InsightFace buffalo_l 权重（github release 走 gh-proxy；insightface 自带下载会直连 github 大概率失败）
mkdir -p ~/.insightface/models
cd ~/.insightface/models
if [ ! -f buffalo_l/det_10g.onnx ]; then
  rm -f buffalo_l/det_10g.onnx 2>/dev/null
  for att in 1 2 3 4 5; do
    curl -sSL --retry 3 --retry-delay 10 --connect-timeout 20 -C - -o buffalo_l.zip \
      https://gh-proxy.com/https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_l.zip && break
    echo "  buffalo_l attempt$att failed (size=$(stat -c%s buffalo_l.zip 2>/dev/null))"
    sleep 10
  done
  $PY -m zipfile -e buffalo_l.zip buffalo_l/ \
    && ls -la buffalo_l/ || echo BUFFALO_FAIL
fi

echo "--- IMPORT CHECK ---"
$PY - <<'EOF'
mods = ["torch","torchvision","cv2","imageio","open_clip","scenedetect","onnxruntime","paddle","paddleocr","insightface"]
for m in mods:
    try:
        mod = __import__(m)
        print(f"{m}: OK {getattr(mod, '__version__', 'n/a')}")
    except Exception as e:
        print(f"{m}: FAIL {type(e).__name__}: {e}")
EOF
df -h /data /home | tail -3
echo QC_VENV_SETUP_DONE

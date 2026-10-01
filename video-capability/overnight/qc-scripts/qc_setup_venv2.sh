#!/usr/bin/env bash
# qc_setup_venv2.sh — venv-qc 续装：torch 已就位(2.7.0+cpu)，装剩余检测器包 + buffalo_l + 导入检查
set -x
export TMPDIR=/data/night/tmp
export PIP_CACHE_DIR=/data/night/tmp/pipcache
mkdir -p "$TMPDIR" "$PIP_CACHE_DIR"
PY=/data/night/venv-qc/bin/python3
PIP="$PY -m pip"
INDEX=https://mirrors.aliyun.com/pypi/simple/

$PIP --version || exit 1

# 2. 检测器全家桶（paddlepaddle 即 CPU 版；GPU 版是 paddlepaddle-gpu，不装）
$PIP install paddlepaddle opencv-python imageio imageio-ffmpeg open_clip_torch scenedetect onnxruntime -i "$INDEX" || { echo PKGS_FAIL; exit 1; }

# 3. paddleocr（独立装，失败不拖垮其余）
$PIP install paddleocr -i "$INDEX" && $PY -c "import paddleocr; print('PADDLEOCR_OK', paddleocr.__version__)" || echo PADDLEOCR_FAIL

# 4. insightface（sdist 需编译，已装 gcc12/gcc-c++/python3-devel；独立装）
$PIP install insightface -i "$INDEX" && $PY -c "import insightface; print('INSIGHTFACE_OK', insightface.__version__)" || echo INSIGHTFACE_FAIL

# 5. 预置 InsightFace buffalo_l 权重（gh-proxy + 断点续传重试）
mkdir -p ~/.insightface/models
cd ~/.insightface/models
if [ ! -f buffalo_l/det_10g.onnx ]; then
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
echo QC_VENV2_DONE

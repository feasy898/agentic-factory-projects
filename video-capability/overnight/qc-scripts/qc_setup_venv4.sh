#!/usr/bin/env bash
# qc_setup_venv4.sh — venv-qc 补装 II：先升 pip 23.3.1→26.x（修 cachecontrol TypeError bug），再装 paddleocr/insightface
set -x
export TMPDIR=/data/night/tmp
export PIP_CACHE_DIR=/data/night/tmp/pipcache
PY=/data/night/venv-qc/bin/python3
PIP="$PY -m pip"
INDEX=https://mirrors.aliyun.com/pypi/simple/

pip_retry() {
  local n=$1; shift
  for i in $(seq 1 "$n"); do
    "$@" && return 0
    echo "  attempt $i/$n failed: $*"
    sleep 15
  done
  return 1
}

# 0. 升级 pip 自身（23.3.1 抓大索引页会抛 TypeError('>=')，26.x 已修）
pip_retry 5 $PIP install --upgrade pip -i "$INDEX"
$PIP --version

# 1. paddleocr
pip_retry 5 $PIP install paddleocr -i "$INDEX" \
  && $PY -c "import paddleocr; print('PADDLEOCR_OK', paddleocr.__version__)" || echo PADDLEOCR_FAIL

# 2. insightface（sdist 编译）
pip_retry 5 $PIP install insightface -i "$INDEX" \
  && $PY -c "import insightface; print('INSIGHTFACE_OK', insightface.__version__)" || echo INSIGHTFACE_FAIL

echo "--- IMPORT CHECK ---"
$PY - <<'EOF'
for m in ["paddleocr", "insightface", "paddle", "cv2", "open_clip", "onnxruntime", "scenedetect", "torch"]:
    try:
        mod = __import__(m)
        print(f"{m}: OK {getattr(mod, '__version__', 'n/a')}")
    except Exception as e:
        print(f"{m}: FAIL {type(e).__name__}: {e}")
EOF
echo QC_VENV4_DONE

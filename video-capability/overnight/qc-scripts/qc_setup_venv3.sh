#!/usr/bin/env bash
# qc_setup_venv3.sh — venv-qc 补装：paddleocr + insightface（pip 23.3.1 在索引中断时会抛
# TypeError('>=')，纯属网络抖动，加重试即可）
set -x
export TMPDIR=/data/night/tmp
export PIP_CACHE_DIR=/data/night/tmp/pipcache
PY=/data/night/venv-qc/bin/python3
PIP="$PY -m pip"
INDEX=https://mirrors.aliyun.com/pypi/simple/

pip_retry() {  # pip_retry <n> <args...>
  local n=$1; shift
  for i in $(seq 1 "$n"); do
    "$@" && return 0
    echo "  pip attempt $i/$n failed"
    sleep 15
  done
  return 1
}

# paddleocr（连带 paddlex 依赖较重）
pip_retry 5 $PIP install paddleocr -i "$INDEX" \
  && $PY -c "import paddleocr; print('PADDLEOCR_OK', paddleocr.__version__)" || echo PADDLEOCR_FAIL

# insightface（sdist 编译装）
pip_retry 5 $PIP install insightface -i "$INDEX" \
  && $PY -c "import insightface; print('INSIGHTFACE_OK', insightface.__version__)" || echo INSIGHTFACE_FAIL

echo "--- IMPORT CHECK ---"
$PY - <<'EOF'
for m in ["paddleocr", "insightface", "paddle", "cv2", "open_clip", "onnxruntime", "scenedetect"]:
    try:
        mod = __import__(m)
        print(f"{m}: OK {getattr(mod, '__version__', 'n/a')}")
    except Exception as e:
        print(f"{m}: FAIL {type(e).__name__}: {e}")
EOF
ls ~/.insightface/models/buffalo_l/ 2>/dev/null
echo QC_VENV3_DONE

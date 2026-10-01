#!/usr/bin/env bash
# qc_setup_venv5.sh — venv-qc 补装 III：根因是 PIP_CACHE_DIR 里的坏索引缓存
#   （pip 23.3.1 cachecontrol 对缓存重验证响应 length=None 抛 TypeError，确定性复现；
#    第一次跑成功是因为缓存为空）→ 全部 --no-cache-dir 绕开。
set -x
export TMPDIR=/data/night/tmp
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

# 0. 升 pip（--no-cache-dir）
pip_retry 5 $PIP install --no-cache-dir --upgrade pip -i "$INDEX"
$PIP --version

# 1. paddleocr（依赖树重，禁缓存直下）
pip_retry 5 $PIP install --no-cache-dir paddleocr -i "$INDEX" \
  && $PY -c "import paddleocr; print('PADDLEOCR_OK', paddleocr.__version__)" || echo PADDLEOCR_FAIL

# 2. insightface（sdist 编译，禁缓存）
pip_retry 5 $PIP install --no-cache-dir insightface -i "$INDEX" \
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
echo QC_VENV5_DONE

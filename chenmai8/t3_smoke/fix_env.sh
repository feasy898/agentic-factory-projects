#!/usr/bin/env bash
# T3 env fixes: opencv-full removal, cu118 torchvision, mmpose no-deps, transformers 4.52.1 downgrade
set -uo pipefail
source /data/xdng/smoke/env.sh
LOG=/data/xdng/smoke/logs/fix_env.log
exec >>"$LOG" 2>&1
echo "=== fix_env start $(date -Is) ==="
P="$VENV/bin/pip"

# 1) full opencv needs libxcb (absent, no sudo) — headless provides cv2
$P uninstall -y -q opencv-python 2>&1 | tail -1

# 2) torchvision cu118 build (aliyun default was cu121 -> nms op missing on cu118 torch)
$P install -q --no-deps torchvision==0.19.1+cu118 --index-url https://download.pytorch.org/whl/cu118 2>&1 | grep -E 'Successfully|ERROR' | tail -1

# 3) mmpose without the chumpy build chain; add its runtime deps
$P install -q --no-deps mmpose 2>&1 | grep -E 'Successfully|ERROR' | tail -1
$P install -q munkres json_tricks prettytable 2>&1 | grep -E 'Successfully|ERROR' | tail -1
$P install -q xtcocotools 2>&1 | grep -E 'Successfully|ERROR' | tail -1

# 4) transformers downgrade for index-tts vendored GPT2 (OffloadedCache etc.)
$P install -q "transformers==4.52.1" "huggingface-hub==0.36.2" 2>&1 | grep -E 'Successfully|ERROR' | tail -2

echo "--- import verification ---"
for m in cv2 torchvision face_detection mmcv mmpose transformers; do
  timeout 30 $VENV/bin/python -c "import $m" 2>/dev/null && echo "ok $m" || echo "FAIL $m"
done
$VENV/bin/python -c "import torch, torchvision; from torchvision.ops import nms as _n; print('nms ok', torch.__version__, torchvision.__version__)" 2>&1 | tail -1
$VENV/bin/python -c "import transformers; from transformers.cache_utils import OffloadedCache; print('OffloadedCache ok', transformers.__version__)" 2>&1 | tail -1
echo "=== fix_env done $(date -Is) ==="

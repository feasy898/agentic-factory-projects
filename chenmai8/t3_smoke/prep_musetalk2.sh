#!/usr/bin/env bash
# T3: MuseTalk dependency install v2 (no wait loop)
set -uo pipefail
source /data/xdng/smoke/env.sh
LOG=/data/xdng/smoke/logs/prep_musetalk2.log
exec >>"$LOG" 2>&1
echo "=== prep_musetalk2 start $(date -Is) ==="
P="$VENV/bin/pip"
cat > /tmp/mt_constraints.txt <<EOF
torch==2.4.1
transformers==5.13.0
huggingface-hub<2.0
EOF
$P install -c /tmp/mt_constraints.txt diffusers moviepy 2>&1 | grep -E 'Successfully installed|ERROR' | tail -2
$P install -c /tmp/mt_constraints.txt face-detection 2>&1 | grep -E 'Successfully installed|ERROR' | tail -1
$P install -c /tmp/mt_constraints.txt mmengine mmpose 2>&1 | grep -E 'Successfully installed|ERROR' | tail -2
$P install -c /tmp/mt_constraints.txt -f https://download.openmmlab.com/mmcv/dist/cu118/torch2.4/index.html mmcv 2>&1 | grep -E 'Successfully installed|ERROR|error' | tail -3
for m in diffusers moviepy face_detection mmengine mmpose mmcv; do
  timeout 25 $VENV/bin/python -c "import $m" 2>/dev/null && echo "ok $m" || echo "FAIL $m"
done
echo "=== prep_musetalk2 done $(date -Is) ==="

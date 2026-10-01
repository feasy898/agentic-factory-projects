#!/usr/bin/env bash
# T3: MuseTalk dependency install (queued after step_deps finishes to avoid concurrent pip)
set -uo pipefail
source /data/xdng/smoke/env.sh
LOG=/data/xdng/smoke/logs/prep_musetalk.log
exec >>"$LOG" 2>&1
echo "=== prep_musetalk wait start $(date -Is) ==="
for i in $(seq 1 120); do
  grep -q 'deps step done' /data/xdng/smoke/logs/step_deps.log && break
  sleep 10
done
echo "=== prep_musetalk installing $(date -Is) ==="

P="$VENV/bin/pip"
cat > /tmp/mt_constraints.txt <<EOF
torch==2.4.1
transformers==5.13.0
huggingface-hub<2.0
EOF

# diffusers + moviepy (constraint keeps transformers 5.13)
$P install -q -c /tmp/mt_constraints.txt diffusers moviepy 2>&1 | grep -E 'Successfully installed|ERROR' | tail -2

# face_detection (S3FD FaceAlignment used by preprocessing) — try pypi mirror first
$P install -q -c /tmp/mt_constraints.txt face-detection 2>&1 | grep -E 'Successfully installed|ERROR' | tail -1
$VENV/bin/python -c "from face_detection import FaceAlignment, LandmarksType; print('face_detection ok')" 2>&1 | tail -1

# mm stack: mmengine + mmpose from aliyun; mmcv prebuilt wheel for cu118+torch2.4 from openmmlab
$P install -q -c /tmp/mt_constraints.txt mmengine mmpose 2>&1 | grep -E 'Successfully installed|ERROR' | tail -2
$P install -q -c /tmp/mt_constraints.txt -f https://download.openmmlab.com/mmcv/dist/cu118/torch2.4/index.html mmcv 2>&1 | grep -E 'Successfully installed|ERROR' | tail -1

$VENV/bin/python -c "
import importlib
for m in ['diffusers','moviepy','face_detection','mmengine','mmpose','mmcv']:
    try:
        importlib.import_module(m); print('ok', m)
    except Exception as e:
        print('FAIL', m, type(e).__name__, str(e)[:100])
" 2>&1 | grep -E '^ok|^FAIL'
echo "=== prep_musetalk done $(date -Is) ==="

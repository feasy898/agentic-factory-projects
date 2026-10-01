#!/usr/bin/env bash
# Sequential judge smoke on card1: three models, ONE resident at a time (each in its own python process).
set -uo pipefail
export CUDA_VISIBLE_DEVICES=1
V=/data/night/venv-judge/bin/python
S=/data/night/scripts
R=/data/night/results
L=/data/night/logs
mkdir -p $R $L
nvidia-smi --query-gpu=index,memory.used --format=csv,noheader > $L/gpu_before_smoke.txt

echo "=== [1/3] OmniJev-4B smoke $(date +%T) ==="
$V $S/omnijev_infer.py --image /data/night/golden/test_hand.jpg \
    --questions $S/omnijev_smoke_q.json --out $R/omnijev_smoke.json
echo "omnijev_rc=$?"

echo "=== [2/3] Visual-Jev-4B smoke $(date +%T) ==="
$V $S/visualjev_infer.py --image /data/night/golden/test_hand.jpg \
    --questions $S/visualjev_smoke_q.json --out $R/visualjev_smoke.json
echo "visualjev_rc=$?"

echo "=== [3/3] VideoChat3-4B smoke $(date +%T) ==="
VC3PY=/data/night/venv-vc3/bin/python
[ -x $VC3PY ] || VC3PY=$V
$VC3PY $S/videochat3_infer.py --video /data/night/clips/smoke_counter.mp4 \
    --fps 1 --max-pixels 268144 \
    --question "What color is the moving ball in the video? Answer briefly." \
    --out $R/videochat3_smoke.json
echo "videochat3_rc=$?"

nvidia-smi --query-gpu=index,memory.used --format=csv,noheader > $L/gpu_after_smoke.txt
echo "SMOKE_ALL_DONE $(date +%T)"

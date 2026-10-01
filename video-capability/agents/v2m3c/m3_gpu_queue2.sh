#!/usr/bin/env bash
# V2-M3C GPU 续跑队列: 审计重跑(真实fn) → 合成源验证 → 沙箱三车道实测
set -ex
cd /root/cradle
export CRADLE_CLIP_WEIGHTS=/root/cradle/models/clip/ViT-L-14.pt
export HF_HUB_OFFLINE=1
PY=/root/cradle/.venv/bin/python

echo "=== STEP 2R: overlay G7 audit (real fns) ==="; date
$PY tools/m3_overlay_audit.py --overlays assets/overlays

echo "=== STEP 3: synthetic-source validation (Wan x2) ==="; date
$PY tools/m3_evidence_validate.py --sweep 0.30

echo "=== STEP 4: sandbox + lane shots (Wan x3) ==="; date
bash scripts/m3_sandbox.sh
bash scripts/m3_lane_shots.sh

echo "=== ALL DONE ==="; date

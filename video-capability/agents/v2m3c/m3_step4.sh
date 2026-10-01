#!/usr/bin/env bash
# V2-M3C: STEP 4 重跑 (沙箱三车道实测)
set -ex
cd /root/cradle
export CRADLE_CLIP_WEIGHTS=/root/cradle/models/clip/ViT-L-14.pt
export HF_HUB_OFFLINE=1

echo "=== STEP 4 (retry): sandbox + lane shots (Wan x3) ==="; date
bash scripts/m3_sandbox.sh
bash scripts/m3_lane_shots.sh

echo "=== ALL DONE ==="; date

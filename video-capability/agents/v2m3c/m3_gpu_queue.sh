#!/usr/bin/env bash
# V2-M3C GPU 串行总队列: overlay 生成(6) → G7 审计 → 合成源验证 → 沙箱三车道实测
# Wan 消耗预算: 6 (overlays) + 2 (evidence_validate 重绘) + 3 (S09 n_best=2 + S18 1) = 11
set -ex
cd /root/cradle
export CRADLE_CLIP_WEIGHTS=/root/cradle/models/clip/ViT-L-14.pt
export HF_HUB_OFFLINE=1
PY=/root/cradle/.venv/bin/python

echo "=== STEP 1: overlay gen (6 clips, Wan x6) ==="; date
$PY tools/m3_gen_overlays.py --out assets/overlays

echo "=== STEP 2: overlay G7 audit ==="; date
$PY tools/m3_overlay_audit.py --overlays assets/overlays

echo "=== STEP 3: synthetic-source validation (Wan x2) ==="; date
$PY tools/m3_evidence_validate.py --sweep 0.30

echo "=== STEP 4: sandbox + lane shots (Wan x3) ==="; date
bash scripts/m3_sandbox.sh
bash scripts/m3_lane_shots.sh

echo "=== ALL DONE ==="; date

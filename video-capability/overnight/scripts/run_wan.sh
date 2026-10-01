#!/usr/bin/env bash
# run_wan.sh — Wan2.1-T2V-1.3B fp16 @ 卡1 (CUDA_VISIBLE_DEVICES=1)
# 用法: run_wan.sh PROMPT [SEED=42] [OUT=/data/night/clips/wan_<ts>.mp4] [NUM_FRAMES=81] [STEPS=50] [H=480] [W=832]
# 注意: NUM_FRAMES 必须满足 4k+1 (81@16fps≈5s, 49≈3s)
set -euo pipefail
PROMPT=${1:?用法: run_wan.sh "PROMPT" [SEED] [OUT] [NUM_FRAMES] [STEPS] [H] [W]}
SEED=${2:-42}
OUT=${3:-/data/night/clips/wan_$(date +%s).mp4}
NF=${4:-81}
STEPS=${5:-50}
H=${6:-480}
W=${7:-832}
mkdir -p "$(dirname "$OUT")" /data/night/logs
export CUDA_VISIBLE_DEVICES=1
LOG=${OUT%.mp4}.log
echo "[run_wan] prompt=$PROMPT seed=$SEED out=$OUT frames=$NF steps=$STEPS ${H}x${W}"
/data/night/venv/bin/python3 /data/night/scripts/gen_wan.py \
  --prompt "$PROMPT" --seed "$SEED" --out "$OUT" \
  --num-frames "$NF" --steps "$STEPS" --height "$H" --width "$W" 2>&1 | tee "$LOG"

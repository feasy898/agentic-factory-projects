#!/usr/bin/env bash
# run_ltx.sh — Lightricks/LTX-Video 2B fp16 @ 卡1 (CUDA_VISIBLE_DEVICES=1)，VAE fp32 自动降级
# 用法: run_ltx.sh PROMPT [SEED=42] [OUT=/data/night/clips/ltx_<ts>.mp4] [NUM_FRAMES=49] [STEPS=50] [H=480] [W=704]
# 注意: NUM_FRAMES 必须满足 8k+1 (49@24fps≈2s, 73≈3s, 121≈5s)
set -euo pipefail
PROMPT=${1:?用法: run_ltx.sh "PROMPT" [SEED] [OUT] [NUM_FRAMES] [STEPS] [H] [W]}
SEED=${2:-42}
OUT=${3:-/data/night/clips/ltx_$(date +%s).mp4}
NF=${4:-49}
STEPS=${5:-50}
H=${6:-480}
W=${7:-704}
mkdir -p "$(dirname "$OUT")" /data/night/logs
export CUDA_VISIBLE_DEVICES=1
LOG=${OUT%.mp4}.log
echo "[run_ltx] prompt=$PROMPT seed=$SEED out=$OUT frames=$NF steps=$STEPS ${H}x${W}"
/data/night/venv/bin/python3 /data/night/scripts/gen_ltx.py \
  --prompt "$PROMPT" --seed "$SEED" --out "$OUT" \
  --num-frames "$NF" --steps "$STEPS" --height "$H" --width "$W" 2>&1 | tee "$LOG"

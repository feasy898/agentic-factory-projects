#!/usr/bin/env bash
# launch_ltx_smoke.sh — LTX-Video 2B 冒烟：73帧@24fps≈3s, 480x704, fp16(含 VAE fp32 自动降级), nohup
set -x
nvidia-smi --query-gpu=index,memory.used --format=csv,noheader
nohup bash /data/night/scripts/run_ltx.sh \
  'A close-up shot of a persons hand holding a glass of water, fingers clearly visible, cinematic lighting' \
  42 /data/night/clips/ltx_smoke.mp4 73 50 480 704 \
  > /data/night/logs/ltx_smoke.log 2>&1 &
echo "LTX_SMOKE_PID=$!"
ls /data/night/models/LTX-Video/

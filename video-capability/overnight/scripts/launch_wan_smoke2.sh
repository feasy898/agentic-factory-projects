#!/usr/bin/env bash
# launch_wan_smoke2.sh — Wan 冒烟第2次（修复 numpy 元数据后），nohup 启动 run_wan.sh
set -x
[ -f /data/night/clips/wan_smoke.mp4 ] && mv /data/night/clips/wan_smoke.mp4 /data/night/clips/wan_smoke_run1.mp4
nohup bash /data/night/scripts/run_wan.sh \
  'A close-up shot of a persons hand holding a glass of water, fingers clearly visible, cinematic lighting' \
  42 /data/night/clips/wan_smoke.mp4 49 30 480 832 \
  > /data/night/logs/wan_smoke2.log 2>&1 &
echo "SMOKE2_PID=$!"
du -sh /data/night/models/LTX-Video

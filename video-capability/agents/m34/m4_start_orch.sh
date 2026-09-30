#!/usr/bin/env bash
# M4 恢复演示启动器: exec 保证 $! 即 python 进程 PID。
# 用法: nohup bash scripts/m4_start_orch.sh <sandbox> <logfile> & echo $! > <sandbox>/workdir/orchestrator.pid
SB="$1"
LOG="$2"
cd /root/cradle || exit 1
export CRADLE_ROOT="$SB"
export CRADLE_CLIP_WEIGHTS="$SB/models/clip/ViT-L-14.pt"
export HF_HUB_OFFLINE=1
exec /root/cradle/.venv/bin/python -m src.cli run --poll 5 --verbose >> "$LOG" 2>&1

#!/usr/bin/env bash
# M5 阶段1: 竖/横 A/B — ingest 10 张 A/B 卡 → orchestrator 跑完全部终态 (Wan 480p, n_best=1)。
# 于 tmux cradle_m5 内运行: bash scripts/m5_ab_run.sh
set -euo pipefail
cd /root/cradle
export CRADLE_ROOT=/root/cradle_m5
export CRADLE_CLIP_WEIGHTS=/root/cradle_m5/models/clip/ViT-L-14.pt
export HF_HUB_OFFLINE=1
PY=/root/cradle/.venv/bin/python
$PY -m src.cli initdb
$PY -m src.cli ingest /root/cradle/templates/abcards
$PY -m src.cli run --poll 15
$PY -m src.cli status --events 5
$PY -m src.cli report --out /root/cradle_m5/workdir/m5_ab_report.json
echo "AB_DONE"

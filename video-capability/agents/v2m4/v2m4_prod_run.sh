#!/usr/bin/env bash
# V2-M4 量产: ingest 19 张 v2 卡 → orchestrator run --poll 全终态 → DB 快照。
# 于 setsid nohup 内运行: bash scripts/v2m4_prod_run.sh (D-038: 不用 tmux)。
set -euo pipefail
cd /root/cradle
export CRADLE_ROOT=/root/cradle_v2m4
export CRADLE_CLIP_WEIGHTS=/root/cradle_v2m4/models/clip/ViT-L-14.pt
export HF_HUB_OFFLINE=1
PY=/root/cradle/.venv/bin/python
$PY -m src.cli initdb
$PY -m src.cli ingest /root/cradle/templates/shotcards_v2
$PY -m src.cli run --poll 15
$PY -m src.cli status --events 10
$PY -m src.cli report --out /root/cradle_v2m4/workdir/logs/v2m4_prod_report.json
echo "V2M4_PROD_DONE"

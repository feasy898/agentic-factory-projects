#!/usr/bin/env bash
# M5 阶段2: 量产 — ingest 全部生产镜头卡 → orchestrator 跑完全部终态 (Wan n_best=3 + 短路/重试/降级)。
# 于 tmux cradle_m5 内运行: bash scripts/m5_prod_run.sh
# 注意: 与 A/B 同库累计 Wan 守卫; 运行前先 nvidia-smi 确认空闲。
set -euo pipefail
cd /root/cradle
export CRADLE_ROOT=/root/cradle_m5
export CRADLE_CLIP_WEIGHTS=/root/cradle_m5/models/clip/ViT-L-14.pt
export HF_HUB_OFFLINE=1
PY=/root/cradle/.venv/bin/python
$PY -m src.cli initdb
$PY -m src.cli ingest /root/cradle/templates/shotcards
$PY -m src.cli run --poll 15
$PY -m src.cli status --events 5
$PY -m src.cli report --out /root/cradle_m5/workdir/m5_prod_report.json
echo "PROD_DONE"

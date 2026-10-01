#!/usr/bin/env bash
# M5 阶段2.3: 9 条成片 — compose-video 按 spec 显式从指定候选集合合成 (G6 两级校验+CER 留档)。
# 于 tmux 内运行: bash scripts/m5_compose_videos.sh
# 前置: 量产 run 已完成(S01-S17 终态), specs 已上传 /root/cradle_m5/specs/。
set -euo pipefail
cd /root/cradle
export CRADLE_ROOT=/root/cradle_m5
export CRADLE_CLIP_WEIGHTS=/root/cradle_m5/models/clip/ViT-L-14.pt
export HF_HUB_OFFLINE=1
PY=/root/cradle/.venv/bin/python
$PY -m src.cli compose-video --spec /root/cradle_m5/specs
$PY -m src.cli status --events 5
echo "COMPOSE_DONE"

#!/usr/bin/env bash
# V2-M4 成片合成: compose-video 按 9 份 spec 显式合成 (G6 两级校验+CER 留档)。
# 于 setsid nohup 内运行: bash scripts/v2m4_compose.sh
set -euo pipefail
cd /root/cradle
export CRADLE_ROOT=/root/cradle_v2m4
export CRADLE_CLIP_WEIGHTS=/root/cradle_v2m4/models/clip/ViT-L-14.pt
export HF_HUB_OFFLINE=1
PY=/root/cradle/.venv/bin/python
$PY -m src.cli compose-video --spec /root/cradle_v2m4/specs
$PY -m src.cli status --events 5
echo "V2M4_COMPOSE_DONE"

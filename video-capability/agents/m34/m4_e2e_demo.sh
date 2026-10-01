#!/usr/bin/env bash
# M4 端到端一键出片: 全新 CRADLE_ROOT 沙箱内 initdb → ingest(6 卡) → run --once(生成→六门禁→路由→合成)。
# 用法: bash scripts/m4_e2e_demo.sh [沙箱根, 默认 /root/cradle_m4_sandbox]
# 依赖: 仓库代码 + ~/cradle/.venv(GPU); 沙箱需已备好 config/templates/assets/m4_cards。
set -euo pipefail

SB="${1:-/root/cradle_m4_sandbox}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
PY="$REPO/.venv/bin/python"
export CRADLE_ROOT="$SB"
# 沙箱环境: CLIP 权重指向沙箱内 models/(软链到真实权重, 只读); 禁 HF hub 在线校验防墙内卡死
export CRADLE_CLIP_WEIGHTS="$SB/models/clip/ViT-L-14.pt"
export HF_HUB_OFFLINE=1

t0=$(date +%s)
ts() { echo "[$(printf '%04d' $(($(date +%s) - t0)))s] $*"; }

ts "=== phase 1/3: initdb ==="
"$PY" -m src.cli initdb

ts "=== phase 2/3: ingest 6 cards (m4_cards/) + run --once 全链 ==="
# run --task-file: 先 ingest 再单命令跑完 生成→门禁→路由→重试/fallback→合成 (不动点)
"$PY" -m src.cli run --task-file "$SB/m4_cards" --template product_seeding_25s --once --verbose

ts "=== phase 3/3: final status + yield report ==="
"$PY" -m src.cli status --events 5
"$PY" -m src.cli report --out "$SB/workdir/m4_yield_report.json" | head -30

ts "=== artifacts ==="
ls -la "$SB/output/" 2>/dev/null || true
for f in "$SB"/output/*.mp4; do
  [ -e "$f" ] || continue
  ffprobe -v quiet -show_entries "format=duration,size" -show_entries "stream=codec_name,codec_type,width,height,r_frame_rate" -of csv "$f" | sed "s|^|  $(basename "$f") |"
done
ts "done"

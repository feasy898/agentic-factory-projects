#!/usr/bin/env bash
# T3: run remaining smokes sequentially on GPU1: indextts -> voxcpm -> musetalk
set -uo pipefail
source /data/xdng/smoke/env.sh
LOG=/data/xdng/smoke/logs/chain.log
exec >>"$LOG" 2>&1
PY="$VENV/bin/python"
echo "=== chain start $(date -Is) ==="

echo "--- voxcpm import precheck ---"
timeout 60 $PY -c "from voxcpm import VoxCPM; print('voxcpm import ok')" 2>&1 | tail -1

echo "--- smoke: indextts (fp32 + fp16 attempt), 25min box ---"
cd /data/xdng/smoke
timeout 1500 $PY smoke_indextts.py both >> logs/smoke_indextts.log 2>&1
echo "indextts rc=$? at $(date -Is)"

echo "--- smoke: voxcpm, 25min box ---"
timeout 1500 $PY smoke_voxcpm.py >> logs/smoke_voxcpm.log 2>&1
echo "voxcpm rc=$? at $(date -Is)"

echo "--- smoke: musetalk, 25min box (internal timeout) ---"
bash /data/xdng/smoke/smoke_musetalk.sh >> logs/smoke_musetalk_outer.log 2>&1
echo "musetalk rc=$? at $(date -Is)"

echo "--- assemble ---"
$PY /data/xdng/smoke/assemble_report.py >> logs/assemble.log 2>&1
echo "assemble rc=$? at $(date -Is)"
echo "=== chain done $(date -Is) ==="

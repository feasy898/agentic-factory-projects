#!/bin/bash
# J6 金标批跑：40 条 golden clip 逐条跑 qc_detectors.py（CPU-only，不碰卡0/卡1）
# 注意 clip_id 是 3 位零填充（golden_001..golden_040）
PY=/data/night/venv-qc/bin/python
SCRIPT=/data/night/scripts/qc_detectors.py
OUT=/data/night/results/j6
mkdir -p "$OUT"
for i in $(seq 1 40); do
  cid=$(printf "golden_%03d" "$i")
  clip=/data/night/golden/clips/$cid.mp4
  frames=/data/night/golden/frames/$cid
  out=$OUT/$cid.qc.json
  if [ ! -f "$clip" ]; then echo "[MISSING] $clip"; continue; fi
  if [ -s "$out" ]; then echo "[skip] $cid (exists)"; continue; fi
  echo "=== $cid start $(date +%H:%M:%S) ==="
  "$PY" "$SCRIPT" --clip "$clip" --frames "$frames" --out "$out" || echo "[FAIL] $cid exit=$?"
done
echo "ALL_DONE $(date +%H:%M:%S)"

#!/usr/bin/env bash
# run_vc3_phase3.sh — 仅 Phase 3（VideoChat3-4B）。
# 前情：MS master 的 config.json/video_processing_videochat3.py 与 HF 钉死 revision(37fa901) 不一致
#       导致两次冒烟失败（generation decoding_method=None / 视觉塔 flash_attn 路径）。
#       已用 anolis 的精确副本覆盖小文件（sha256 全对齐）、权重 stat 尺寸逐一相符。
#       权重已在 /dev/shm/jmodels/VideoChat3-4B（.PREFETCH_OK 在），预取秒过。
set -uo pipefail
ROOT=/root/judgenight
R=$ROOT/results/judges
L=$ROOT/logs
M=/dev/shm/jmodels
VC=$ROOT/venvs/venv-vc3
export CUDA_VISIBLE_DEVICES=0
export TOKENIZERS_PARALLELISM=false
mkdir -p $R $L $M
exec >> $L/run_all.log 2>&1
step(){ echo "[$(date '+%F %T')] $*"; }

VC3PY=""
if [ -x $VC/bin/python ] && $VC/bin/python -c "import transformers, torch; assert transformers.__version__.startswith('4.')" 2>/dev/null; then
  VC3PY=$VC/bin/python
else
  echo "phase3_videochat3_rc=venv_build_failed" >> $L/phases.rc
  step "venv-vc3 unusable -> phase skipped"
fi
if [ -n "$VC3PY" ]; then
  if [ -f $M/VideoChat3-4B/.PREFETCH_OK ]; then
    step "prefetch skip (marker present)"
    $VC3PY $ROOT/scripts/videochat3_batch.py --clips-dir $ROOT/smoke_clips \
      --out-dir $R/videochat3_smoke --raw-dir $R/videochat3_smoke/raw \
      --frames-dir $ROOT/frames/videochat3_smoke --model $M/VideoChat3-4B \
      --meta $R/videochat3_smoke/run_metadata2.json
    if [ -f $R/videochat3_smoke/golden_001.json ] && ! grep -q "judge FAILED" $R/videochat3_smoke/golden_001.json; then
      step "smoke OK: $(head -c 300 $R/videochat3_smoke/golden_001.json)"
      $VC3PY $ROOT/scripts/videochat3_batch.py --clips-dir $ROOT/clips \
        --out-dir $R/videochat3 --raw-dir $R/videochat3/raw \
        --frames-dir $ROOT/frames/videochat3 --model $M/VideoChat3-4B \
        --meta $R/videochat3/run_metadata.json
      echo "phase3_videochat3_rc=$?" >> $L/phases.rc
    else
      echo "phase3_videochat3_rc=smoke_failed" >> $L/phases.rc
      step "VideoChat3 smoke FAILED -> phase skipped"
    fi
  else
    echo "phase3_videochat3_rc=prefetch_missing" >> $L/phases.rc
  fi
fi
pkill -f videochat3_batch.py 2>/dev/null
rm -rf $M/VideoChat3-4B
nvidia-smi --query-gpu=memory.used --format=csv,noheader > $L/gpu_after_all.txt
step "=== summary ==="
for j in omnijev visualjev videochat3; do
  n=$(ls $R/$j/golden_*.json 2>/dev/null | wc -l)
  step "$j: $n/40 protocol JSONs"
done
cat $L/phases.rc 2>/dev/null
echo "RUN_ALL_DONE $(date '+%F %T')"

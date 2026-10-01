#!/usr/bin/env bash
# run_judges_full.sh — 金标 40 clip 全量盲测（旧 V100 机, GPU0 全程独占）。
# 三模型顺序加载：各自独立进程，跑完即释放，无同时驻留。
# 模型供给：hf-mirror 并行分块预取到 /dev/shm tmpfs（revision 钉死 = anolis 冒烟验证的 commit）。
# 降级：任一阶段失败记录 rc 后继续下一阶段；VC3 无 decord 时自动退回 ffmpeg 帧列表输入。
set -uo pipefail
ROOT=/root/judgenight
R=$ROOT/results/judges
L=$ROOT/logs
M=/dev/shm/jmodels
VJ=$ROOT/venvs/venv-judge
VC=$ROOT/venvs/venv-vc3
IDX="https://mirrors.cloud.tencent.com/pypi/simple/"
PY=$VJ/bin/python
export CUDA_VISIBLE_DEVICES=0
export TOKENIZERS_PARALLELISM=false
mkdir -p $R $L $M
exec >> $L/run_all.log 2>&1
step(){ echo "[$(date '+%F %T')] $*"; }

REV_OMNI="ffe5f436eaf22e20e2f041f8e74e121fd057a6cb"   # tinnel123/OmniJev rev v1.1
REV_Q35="851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a"    # Qwen/Qwen3.5-4B
REV_VJ="7a3f1bb0d8f7bfbbd8514d968ab7de3518849c8d"     # guanxuyu/visual-jev-4b-answer-sft
REV_VC3="37fa901ec5913f84bc31108ebc1e60ad1903634c"    # MCG-NJU/VideoChat3-4B
REV_QVL="main"                                        # anolis 无 tree 记录，用 main

pf(){  # pf <repo> <revision> <dest>
  if [ -f "$3/.PREFETCH_OK" ]; then step "prefetch skip $3 (marker present)"; return 0; fi
  step "prefetch $1@$2 -> $3"
  $PY $ROOT/scripts/prefetch_model.py "$1" "$2" "$3" --workers 8 || return 1
}
nvidia-smi --query-gpu=memory.used --format=csv,noheader > $L/gpu_before_all.txt
step "=== RUN_ALL START gpu=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader) ==="

step "=== PHASE 1/3 OmniJev-4B ==="
if pf Qwen/Qwen3.5-4B $REV_Q35 $M/Qwen3.5-4B && pf tinnel123/OmniJev $REV_OMNI $M/OmniJev-4B-v1.1; then
  $PY $ROOT/scripts/omnijev_batch.py --clips-dir $ROOT/smoke_clips \
    --out-dir $R/omnijev_smoke --raw-dir $R/omnijev_smoke/raw \
    --src-dir $ROOT/src/OmniJev-main --ckpt $M/OmniJev-4B-v1.1 --base $M/Qwen3.5-4B \
    --meta $R/omnijev_smoke/run_metadata.json
  if [ -f $R/omnijev_smoke/golden_001.json ] && ! grep -q "judge FAILED" $R/omnijev_smoke/golden_001.json; then
    step "smoke OK: $(head -c 300 $R/omnijev_smoke/golden_001.json)"
    $PY $ROOT/scripts/omnijev_batch.py --clips-dir $ROOT/clips \
      --out-dir $R/omnijev --raw-dir $R/omnijev/raw \
      --src-dir $ROOT/src/OmniJev-main --ckpt $M/OmniJev-4B-v1.1 --base $M/Qwen3.5-4B \
      --meta $R/omnijev/run_metadata.json
    echo "phase1_omnijev_rc=$?" >> $L/phases.rc
  else
    echo "phase1_omnijev_rc=smoke_failed" >> $L/phases.rc
    step "OmniJev smoke FAILED -> phase skipped"
  fi
else
  echo "phase1_omnijev_rc=prefetch_failed" >> $L/phases.rc
fi
pkill -f omnijev_batch.py 2>/dev/null
rm -rf $M/Qwen3.5-4B $M/OmniJev-4B-v1.1
nvidia-smi --query-gpu=memory.used --format=csv,noheader > $L/gpu_after_phase1.txt
df -h /dev/shm | tail -1

step "=== PHASE 2/3 Visual-Jev-4B ==="
if pf Qwen/Qwen3-VL-4B-Instruct $REV_QVL $M/Qwen3-VL-4B-Instruct && \
   pf guanxuyu/visual-jev-4b-answer-sft $REV_VJ $M/visual-jev-4b-answer-sft; then
  $PY $ROOT/scripts/visualjev_batch.py --clips-dir $ROOT/smoke_clips \
    --out-dir $R/visualjev_smoke --raw-dir $R/visualjev_smoke/raw \
    --code-dir $ROOT/src/Visual-Jev-main/code --frames-dir $ROOT/frames/visualjev_smoke \
    --base $M/Qwen3-VL-4B-Instruct --adapter $M/visual-jev-4b-answer-sft \
    --meta $R/visualjev_smoke/run_metadata.json
  if [ -f $R/visualjev_smoke/golden_001.json ] && ! grep -q "judge FAILED" $R/visualjev_smoke/golden_001.json; then
    step "smoke OK: $(head -c 300 $R/visualjev_smoke/golden_001.json)"
    $PY $ROOT/scripts/visualjev_batch.py --clips-dir $ROOT/clips \
      --out-dir $R/visualjev --raw-dir $R/visualjev/raw \
      --code-dir $ROOT/src/Visual-Jev-main/code --frames-dir $ROOT/frames/visualjev \
      --base $M/Qwen3-VL-4B-Instruct --adapter $M/visual-jev-4b-answer-sft \
      --meta $R/visualjev/run_metadata.json
    echo "phase2_visualjev_rc=$?" >> $L/phases.rc
  else
    echo "phase2_visualjev_rc=smoke_failed" >> $L/phases.rc
    step "Visual-Jev smoke FAILED -> phase skipped"
  fi
else
  echo "phase2_visualjev_rc=prefetch_failed" >> $L/phases.rc
fi
pkill -f visualjev_batch.py 2>/dev/null
rm -rf $M/Qwen3-VL-4B-Instruct $M/visual-jev-4b-answer-sft
nvidia-smi --query-gpu=memory.used --format=csv,noheader > $L/gpu_after_phase2.txt

step "=== PHASE 3/3 VideoChat3-4B (venv clone -> transformers 4.57.6) ==="
VC3PY=""
if [ -x $VC/bin/python ] && $VC/bin/python -c "import transformers, torch; assert transformers.__version__.startswith('4.')" 2>/dev/null; then
  VC3PY=$VC/bin/python
else
  step "hardlink-clone venv-judge -> venv-vc3, downgrade transformers"
  rm -rf $VC
  cp -al $VJ $VC 2>/dev/null || step "cp -al failed, falling back to real copy"
  [ -x $VC/bin/python ] || cp -a $VJ $VC
  grep -rl "venv-judge" $VC/bin 2>/dev/null | while read -r f; do
    sed -i "s|venvs/venv-judge|venvs/venv-vc3|g" "$f"
  done
  sed -i "s|venvs/venv-judge|venvs/venv-vc3|g" $VC/pyvenv.cfg 2>/dev/null
  $VC/bin/pip install -q --no-cache-dir -i $IDX --timeout 120 --retries 8 \
    transformers==4.57.6 || echo "phase3_note=transformers_downgrade_failed" >> $L/phases.rc
  $VC/bin/pip install -q --no-cache-dir -i $IDX --timeout 120 --retries 8 eva-decord \
    || step "eva-decord unavailable -> VC3 uses ffmpeg-frames input mode"
  if $VC/bin/python -c "import transformers, torch; assert transformers.__version__.startswith('4.'); assert torch.cuda.is_available()" 2>/dev/null; then
    VC3PY=$VC/bin/python
    find $VC -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null
  else
    echo "phase3_videochat3_rc=venv_build_failed" >> $L/phases.rc
    step "venv-vc3 unusable -> phase skipped"
  fi
fi
if [ -n "$VC3PY" ]; then
  if pf MCG-NJU/VideoChat3-4B $REV_VC3 $M/VideoChat3-4B; then
    $VC3PY $ROOT/scripts/videochat3_batch.py --clips-dir $ROOT/smoke_clips \
      --out-dir $R/videochat3_smoke --raw-dir $R/videochat3_smoke/raw \
      --frames-dir $ROOT/frames/videochat3_smoke --model $M/VideoChat3-4B \
      --meta $R/videochat3_smoke/run_metadata.json
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
    echo "phase3_videochat3_rc=prefetch_failed" >> $L/phases.rc
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
df -h / /dev/shm | tail -2
echo "RUN_ALL_DONE $(date '+%F %T')"

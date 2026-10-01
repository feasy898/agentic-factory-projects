#!/usr/bin/env bash
# v4: idempotent + locked. clone generation venv -> venv-judge, verify, install judge deps, download weights.
set -uo pipefail
LOG=/data/night/logs/setup_judge_env4.log
VENV=/data/night/venv-judge
SRC=/data/night/venv
LOCK=/data/night/.judge_setup.lock
IDX="https://mirrors.cloud.tencent.com/pypi/simple/"
PIPOPT="-i $IDX --timeout 120 --retries 8"

step(){ echo "[$(date +%F\ %T)] $*"; }

mkdir "$LOCK" 2>/dev/null || { step "another setup is running (lock exists), exit"; exit 0; }
trap 'rmdir "$LOCK" 2>/dev/null' EXIT

verify_clone(){
  [ -x $VENV/bin/python ] || return 1
  local n=$(ls $VENV/lib/python3.11/site-packages 2>/dev/null | wc -l)
  [ "$n" -ge 100 ] || return 1
  $VENV/bin/python -c "import torch; assert torch.__version__.startswith('2.7.0'), torch.__version__" 2>/dev/null || return 1
  return 0
}

if ! verify_clone; then
  step "clone $SRC -> $VENV (fresh)"
  rm -rf $VENV
  cp -a $SRC $VENV || { step "CLONE_FAIL"; exit 1; }
  grep -rl "/data/night/venv" $VENV/bin 2>/dev/null | while read -r f; do
    sed -i "s|/data/night/venv|/data/night/venv-judge|g" "$f"
  done
  sync
  verify_clone || { step "CLONE_VERIFY_FAIL (pkgs=$(ls $VENV/lib/python3.11/site-packages 2>/dev/null | wc -l))"; exit 1; }
  step "clone verified: torch OK"
else
  step "clone already good, skip"
fi

step "install judge deps (transformers 5.17 / peft 0.21 / tokenizers 0.23.2 / hub[cli] / qwen-vl-utils)"
ok=0
for attempt in 1 2 3; do
  $VENV/bin/pip install transformers==5.17.0 peft==0.21.0 "safetensors>=0.8.0" tokenizers==0.23.2 "huggingface_hub[cli]" "qwen-vl-utils[decord]" opencv-python-headless einops matplotlib $PIPOPT >> $LOG.pip 2>&1 && { ok=1; break; }
  step "pip attempt $attempt failed, retrying"
  sleep 10
done
[ $ok -eq 1 ] && step "PKGS OK" || { step "PKGS_FAIL"; exit 1; }
$VENV/bin/python -c "import transformers, peft; print('transformers', transformers.__version__, '| peft', peft.__version__)" || { step "IMPORT_FAIL"; exit 1; }

download_weights(){
  export HF_ENDPOINT=https://hf-mirror.com
  local hf="$VENV/bin/hf"
  [ -x "$hf" ] || hf="$VENV/bin/python -m huggingface_hub.commands.huggingface_cli"
  dl(){ step "dl begin $1 rev=$2"; $hf download "$1" ${2:+--revision "$2"} --local-dir "$3" --max-workers 4 >> $LOG.dl 2>&1 && step "dl OK $1" || step "dl FAIL $1"; }
  dl tinnel123/OmniJev v1.1               /data/night/models/OmniJev-4B-v1.1
  dl guanxuyu/visual-jev-4b-answer-sft "" /data/night/models/visual-jev-4b-answer-sft
  dl Qwen/Qwen3.5-4B ""                   /data/night/models/Qwen3.5-4B
  dl Qwen/Qwen3-VL-4B-Instruct ""         /data/night/models/Qwen3-VL-4B-Instruct
  dl MCG-NJU/VideoChat3-4B ""             /data/night/models/VideoChat3-4B
  step "ALL_WEIGHTS_DONE"
}
download_weights

step "=== freeze (judge-relevant) ==="
$VENV/bin/pip freeze 2>/dev/null | grep -E "^(torch|torchvision|transformers|peft|tokenizers|huggingface-hub|accelerate|safetensors|qwen-vl-utils|decord|numpy|pillow)"
step "SETUP4_ALL_DONE"

#!/usr/bin/env bash
# v5: download the 3 big judge base/weight repos with Xet disabled (hf-mirror CAS 401 workaround)
set -uo pipefail
LOG=/data/night/logs/dl_judge_weights5.log
VENV=/data/night/venv-judge
LOCK=/data/night/.judge_dl5.lock
step(){ echo "[$(date +%F\ %T)] $*"; }
mkdir "$LOCK" 2>/dev/null || { step "lock exists, exit"; exit 0; }
trap 'rmdir "$LOCK" 2>/dev/null' EXIT

export HF_ENDPOINT=https://hf-mirror.com
export HF_HUB_DISABLE_XET=1
hf="$VENV/bin/hf"; [ -x "$hf" ] || hf="$VENV/bin/python -m huggingface_hub.commands.huggingface_cli"
dl(){ step "dl begin $1"; $hf download "$1" --local-dir "$2" --max-workers 4 >> $LOG.dl 2>&1 && step "dl OK $1" || step "dl FAIL $1"; }
dl Qwen/Qwen3.5-4B              /data/night/models/Qwen3.5-4B
dl Qwen/Qwen3-VL-4B-Instruct    /data/night/models/Qwen3-VL-4B-Instruct
dl MCG-NJU/VideoChat3-4B        /data/night/models/VideoChat3-4B
step "DL5_ALL_DONE"

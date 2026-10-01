#!/usr/bin/env bash
# v7: dedicated venv-vc3 for VideoChat3 remote code (needs transformers 4.x; 5.17 breaks its video processor)
set -uo pipefail
LOG=/data/night/logs/setup_vc3_venv.log
VENV=/data/night/venv-vc3
SRC=/data/night/venv-judge
LOCK=/data/night/.vc3_venv.lock
IDX="https://mirrors.cloud.tencent.com/pypi/simple/"
step(){ echo "[$(date +%F\ %T)] $*"; }
mkdir "$LOCK" 2>/dev/null || { step "lock exists, exit"; exit 0; }
trap 'rmdir "$LOCK" 2>/dev/null' EXIT

if ! $VENV/bin/python -c "import transformers; assert transformers.__version__.startswith('4.')" 2>/dev/null; then
  step "clone $SRC -> $VENV"
  rm -rf $VENV
  cp -a $SRC $VENV || { step "CLONE_FAIL"; exit 1; }
  grep -rl "/data/night/venv-judge" $VENV/bin 2>/dev/null | while read -r f; do
    sed -i "s|/data/night/venv-judge|/data/night/venv-vc3|g" "$f"
  done
  sync
  $VENV/bin/python -c "import torch; assert torch.__version__.startswith('2.7.0')" || { step "CLONE_VERIFY_FAIL"; exit 1; }
  step "downgrade transformers to latest 4.x"
  $VENV/bin/pip install "transformers<5" -i $IDX --timeout 120 --retries 8 >> $LOG.pip 2>&1 || \
  $VENV/bin/pip install "transformers<5" -i $IDX --timeout 120 --retries 8 >> $LOG.pip 2>&1 || { step "DOWNGRADE_FAIL"; exit 1; }
fi
$VENV/bin/python -c "import transformers, torch; print('vc3 venv:', transformers.__version__, torch.__version__)"
step "VC3_VENV_DONE"

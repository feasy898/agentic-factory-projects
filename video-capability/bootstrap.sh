#!/usr/bin/env bash
# CRADLE bootstrap: repo skeleton + git init (run once on GPU server)
set -euo pipefail
cd ~/cradle

mkdir -p config src/api src/gen src/gates templates/narrative templates/shotcards \
         assets/products assets/scenes tests workdir/candidates workdir/gated \
         output reports/milestones reports/gallery_failures

# api.env: user may later fill; empty fields mean "use local fallback"
if [ ! -f config/api.env ]; then
cat > config/api.env <<'EOF'
# Optional OpenAI-compatible APIs. Empty = local fallback path.
IMAGE_API_BASE=
IMAGE_API_KEY=
IMAGE_MODEL=
VLM_API_BASE=
VLM_API_KEY=
VLM_MODEL=
TTS_API_BASE=
TTS_API_KEY=
TTS_API_MODEL=
ASR_API_BASE=
ASR_API_KEY=
ASR_API_MODEL=
EOF
fi

if [ ! -f config/settings.yaml ]; then
cat > config/settings.yaml <<'EOF'
project: cradle
device: cuda
dtype: fp16          # V100: fp16 only, bf16 unsupported
hf_endpoint: https://hf-mirror.com
paths:
  assets: assets
  candidates: workdir/candidates
  gated: workdir/gated
  output: output
  db: workdir/cradle.sqlite3
budgets:
  image_api: 300
  vlm_api: 1500
  tts_api: 200
  asr_api: 200
  wan_candidates_total: 200
debug_model: ltx      # iteration-phase generator
prod_model: wan_i2v_13b
EOF
fi

if [ ! -f .gitignore ]; then
cat > .gitignore <<'EOF'
.venv/
__pycache__/
*.pyc
*.pyo
.ipynb_checkpoints/
workdir/candidates/
workdir/gated/
workdir/*.sqlite3-wal
workdir/*.sqlite3-shm
output/*.mp4
output/*.mov
output/*.wav
output/*.m4a
models/
nohup.out
*.log
hf_download/
EOF
fi

if [ ! -d .git ]; then
  git init -q
  git config user.name "cradle-agent"
  git config user.email "cradle@localhost"
fi

git add -A
git commit -q -m "M0: bootstrap repo skeleton, SPECS v1.0, config templates" || true
echo "BOOTSTRAP_OK"
git log --oneline | head -3
find . -maxdepth 2 -type d | grep -v .git | sort

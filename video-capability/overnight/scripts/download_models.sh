#!/usr/bin/env bash
# download_models.sh — Wan2.1-T2V-1.3B-Diffusers (modelscope, 28.9G) + Lightricks/LTX-Video diffusers 子目录 (hf-mirror, ~30G)
# 等 setup_venv2.log 出现 SETUP_DONE 后才开始
set -x
export TMPDIR=/data/night/tmp
PY=/data/night/venv/bin/python3
df -h /data

for i in $(seq 1 180); do grep -q SETUP_DONE /data/night/logs/setup_venv2.log 2>/dev/null && break; sleep 10; done
grep -q SETUP_DONE /data/night/logs/setup_venv2.log || { echo WAIT_SETUP_TIMEOUT; exit 1; }

# ---- 1) Wan2.1-T2V-1.3B-Diffusers via modelscope（含 umt5 text_encoder 与 vae 子目录）
WAN_OK=0
for a in 1 2 3; do
  $PY -m modelscope download --model Wan-AI/Wan2.1-T2V-1.3B-Diffusers --local_dir /data/night/models/Wan2.1-T2V-1.3B-Diffusers && { WAN_OK=1; break; }
  echo "WAN_ATTEMPT${a}_RETRY"; sleep 5
done
[ $WAN_OK -eq 1 ] && echo WAN_DL_OK || echo WAN_DL_FAIL
ls -la /data/night/models/Wan2.1-T2V-1.3B-Diffusers/ 2>&1

# ---- 2) Lightricks/LTX-Video via hf-mirror，只拉 diffusers 子目录（根目录 250G 单文件历史权重绝不拉）
export HF_ENDPOINT=https://hf-mirror.com
export HF_HUB_ENABLE_HF_TRANSFER=0
$PY - <<'EOF' && echo LTX_DL_OK || echo LTX_DL_FAIL
from huggingface_hub import snapshot_download
p = snapshot_download(
    "Lightricks/LTX-Video",
    local_dir="/data/night/models/LTX-Video",
    allow_patterns=[
        "model_index.json", "scheduler/*", "text_encoder/*", "tokenizer/*",
        "transformer/*", "vae/*", "README.md",
        "LTX-Video-Open-Weights-License-0.X.txt", "ltx-video-2b-v0.9.1.license.txt",
    ],
    max_workers=4,
)
print("LTX_DIR", p)
EOF
ls -la /data/night/models/LTX-Video/ 2>&1
df -h /data
echo DOWNLOAD_DONE

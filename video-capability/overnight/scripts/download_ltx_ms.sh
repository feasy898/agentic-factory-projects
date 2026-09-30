#!/usr/bin/env bash
# download_ltx_ms.sh — LTX-Video 切 modelscope 官方镜像（hf-mirror 实测 ~2.7MB/s 太慢）
# allow_patterns 只拉 diffusers 子目录，根目录 250G 历史单文件权重绝不拉
set -x
export TMPDIR=/data/night/tmp
PY=/data/night/venv/bin/python3
LTX_OK=0
for a in 1 2 3; do
  $PY - <<'EOF' && { LTX_OK=1; break; } || { echo "LTX_ATTEMPT${a}_RETRY"; sleep 5; }
from modelscope import snapshot_download
p = snapshot_download(
    "Lightricks/LTX-Video",
    local_dir="/data/night/models/LTX-Video",
    allow_patterns=[
        "model_index.json", "scheduler/*", "text_encoder/*", "tokenizer/*",
        "transformer/*", "vae/*", "README.md",
        "LTX-Video-Open-Weights-License-0.X.txt", "ltx-video-2b-v0.9.1.license.txt",
    ],
)
print("LTX_DIR", p)
EOF
done
[ $LTX_OK -eq 1 ] && echo LTX_MS_OK || echo LTX_MS_FAIL
ls /data/night/models/LTX-Video/ 2>&1
df -h /data
echo LTX_MS_DONE

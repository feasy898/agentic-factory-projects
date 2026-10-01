#!/usr/bin/env bash
# download_wan_fix.sh — 修复: modelscope 无 __main__, 改用 Python API snapshot_download
set -x
export TMPDIR=/data/night/tmp
PY=/data/night/venv/bin/python3
WAN_OK=0
for a in 1 2 3; do
  $PY - <<'EOF' && { WAN_OK=1; break; } || { echo "WAN_ATTEMPT${a}_RETRY"; sleep 5; }
from modelscope import snapshot_download
p = snapshot_download("Wan-AI/Wan2.1-T2V-1.3B-Diffusers", local_dir="/data/night/models/Wan2.1-T2V-1.3B-Diffusers")
print("WAN_DIR", p)
EOF
done
[ $WAN_OK -eq 1 ] && echo WAN_DL_OK || echo WAN_DL_FAIL
ls /data/night/models/Wan2.1-T2V-1.3B-Diffusers/ 2>&1
echo WAN_DOWNLOAD_DONE

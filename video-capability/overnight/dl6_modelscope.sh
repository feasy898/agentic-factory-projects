#!/usr/bin/env bash
# v6: download Qwen3-VL-4B-Instruct + VideoChat3-4B from ModelScope direct URLs (hf-mirror CAS path too slow)
set -uo pipefail
LOG=/data/night/logs/dl6_modelscope.log
LOCK=/data/night/.judge_dl6.lock
step(){ echo "[$(date +%F\ %T)] $*"; }
mkdir "$LOCK" 2>/dev/null || { step "lock exists, exit"; exit 0; }
trap 'rmdir "$LOCK" 2>/dev/null' EXIT

fetch_repo(){
  local model="$1" dest="$2" listjson="$3"
  step "fetch $model -> $dest"
  mkdir -p "$dest"
  python3 - "$listjson" "$dest" <<'EOF' > /tmp/dl6_manifest.txt
import json, sys
listjson, dest = sys.argv[1], sys.argv[2]
d = json.load(open(listjson))
for f in d["Data"]["Files"]:
    if f["Type"] == "tree":
        continue
    print(f["Path"], f["Size"])
EOF
  local total=$(wc -l < /tmp/dl6_manifest.txt) i=0
  while read -r path size; do
    i=$((i+1))
    local out="$dest/$path"
    mkdir -p "$(dirname "$out")"
    local cursize=0; [ -f "$out" ] && cursize=$(stat -c%s "$out")
    if [ "$cursize" = "$size" ]; then step "skip($i/$total) $path"; continue; fi
    step "get($i/$total) $path ($size bytes)"
    curl -sL --fail --retry 5 --retry-delay 5 -C - --max-time 3600 \
      -o "$out" "https://modelscope.cn/api/v1/models/$model/repo?Revision=master&FilePath=$path" \
      && step "ok $path" || step "FAIL $path"
  done < /tmp/dl6_manifest.txt
  step "repo done: $model"
}

fetch_repo Qwen/Qwen3-VL-4B-Instruct /data/night/models/Qwen3-VL-4B-Instruct /tmp/vl_files.json
fetch_repo MCG-NJU/VideoChat3-4B     /data/night/models/VideoChat3-4B     /tmp/vc3_files.json
step "DL6_ALL_DONE"

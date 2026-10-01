#!/usr/bin/env bash
# T3 bootstrap: workspace, tools, repo clones, weight downloads (parallel, nohup)
set -uo pipefail
source /data/xdng/smoke/env.sh
LOG=/data/xdng/smoke/logs/bootstrap.log
exec >>"$LOG" 2>&1
echo "=== bootstrap start $(date -Is) ==="

# 1) tools: huggingface_hub (hf download) + imageio-ffmpeg (static ffmpeg binary, no sudo)
"$VENV/bin/pip" install -q -U huggingface_hub imageio-ffmpeg
mkdir -p /data/xdng/bin
FF="$("$VENV/bin/python" -c 'import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())' 2>/dev/null)"
echo "imageio ffmpeg: $FF"
[ -n "$FF" ] && ln -sf "$FF" /data/xdng/bin/ffmpeg && /data/xdng/bin/ffmpeg -version 2>/dev/null | head -1

# 2) clone repos
cd /data/xdng/smoke/repos
[ -d index-tts ] || git clone --depth 1 https://github.com/index-tts/index-tts.git 2>&1 | tail -1
[ -d VoxCPM ]    || git clone --depth 1 https://github.com/OpenBMB/VoxCPM.git 2>&1 | tail -1
[ -d MuseTalk ]  || git clone --depth 1 https://github.com/TMElyralab/MuseTalk.git 2>&1 | tail -1
echo "--- MuseTalk remote branches ---"
git -C MuseTalk ls-remote --heads https://github.com/TMElyralab/MuseTalk.git | awk '{print $2}' || true
echo "--- index-tts HEAD ---"
git -C index-tts log -1 --format='%H %ad %s' --date=short || true
echo "--- VoxCPM HEAD ---"
git -C VoxCPM log -1 --format='%H %ad %s' --date=short || true
echo "--- MuseTalk HEAD ---"
git -C MuseTalk log -1 --format='%H %ad %s' --date=short || true

# 3) probe Qwen3-ASR model names on hf-mirror API
echo "--- Qwen3-ASR name probe ---"
for N in Qwen3-ASR-0.6B Qwen3-ASR-1.7B Qwen3-ASR-0.6B-hf Qwen3-ASR-1.7B-hf; do
  CODE=$(curl -s -o /dev/null -w '%{http_code}' -m 15 "https://hf-mirror.com/api/models/Qwen/$N")
  echo "Qwen/$N -> $CODE"
done

# 4) start weight downloads in parallel (background, each with own log)
cd /data/xdng/smoke
nohup "$VENV/bin/hf" download IndexTeam/IndexTTS-2.5 --local-dir /data/xdng/models/dub-tts > logs/dl_dubtts.log 2>&1 &
echo "dl dub-tts pid $!"
nohup "$VENV/bin/hf" download openbmb/VoxCPM2 --local-dir /data/xdng/models/alt-tts-b > logs/dl_altttsb.log 2>&1 &
echo "dl alt-tts-b pid $!"
nohup "$VENV/bin/hf" download TMElyralab/MuseTalk --local-dir /data/xdng/models/lip-fast-repo > logs/dl_lipfast_repo.log 2>&1 &
echo "dl lip-fast main repo pid $!"
echo "=== bootstrap core done $(date -Is) ==="

#!/usr/bin/env bash
# T3 bootstrap fix: huggingface_hub<1.0, create repos dir, clones, weight downloads
set -uo pipefail
source /data/xdng/smoke/env.sh
LOG=/data/xdng/smoke/logs/bootstrap.log
exec >>"$LOG" 2>&1
echo "=== bootstrap2 start $(date -Is) ==="

"$VENV/bin/pip" install -q "huggingface_hub<1.0"
"$VENV/bin/python" -c "import huggingface_hub,transformers; print('hub',huggingface_hub.__version__,'tf',transformers.__version__)"

mkdir -p /data/xdng/smoke/repos
cd /data/xdng/smoke/repos
[ -d index-tts ] || git clone --depth 1 https://github.com/index-tts/index-tts.git 2>&1 | tail -1
[ -d VoxCPM ]    || git clone --depth 1 https://github.com/OpenBMB/VoxCPM.git 2>&1 | tail -1
[ -d MuseTalk ]  || git clone --depth 1 https://github.com/TMElyralab/MuseTalk.git 2>&1 | tail -1
echo "--- MuseTalk remote branches ---"
git -C MuseTalk ls-remote --heads origin 2>/dev/null | awk '{print $2}' || true
for r in index-tts VoxCPM MuseTalk; do
  echo "--- $r HEAD: $(git -C $r log -1 --format='%H %ad %s' --date=short 2>/dev/null)"
done

echo "--- Qwen3-ASR name probe ---"
for N in Qwen3-ASR-0.6B Qwen3-ASR-1.7B Qwen3-ASR-0.6B-hf Qwen3-ASR-1.7B-hf; do
  CODE=$(curl -s -o /dev/null -w '%{http_code}' -m 15 "https://hf-mirror.com/api/models/Qwen/$N")
  echo "Qwen/$N -> $CODE"
done

cd /data/xdng/smoke
nohup "$VENV/bin/hf" download IndexTeam/IndexTTS-2.5 --local-dir /data/xdng/models/dub-tts > logs/dl_dubtts.log 2>&1 &
echo "dl dub-tts pid $!"
nohup "$VENV/bin/hf" download openbmb/VoxCPM2 --local-dir /data/xdng/models/alt-tts-b > logs/dl_altttsb.log 2>&1 &
echo "dl alt-tts-b pid $!"
nohup "$VENV/bin/hf" download TMElyralab/MuseTalk --local-dir /data/xdng/models/lip-fast-repo > logs/dl_lipfast_repo.log 2>&1 &
echo "dl lip-fast repo pid $!"
echo "=== bootstrap2 done $(date -Is) ==="

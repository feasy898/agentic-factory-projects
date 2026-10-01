#!/usr/bin/env bash
# T3 smoke: lip-fast (MuseTalk 1.5) on a 2-second clip, fp16, GPU1 (CUDA_VISIBLE_DEVICES=1).
# Run from the MuseTalk repo root: preprocessing hardcodes './models/dwpose/...' AND
# './musetalk/utils/dwpose/...' relative to CWD, so models/ is symlinked into the repo.
set -uo pipefail
source /data/xdng/smoke/env.sh
REPO=/data/xdng/smoke/repos/MuseTalk
LOG=/data/xdng/smoke/logs/smoke_musetalk.log
RESULT_JSON=/data/xdng/smoke/artifacts/lip-fast_v15.json

t0=$(date +%s)
finish() { # ok artifact error
  SECS=$(( $(date +%s) - t0 ))
  /data/xdng/venv/bin/python -c "
import json, sys
ok, artifact, error, secs = sys.argv[1] == 'true', (sys.argv[2] or None), (sys.argv[3] or None), float(sys.argv[4])
json.dump({'model': 'lip-fast', 'dtype': 'fp16', 'ok': ok, 'seconds': secs,
           'artifact_path': artifact, 'error': error}, open('$RESULT_JSON', 'w'), indent=1)
print('WROTE $RESULT_JSON')
" "$1" "$2" "$3" "$SECS"
}

mkdir -p "$REPO/models"
ln -sfn /data/xdng/models/lip-fast-repo/musetalk    "$REPO/models/musetalk"
ln -sfn /data/xdng/models/lip-fast-repo/musetalkV15 "$REPO/models/musetalkV15"
ln -sfn /data/xdng/models/lip-fast/sd-vae           "$REPO/models/sd-vae"
ln -sfn /data/xdng/models/lip-fast/whisper          "$REPO/models/whisper"
ln -sfn /data/xdng/models/lip-fast/dwpose           "$REPO/models/dwpose"
ln -sfn /data/xdng/models/lip-fast/face-parse-bisent "$REPO/models/face-parse-bisent"

cat > /data/xdng/smoke/assets/mt_config.yaml <<'YAML'
task_0:
 video_path: "/data/xdng/smoke/assets/clip_2s.mp4"
 audio_path: "/data/xdng/smoke/assets/clip_2s.wav"
YAML

cd "$REPO"
export PYTHONPATH="$REPO"
echo "=== musetalk smoke start $(date -Is) ==="
timeout 1500 /data/xdng/venv/bin/python scripts/inference.py \
  --inference_config /data/xdng/smoke/assets/mt_config.yaml \
  --result_dir /data/xdng/smoke/artifacts/mt_results \
  --version v15 --vae_type sd-vae --gpu_id 0 --use_float16 \
  --unet_model_path ./models/musetalkV15/unet.pth \
  --unet_config ./models/musetalkV15/musetalk.json \
  --whisper_dir ./models/whisper \
  --ffmpeg_path /data/xdng/bin \
  --output_vid_name lip-fast_v15.mp4 >>"$LOG" 2>&1
RC=$?
echo "=== musetalk smoke rc=$RC $(date -Is) ==="
OUT=$(find /data/xdng/smoke/artifacts/mt_results -name 'lip-fast_v15.mp4' 2>/dev/null | head -1)
if [ $RC -eq 0 ] && [ -n "$OUT" ]; then
  /data/xdng/bin/ffmpeg -y -loglevel error -i "$OUT" -c copy /data/xdng/smoke/artifacts/lip-fast_v15.mp4
  finish true /data/xdng/smoke/artifacts/lip-fast_v15.mp4 ""
else
  tail -30 "$LOG"
  finish false "" "inference rc=$RC (see logs/smoke_musetalk.log)"
fi

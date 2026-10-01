#!/usr/bin/env bash
# T3 downloads round 2: fix xet timeouts, queue MuseTalk auxiliary weights
set -uo pipefail
source /data/xdng/smoke/env.sh
LOG=/data/xdng/smoke/logs/downloads2.log
exec >>"$LOG" 2>&1
echo "=== downloads2 start $(date -Is) ==="

# 1) kill stuck dub-tts download (xet bridge timeouts), drop hf_xet, restart via plain HTTP resolve
pkill -f 'hf download IndexTeam' || true
sleep 1
"$VENV/bin/pip" uninstall -y -q hf_xet 2>&1 | tail -1
nohup "$VENV/bin/hf" download IndexTeam/IndexTTS-2.5 --local-dir /data/xdng/models/dub-tts --max-workers 2 > logs/dl_dubtts2.log 2>&1 &
echo "dl dub-tts restarted pid $!"

# 2) MuseTalk auxiliary weights (parallel)
nohup "$VENV/bin/hf" download stabilityai/sd-vae-ft-mse --local-dir /data/xdng/models/lip-fast/sd-vae > logs/dl_sdvae.log 2>&1 &
echo "dl sd-vae pid $!"
nohup "$VENV/bin/hf" download openai/whisper-tiny --local-dir /data/xdng/models/lip-fast/whisper > logs/dl_whisper.log 2>&1 &
echo "dl whisper pid $!"
nohup "$VENV/bin/hf" download yzd-v/DWPose --include "dw-ll_ucoco_384.pth" --local-dir /data/xdng/models/lip-fast/dwpose > logs/dl_dwpose.log 2>&1 &
echo "dl dwpose pid $!"
nohup "$VENV/bin/hf" download ManyOtherFunctions/face-parse-bisent --local-dir /data/xdng/models/lip-fast/face-parse-bisent > logs/dl_faceparse.log 2>&1 &
echo "dl face-parse pid $!"
( curl -sL -m 300 https://download.pytorch.org/models/resnet18-5c106cde.pth -o /data/xdng/models/lip-fast/face-parse-bisent/resnet18-5c106cde.pth && echo "resnet18 ok $(du -h /data/xdng/models/lip-fast/face-parse-bisent/resnet18-5c106cde.pth)" ) 2>&1 | tail -1
echo "=== downloads2 done $(date -Is) ==="

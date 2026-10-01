#!/usr/bin/env bash
# T3: install VoxCPM + index-tts dep subsets, restart xet-stuck downloads, relaunch ASR smoke
set -uo pipefail
source /data/xdng/smoke/env.sh
LOG=/data/xdng/smoke/logs/step_deps.log
exec >>"$LOG" 2>&1
echo "=== deps step start $(date -Is) ==="

P="$VENV/bin/pip"
PY="$VENV/bin/python"
cat > /tmp/constraints.txt <<EOF
torch==2.4.1
transformers==5.13.0
huggingface-hub<2.0
numpy==2.4.6
EOF

# VoxCPM package (no deps) + its import-critical deps
$P install -q --no-deps /data/xdng/smoke/repos/VoxCPM 2>&1 | tail -1
$P install -q -c /tmp/constraints.txt einops inflect addict wetext simplejson sortedcontainers 2>&1 | grep -E 'Successfully|ERROR' | tail -1

# index-tts dep subset (no torch/transformers changes thanks to constraints)
$P install -q -c /tmp/constraints.txt cn2an jieba g2p-en descript-audiotools munch json5 omegaconf ffmpeg-python opencv-python-headless matplotlib pandas textstat fugashi unidic-lite modelscope 2>&1 | grep -E 'Successfully installed|ERROR' | tail -2

$PY -c "
import importlib
for m in ['einops','inflect','addict','wetext','simplejson','sortedcontainers','cn2an','jieba','g2p_en','descript_audiotools','munch','json5','omegaconf','ffmpeg','cv2','matplotlib','pandas','textstat','fugashi','modelscope']:
    try:
        importlib.import_module(m); print('ok', m)
    except Exception as e:
        print('FAIL', m, type(e).__name__, str(e)[:80])
" 2>&1 | grep -E '^ok|^FAIL' | sort | uniq -c | sort -rn | head; echo "---module check done---"
$PY -c "import importlib; importlib.import_module('modelscope')" 2>/dev/null || true

# restart xet-stuck downloads (processes predate hf_xet uninstall)
pkill -f 'hf download openbmb' || true
pkill -f 'hf download TMElyralab' || true
sleep 1
nohup $VENV/bin/hf download openbmb/VoxCPM2 --local-dir /data/xdng/models/alt-tts-b --max-workers 2 > logs/dl_altttsb2.log 2>&1 &
echo "alt-tts-b redl pid $!"
nohup $VENV/bin/hf download TMElyralab/MuseTalk --local-dir /data/xdng/models/lip-fast-repo --max-workers 2 > logs/dl_lipfast_repo2.log 2>&1 &
echo "lip-fast-repo redl pid $!"

# relaunch ASR smoke (25 min box)
cd /data/xdng/smoke
nohup timeout 1500 $PY smoke_asr.py /data/xdng/smoke/assets/ref_zh.wav > logs/smoke_asr.log 2>&1 &
echo "asr smoke relaunched pid $! at $(date -Is)"
echo "=== deps step done $(date -Is) ==="

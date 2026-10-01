#!/usr/bin/env bash
# T3 orchestrator: wait per-model weights -> run smoke (25 min box each) -> assemble report
set -uo pipefail
source /data/xdng/smoke/env.sh
LOG=/data/xdng/smoke/logs/run_smokes.log
exec >>"$LOG" 2>&1
PY="$VENV/bin/python"

wait_dl() { # pattern-file-marker
  local pat="$1"
  echo "[$(date -Is)] waiting for download: $pat"
  for i in $(seq 1 240); do
    pgrep -f "$pat" >/dev/null 2>&1 || return 0
    sleep 10
  done
  echo "[$(date -Is)] WARN: download still running after 40min wait: $pat"
  return 0
}

echo "=== run_smokes start $(date -Is) ==="

# --- item 3: dub-tts fp32 + fp16 attempt ---
wait_dl 'hf download IndexTeam/IndexTTS[-]2.5'
echo "[$(date -Is)] dub-tts weights ready; running smoke (fp32 then fp16 attempt)"
cd /data/xdng/smoke
timeout 1500 $PY smoke_indextts.py both >> logs/smoke_indextts.log 2>&1
echo "[$(date -Is)] indextts smoke rc=$?"

# --- item 2: lip-fast (MuseTalk 1.5) ---
wait_dl 'hf download TMElyralab/MuseTalk'
for i in $(seq 1 120); do
  grep -q 'prep_musetalk done' logs/prep_musetalk.log 2>/dev/null && break
  sleep 10
done
echo "[$(date -Is)] starting musetalk smoke"
bash /data/xdng/smoke/smoke_musetalk.sh
echo "[$(date -Is)] musetalk smoke rc=$?"

# --- item 1: alt-tts-b (VoxCPM2) ---
wait_dl 'hf download openbmb/VoxCPM2'
echo "[$(date -Is)] alt-tts-b weights ready; running smoke"
cd /data/xdng/smoke
timeout 1500 $PY smoke_voxcpm.py >> logs/smoke_voxcpm.log 2>&1
echo "[$(date -Is)] voxcpm smoke rc=$?"

# --- assemble ---
$PY /data/xdng/smoke/assemble_report.py >> logs/assemble.log 2>&1
echo "[$(date -Is)] report assembled rc=$? -> /data/xdng/smoke/smoke_report.json"
echo "=== run_smokes done $(date -Is) ==="

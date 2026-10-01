#!/usr/bin/env bash
# M3 三车道实测: pure_gen_short(S09 雨窗 2s) / compositing_2d5(S01 毛肚 5s) /
# evidence_transfer(S18 演示源 3s) 各 ≥1 条真实镜头走完整 initdb→ingest→run→G1-G7 门禁链。
# 在 M3 沙箱内执行: bash scripts/m3_lane_shots.sh (先 bash scripts/m3_sandbox.sh)
set -euo pipefail
SB=/root/cradle_m3
cd "$SB"
export CRADLE_ROOT="$SB"
export CRADLE_CLIP_WEIGHTS=/root/cradle/models/clip/ViT-L-14.pt
export HF_HUB_OFFLINE=1
PY=/root/cradle/.venv/bin/python

$PY -m src.cli initdb
$PY -m src.cli ingest templates/shotcards_v2/S09_rain_window.json
$PY -m src.cli ingest templates/shotcards_v2/S01_evidence_product.json
$PY -m src.cli ingest templates/shotcards_v2/S18_evidence_demo.json
$PY -m src.cli run --once
$PY -m src.cli status --events 40
$PY - <<'PYEOF'
import json, sqlite3
db = sqlite3.connect("/root/cradle_m3/workdir/cradle.sqlite3")
db.row_factory = sqlite3.Row
rows = db.execute(
    "SELECT shot_id, lane, status, attempts, error FROM tasks WHERE shot_id IN ('S09','S01','S18')"
).fetchall()
out = []
for r in rows:
    cand = db.execute(
        "SELECT id, path, verdict, overall_score, gate_json FROM candidates "
        "WHERE shot_id=? ORDER BY id", (r["shot_id"],)).fetchall()
    out.append({"task": dict(r), "candidates": [
        {"id": c["id"], "verdict": c["verdict"], "overall_score": c["overall_score"],
         "gates": json.loads(c["gate_json"])} for c in cand]})
with open("/root/cradle_m3/workdir/logs/v2m3_lane_shots.json", "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)
print("lane shots snapshot -> workdir/logs/v2m3_lane_shots.json")
for o in out:
    print(o["task"]["shot_id"], o["task"]["lane"], o["task"]["status"])
PYEOF

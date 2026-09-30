#!/usr/bin/env bash
# V2-M3C: S01 (compositing_2d5) 单镜头重跑 —— 分辨率修复后
set -ex
export CRADLE_ROOT=/root/cradle_m3
export CRADLE_CLIP_WEIGHTS=/root/cradle/models/clip/ViT-L-14.pt
export HF_HUB_OFFLINE=1
cd /root/cradle
PY=/root/cradle/.venv/bin/python

# 清沙箱 DB 中 S01 旧行 (blocked 残留)
$PY - <<'PYCLEAN'
import sqlite3
db = sqlite3.connect("/root/cradle_m3/workdir/cradle.sqlite3")
for t in ("candidates", "events_ref", "events"):
    try:
        db.execute(f"DELETE FROM {t} WHERE shot_id='S01'")
    except sqlite3.OperationalError:
        pass
db.execute("DELETE FROM tasks WHERE shot_id='S01'")
db.commit()
print("S01 rows cleaned")
PYCLEAN

$PY -m src.cli ingest /root/cradle_m3/templates/shotcards_v2/S01_evidence_product.json
for i in $(seq 1 20); do
  $PY -m src.cli run --once >/dev/null 2>&1 || true
  ST=$($PY - <<'PYSNAP'
import sqlite3
db = sqlite3.connect("/root/cradle_m3/workdir/cradle.sqlite3")
st = db.execute("SELECT status FROM tasks WHERE shot_id='S01'").fetchone()
print(st[0] if st else "none")
PYSNAP
)
  echo "pass $i: S01=$ST"
  case "$ST" in accepted|fallback|blocked|composed) break;; esac
done

# 全量 snapshot 刷新 (三镜头)
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
print("lane shots snapshot refreshed")
for o in out:
    print(o["task"]["shot_id"], o["task"]["lane"], o["task"]["status"])
PYEOF

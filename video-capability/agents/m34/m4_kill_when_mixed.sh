#!/usr/bin/env bash
# M4 崩溃演示 watcher: 轮询沙箱 DB, 出现 "gating>=1 且 generating>=1" 窗口时 kill -9 编排器。
# 用法: bash scripts/m4_kill_when_mixed.sh <sandbox>
SB="$1"
DB="$SB/workdir/cradle.sqlite3"
PIDFILE="$SB/workdir/orchestrator.pid"
SNAP="$SB/workdir/logs/m4_prekill_snapshot.txt"

for i in $(seq 1 180); do
  R=$(python3 - "$DB" <<'PYEOF'
import sqlite3, sys
db = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
print(dict(db.execute("select status, count(*) from tasks group by status").fetchall()))
PYEOF
)
  echo "$(date +%T) poll#$i $R"
  if echo "$R" | grep -q "'generating': 1" && echo "$R" | grep -q "'gating':"; then
    {
      echo "=== PRE-KILL SNAPSHOT $(date +%F' '%T) ==="
      python3 - "$DB" <<'PYEOF'
import sqlite3, sys, os
db = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
db.row_factory = sqlite3.Row
print("-- tasks --")
for r in db.execute("select shot_id, status, attempts, error from tasks order by shot_id"):
    print(dict(r))
print("-- candidates --")
for r in db.execute("select id, shot_id, verdict, selected, path from candidates order by id"):
    d = dict(r)
    d["mtime"] = os.stat(d["path"]).st_mtime if os.path.exists(d["path"]) else None
    d["size"] = os.stat(d["path"]).st_size if os.path.exists(d["path"]) else None
    print(d)
PYEOF
      echo "-- run1 log tail --"
      tail -5 "$SB/workdir/logs/m4_run1.log" | grep -a -v "it/s" || true
    } > "$SNAP" 2>&1
    PID=$(cat "$PIDFILE")
    kill -9 "$PID"
    echo "KILL9 pid=$PID at $(date +%F' '%T)"
    exit 0
  fi
  sleep 1
done
echo "TIMEOUT: window not caught"
exit 1

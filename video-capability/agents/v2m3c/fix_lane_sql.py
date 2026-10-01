#!/usr/bin/env python3
"""Fix lost quotes in m3_lane_shots.sh PYSNAP SQL."""
from pathlib import Path

p = Path("/root/cradle/scripts/m3_lane_shots.sh")
s = p.read_text(encoding="utf-8")
old = 'rows = db.execute("SELECT status FROM tasks WHERE shot_id IN (S09,S01,S18)").fetchall()'
new = 'rows = db.execute("SELECT status FROM tasks WHERE shot_id IN (\'S09\',\'S01\',\'S18\')").fetchall()'
assert old in s, "broken SQL line not found"
p.write_text(s.replace(old, new), encoding="utf-8")
print("SQL quotes fixed")

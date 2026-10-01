"""V2-M4: production DB snapshot -> JSON for report.

Usage (on server): CRADLE_ROOT=/root/cradle_v2m4 python v2m4_stats.py
Dumps tasks, candidates (with G7 sub-scores), per-lane yield, G7 trigger detail,
Wan usage, and m5_videos ledger to /root/cradle_v2m4/workdir/logs/v2m4_stats.json.
"""
import json
import os
import sqlite3
import sys

SB = os.environ.get("CRADLE_ROOT", "/root/cradle_v2m4")
db = sqlite3.connect(os.path.join(SB, "workdir", "cradle.sqlite3"))
db.row_factory = sqlite3.Row

WAN_LANES_SQL = "('first_frame_i2v','pure_gen_short','evidence_transfer','t2v')"
TERMINAL = ("accepted", "fallback", "blocked", "composed")

tasks = db.execute(
    "SELECT shot_id, narrative_slot, lane, status, attempts, error FROM tasks ORDER BY shot_id"
).fetchall()

cands = db.execute(
    "SELECT c.id, c.shot_id, c.verdict, c.overall_score, c.gate_json, c.path "
    "FROM candidates c ORDER BY c.shot_id, c.id"
).fetchall()

out = {"tasks": [], "candidates": [], "videos": []}
g7_triggers = []
for t in tasks:
    out["tasks"].append(dict(t))
for c in cands:
    gates = json.loads(c["gate_json"] or "{}")
    entry = {"id": c["id"], "shot_id": c["shot_id"], "verdict": c["verdict"],
             "overall_score": c["overall_score"], "path": c["path"], "gates": gates}
    g7 = gates.get("G7") or {}
    if isinstance(g7, dict):
        subs = g7.get("detail") or {}
        entry["g7"] = {k: g7.get(k) for k in ("passed", "score") if k in g7}
        entry["g7_subs"] = {k: {kk: v.get(kk) for kk in ("score", "triggered", "skipped", "reason")}
                            for k, v in subs.items() if isinstance(v, dict)}
        if g7.get("passed") is False:
            trig = [k for k, v in subs.items()
                    if isinstance(v, dict) and v.get("triggered")]
            g7_triggers.append({"candidate": c["id"], "shot_id": c["shot_id"],
                                "g7_score": g7.get("score"), "triggered": trig})
    out["candidates"].append(entry)

# per-lane yield: task level + candidate level
lanes = {}
for t in out["tasks"]:
    L = lanes.setdefault(t["lane"], {"tasks": 0, "terminal": 0, "accepted": 0, "fallback": 0,
                                     "blocked": 0, "composed": 0, "cand_total": 0, "cand_pass": 0,
                                     "cand_fail": 0, "wan_candidates": 0})
    L["tasks"] += 1
    if t["status"] in TERMINAL:
        L["terminal"] += 1
    if t["status"] in ("accepted", "composed"):
        L["accepted"] += 1
    elif t["status"] == "fallback":
        L["fallback"] += 1
    elif t["status"] == "blocked":
        L["blocked"] += 1
wan_total = 0
for c in out["candidates"]:
    lane = next((t["lane"] for t in out["tasks"] if t["shot_id"] == c["shot_id"]), "?")
    L = lanes.setdefault(lane, {"tasks": 0, "terminal": 0, "accepted": 0, "fallback": 0,
                                "blocked": 0, "composed": 0, "cand_total": 0, "cand_pass": 0,
                                "cand_fail": 0, "wan_candidates": 0})
    L["cand_total"] += 1
    if c["verdict"] == "pass":
        L["cand_pass"] += 1
    else:
        L["cand_fail"] += 1
    is_wan = False
    for t in out["tasks"]:
        if t["shot_id"] == c["shot_id"] and t["lane"] in ("first_frame_i2v", "pure_gen_short",
                                                          "evidence_transfer"):
            is_wan = True
    if is_wan:
        L["wan_candidates"] += 1
        wan_total += 1
out["per_lane_yield"] = lanes
out["wan_candidates_total"] = wan_total
out["g7_killed"] = g7_triggers

vids = db.execute("SELECT video_id, template_id, spec_json, shots_json, path, g6_json "
                  "FROM m5_videos ORDER BY video_id").fetchall()
for v in vids:
    out["videos"].append({k: v[k] for k in v.keys()})

path = os.path.join(SB, "workdir", "logs", "v2m4_stats.json")
with open(path, "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=1)
print("stats ->", path)
print(json.dumps(out["per_lane_yield"], ensure_ascii=False, indent=1))
print("wan_candidates_total =", wan_total)
print("g7_killed =", json.dumps(g7_triggers, ensure_ascii=False))

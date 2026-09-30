#!/usr/bin/env python3
"""M2 任务6: Wan 装配一次性验证 (D-029)。

十镜头闭环全绿后, 用装配好的 src/gen/wan.py (DiffSynth Fun-InP) 跑 1 条候选过全门禁链,
目的: M5 量产前消除装配风险。生成 + 真实六门禁 + 记账, 产物:
  workdir/candidates/wan_verify_S01.mp4
  reports/milestones/m2_wan_verify.json
"""
import json
import os
import sys
import time

os.chdir(os.path.expanduser("~/cradle"))
sys.path.insert(0, os.getcwd())

from src.db import DB
from src.orchestrator import Orchestrator
from src.schema import load_shotcard

out = {"script": "m2_wan_verify", "model": "PAI/Wan2.1-Fun-1.3B-InP via src/gen/wan.py (D-028)"}
card = load_shotcard("templates/shotcards/S01_evidence_product.json")
out["card"] = {k: card[k] for k in ("shot_id", "resolution", "duration_sec", "fps", "lane")}
print("production card:", json.dumps(out["card"]))

from src.gen.wan import generate as wan_generate

t0 = time.time()
meta = wan_generate(card, seed=42, out_path="workdir/candidates/wan_verify_S01.mp4", steps=20)
out["gen_meta"] = meta
out["total_sec"] = round(time.time() - t0, 1)
print("gen meta:", json.dumps(meta))

# 真实门禁链(与 orchestrator 同路径; 生产卡口径 480×832/5.0s@16fps)
db = DB("/tmp/m2_wan_verify.sqlite3")
db.migrate()
orch = Orchestrator(db)
gates = orch._default_gater()(meta["path"], card)
out["gates"] = gates
for g in ("G1", "G2", "G3", "G4", "G5", "G6"):
    d = gates.get(g, {})
    print(g, "passed=", d.get("passed"), "score=", d.get("score"),
          json.dumps({k: v for k, v in (d.get("detail") or {}).items()
                      if k in ("worst", "defects", "min_similarity", "min_adjacent_similarity",
                               "overall_score", "overall_defect", "verdict", "main_issue", "checks")},
                     ensure_ascii=False)[:400])
from src.gates import all_passed

out["all_passed"] = all_passed(gates)
with open("reports/milestones/m2_wan_verify.json", "w") as f:
    json.dump(out, f, ensure_ascii=False, indent=1, default=str)
print("WAN VERIFY DONE all_passed=", out["all_passed"])

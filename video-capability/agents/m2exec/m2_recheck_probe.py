#!/usr/bin/env python3
"""重校准后复验: 对已存在的探针候选重跑门禁, 确认 G2/G5 行为合理。"""
import json
import os
import sys

os.chdir(os.path.expanduser("~/cradle"))
sys.path.insert(0, os.getcwd())

from src.db import DB
from src.gen.ltx import project_card_for_debug
from src.orchestrator import Orchestrator
from src.schema import load_shotcard

card = project_card_for_debug(load_shotcard("templates/shotcards/S01_evidence_product.json"))
db = DB("/tmp/m2_probe2.sqlite3")
db.migrate()
orch = Orchestrator(db)
gater = orch._default_gater()
gates = gater("workdir/candidates/m2_wiring_probe.mp4", card)
for g in ("G1", "G2", "G3", "G4", "G5", "G6"):
    d = gates.get(g, {})
    print(g, "passed=", d.get("passed"), "score=", d.get("score"),
          json.dumps({k: v for k, v in (d.get("detail") or {}).items()
                      if k in ("worst", "defects", "min_similarity", "min_adjacent_similarity", "overall_score",
                               "overall_defect", "aesthetic", "camera_match", "verdict", "main_issue",
                               "camera_match_basis")}, ensure_ascii=False)[:500])
from src.gates import all_passed

print("ALL_PASSED:", all_passed(gates))

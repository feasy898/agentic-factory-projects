#!/usr/bin/env python3
"""M2 装配探针: 用接线后的 ltx.py 真跑 1 条候选(S01 投影卡, I2V), 再过真实六门禁链。
目的: ① 验证装配/门禁链路 ② 采集 CLIP 启发式与 G3/G4 实测分布, 预判冷启动阈值校准。"""
import json
import os
import sys
import time

os.chdir(os.path.expanduser("~/cradle"))
sys.path.insert(0, os.getcwd())

from src.gen.ltx import generate as ltx_generate, project_card_for_debug
from src.schema import load_shotcard

out = {"script": "m2_wiring_probe", "attempts": []}

card = load_shotcard("templates/shotcards/S01_evidence_product.json")
proj = project_card_for_debug(card)
out["projected"] = {k: proj[k] for k in ("shot_id", "resolution", "duration_sec", "fps", "n_best", "lane")}
print("projected card:", json.dumps(out["projected"]))

t0 = time.time()
meta = ltx_generate(proj, seed=12345, out_path="workdir/candidates/m2_wiring_probe.mp4", steps=12)
out["gen_meta"] = meta
out["load_incl_sec"] = round(time.time() - t0, 1)
print("gen meta:", json.dumps(meta))

# 第二条复用缓存管线, 验证进程级缓存与耗时
t1 = time.time()
meta2 = ltx_generate(proj, seed=12346, out_path="workdir/candidates/m2_wiring_probe2.mp4", steps=12)
out["cached_gen_sec"] = round(time.time() - t1, 1)
out["cached_gen_only"] = meta2["gen_seconds"]
print("cached pipeline total:", out["cached_gen_sec"], "s, gen only:", meta2["gen_seconds"], "s")

# 真实门禁链(与 orchestrator._default_gater 同一路径)
from src.db import DB
from src.orchestrator import Orchestrator

db = DB("/tmp/m2_probe.sqlite3")
db.migrate()
orch = Orchestrator(db)
g1 = orch.gater.__self__ if False else None
gater = orch._default_gater()
gates = gater(meta["path"], proj)
out["gates"] = gates
for g in ("G1", "G2", "G3", "G4", "G5", "G6"):
    d = gates.get(g, {})
    print(g, "passed=", d.get("passed"), "score=", d.get("score"),
          json.dumps({k: v for k, v in (d.get("detail") or {}).items()
                      if k in ("worst", "defects", "min_similarity", "min_adjacent_similarity", "overall_score",
                               "overall_defect", "aesthetic", "camera_match", "verdict", "main_issue",
                               "checks", "error")}, ensure_ascii=False)[:600])

with open("workdir/logs/m2_wiring_probe.json", "w") as f:
    json.dump(out, f, ensure_ascii=False, indent=1, default=str)
print("PROBE DONE")

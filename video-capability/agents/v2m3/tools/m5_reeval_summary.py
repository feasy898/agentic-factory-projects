#!/usr/bin/env python3
"""从 m5_reeval_g5.json 打印分锚重评摘要(不经 CLIP)。"""
import json
import statistics
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
d = json.load(open(REPO / "workdir" / "logs" / "m5_reeval_g5.json"))
rows = d["rows"]
by = {}
for r in rows:
    by.setdefault(r["shot_id"], []).append(r)
hdr = "shot  type   n  m2g5(p50) old(p50) new(p50) new_min new_max new_pass  identity"
print(hdr)
for s in sorted(by):
    rs = by[s]
    m2 = [float(r["m2_g5_score"]) for r in rs if r["m2_g5_score"] is not None]
    old = [r["old_g5"] for r in rs]
    new = [r["new_g5"] for r in rs]
    ident = all(r["food_identity_ok"] for r in rs if r["asset_type"] == "food")
    print(f"{s:5s} {rs[0]['asset_type']:6s} {len(rs):2d} "
          f"{statistics.median(m2):9.4f} {statistics.median(old):8.4f} {statistics.median(new):8.4f} "
          f"{min(new):7.4f} {max(new):7.4f} {sum(1 for x in new if x >= 0.70)}/{len(new):<7d} "
          f"{'OK' if ident else 'BAD'}")
print("total", len(rows), "| identity_violations",
      sum(1 for r in rows if not r["food_identity_ok"]),
      "| new verdicts", {v: sum(1 for r in rows if r["new_verdict"] == v)
                         for v in ("pass", "borderline", "fail")})
# G2 一致性: 新旧 defect 域未动, G2 应不变 — 用 overall_defect 抽查
import collections
diff = collections.Counter()
for r in rows:
    if r["asset_type"] == "food" and abs(r["old_g5"] - float(r["m2_g5_score"] or 0)) > 1e-6:
        diff[r["shot_id"]] += 1
print("food mismatch detail:", dict(diff) or "none")
sys.exit(0)

import sqlite3, json
from collections import Counter

db = sqlite3.connect("/root/cradle_m5/workdir/cradle.sqlite3")
db.row_factory = sqlite3.Row
rows = [dict(r) for r in db.execute("select id, shot_id, verdict, overall_score, gate_json, path from candidates order by id")]
ab = [r for r in rows if str(r["shot_id"]).startswith("AB")]
prod = [r for r in rows if not str(r["shot_id"]).startswith("AB")]

def p50(v):
    v = sorted(v); n = len(v)
    return v[(n-1)//2] if n % 2 else (v[n//2-1] + v[n//2]) / 2

for label, group in (("AB", ab), ("PROD", prod)):
    parsed = [json.loads(r["gate_json"]) for r in group]
    vc = Counter(r["verdict"] for r in group)
    print(f"==== {label} n={len(group)} verdicts={dict(vc)}")
    for gk in ("G1", "G2", "G3", "G4", "G5", "G6"):
        scores = [g[gk]["score"] for g in parsed if gk in g and isinstance(g[gk].get("score"), (int, float))]
        passed = [g[gk]["passed"] for g in parsed if gk in g]
        if scores:
            print(f"  {gk}: pass={sum(passed)}/{len(passed)} min={min(scores):.4f} p50={p50(scores):.4f} max={max(scores):.4f}")

print()
print("==== PROD per-shot candidate counts ====")
cnt = Counter(str(r["shot_id"]) for r in prod)
for s in sorted(cnt, key=lambda x: int(x[1:])):
    vs = [r["verdict"] for r in prod if str(r["shot_id"]) == s]
    print(f"  {s}: n={cnt[s]} verdicts={vs}")

print()
print("==== AB per-card P/L gate scores ====")
for r in ab:
    g = json.loads(r["gate_json"])
    d = {k: round(g[k]["score"], 4) for k in ("G1", "G2", "G3", "G4", "G5", "G6") if k in g}
    print(f"  {r['shot_id']}: overall={r['overall_score']:.4f} {d}")

print()
print("==== FAIL detail ====")
for r in prod:
    if r["verdict"] == "fail":
        g = json.loads(r["gate_json"])
        print(r["id"], r["shot_id"], "overall", r["overall_score"])
        for k in g:
            if not g[k]["passed"]:
                det = g[k].get("detail") or {}
                print("   FAIL GATE", k, "score=", g[k]["score"], "detail=", json.dumps(det, ensure_ascii=False)[:500])
            if k == "G5":
                print("   G5 detail:", json.dumps(g[k].get("detail") or {}, ensure_ascii=False)[:400])

print()
print("==== selected prod candidates (one per shot) ====")
for r in prod:
    if r["selected"]:
        g = json.loads(r["gate_json"])
        d = {k: round(g[k]["score"], 4) for k in ("G1", "G2", "G3", "G4", "G5", "G6") if k in g}
        print(f"  {r['shot_id']}: cand={r['id']} overall={r['overall_score']:.4f} {d}")

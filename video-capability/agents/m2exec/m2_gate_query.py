#!/usr/bin/env python3
"""M2 门禁明细查询/聚合 (报告佐证脚本, SPECS §10 "每条成片门禁明细可追溯")。

用法: python3 reports/milestones/m2_gate_query.py [--db workdir/cradle.sqlite3] [--out <json>]
- 纯 stdlib(SQLite); 输出: 每镜头结局 / 六门禁通过率 / 分数分布 / 失败聚类 / 重试与降级统计。
- 直接 SQL 见同目录 m2_gate_query.sql。
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import statistics
from pathlib import Path

GATES = ("G1", "G2", "G3", "G4", "G5", "G6")


def p50(xs):
    return round(statistics.median(xs), 4) if xs else None


def dist(xs):
    xs = [round(float(x), 4) for x in xs if x is not None]
    return {"min": min(xs) if xs else None, "p50": p50(xs), "max": max(xs) if xs else None, "n": len(xs)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=None)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    db_path = a.db or os.path.expanduser("~/cradle/workdir/cradle.sqlite3")
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row

    tasks = [dict(r) for r in con.execute("SELECT * FROM tasks ORDER BY id")]
    cands = [dict(r) for r in con.execute("SELECT * FROM candidates ORDER BY shot_id, id")]
    for c in cands:
        c["gate_json"] = json.loads(c["gate_json"] or "{}")

    # ---- 每镜头结局 ----
    per_shot = {}
    for t in tasks:
        sel = con.execute("SELECT path, verdict, overall_score FROM candidates WHERE shot_id=? AND selected=1",
                          (t["shot_id"],)).fetchone()
        per_shot[t["shot_id"]] = {
            "status": t["status"],
            "lane": t["lane"],
            "attempts": t["attempts"],
            "n_candidates": sum(1 for c in cands if c["shot_id"] == t["shot_id"]),
            "n_pass": sum(1 for c in cands if c["shot_id"] == t["shot_id"] and c["verdict"] == "pass"),
            "n_fail": sum(1 for c in cands if c["shot_id"] == t["shot_id"] and c["verdict"] == "fail"),
            "selected": dict(sel) if sel else None,
            "error": t["error"],
        }

    # ---- 六门禁通过率与分数分布(仅真实生成候选, fallback 不计) ----
    gen = [c for c in cands if c["verdict"] in ("pass", "fail")]
    gate_stats = {}
    for g in GATES:
        scores, passed, present = [], 0, 0
        for c in gen:
            d = c["gate_json"].get(g)
            if not d:
                continue
            present += 1
            scores.append(d.get("score", 0.0))
            passed += bool(d.get("passed"))
        gate_stats[g] = {
            "evaluated": present,
            "passed": passed,
            "pass_rate": round(passed / present, 4) if present else None,
            "score_dist": dist(scores),
        }

    # ---- 候选级 overall(六门禁均分, D-018) ----
    overall = dist([c["overall_score"] for c in gen])

    # ---- 失败聚类 ----
    fail_clusters = {}
    for c in gen:
        if c["verdict"] != "fail":
            continue
        failed_gates = [g for g in GATES if c["gate_json"].get(g) and not c["gate_json"][g].get("passed")]
        g5 = (c["gate_json"].get("G5") or {}).get("detail", {})
        issue = g5.get("main_issue") or ("gate_fail:" + "+".join(failed_gates))
        key = f"{issue}|{'+'.join(failed_gates)}"
        fail_clusters.setdefault(key, {"count": 0, "shots": set()})
        fail_clusters[key]["count"] += 1
        fail_clusters[key]["shots"].add(c["shot_id"])
    fail_clusters = {
        k: {"count": v["count"], "shots": sorted(v["shots"])} for k, v in
        sorted(fail_clusters.items(), key=lambda kv: -kv[1]["count"])
    }

    # ---- 记账汇总 ----
    gen_meta = dist([t.get("duration_s") for t in tasks if t.get("duration_s")])
    vram = dist([t.get("vram_peak_mb") for t in tasks if t.get("vram_peak_mb")])

    report = {
        "db": db_path,
        "tasks_total": len(tasks),
        "by_status": {s: sum(1 for t in tasks if t["status"] == s) for s in
                      ("pending", "generating", "gating", "accepted", "retrying", "fallback", "composed", "blocked")},
        "candidates_total": len(cands),
        "candidates_generated": len(gen),
        "candidates_fallback": sum(1 for c in cands if c["verdict"] == "fallback"),
        "per_shot": per_shot,
        "gate_stats": gate_stats,
        "candidate_overall_dist": overall,
        "fail_clusters": fail_clusters,
        "task_duration_dist": gen_meta,
        "task_vram_peak_dist": vram,
    }
    text = json.dumps(report, ensure_ascii=False, indent=1)
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")
        print(f"written -> {a.out}")
    print(text)


if __name__ == "__main__":
    main()

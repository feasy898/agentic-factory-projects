#!/usr/bin/env python
"""V2-M2: G7 校准分析 (SPECS_V2 §4) — 全部离线, 输入=M1 全量运行的原始指标 JSON。

不重跑模型: 每子项原始分数/序列已在运行 JSON 中; G7b 用 dets_raw 离线重放
LiteByteTracker(任意 det 阈值), G7a 有 bbox/fullframe 双口径序列。

输出:
- reports/fixtures/g7_dist_*.png        分布图(直方图, fail/pass_structural/pass_candidate 三组)
- reports/fixtures/g7_roc_*.png         每子项阈值扫描 ROC + 组合整体 ROC
- workdir/logs/v2m1_calibration.json    扫描原始数据(报告数字出处)
stdout: 每子项可分性摘要 + 工作点候选表
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.gates.g7_object_persistence import (  # noqa: E402
    LiteByteTracker,
    count_series_metrics,
    tracker_stats,
)

RUN_JSON = ROOT / "workdir" / "logs" / "v2m1_g7_initial.json"
OUT_DIR = ROOT / "reports" / "fixtures"
OUT_JSON = ROOT / "workdir" / "logs" / "v2m1_calibration.json"


def load():
    return json.loads(RUN_JSON.read_text(encoding="utf-8"))


def replay_b(dets_raw, det_thr, high_thr=0.35, min_hits=2, max_age=2, n_frames=None):
    """离线重放跟踪器(与运行期同代码路径)。"""
    dets_rt = [[d for d in frame if d["score"] >= det_thr] for frame in dets_raw]
    tr = LiteByteTracker(high_thresh=high_thr, min_hits=min_hits, max_age=max_age)
    for i, dets in enumerate(dets_rt):
        tr.update(dets, i)
    stats = tracker_stats(tr, n_frames or len(dets_raw))
    m = count_series_metrics(stats["counts"])
    return {"counts": stats["counts"], "max_abs_delta": m["max_abs_delta"],
            "variance": m["variance"], "churn": stats["churn"]}


def series_by_label(recs, extract, labels=("fail", "pass_structural", "pass_candidate")):
    return {lab: [extract(r) for r in recs if r["label"] == lab and extract(r) is not None]
            for lab in labels}


def hist_plot(vals_by_label, title, path, xlabel, logy=False):
    import matplotlib

    matplotlib.use("Agg")
    matplotlib.rcParams["font.family"] = ["Noto Serif CJK SC", "DejaVu Sans"]
    matplotlib.rcParams["axes.unicode_minus"] = False
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(7, 4.2))
    colors = {"fail": "#d62728", "pass_structural": "#2ca02c", "pass_candidate": "#1f77b4"}
    for lab, vals in vals_by_label.items():
        if not vals:
            continue
        ax.hist(vals, bins=20, alpha=0.55, label=f"{lab} (n={len(vals)})",
                color=colors.get(lab), edgecolor="white")
    ax.set_title(title)
    ax.set_xlabel(xlabel)
    ax.set_ylabel("count" + (" (log)" if logy else ""))
    if logy:
        ax.set_yscale("log")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def roc_curve(pos, neg, higher_is_worse=True, n=200):
    """pos=缺陷组分数, neg=正常组分数。返回 [(thr, 漏网率, 误杀率)]。

    判定方向: higher_is_worse → 触发条件 score > thr; 否则 score < thr。
    漏网率 = pos 中未触发比例; 误杀率对 pos=pass 组 = 触发比例。
    """
    import numpy as np

    allv = sorted(set([v for v in pos + neg if v is not None]))
    if not allv:
        return []
    lo, hi = min(allv), max(allv)
    grid = list(np.linspace(lo, hi, n))
    pts = []
    for thr in grid:
        if higher_is_worse:
            miss = sum(1 for v in pos if not (v > thr)) / max(1, len(pos))
            fk = sum(1 for v in neg if v > thr) / max(1, len(neg))
        else:
            miss = sum(1 for v in pos if not (v < thr)) / max(1, len(pos))
            fk = sum(1 for v in neg if v < thr) / max(1, len(neg))
        pts.append((float(thr), miss, fk))
    return pts


def plot_roc(pts, title, path, xlabel="误杀率(正常组触发比例)"):
    import matplotlib

    matplotlib.use("Agg")
    matplotlib.rcParams["font.family"] = ["Noto Serif CJK SC", "DejaVu Sans"]
    matplotlib.rcParams["axes.unicode_minus"] = False
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(5, 4.2))
    xs = [p[2] for p in pts]
    ys = [p[1] for p in pts]
    ax.plot(xs, ys, "-o", ms=2.5)
    ax.set_xlabel(xlabel)
    ax.set_ylabel("漏网率(缺陷组未拦截比例)")
    ax.set_title(title)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def main() -> int:
    data = load()
    recs = data["records"]
    out = {"source": str(RUN_JSON), "per_sub": {}, "combined": {}, "operating_points": {}}
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    fails = [r for r in recs if r["label"] == "fail"]
    struct = [r for r in recs if r["label"] == "pass_structural"]
    cands = [r for r in recs if r["label"] == "pass_candidate"]

    # ---------- G7a / G7d ----------
    a_bbox_f = [r["subs"]["a"]["score"] for r in fails]
    a_bbox_s = [r["subs"]["a"]["score"] for r in struct if not r["subs"]["a"]["skipped"]]
    a_bbox_c = [r["subs"]["a"]["score"] for r in cands if not r["subs"]["a"]["skipped"]]
    a_full = lambda r: (min(r["subs"]["a"]["sims_fullframe"]) if r["subs"]["a"].get("sims_fullframe")
                        else (r["subs"]["d"]["score"] if not r["subs"]["d"]["skipped"] else None))
    a_full_f = [a_full(r) for r in fails]
    a_full_s = [a_full(r) for r in struct if not r["subs"]["a"]["skipped"]]
    a_full_c = [a_full(r) for r in cands if not r["subs"]["a"]["skipped"]]
    d_f = [r["subs"]["d"]["score"] for r in fails if not r["subs"]["d"]["skipped"]]
    d_s = [r["subs"]["d"]["score"] for r in struct if not r["subs"]["d"]["skipped"]]
    d_c = [r["subs"]["d"]["score"] for r in cands if not r["subs"]["d"]["skipped"]]

    hist_plot(series_by_label(recs, lambda r: r["subs"]["a"]["score"] or None),
              "G7a 跨步主体余弦最小值(bbox 口径) 分布", OUT_DIR / "g7_dist_a.png", "min cosine vs t0")
    hist_plot({"fail": d_f, "pass_structural": d_s, "pass_candidate": d_c},
              "G7d 首尾全帧余弦 分布", OUT_DIR / "g7_dist_d.png", "cosine(first, last)")
    roc_a = roc_curve([v for v in a_bbox_f if v is not None],
                      [v for v in a_bbox_s + a_bbox_c if v is not None], higher_is_worse=False)
    roc_d = roc_curve(d_f, d_s + d_c, higher_is_worse=False)
    plot_roc(roc_a, "G7a ROC (阈值越低越严)", OUT_DIR / "g7_roc_a.png")
    plot_roc(roc_d, "G7d ROC", OUT_DIR / "g7_roc_d.png")
    out["per_sub"]["a"] = {"fail": a_bbox_f, "struct": a_bbox_s, "cand": a_bbox_c, "roc": roc_a}
    out["per_sub"]["d"] = {"fail": d_f, "struct": d_s, "cand": d_c, "roc": roc_d}

    # ---------- G7c ----------
    c_static = lambda r: r["subs"]["c"].get("p95_px")
    c_full = lambda r: (max(r["subs"]["c"]["p95_px_full_per_pair"])
                        if r["subs"]["c"].get("p95_px_full_per_pair") else None)
    c_f = [c_static(r) for r in fails if not r["subs"]["c"]["skipped"]]
    c_s = [c_static(r) for r in struct if not r["subs"]["c"]["skipped"]]
    c_c = [c_static(r) for r in cands if not r["subs"]["c"]["skipped"]]
    cf_f = [c_full(r) for r in fails if not r["subs"]["c"]["skipped"]]
    cf_c = [c_full(r) for r in cands if not r["subs"]["c"]["skipped"]]
    hist_plot({"fail": c_f, "pass_structural": c_s, "pass_candidate": c_c},
              "G7c 静态区光流 P95(px, 相邻采样帧对取最大) 分布", OUT_DIR / "g7_dist_c.png",
              "flow p95 px")
    roc_c = roc_curve([v for v in c_f if v is not None],
                      [v for v in (c_s + c_c) if v is not None], higher_is_worse=True)
    plot_roc(roc_c, "G7c ROC (静态区 p95)", OUT_DIR / "g7_roc_c.png")
    out["per_sub"]["c"] = {"fail": c_f, "struct": c_s, "cand": c_c, "roc": roc_c,
                           "fail_full": cf_f, "cand_full": cf_c}

    # ---------- G7b 离线重放(det 阈值扫描) ----------
    b_grid = {}
    for det_thr in (0.25, 0.30, 0.35, 0.40):
        for churn_max_hint in (3,):
            rows = []
            for r in recs:
                b = r["subs"]["b"]
                if b["skipped"] or "dets_raw" not in b:
                    rows.append((r["fixture_id"], r["label"], None, None, None))
                    continue
                st = replay_b(b["dets_raw"], det_thr, n_frames=len(b["dets_raw"]))
                rows.append((r["fixture_id"], r["label"], st["max_abs_delta"],
                             st["variance"], st["churn"]))
            b_grid[det_thr] = rows
    # churn 分布(det_thr=0.30)
    def churn_at(det_thr, lab):
        return [row[4] for row in b_grid[det_thr] if row[1] == lab and row[4] is not None]

    hist_plot({lab: churn_at(0.30, lab) for lab in ("fail", "pass_structural", "pass_candidate")},
              "G7b churn 分布(离线重放 det_thr=0.30)", OUT_DIR / "g7_dist_b_churn.png", "churn events")
    out["per_sub"]["b"] = {"grid_det_thr": {str(k): v for k, v in b_grid.items()}}

    # 摘要
    print("== 分布摘要 (p50 / p90 / min / max) ==")
    import numpy as np

    def summ(vals):
        vals = [v for v in vals if v is not None]
        if not vals:
            return "n/a"
        return (f"p50={np.percentile(vals, 50):.3f} p90={np.percentile(vals, 90):.3f}"
                f" min={min(vals):.3f} max={max(vals):.3f}")

    for name, f, s, c in (("a_bbox", a_bbox_f, a_bbox_s, a_bbox_c),
                          ("a_full", a_full_f, a_full_s, a_full_c),
                          ("d", d_f, d_s, d_c),
                          ("c_static_p95", c_f, c_s, c_c)):
        print(f"{name}: fail[{summ(f)}] struct[{summ(s)}] cand[{summ(c)}]")

    # ---------- 组合工作点扫描(不对称原则: fail 拦截≥90% 约束下最小化误杀) ----------
    # 任一子项触发 → fail。struct 只有 a/d 活跃(b/c 按无主体跳过)。
    b_opts = [
        # (det_thr, delta_tol, var_max, churn_max)
        (0.25, 2, 4, 3), (0.25, 2, 4, 5), (0.25, 3, 4, 5),
        (0.30, 2, 4, 3), (0.30, 2, 4, 5), (0.30, 3, 4, 5), (0.30, 3, 25, 8), (0.30, 4, 100, 12),
        (0.35, 2, 4, 5), (0.35, 3, 25, 8), (0.40, 3, 25, 8), (0.40, 4, 100, 12),
        None,  # b 关闭
    ]
    a_grid = [0.70, 0.75, 0.80, 0.85, 0.88, 0.90, 0.92]
    d_grid = [0.80, 0.84, 0.86, 0.88, 0.90, 0.92]
    c_grid = [1.0, 2.0, 3.0, 4.0, 4.5, 5.0, 6.0, 8.0, 10.0, None]  # None = c 关闭

    fids = [r["fixture_id"] for r in recs]
    lab_of = {r["fixture_id"]: r["label"] for r in recs}

    def trig_vectors(a_mode):
        """每个 fixture 在各阈值栅格上的触发位。a_mode: 'bbox' | 'full'。"""
        a_t, d_t, c_t, b_t = {}, {}, {}, {}
        for r in recs:
            fid = r["fixture_id"]
            a_val = (r["subs"]["a"]["score"] if a_mode == "bbox"
                     else (min(r["subs"]["a"]["sims_fullframe"])
                           if r["subs"]["a"].get("sims_fullframe") else r["subs"]["d"]["score"]))
            a_skip = r["subs"]["a"]["skipped"]
            d_skip = r["subs"]["d"]["skipped"]
            c = r["subs"]["c"]
            a_t[fid] = {thr: (not a_skip and a_val is not None and a_val < thr) for thr in a_grid}
            d_t[fid] = {thr: (not d_skip and r["subs"]["d"]["score"] < thr) for thr in d_grid}
            c_t[fid] = {thr: ((not c["skipped"]) and c.get("p95_px") is not None
                              and c["p95_px"] > thr) for thr in c_grid if thr is not None}
            c_t[fid][None] = False
        return a_t, d_t, c_t, b_t

    results = []
    for a_mode in ("bbox", "full"):
        a_t, d_t, c_t, _ = trig_vectors(a_mode)
        for b_opt in b_opts:
            # b 触发位(每个 fixture)
            b_trig = {}
            if b_opt is None:
                for fid in fids:
                    b_trig[fid] = False
            else:
                det_thr, dtol, vmax, cmax = b_opt
                for r in recs:
                    b = r["subs"]["b"]
                    if b["skipped"] or "dets_raw" not in b:
                        b_trig[r["fixture_id"]] = False
                        continue
                    st = replay_b(b["dets_raw"], det_thr, n_frames=len(b["dets_raw"]))
                    b_trig[r["fixture_id"]] = (st["max_abs_delta"] > dtol or st["variance"] > vmax
                                               or st["churn"] > cmax)
            for a_thr in a_grid:
                for d_thr in d_grid:
                    for c_thr in c_grid:
                        miss = killed_c = killed_s = 0
                        missed_f, killed_cl = [], []
                        for fid in fids:
                            trig = a_t[fid][a_thr] or d_t[fid][d_thr] or c_t[fid][c_thr] or b_trig[fid]
                            lab = lab_of[fid]
                            if lab == "fail":
                                if not trig:
                                    miss += 1
                                    missed_f.append(fid)
                            elif lab == "pass_candidate":
                                if trig:
                                    killed_c += 1
                                    killed_cl.append(fid)
                            else:
                                if trig:
                                    killed_s += 1
                        results.append({
                            "a_mode": a_mode, "a_thr": a_thr, "d_thr": d_thr, "c_thr": c_thr,
                            "b_opt": b_opt, "fail_missed": miss, "missed_fids": missed_f,
                            "cand_killed": killed_c, "killed_cand_fids": killed_cl,
                            "struct_killed": killed_s,
                        })
    # 排序: struct_killed 升序 → fail_missed 升序 → cand_killed 升序
    results.sort(key=lambda x: (x["struct_killed"], x["fail_missed"], x["cand_killed"]))
    out["combo"] = results
    print("\n== 组合工作点 TOP20 (排序键: struct 误杀 → fail 漏网 → cand 误杀) ==")
    for x in results[:20]:
        print(f"a({x['a_mode']}<{x['a_thr']}) d<{x['d_thr']} c>{x['c_thr']} b={x['b_opt']}"
              f" | miss={x['fail_missed']}{x['missed_fids'] or ''}"
              f" cand_kill={x['cand_killed']}{x['killed_cand_fids'] if x['cand_killed'] <= 6 else ''}"
              f" struct_kill={x['struct_killed']}")

    OUT_JSON.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"OK -> {OUT_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

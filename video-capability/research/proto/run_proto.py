#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_proto.py — P1 原型驱动：纯代码帧差时间线在金标定格夹具上的确定性检出。

假设（全部来自 manifest/judge 报告，非本文件发明）：
  * golden_017 / golden_028 = A 类注入缺陷 frame_freeze，注入区间 1.531s -> 3.531s（2.0s）；
  * golden_001 / golden_006 = C 类干净对照（score_temporal_rerun.py 的 C_CLIPS 名单），
    已知 J1(glm8) 对 golden_017 漏检且给出错误算术依据（"无近似零差对，排除定格"）。

验收口径（本脚本退出码）：
  exit 0 当且仅当 两条 freeze 夹具均检出内嵌定格（检出区间与注入区间端点误差 <= TOL）
              且 两条干净对照均不检出内嵌定格。
其余情况 exit 1（如实失败，不做假绿）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import sheetframe as sf

BASE = Path("/opt/gpumachine/projects/video-capability/overnight/数据")
GOLDEN = BASE / "golden" / "clips"
OUT = Path(__file__).resolve().parent / "out"
TOL = 0.35          # 检出区间端点 vs 注入区间端点的容差（秒）
MIN_FREEZE_S = 1.0  # 定格最短时长（注入为 2.0s，取一半防边界采样偏移）

FREEZE_CLIPS = ["golden_017", "golden_028"]
CONTROL_CLIPS = ["golden_001", "golden_006"]


def injected_spans() -> dict:
    m = json.loads((BASE / "golden" / "manifest.json").read_text(encoding="utf-8"))
    out = {}
    for it in m["items"]:
        if it.get("defect_type") == "frame_freeze":
            ip = it.get("inject_pos", {})
            out[it["clip_id"]] = {"start_s": ip.get("start_s"), "end_s": ip.get("end_s"),
                                  "duration_s": ip.get("duration_s"), "mode": ip.get("mode")}
    return out


def span_match(det: dict, inj: dict, tol: float = TOL) -> bool:
    return (abs(det["start_s"] - inj["start_s"]) <= tol
            and abs(det["end_s"] - inj["end_s"]) <= tol)


def main() -> int:
    inj = injected_spans()
    rows, ok_all = [], True
    for cid in FREEZE_CLIPS + CONTROL_CLIPS:
        clip = GOLDEN / f"{cid}.mp4"
        expect = "freeze" if cid in FREEZE_CLIPS else "clean"
        meta = sf.analyze_video(clip, OUT / cid, min_freeze_s=MIN_FREEZE_S)
        spans = meta["freeze"]["spans"]
        if expect == "freeze":
            hit = any(span_match(s, inj[cid]) for s in spans)
        else:
            hit = len(spans) == 0
        ok_all &= hit
        rows.append({
            "clip_id": cid, "expect": expect,
            "keyframe_count": meta["keyframe_count"],
            "threshold": meta["threshold"], "score_stats": meta["score_stats"],
            "detected_spans": spans, "injected": inj.get(cid),
            "eps": meta["freeze"]["eps"],
            "outside_motion": meta["freeze"]["outside_motion"],
            "sheets": [{"path": s["path"], "width": s["width"], "height": s["height"],
                        "cells": s["cells"]} for s in meta["overviews"]],
            "verdict": "PASS" if hit else "FAIL",
        })

    result = {"tolerance_s": TOL, "min_freeze_s": MIN_FREEZE_S,
              "all_pass": ok_all, "clips": rows}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "proto_results.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"{'clip':<12}{'expect':<8}{'kf':>4}{'thr':>9}{'verdict':>9}  detected vs injected")
    for r in rows:
        det = r["detected_spans"][0] if r["detected_spans"] else None
        det_s = f"{det['start_s']:.3f}-{det['end_s']:.3f}s" if det else "-"
        injs = (f"{r['injected']['start_s']:.3f}-{r['injected']['end_s']:.3f}s"
                if r["injected"] else "-")
        print(f"{r['clip_id']:<12}{r['expect']:<8}{r['keyframe_count']:>4}"
              f"{r['threshold']:>9.4f}{r['verdict']:>9}  {det_s} vs {injs}")
        for sh in r["sheets"]:
            print(f"    sheet: {Path(sh['path']).name} {sh['width']}x{sh['height']} {sh['cells']} cells")
    print("P1_ALL_PASS" if ok_all else "P1_FAILED")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())

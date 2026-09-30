#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
j6_to_protocol.py — J6 专用检测器 → 盲测协议 JSON 转换器（边界测试方案.md §2.3）

输入: /data/night/results/j6/<clip_id>.qc.json   (qc_detectors.py 的输出)
输出: /data/night/results/j6/protocol/<clip_id>.json
      {"clip_id", "defect_detected", "defect_types", "confidence", "spans"}
汇总: /data/night/results/j6/_j6_summary.json  (阈值+全候选证据, 供评测与追溯)

规则（任务书指定，写死）:
  帧间 ArcFace 余弦突降   → identity_drift / face_blur 候选
  帧差/CLIP 相似度突变    → frame_freeze / flicker / temporal_swap 候选
  OCR 置信度骤降或乱码    → garble_text
  色偏统计               → color_shift
  confidence 用对应指标归一化。

盲测性声明: 全部阈值在批跑产出未逐条查看前一次写定（2026-09-29，先于本批任何
逐 clip 结果的人工检视），只依赖指标语义与冒烟片（合成时钟片）量级，不针对任何
金标标签调参。转换器不读取 manifest 的标签字段。
"""
import json
import math
import sys
from pathlib import Path

# ------------------------------------------------------------------ 固定阈值
THR = {
    "face_drift_cos": 0.30,    # ArcFace 余弦 < 0.30 → identity_drift（跨人水平）
    "face_blur_cos": 0.50,     # [0.30, 0.50) → face_blur（同人但退化/可疑）
    "freeze_diff": 1.2,        # 帧差(均值绝对差,0-255) < 1.2 且 < median*ratio → frame_freeze
    "freeze_ratio": 0.35,
    "spike_k": 3.0,            # 帧差尖峰: > mean + 3σ（与管线一致）
    "swap_sim": 0.75,          # 单尖峰对 + CLIP 相似度 < 0.75 → temporal_swap
    "flicker_cap": 0.85,       # 单尖峰但 CLIP 相似度尚高 → flicker（上限 0.85）
    "luma_alt": 10.0,          # 亮度(0-255)相邻差 ≥10 且符号交替 → flicker 支持
    "garble_drop": 0.25,       # OCR 逐帧均分最大跌落 ≥ 0.25 且低点 < 0.78 → garble_text
    "garble_low": 0.78,
    "garble_ratio": 0.45,      # 乱码字符占比 ≥ 0.45（≥4 字符）→ garble_text
    "garble_unif": 0.70,       # 所有含字帧均分 < 0.70 → garble_text（整体乱码）
    "hue_shift": 30.0,         # 相邻帧圆形色相差 ≥ 30° → color_shift
    "sat_jump": 0.30,          # |Δ饱和度| ≥ 0.30 且非符号交替 → color_shift
    "emit_conf": 0.45,         # 候选置信度 ≥ 0.45 才进入 defect_types
}
ALLOWED_TYPES = ["frame_freeze", "flicker", "color_shift", "face_blur", "garble_text",
                 "temporal_swap", "pixelate", "ghosting", "identity_drift", "other"]
COMMON_PUNCT = set("，。！？、：；·「」『』（）《》〈〉…—～“”‘’!,.?:;\"'()[]{}<>+-*/=%&|~^$#@_ ")


def clip01(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def circ_hue_dist(a, b):
    if a is None or b is None:
        return None
    d = abs(a - b) % 360.0
    return min(d, 360.0 - d)


def frame_ts(i, n, dur):
    """第 i 帧（0 基）近似时间戳：均匀抽帧中点。dur 缺失时按 8s 假设。"""
    return round(dur * (i + 0.5) / n, 3)


# ------------------------------------------------------------------ 各规则
def rule_face(qc, cand):
    cos = qc.get("face_consistency") or []
    valid = [c for c in cos if c is not None]
    if len(cos) == 0 or not valid:
        return "insufficient_face_signal"
    worst_drift = worst_blur = None
    for i, c in enumerate(cos):
        if c is None:
            continue
        if c < THR["face_drift_cos"]:
            conf = clip01((THR["face_drift_cos"] - c) / THR["face_drift_cos"])
            if worst_drift is None or conf > worst_drift["conf"]:
                worst_drift = {"conf": conf, "pair": i, "cos": round(c, 4)}
        elif c < THR["face_blur_cos"]:
            conf = clip01((THR["face_blur_cos"] - c) / (THR["face_blur_cos"] - THR["face_drift_cos"]))
            if worst_blur is None or conf > worst_blur["conf"]:
                worst_blur = {"conf": conf, "pair": i, "cos": round(c, 4)}
    if worst_drift:
        cand["identity_drift"] = worst_drift
    if worst_blur:
        cand["face_blur"] = worst_blur
    return "ok"


def rule_frame_series(qc, cand, n, dur):
    scores = (qc.get("meta") or {}).get("frame_diff_scores") or []
    sims = qc.get("clip_sim") or []
    if len(scores) < 2:
        return "insufficient_frame_series"
    arr = scores
    mu = sum(arr) / len(arr)
    sd = math.sqrt(sum((s - mu) ** 2 for s in arr) / len(arr))
    thr = mu + THR["spike_k"] * sd
    med = sorted(arr)[len(arr) // 2] if len(arr) % 2 else \
        (sorted(arr)[len(arr) // 2 - 1] + sorted(arr)[len(arr) // 2]) / 2.0
    flagged = [i for i, s in enumerate(arr) if s > thr]

    # --- frame_freeze: 内部近零对（排除含首帧的对）
    for i, s in enumerate(arr):
        if i == 0:
            continue
        if s < THR["freeze_diff"] and (med <= 0 or s < THR["freeze_ratio"] * med):
            conf = clip01((THR["freeze_diff"] - s) / THR["freeze_diff"])
            if conf >= cand.get("frame_freeze", {}).get("conf", -1):
                cand["frame_freeze"] = {"conf": conf, "pair": i,
                                        "score": round(s, 3), "median": round(med, 3)}

    # --- 尖峰分组: 连簇→flicker；孤立峰→按 CLIP 相似度分流 temporal_swap / flicker
    runs = []
    for i in flagged:
        if runs and runs[-1][-1] == i - 1:
            runs[-1].append(i)
        else:
            runs.append([i])
    for run in runs:
        excess = max(arr[i] - thr for i in run)
        if len(run) >= 2:
            conf = clip01(0.40 + (len(run) - 1) * 0.15 + excess / 40.0)
            if conf > cand.get("flicker", {}).get("conf", -1):
                cand["flicker"] = {"conf": conf, "pairs": run,
                                   "excess": round(excess, 2), "kind": "spike_cluster"}
        else:
            i = run[0]
            sim = sims[i] if i < len(sims) else None
            if sim is not None and sim < THR["swap_sim"]:
                conf = max(0.40, clip01((THR["swap_sim"] - sim) / (THR["swap_sim"] - 0.30)))
                if conf > cand.get("temporal_swap", {}).get("conf", -1):
                    cand["temporal_swap"] = {"conf": conf, "pair": i,
                                             "clip_sim": round(sim, 4), "kind": "spike+sim_drop"}
            else:
                conf = clip01(0.35 + excess / 40.0, hi=THR["flicker_cap"])
                if conf > cand.get("flicker", {}).get("conf", -1):
                    cand["flicker"] = {"conf": conf, "pairs": [i],
                                       "excess": round(excess, 2), "kind": "single_spike_high_sim"}

    # --- 场景切割 → temporal_swap
    dur_v = dur if dur > 0 else 8.0
    for t in (qc.get("scene_cuts") or []):
        if 0.25 * dur_v < t < 0.90 * dur_v:
            if 0.75 > cand.get("temporal_swap", {}).get("conf", -1):
                cand["temporal_swap"] = {"conf": 0.75, "cut_s": t, "kind": "scene_cut_mid"}
    return "ok"


def rule_garble(qc, cand, n, dur):
    per = (qc.get("meta") or {}).get("ocr_per_frame") or []
    ms = []   # (frame_idx, mean_score, n_chars)
    for j, e in enumerate(per):
        texts = e.get("texts") or []
        scores = e.get("scores") or []
        total = sum(len(t) for t in texts)
        if total == 0:
            continue
        m = (sum(scores) / len(scores)) if scores else None
        ms.append((j, m, total, "".join(texts)))
    if not ms:
        return "no_text"
    # 1) 置信度骤降
    vals = [(j, m, t) for j, m, t, _ in ms if m is not None]
    if len(vals) >= 2:
        hi = max(vals, key=lambda x: x[1])
        lo = min(vals, key=lambda x: x[1])
        drop = hi[1] - lo[1]
        if drop >= THR["garble_drop"] and lo[1] < THR["garble_low"]:
            conf = max(0.40, clip01(drop / 0.50))
            cand["garble_text"] = {"conf": conf, "kind": "conf_drop",
                                   "drop": round(drop, 3),
                                   "frames": [lo[0], hi[0]],
                                   "mean_scores": [round(lo[1], 3), round(hi[1], 3)]}
    # 2) 乱码字符占比
    for j, m, total, joined in ms:
        nonspace = [c for c in joined if not c.isspace()]
        if len(nonspace) < 4:
            continue
        good = sum(1 for c in nonspace if ("\u4e00" <= c <= "\u9fff") or c.isascii() and (c.isalnum() or c in COMMON_PUNCT) or c in COMMON_PUNCT)
        ratio = 1.0 - good / len(nonspace)
        if ratio >= THR["garble_ratio"]:
            conf = max(0.50, clip01(ratio))
            if conf > cand.get("garble_text", {}).get("conf", -1):
                cand["garble_text"] = {"conf": conf, "kind": "garble_ratio",
                                       "ratio": round(ratio, 3), "frame": j,
                                       "sample": joined[:40]}
    # 3) 整体低置信（全程乱码）
    if "garble_text" not in cand:
        allm = [m for _, m, _, _ in ms if m is not None]
        if allm and max(allm) < THR["garble_unif"]:
            conf = max(0.40, clip01(0.40 + (THR["garble_unif"] - max(allm)) * 1.5, hi=0.85))
            cand["garble_text"] = {"conf": conf, "kind": "uniform_low_conf",
                                   "max_mean": round(max(allm), 3)}
    return "ok"


def rule_color(qc, cand, n, dur):
    stats = qc.get("color_stats") or []
    if len(stats) < 2:
        return "insufficient_color_stats"
    luma = [s["mean_luma_0_255"] for s in stats]
    sat = [s["mean_sat_0_1"] for s in stats]
    hue = [s["hue_circ_mean_deg"] for s in stats]
    hw = [s["hue_weight"] for s in stats]
    dsat = [sat[j + 1] - sat[j] for j in range(len(sat) - 1)]

    # 色相差
    for j in range(len(stats) - 1):
        if min(hw[j], hw[j + 1]) < 0.05:
            continue
        dh = circ_hue_dist(hue[j], hue[j + 1])
        if dh is not None and dh >= THR["hue_shift"]:
            conf = max(0.40, clip01((dh - THR["hue_shift"]) / 60.0))
            if conf > cand.get("color_shift", {}).get("conf", -1):
                cand["color_shift"] = {"conf": conf, "kind": "hue_shift", "pair": j,
                                       "hue_delta_deg": round(dh, 1)}
    # 饱和度跳变（排除符号交替——那是 flicker 的曝光/饱和交替）
    for j, d in enumerate(dsat):
        if abs(d) < THR["sat_jump"]:
            continue
        alt = any(k != j and dsat[k] * d < 0 and abs(dsat[k]) >= 0.25
                  for k in (j - 1, j + 1) if 0 <= k < len(dsat))
        if alt:
            conf_f = max(0.45, clip01(0.45 + (min(abs(d), 0.5) - THR["sat_jump"]) / 0.4))
            if conf_f > cand.get("flicker", {}).get("conf", -1):
                cand["flicker"] = {"conf": conf_f, "pairs": [j], "kind": "sat_alternation",
                                   "dsat": round(d, 3)}
        else:
            conf = max(0.40, clip01((abs(d) - THR["sat_jump"]) / 0.40 + 0.40, hi=0.90))
            if conf > cand.get("color_shift", {}).get("conf", -1):
                cand["color_shift"] = {"conf": conf, "kind": "sat_jump", "pair": j,
                                       "dsat": round(d, 3)}
    return "ok"


# ------------------------------------------------------------------ 主流程
def convert(qc_path: Path, out_dir: Path):
    qc = json.loads(qc_path.read_text(encoding="utf-8"))
    clip_id = qc_path.stem.replace(".qc", "")
    meta = qc.get("clip_meta") or {}
    dur = float(meta.get("duration_sec") or 0)
    n = len(qc.get("frames") or [])
    if n == 0:
        n = len(qc.get("color_stats") or []) or 8

    cand = {}   # type → evidence(含 conf)
    status = {
        "face": rule_face(qc, cand),
        "frame": rule_frame_series(qc, cand, n, dur),
        "garble": rule_garble(qc, cand, n, dur),
        "color": rule_color(qc, cand, n, dur),
    }

    for t, ev in cand.items():
        assert t in ALLOWED_TYPES, t

    emitted = sorted(((t, ev) for t, ev in cand.items() if ev["conf"] >= THR["emit_conf"]),
                     key=lambda x: -x[1]["conf"])
    detected = bool(emitted)
    max_signal = max((ev["conf"] for ev in cand.values()), default=0.0)
    confidence = round(max(emitted, key=lambda x: x[1]["conf"])[1]["conf"], 3) if detected \
        else round(1.0 - max_signal, 3)

    spans = []
    for t, ev in emitted:
        if "pair" in ev:
            i = ev["pair"]
            s, e = frame_ts(i, n, dur), frame_ts(i + 1, n, dur)
        elif "pairs" in ev:
            idx = ev["pairs"]
            s, e = frame_ts(min(idx), n, dur), frame_ts(max(idx) + 1, n, dur)
        elif "frames" in ev:
            idx = ev["frames"]
            s, e = frame_ts(min(idx), n, dur), frame_ts(max(idx), n, dur)
        elif "cut_s" in ev:
            s, e = max(0.0, ev["cut_s"] - 0.5), ev["cut_s"] + 0.5
        elif "frame" in ev:
            s, e = frame_ts(ev["frame"], n, dur), frame_ts(ev["frame"] + 1, n, dur)
        else:
            s, e = 0.0, round(dur, 3)
        spans.append({"type": t, "start_s": round(s, 3), "end_s": round(e, 3),
                      "evidence": {k: v for k, v in ev.items() if k not in ("conf",)}})

    proto = {
        "clip_id": clip_id,
        "defect_detected": detected,
        "defect_types": [t for t, _ in emitted],
        "confidence": confidence,
        "spans": spans,
    }
    out_path = out_dir / f"{clip_id}.json"
    out_path.write_text(json.dumps(proto, ensure_ascii=False, indent=2), encoding="utf-8")
    return proto, cand, status, qc


def main():
    src_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/data/night/results/j6")
    out_dir = src_dir / "protocol"
    out_dir.mkdir(parents=True, exist_ok=True)
    qcs = sorted(src_dir.glob("golden_*.qc.json"))
    summary = {"judge": "J6 专用检测器管线",
               "generated_by": "j6_to_protocol.py",
               "thresholds": THR,
               "confidence_semantics": (
                   "defect_detected=true 时 confidence=最强候选的归一化置信度; "
                   "false 时 confidence=1-最强候选信号(干净侧置信度)"),
               "emit_rule": f"候选置信度 ≥ {THR['emit_conf']} 才进入 defect_types",
               "allowed_types": ALLOWED_TYPES,
               "blind_note": "阈值先验一次写定，转换器不读金标标签; 时间戳=均匀抽帧中点近似",
               "per_clip": {}}
    n_ok = 0
    for p in qcs:
        try:
            proto, cand, status, qc = convert(p, out_dir)
            summary["per_clip"][proto["clip_id"]] = {
                "defect_detected": proto["defect_detected"],
                "defect_types": proto["defect_types"],
                "confidence": proto["confidence"],
                "all_candidates": cand,
                "rule_status": status,
                "detector_errors": qc.get("errors") or {},
                "n_frames": len(qc.get("frames") or []),
            }
            n_ok += 1
        except Exception as e:  # noqa: BLE001
            summary["per_clip"][p.stem.replace(".qc", "")] = {"ERROR": f"{type(e).__name__}: {e}"}
    (src_dir / "_j6_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"converted {n_ok}/{len(qcs)} → {out_dir}")
    ndet = sum(1 for v in summary["per_clip"].values() if v.get("defect_detected"))
    print(f"defect_detected: {ndet}/{len(summary['per_clip'])}")


if __name__ == "__main__":
    main()

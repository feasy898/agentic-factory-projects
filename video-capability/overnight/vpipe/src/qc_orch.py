#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
qc_orch.py — vpipe 质检编排器：专用检测器规则引擎 + 多 judge 合议（vpipe SPEC.md 模块 3）

职责（边界测试方案.md §3 交付物3 / judge基准报告.md §11 定稿建议）:
  1. 检测器规则引擎：消费 qc_detectors.py 的检测 JSON（OCR/帧差/CLIP/ArcFace/色偏统计，
     产线脚本见 overnight/qc-scripts/j6/qc_detectors.py），按 thresholds.yaml 的
     judges.J6_detectors.rule_params 跑规则 → J6 候选（本文件 rule_* 系列移植自今晚已验证的
     overnight/qc-scripts/j6/j6_to_protocol.py，阈值改从 YAML 读，禁止写死）。
  2. judge 合议：按 thresholds.yaml 的 ensemble 段（当前推荐 E10 = J1∨J3@0.70）合成 clip 级
     verdict，并产出 contracts/qc_report.schema.json 合规的报告。
  3. 资产登记：输入判官文件与输出报告写入 contracts/asset_manifest.schema.json 合规的 manifest。

两种运行模式:
  A) 回放模式（验收用，不跑任何模型）:
     python src/qc_orch.py --from-tonight \
        --judges-root ../数据/judges --golden ../eval/golden_manifest.json \
        --thresholds ../eval/thresholds.yaml --out-dir out/qc_reports \
        [--manifest out/asset_manifest.json]
     输入=今晚已落盘的判官产物：J1=glm8/*.json（六字段协议）、J3=omnijev/run_metadata.json
     （逐 clip 9 通道概率）、J5=videochat3/*.json、J6=detectors/_j6_summary.json
     （全候选置信度）；J2/J4 不进 E10（J2 备用、J4 已判弃用），但仍嵌报告可追溯。
  B) 在线模式（生产形态）:
     python src/qc_orch.py --online --clip-id X --detector-json X.qc.json \
        --judge-file J1=path1 --judge-file J5=path2 [--judge-probs J3=run_metadata.json] ...

契约: 模块只通过 contracts/*.schema.json 的 JSON 与其他模块通信；不 import 任何 vpipe 兄弟模块。
阈值: 一切判定阈值来自 --thresholds 指定的 YAML；本文件不出现第二套数值。
降级: 判官文件缺失/解析失败 → errors 登记 + 该判官弃权，合议用剩余通道继续（方案 §4）。
"""
import argparse
import datetime
import hashlib
import json
import math
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import yaml

TYPES8 = ["frame_freeze", "flicker", "color_shift", "face_blur",
          "garble_text", "temporal_swap", "pixelate", "ghosting"]
TYPE_ALIAS = {"text_error": "garble_text"}   # judge基准报告 §1.2 观测别名
COMMON_PUNCT = set("，。！？、：；·「」『』（）《》〈〉…—～“”‘’!,.?:;\"'()[]{}<>+-*/=%&|~^$#@_ ")


def now_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")


def log(msg):
    print(f"[qc_orch {datetime.datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def sha256_file(path, buf=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(buf)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def norm_type(t):
    t = str(t).strip().lower()
    return TYPE_ALIAS.get(t, t)


def clip01(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


# =====================================================================
# 1) J3 概率判官（L1 主判）
# =====================================================================
def j3_flag(probs, thr):
    """thresholds.judges.J3_omnijev.rule 的确定性实现：任一 8 类 P>thr 或 overall>thr。
    严格大于（与 judge基准报告 §7 扫描口径一致）。"""
    if not probs:
        return False, []
    hit = [t for t in TYPES8 if probs.get(t) is not None and probs[t] > thr]
    if probs.get("overall") is not None and probs["overall"] > thr:
        return True, (hit or ["overall"])
    return bool(hit), hit


# =====================================================================
# 2) J6 规则引擎（移植 j6_to_protocol.py；阈值全部由 thresholds.yaml 注入）
# =====================================================================
def circ_hue_dist(a, b):
    if a is None or b is None:
        return None
    d = abs(a - b) % 360.0
    return min(d, 360.0 - d)


def frame_ts(i, n, dur):
    return round(dur * (i + 0.5) / n, 3) if n else 0.0


def rule_face(qc, cand, T):
    cos = qc.get("face_consistency") or []
    valid = [c for c in cos if c is not None]
    if len(cos) == 0 or not valid:
        return "insufficient_face_signal"
    worst = {"identity_drift": None, "face_blur": None}
    for i, c in enumerate(cos):
        if c is None:
            continue
        if c < T["face_drift_cos"]:
            conf = clip01((T["face_drift_cos"] - c) / T["face_drift_cos"])
            if worst["identity_drift"] is None or conf > worst["identity_drift"]["conf"]:
                worst["identity_drift"] = {"conf": conf, "pair": i, "cos": round(c, 4)}
        elif c < T["face_blur_cos"]:
            conf = clip01((T["face_blur_cos"] - c) / (T["face_blur_cos"] - T["face_drift_cos"]))
            if worst["face_blur"] is None or conf > worst["face_blur"]["conf"]:
                worst["face_blur"] = {"conf": conf, "pair": i, "cos": round(c, 4)}
    for k, v in worst.items():
        if v:
            cand[k] = v
    return "ok"


def rule_frame_series(qc, cand, T, n, dur):
    scores = (qc.get("meta") or {}).get("frame_diff_scores") or []
    sims = qc.get("clip_sim") or []
    if len(scores) < 2:
        return "insufficient_frame_series"
    mu = sum(scores) / len(scores)
    sd = math.sqrt(sum((s - mu) ** 2 for s in scores) / len(scores))
    thr = mu + T["spike_k"] * sd
    srt = sorted(scores)
    med = srt[len(srt) // 2] if len(srt) % 2 else (srt[len(srt) // 2 - 1] + srt[len(srt) // 2]) / 2.0
    flagged = [i for i, s in enumerate(scores) if s > thr]

    for i, s in enumerate(scores):                       # frame_freeze（内部近零对）
        if i == 0:
            continue
        if s < T["freeze_diff"] and (med <= 0 or s < T["freeze_ratio"] * med):
            conf = clip01((T["freeze_diff"] - s) / T["freeze_diff"])
            if conf >= cand.get("frame_freeze", {}).get("conf", -1):
                cand["frame_freeze"] = {"conf": conf, "pair": i,
                                        "score": round(s, 3), "median": round(med, 3)}

    runs = []                                            # 尖峰分组
    for i in flagged:
        if runs and runs[-1][-1] == i - 1:
            runs[-1].append(i)
        else:
            runs.append([i])
    for run in runs:
        excess = max(scores[i] - thr for i in run)
        if len(run) >= 2:
            conf = clip01(0.40 + (len(run) - 1) * 0.15 + excess / 40.0)
            if conf > cand.get("flicker", {}).get("conf", -1):
                cand["flicker"] = {"conf": conf, "pairs": run,
                                   "excess": round(excess, 2), "kind": "spike_cluster"}
        else:
            i = run[0]
            sim = sims[i] if i < len(sims) else None
            if sim is not None and sim < T["swap_sim"]:
                conf = max(0.40, clip01((T["swap_sim"] - sim) / (T["swap_sim"] - 0.30)))
                if conf > cand.get("temporal_swap", {}).get("conf", -1):
                    cand["temporal_swap"] = {"conf": conf, "pair": i,
                                             "clip_sim": round(sim, 4), "kind": "spike+sim_drop"}
            else:
                conf = clip01(0.35 + excess / 40.0, hi=T["flicker_cap"])
                if conf > cand.get("flicker", {}).get("conf", -1):
                    cand["flicker"] = {"conf": conf, "pairs": [i],
                                       "excess": round(excess, 2), "kind": "single_spike_high_sim"}

    dur_v = dur if dur > 0 else 8.0                      # 场景切割 → temporal_swap
    for t in (qc.get("scene_cuts") or []):
        if 0.25 * dur_v < t < 0.90 * dur_v:
            if 0.75 > cand.get("temporal_swap", {}).get("conf", -1):
                cand["temporal_swap"] = {"conf": 0.75, "cut_s": t, "kind": "scene_cut_mid"}
    return "ok"


def rule_garble(qc, cand, T):
    per = (qc.get("meta") or {}).get("ocr_per_frame") or []
    ms = []
    for j, e in enumerate(per):
        texts = e.get("texts") or []
        scores = e.get("scores") or []
        if sum(len(t) for t in texts) == 0:
            continue
        m = (sum(scores) / len(scores)) if scores else None
        ms.append((j, m, "".join(texts)))
    if not ms:
        return "no_text"
    vals = [(j, m) for j, m, _ in ms if m is not None]
    if len(vals) >= 2:                                   # 1) 置信度骤降
        hi = max(vals, key=lambda x: x[1])
        lo = min(vals, key=lambda x: x[1])
        drop = hi[1] - lo[1]
        if drop >= T["garble_drop"] and lo[1] < T["garble_low"]:
            conf = max(0.40, clip01(drop / 0.50))
            cand["garble_text"] = {"conf": conf, "kind": "conf_drop", "drop": round(drop, 3),
                                   "frames": [lo[0], hi[0]],
                                   "mean_scores": [round(lo[1], 3), round(hi[1], 3)]}
    for j, m, joined in ms:                              # 2) 乱码字符占比
        nonspace = [c for c in joined if not c.isspace()]
        if len(nonspace) < 4:
            continue
        good = sum(1 for c in nonspace
                   if ("\u4e00" <= c <= "\u9fff") or c in COMMON_PUNCT
                   or (c.isascii() and c.isalnum()))
        ratio = 1.0 - good / len(nonspace)
        if ratio >= T["garble_ratio"]:
            conf = max(0.50, clip01(ratio))
            if conf > cand.get("garble_text", {}).get("conf", -1):
                cand["garble_text"] = {"conf": conf, "kind": "garble_ratio",
                                       "ratio": round(ratio, 3), "frame": j, "sample": joined[:40]}
    if "garble_text" not in cand:                        # 3) 整体低置信
        allm = [m for _, m, _ in ms if m is not None]
        if allm and max(allm) < T["garble_unif"]:
            conf = max(0.40, clip01(0.40 + (T["garble_unif"] - max(allm)) * 1.5, hi=0.85))
            cand["garble_text"] = {"conf": conf, "kind": "uniform_low_conf",
                                   "max_mean": round(max(allm), 3)}
    return "ok"


def rule_color(qc, cand, T):
    stats = qc.get("color_stats") or []
    if len(stats) < 2:
        return "insufficient_color_stats"
    sat = [s["mean_sat_0_1"] for s in stats]
    hue = [s["hue_circ_mean_deg"] for s in stats]
    hw = [s["hue_weight"] for s in stats]
    dsat = [sat[j + 1] - sat[j] for j in range(len(sat) - 1)]
    for j in range(len(stats) - 1):                      # 色相差
        if min(hw[j], hw[j + 1]) < 0.05:
            continue
        dh = circ_hue_dist(hue[j], hue[j + 1])
        if dh is not None and dh >= T["hue_shift_deg"]:
            conf = max(0.40, clip01((dh - T["hue_shift_deg"]) / 60.0))
            if conf > cand.get("color_shift", {}).get("conf", -1):
                cand["color_shift"] = {"conf": conf, "kind": "hue_shift", "pair": j,
                                       "hue_delta_deg": round(dh, 1)}
    for j, d in enumerate(dsat):                         # 饱和度跳变
        if abs(d) < T["sat_jump"]:
            continue
        alt = any(k != j and dsat[k] * d < 0 and abs(dsat[k]) >= 0.25
                  for k in (j - 1, j + 1) if 0 <= k < len(dsat))
        if alt:
            conf_f = max(0.45, clip01(0.45 + (min(abs(d), 0.5) - T["sat_jump"]) / 0.4))
            if conf_f > cand.get("flicker", {}).get("conf", -1):
                cand["flicker"] = {"conf": conf_f, "pairs": [j], "kind": "sat_alternation",
                                   "dsat": round(d, 3)}
        else:
            conf = max(0.40, clip01((abs(d) - T["sat_jump"]) / 0.40 + 0.40, hi=0.90))
            if conf > cand.get("color_shift", {}).get("conf", -1):
                cand["color_shift"] = {"conf": conf, "kind": "sat_jump", "pair": j,
                                       "dsat": round(d, 3)}
    return "ok"


def run_j6_rules(detector_json, T, n_frames, dur_s):
    """对单 clip 的检测 JSON 跑全部规则。返回 (cand{type:ev}, rule_status{})。"""
    cand, status = {}, {}
    status["face"] = rule_face(detector_json, cand, T)
    status["frame"] = rule_frame_series(detector_json, cand, T, n_frames, dur_s)
    status["garble"] = rule_garble(detector_json, cand, T)
    status["color"] = rule_color(detector_json, cand, T)
    return cand, status


def j6_span_from_ev(ev, n, dur):
    """由候选证据推时间区间（移植 j6_to_protocol.convert 的 span 逻辑）。"""
    if "pair" in ev:
        s, e = frame_ts(ev["pair"], n, dur), frame_ts(ev["pair"] + 1, n, dur)
    elif "pairs" in ev:
        s, e = frame_ts(min(ev["pairs"]), n, dur), frame_ts(max(ev["pairs"]) + 1, n, dur)
    elif "frames" in ev:
        s, e = frame_ts(min(ev["frames"]), n, dur), frame_ts(max(ev["frames"]), n, dur)
    elif "cut_s" in ev:
        s, e = max(0.0, ev["cut_s"] - 0.5), ev["cut_s"] + 0.5
    elif "frame" in ev:
        s, e = frame_ts(ev["frame"], n, dur), frame_ts(ev["frame"] + 1, n, dur)
    elif "span" in ev and isinstance(ev["span"], (list, tuple)) and len(ev["span"]) == 2:
        # qc_detectors_v2.py 的候选自带秒级区间（v2 增量分支，向后兼容）
        s, e = float(ev["span"][0]), float(ev["span"][1])
    else:
        s, e = 0.0, round(dur, 3)
    return {"start_s": round(s, 3), "end_s": round(e, 3)}


# =====================================================================
# 3) 合议 → QCReport（contracts/qc_report.schema.json）
# =====================================================================
def norm_spans_field(raw):
    """盲测协议 spans（字符串或对象数组）→ 契约的规范对象数组。"""
    out = []
    if isinstance(raw, str):
        out.append({"type": "note", "evidence": {"text": raw}})
    elif isinstance(raw, list):
        for sp in raw:
            if isinstance(sp, dict):
                out.append({"type": str(sp.get("type", "note")),
                            "start_s": sp.get("start_s"),
                            "end_s": sp.get("end_s"),
                            "evidence": {k: v for k, v in sp.items()
                                         if k not in ("type", "start_s", "end_s")} or {}})
            elif isinstance(sp, str):
                out.append({"type": "note", "evidence": {"text": sp}})
    return out


def synthesize_qc_report(clip_id, mode, judges_raw, j6_cand, j6_emit, probs,
                         thr_cfg, ens_id, thresholds_sha, inputs, errors):
    """由各通道信号合成一份契约合规的 QCReport。纯函数（除读 YAML 外无副作用）。"""
    j3_thr = float(thr_cfg["judges"]["J3_omnijev"]["thr"])
    auto_rej = float(thr_cfg["judges"]["J3_omnijev"]["auto_reject_p"])
    reasons, defects_map = [], {}

    # --- E10 合议：detected = J1 ∨ J3@thr ---
    j1 = judges_raw.get("J1")
    j3_det = False
    j3_hit_types = []
    j3_max_p = 0.0
    if probs:
        j3_det, j3_hit_types = j3_flag(probs, j3_thr)
        vals = [probs.get(t) for t in TYPES8 if probs.get(t) is not None] + \
               ([probs["overall"]] if probs.get("overall") is not None else [])
        j3_max_p = max(vals) if vals else 0.0
    j1_det = bool(j1 and j1.get("defect_detected"))
    detected = bool(j1_det or j3_det)

    # --- decision（thresholds.judges.J3_omnijev: ≥auto_rej 自动打回；检出但 <auto_rej 灰区人工）---
    if not detected:
        decision = "pass"
        reasons.append("E10 未触发：J1 未检出且 J3 无通道 P>%.2f" % j3_thr)
    elif probs and j3_max_p >= auto_rej:
        decision = "auto_reject"
        reasons.append("J3 最大通道 P=%.3f ≥ %.2f（高置信区间实测 8/8 全对，基准报告 §5）"
                       % (j3_max_p, auto_rej))
    else:
        decision = "manual_review"
        trig = ("J3@%.2f 触发[%s] 最大P=%.3f" % (j3_thr, ",".join(j3_hit_types) or "overall", j3_max_p)
                if j3_det else "J1 检出（无概率通道≥%.2f）" % auto_rej)
        reasons.append("E10 检出、未达 auto_reject 线：灰区人工复核（%s）" % trig)

    # --- defects 归并 ---
    def add_defect(dtype, source, conf, span=None, evidence=None):
        dtype = norm_type(dtype)
        d = defects_map.setdefault(dtype, {"type": dtype, "sources": [], "confidence": 0.0,
                                           "span": None, "evidence": {}})
        if source not in d["sources"]:
            d["sources"].append(source)
        d["confidence"] = max(d["confidence"], float(conf) if conf is not None else 0.0)
        if span and not d["span"]:
            d["span"] = span
        if evidence:
            d["evidence"][source] = evidence

    if j1_det:
        for t in (j1.get("defect_types") or []) or ["other"]:
            add_defect(t, "J1", j1.get("confidence") or 1.0,
                       evidence={"notes": (j1.get("notes") or "")[:160]})
    for code in ("J2", "J5"):
        r = judges_raw.get(code)
        if r and r.get("defect_detected"):
            for t in (r.get("defect_types") or []) or ["other"]:
                add_defect(t, code, r.get("confidence") or 1.0,
                           evidence={"notes": (r.get("notes") or "")[:160]})
    if probs and j3_det:
        src = {"channel_probs": {t: probs.get(t) for t in TYPES8 if probs.get(t) is not None},
               "overall": probs.get("overall")}
        for t in j3_hit_types:
            add_defect(t, "J3", probs.get(t, probs.get("overall")), evidence=src)
    for t, ev in sorted(j6_cand.items()):
        if ev.get("conf", 0) >= j6_emit:                 # J6 仅作信号：emit 后进 defects，不翻转 verdict
            add_defect(t, "J6", ev["conf"],
                       span=None,                        # span 由调用方以真实 n/dur 补算（见 run_tonight/run_online）
                       evidence={"kind": ev.get("kind"), "conf_src": round(ev["conf"], 3)})
    defects = sorted(defects_map.values(), key=lambda d: -d["confidence"])
    for d in defects:                                    # 契约：span 可选，无区间时省略键（不许 null）
        if d.get("span") is None:
            d.pop("span", None)

    # --- verdict confidence：参与合议通道的最大缺陷侧信号 ---
    conf_signals = [j3_max_p] if j3_det else []
    if j1_det and j1.get("confidence") is not None:
        conf_signals.append(float(j1["confidence"]))
    verdict_conf = round(max(conf_signals), 4) if conf_signals else 0.0

    # --- scores ---
    scores = {
        "per_type": {t: (probs.get(t) if probs else None) for t in TYPES8},
        "overall": (probs.get("overall") if probs else None),
        "thresholds_applied": {
            "ensemble_id": ens_id,
            "j3_thr": j3_thr,
            "auto_reject_p": auto_rej,
            "j6_emit_conf": j6_emit,
            "thresholds_sha256": thresholds_sha,
        },
    }

    # --- spans（J6 契约化 + 帧级 judge 的采样说明）---
    spans = []
    for d in defects:
        if d.get("span"):
            spans.append({"type": d["type"], "start_s": d["span"]["start_s"],
                          "end_s": d["span"]["end_s"], "evidence": d["evidence"]})
    for code in ("J1", "J2", "J5"):
        r = judges_raw.get(code)
        if r and r.get("spans"):
            for sp in norm_spans_field(r["spans"]):
                sp["evidence"] = dict(sp.get("evidence") or {}, source=code)
                spans.append(sp)

    report = {
        "schema_version": "1.0",
        "clip_id": clip_id,
        "generated_at": now_iso(),
        "qc_mode": mode,
        "verdict": {
            "defect_detected": detected,
            "decision": decision,
            "confidence": verdict_conf,
            "decided_by": ens_id,
            "reasons": reasons,
        },
        "defects": defects,
        "scores": scores,
        "spans": spans,
        "judges": judges_raw,
        "inputs": inputs,
        "errors": errors,
    }
    return report


# =====================================================================
# 4) asset manifest 登记（contracts/asset_manifest.schema.json）
# =====================================================================
def manifest_register(manifest_path, generator, entries):
    """entries=[{asset_id,kind,path,sha256,size_bytes,provenance?,evidence?}]；按 asset_id 去重替换。"""
    doc = {"schema_version": "1.0", "name": manifest_path.stem,
           "generated_at": now_iso(), "generator": generator, "items": []}
    if manifest_path.exists():
        try:
            old = load_json(manifest_path)
            doc["items"] = old.get("items", [])
        except Exception as e:
            log(f"[manifest] 旧表读取失败，重建：{e}")
    by_id = {it.get("asset_id"): i for i, it in enumerate(doc["items"])}
    for e in entries:
        rec = {"asset_id": e["asset_id"], "kind": e["kind"], "path": str(e["path"]),
               "sha256": e["sha256"], "size_bytes": int(e["size_bytes"]),
               "registered_at": now_iso()}
        for k in ("provenance", "probe", "evidence"):
            if e.get(k):
                rec[k] = e[k]
        if rec["asset_id"] in by_id:
            doc["items"][by_id[rec["asset_id"]]] = rec
        else:
            doc["items"].append(rec)
            by_id[rec["asset_id"]] = len(doc["items"]) - 1
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")


# =====================================================================
# 5) 回放模式（今晚数据）
# =====================================================================
def run_tonight(args, thr, ens_id, thr_sha):
    jroot = Path(args.judges_root)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    golden = load_json(args.golden)
    clips = [it["clip_id"] for it in golden["items"]]
    dur_of = {it["clip_id"]: (it.get("verify") or {}).get("dur_s", 0.0) for it in golden["items"]}

    j3_thr = float(thr["judges"]["J3_omnijev"]["thr"])
    j6_emit = float(thr["judges"]["J6_detectors"]["emit_conf"])
    j6_T = {k: float(v) for k, v in thr["judges"]["J6_detectors"]["rule_params"].items()}

    # J3 概率表：omnijev/run_metadata.json（逐 clip 9 通道）
    probs_by_clip, j3_src = {}, jroot / "omnijev" / "run_metadata.json"
    if j3_src.exists():
        rm = load_json(j3_src)
        probs_by_clip = {c["clip_id"]: c["probs"] for c in rm.get("clips", []) if c.get("ok")}
    else:
        log(f"[WARN] J3 概率源缺失: {j3_src} → 全部 clip 的 L1 主判弃权（errors 登记）")

    # J6 全候选：detectors/_j6_summary.json（per_clip.all_candidates）
    j6_by_clip, j6_src = {}, jroot / "detectors" / "_j6_summary.json"
    if j6_src.exists():
        summ = load_json(j6_src)
        j6_by_clip = summ.get("per_clip", {})
    else:
        log(f"[WARN] J6 汇总缺失: {j6_src} → J6 信号弃权")

    proto_dirs = {"J1": jroot / "glm8", "J2": jroot / "glm3", "J5": jroot / "videochat3",
                  "J6": jroot / "detectors"}
    m_entries, reports = [], []
    n_det = n_pass = n_review = n_reject = 0
    for cid in clips:
        errors, judge_files = {}, {}
        judges_raw = {}
        for code, d in proto_dirs.items():
            p = d / f"{cid}.json"
            if not p.exists():
                errors[f"judge_{code}"] = f"协议文件缺失: {p}"
                continue
            try:
                judges_raw[code] = load_json(p)
                judge_files[code] = str(p)
            except Exception as e:
                errors[f"judge_{code}"] = f"解析失败: {type(e).__name__}: {e}"

        # J3 协议合成（概率通道 → 六字段），供嵌入与追溯
        probs = probs_by_clip.get(cid)
        if probs is not None:
            det, hits = j3_flag(probs, j3_thr)
            pvals = [probs[t] for t in TYPES8 if probs.get(t) is not None] + \
                    ([probs["overall"]] if probs.get("overall") is not None else [])
            judges_raw["J3"] = {
                "clip_id": cid, "defect_detected": det,
                "defect_types": hits if hits else (["overall"] if det else []),
                "confidence": round(max(pvals), 4) if pvals else None,
                "spans": "16帧4x4拼图 9通道概率（run_metadata.json），阈值 %.2f" % j3_thr,
                "notes": "; ".join(f"{t}={probs[t]:.3f}" for t in TYPES8 + ["overall"]
                                   if probs.get(t) is not None),
            }
            judge_files["J3"] = str(j3_src)
        else:
            errors["judge_J3"] = f"概率缺失: {j3_src}"

        # J6：从全候选按 YAML emit 阈重发（ tonight 协议文件是 0.45 版，仅作嵌入追溯）
        j6_cand = {}
        pc = j6_by_clip.get(cid)
        if pc and "all_candidates" in pc:
            for t, ev in pc["all_candidates"].items():
                e2 = dict(ev)
                e2["_n"] = pc.get("n_frames", 8)
                e2["_dur"] = dur_of.get(cid, 0.0) or 8.0
                j6_cand[t] = e2
            j6_cand = {t: ev for t, ev in j6_cand.items() if ev.get("conf", 0) >= j6_emit}
        else:
            errors.setdefault("judge_J6", f"全候选缺失: {j6_src}")

        rep = synthesize_qc_report(
            cid, "tonight_replay", judges_raw, j6_cand, j6_emit, probs,
            thr, ens_id, thr_sha,
            inputs={"clip": None, "frames_dir": None, "judge_files": judge_files},
            errors=errors)

        # J6 信号 defects 的 span 用真实 n/dur 重算（synthesize 里不便传，这里补）
        n_f = (pc or {}).get("n_frames", 8)
        dur = dur_of.get(cid, 0.0) or 8.0
        for d in rep["defects"]:
            if "J6" in d["sources"] and not d.get("span"):
                ev = (j6_by_clip.get(cid, {}).get("all_candidates") or {}).get(d["type"])
                if ev:
                    d["span"] = j6_span_from_ev(ev, n_f, dur)

        op = out_dir / f"{cid}.json"
        op.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
        reports.append(rep)
        v = rep["verdict"]
        n_det += v["defect_detected"]
        n_pass += v["decision"] == "pass"
        n_review += v["decision"] == "manual_review"
        n_reject += v["decision"] == "auto_reject"
        # 登记：输入判官文件 + 输出报告
        for code, p in judge_files.items():
            fp = Path(p)
            m_entries.append({"asset_id": f"judge:{code}:{cid}", "kind": "judge_output",
                              "path": p, "sha256": sha256_file(fp),
                              "size_bytes": fp.stat().st_size})
        m_entries.append({"asset_id": f"qc:{cid}", "kind": "qc_report", "path": str(op),
                          "sha256": sha256_file(op), "size_bytes": op.stat().st_size,
                          "provenance": {"module": "qc_orch", "source": f"golden:{cid}"},
                          "evidence": {"qc_mode": "tonight_replay", "ensemble": ens_id}})
    if args.manifest:
        manifest_register(Path(args.manifest), "qc_orch.py@vpipe1.0", m_entries)
        log(f"[manifest] 登记 {len(m_entries)} 条 → {args.manifest}")
    log(f"[done] 回放 {len(clips)} clips → {out_dir}  检出={n_det} "
        f"(pass={n_pass} manual_review={n_review} auto_reject={n_reject})")
    return 0


# =====================================================================
# 6) 在线模式
# =====================================================================
def run_online(args, thr, ens_id, thr_sha):
    j6_emit = float(thr["judges"]["J6_detectors"]["emit_conf"])
    j6_T = {k: float(v) for k, v in thr["judges"]["J6_detectors"]["rule_params"].items()}
    errors, judges_raw, judge_files = {}, {}, {}
    # 检测器 JSON → 规则引擎 → J6 候选
    j6_cand, rule_status = {}, {}
    if args.detector_json:
        try:
            qc = load_json(args.detector_json)
            meta = qc.get("clip_meta") or {}
            dur = float(meta.get("duration_sec") or 0)
            n = len(qc.get("frames") or []) or len(qc.get("color_stats") or []) or 8
            j6_cand, rule_status = run_j6_rules(qc, j6_T, n, dur)
            j6_cand = {t: dict(ev, _n=n, _dur=dur or 8.0)
                       for t, ev in j6_cand.items() if ev.get("conf", 0) >= j6_emit}
            judge_files["J6"] = str(args.detector_json)
        except Exception as e:
            errors["j6_rules"] = f"{type(e).__name__}: {e}"
    for spec in args.judge_file or []:
        code, _, p = spec.partition("=")
        try:
            judges_raw[code] = load_json(p)
            judge_files[code] = p
        except Exception as e:
            errors[f"judge_{code}"] = f"{type(e).__name__}: {e}"
    probs = None
    if args.judge_probs:
        code, _, p = args.judge_probs.partition("=")
        try:
            rm = load_json(p)
            probs = next((c["probs"] for c in rm.get("clips", [])
                          if c.get("clip_id") == args.clip_id and c.get("ok")), None)
            judge_files[code] = p
            if probs is None:
                errors[f"judge_{code}"] = f"run_metadata 中无 {args.clip_id} 的概率"
        except Exception as e:
            errors[f"judge_{code}"] = f"{type(e).__name__}: {e}"
    if probs is not None:
        det, hits = j3_flag(probs, float(thr["judges"]["J3_omnijev"]["thr"]))
        judges_raw.setdefault("J3", {"clip_id": args.clip_id, "defect_detected": det,
                                     "defect_types": hits, "confidence": max(
                                         [probs.get(t, 0) for t in TYPES8] + [probs.get("overall", 0)]),
                                     "spans": "prob_channels", "notes": ""})
    rep = synthesize_qc_report(args.clip_id, "online", judges_raw, j6_cand, j6_emit, probs,
                               thr, ens_id, thr_sha,
                               inputs={"clip": args.clip, "frames_dir": args.frames,
                                       "judge_files": judge_files},
                               errors=errors)
    rep["evidence_rule_status"] = rule_status  # 仅在线模式附规则状态（契约 errors 之外的过程信息）
    out = Path(args.out) if args.out else Path(f"{args.clip_id}.qc_report.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"[done] 在线质检 {args.clip_id} → {out}  verdict={rep['verdict']}")
    return 0


# =====================================================================
def main():
    ap = argparse.ArgumentParser(description="vpipe qc_orch：检测器规则引擎 + judge 合议")
    ap.add_argument("--thresholds", required=True, help="eval/thresholds.yaml")
    ap.add_argument("--from-tonight", action="store_true", help="回放今晚判官落盘产物")
    ap.add_argument("--online", action="store_true", help="在线模式（检测器 JSON + 判官文件）")
    ap.add_argument("--judges-root", default="../数据/judges")
    ap.add_argument("--golden", default="../eval/golden_manifest.json")
    ap.add_argument("--out-dir", default="out/qc_reports")
    ap.add_argument("--manifest", default="", help="asset manifest 输出路径（缺省不登记）")
    ap.add_argument("--detector-json", help="在线：qc_detectors.py 产出的检测 JSON")
    ap.add_argument("--clip", help="在线：clip 路径")
    ap.add_argument("--frames", help="在线：帧目录")
    ap.add_argument("--clip-id", default="clip", help="在线：clip ID")
    ap.add_argument("--judge-file", action="append", help="在线：J代码=协议JSON路径，可多次")
    ap.add_argument("--judge-probs", help="在线：J代码=run_metadata.json（概率型判官）")
    ap.add_argument("--out", help="在线：输出报告路径")
    args = ap.parse_args()

    thr_path = Path(args.thresholds)
    thr = yaml.safe_load(thr_path.read_text(encoding="utf-8"))
    ens_id = thr["ensemble"]["recommended"]
    thr_sha = sha256_file(thr_path)
    log(f"[cfg] thresholds={thr_path} sha256={thr_sha[:12]}… ensemble={ens_id}")
    if args.from_tonight:
        return run_tonight(args, thr, ens_id, thr_sha)
    if args.online:
        return run_online(args, thr, ens_id, thr_sha)
    ap.error("需要 --from-tonight 或 --online 之一")


if __name__ == "__main__":
    sys.exit(main())

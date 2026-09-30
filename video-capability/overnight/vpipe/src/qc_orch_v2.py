#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
qc_orch_v2.py — 质检编排（检测器规则引擎 + judge 合议）· 模块重生成 v2
=====================================================================
按 SPEC.md §2.3 + contracts/qc_report.schema.json + eval/thresholds.yaml 从零重写。
重生成纪律（SPEC §0/§6）：
  * 不 import 兄弟模块；模块间只靠契约 JSON 通信。
  * 一切判定阈值只从 thresholds.yaml 读（--thresholds 传入），源码无第二套判定阈值。
  * 任一判官缺失/解析失败 → errors 登记弃权，合议用剩余通道继续（方案 §4）。

回放模式（验收路径，不跑任何模型）：
  python src/qc_orch_v2.py --from-tonight --judges-root ../数据/judges \
      --golden eval/golden_manifest.json --thresholds eval/thresholds.yaml \
      --out-dir out/qc_reports_v2 [--manifest out/asset_manifest_v2.json]

在线模式（生产形态：检测器/判官在别处跑完落盘，本模块只做契约校验+合议）：
  python src/qc_orch_v2.py --online --clip-id X [--clip X.mp4] [--detector-json X.qc.json] \
      [--judge-file J1=p.json ...] [--judge-probs J3=run_metadata.json] --thresholds eval/thresholds.yaml \
      [--out-dir out/qc_reports_online]
      [--expect-duration S] [--profile avatar_talk] [--known-cuts cuts.json] [--skip-l0]

L0 确定性预检（2026-10-01 接线，工程方案v3.1 P0-2；thresholds.yaml l0_preflight）：
  在线模式提供 --clip 时默认先跑 L0（拒收层，不进 judge）：
    ffprobe 时长 vs --expect-duration（偏差 >duration_dev_max 拒）；profile=avatar 时按
    口播垫尾豁免（允许窗 = [expect×(1−dev), ceil(expect)+avatar_tail_max_s]，数字人实验
    报告 §7-4：成片时长=ceil(音频时长)+垫尾不是缺陷）；采样帧黑屏/单色占比 >black_frame_ratio_max 拒。
  拒收 → 写 <out-dir>/<clip_id>.l0.json（含全部实测数字），退出码 4，不跑判官。
  全部数值只从 thresholds.yaml l0_preflight 段读。

核心签名（SPEC §2.3）：
  run_j6_rules(detector_json, T, n_frames, dur_s) -> (cand, rule_status)
  j3_flag(probs, thr)                             -> (flag, hit_types)
  synthesize_qc_report(...)                       -> dict（纯函数，产出契约 JSON）
  l0_preflight(clip_path, T, expect_s, profile)   -> (ok, result)（确定性，失败也是数据）

J6 规则引擎重建说明（无旧实现可读，语义从三处合法材料重建）：
  1) eval/thresholds.yaml judges.J6_detectors.rule_params（参数名与 emit_conf）；
  2) yaml known_broken_rules 的失效模式文字（freeze 几何失谐 / garble 手部误报 /
     hue 绝对阈 / scene_cut 误判 / ghosting-pixelate 零覆盖）；
  3) 输入数据本身：judges/detectors/raw/*.qc.json（检测 JSON 契约）× 回放候选行为。
  置信度曲线常数按观测数据拟合，拟合点全部落在 yaml 参数的封闭表达式上
  （见各 RECON_* 注释）；其中 hue 权重下限 RECON_HUE_W 只能约束到区间
  (0.0428, 0.1152]，取 0.10——该参数在 40 条金标上不改变任何触发结果（已实测）。
  J6 在 E10 中只作信号不作否决（yaml role=signal_only），其候选不翻转 verdict。
"""
import argparse
import datetime
import hashlib
import json
import math
import os
import statistics
import subprocess
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

try:
    import cv2
except ImportError:  # L0 黑屏/单色采样用；缺库时该项弃权并记 errors
    cv2 = None

try:
    import jsonschema
except ImportError:  # jsonschema 可缺：退回 required-key 校验并在运行摘要记降级
    jsonschema = None

HERE = Path(__file__).resolve().parent
SCHEMA_QC = HERE.parent / "contracts" / "qc_report.schema.json"
SCHEMA_MANIFEST = HERE.parent / "contracts" / "asset_manifest.schema.json"
GENERATOR = "qc_orch_v2.py@vpipe1.0"

# 规范缺陷词表（contracts/qc_report.schema.json scores.per_type 的 8 类）
TYPES8 = ["frame_freeze", "flicker", "color_shift", "face_blur",
          "garble_text", "temporal_swap", "pixelate", "ghosting"]
TYPE_ALIAS = {"text_error": "garble_text"}
# 判官代码 → thresholds.yaml judges 键（键名后缀即回放数据子目录名）
JUDGE_KEYS = {"J1": "J1_glm8", "J2": "J2_glm3", "J3": "J3_omnijev",
              "J4": "J4_visualjev", "J5": "J5_videochat3",
              "J6": "J6_detectors", "J7": "J7_kimi"}


def norm_type(t):
    t = str(t).strip().lower()
    return TYPE_ALIAS.get(t, t)


def sha256_file(p):
    h = hashlib.sha256()
    h.update(Path(p).read_bytes())
    return h.hexdigest()


def now_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")


def load_json(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def load_thresholds(path):
    if yaml is None:
        raise SystemExit("PyYAML 未安装，无法读 thresholds.yaml（判定阈值唯一来源）")
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


# =====================================================================
# L0 确定性预检（judge基准报告 §11.1 拒收层；2026-10-01 挂进在线模式）
# =====================================================================
def l0_preflight(clip_path, T, expect_s=None, profile=None):
    """L0 拒收层：ffprobe 时长 vs 期望 + 采样帧黑屏/单色占比。全部阈值只从
    thresholds.yaml l0_preflight 段读；profile=avatar 按口播垫尾豁免时长判定
    （数字人实验报告 §7-4：成片时长=ceil(音频时长)+垫尾不是缺陷）。
    返回 (ok: bool, result: dict)；失败原因在 result["failures"]（失败也是数据）。"""
    cfg = T.get("l0_preflight") or {}
    res = {"clip": str(clip_path), "expect_duration_s": expect_s,
           "profile": profile, "failures": [], "checks": {}}
    if not cfg:
        res["skipped"] = "thresholds.yaml 无 l0_preflight 段"
        return True, res
    p = Path(clip_path)
    if not p.exists():
        res["failures"].append("clip 不存在: %s" % p)
        return False, res

    # ---- 时长（ffprobe 实测）----
    dev_max = float(cfg.get("duration_dev_max", 0.02))
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(p)],
            capture_output=True, text=True, timeout=60, check=True)
        dur = float(out.stdout.strip())
    except Exception as e:
        res["failures"].append("ffprobe 时长获取失败 (%s: %s)" % (type(e).__name__, e))
        return False, res
    dur_chk = {"measured_s": round(dur, 3)}
    if expect_s is not None and float(expect_s) > 0:
        exp = float(expect_s)
        avatar_profiles = [str(x) for x in (cfg.get("avatar_profiles") or [])]
        if profile is not None and str(profile) in avatar_profiles:
            tail = float(cfg.get("avatar_tail_max_s", 1.0))
            lo, hi = exp * (1.0 - dev_max), math.ceil(exp) + tail
            ok_dur = (lo - 1e-9) <= dur <= (hi + 1e-9)
            dur_chk.update({"rule": "avatar_tail", "allowed_s": [round(lo, 3), round(hi, 3)],
                            "avatar_tail_max_s": tail})
        else:
            dev = abs(dur - exp) / exp
            ok_dur = dev <= dev_max
            dur_chk.update({"rule": "dev_max", "dev": round(dev, 4), "dev_max": dev_max})
        if not ok_dur:
            res["failures"].append("L0 时长超差: measured=%.3fs expect=%.3fs rule=%s"
                                   % (dur, exp, dur_chk.get("rule")))
    else:
        dur_chk["skipped"] = "未提供 --expect-duration"
    res["checks"]["duration"] = dur_chk

    # ---- 黑屏/单色帧占比（均匀采样，cv2 缺库弃权不拦截）----
    n_samples = int(cfg.get("sample_frames", 64))
    black_luma = float(cfg.get("black_luma_max", 8.0))
    mono_std = float(cfg.get("mono_std_max", 2.0))
    ratio_max = float(cfg.get("black_frame_ratio_max", 0.50))
    bf = {"n_samples": n_samples, "black_luma_max": black_luma,
          "mono_std_max": mono_std, "ratio_max": ratio_max}
    if cv2 is None:
        bf["skipped"] = "cv2 未安装（黑屏检查弃权）"
    else:
        cap = cv2.VideoCapture(str(p))
        if not cap.isOpened():
            res["failures"].append("L0 无法打开视频（cv2）: %s" % p)
            return False, res
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
        idxs = sorted({min(total - 1, int(round(i * (total - 1) / max(1, n_samples - 1))))
                       for i in range(n_samples)} if total > 0 else [])
        bad = 0
        used = 0
        for fi in idxs:
            cap.set(cv2.CAP_PROP_POS_FRAMES, fi)
            ok, frame = cap.read()
            if not ok:
                continue
            used += 1
            g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            if float(g.mean()) < black_luma or float(g.std()) < mono_std:
                bad += 1
        cap.release()
        ratio = (bad / used) if used else 0.0
        bf.update({"used": used, "bad_frames": bad, "ratio": round(ratio, 4)})
        if used and ratio > ratio_max:
            res["failures"].append("L0 黑屏/单色帧占比超差: %.3f > %.3f" % (ratio, ratio_max))
    res["checks"]["black_mono_ratio"] = bf

    return (not res["failures"]), res


# =====================================================================
# J6 检测器规则引擎（移植口径：阈值全由 T 注入；T = thresholds 全量 dict）
# =====================================================================
def run_j6_rules(detector_json: dict, T: dict, n_frames: int, dur_s: float):
    """从检测 JSON 契约（qc_detectors.py 落盘格式）计算规则候选。

    返回 (cand, rule_status)：
      cand: {type -> candidate}，candidate = {conf, kind, span, evidence}
            （每类型只保留最强候选；未过 emit 闸门前全部返回，emit 由调用方按 yaml 施加）
      rule_status: {face|frame|garble|color -> status str}
    """
    p = (T.get("judges") or {}).get("J6_detectors") or {}
    rp = p.get("rule_params") or {}
    face_drift_cos = float(rp.get("face_drift_cos", 0.30))
    face_blur_cos = float(rp.get("face_blur_cos", 0.50))
    freeze_diff = float(rp.get("freeze_diff", 1.2))
    freeze_ratio = float(rp.get("freeze_ratio", 0.35))
    spike_k = float(rp.get("spike_k", 3.0))
    swap_sim = float(rp.get("swap_sim", 0.75))
    flicker_cap = float(rp.get("flicker_cap", 0.85))
    garble_drop = float(rp.get("garble_drop", 0.25))
    garble_low = float(rp.get("garble_low", 0.78))
    hue_shift_deg = float(rp.get("hue_shift_deg", 30.0))
    sat_jump = float(rp.get("sat_jump", 0.30))
    # —— 重建常数（非判定闸门；均为置信度曲线形状，见模块 docstring）——
    RECON_HUE_W = 0.10          # hue 对权重下限，40 条上约束区间 (0.0428, 0.1152]
    RECON_FREEZE_K = 5.0 / 6.0  # freeze conf = 1 - k*min_diff（3 个观测点精确拟合）
    RECON_HUE_FLOOR = 0.40      # hue 弱信号置信度下限（4 个观测点恒 0.4）
    RECON_GARBLEDROP_DIV = 2.0 * garble_drop   # conf_drop conf = min(1, drop/(2*garble_drop))
    RECON_UNIF_A, RECON_UNIF_B = 1.45, 1.5     # uniform conf = min(0.85, A - B*max_mean)

    cand, rule_status = {}, {}
    meta = detector_json.get("meta") or {}
    clip_meta = detector_json.get("clip_meta") or {}
    if dur_s <= 0:
        dur_s = float(clip_meta.get("duration_sec") or 0.0)
    if n_frames <= 0:
        n_frames = len(detector_json.get("color_stats") or []) or int(
            clip_meta.get("nb_frames") or 0) or 8
    dt = (dur_s / n_frames) if (dur_s > 0 and n_frames > 0) else 0.0

    def pair_span(i):  # 帧对 i(=帧 i,i+1) 的时间区间：均匀抽帧中点近似
        return {"start_s": round((i + 0.5) * dt, 3), "end_s": round((i + 1.5) * dt, 3)}

    # ---- face 族（ArcFace 帧间余弦；无人脸信号则弃权）----
    faces_pf = meta.get("faces_per_frame") or []
    fc = [x for x in (detector_json.get("face_consistency") or []) if x is not None]
    if not any(faces_pf):
        rule_status["face"] = "insufficient_face_signal"
    else:
        rule_status["face"] = "ok"
        below = [x for x in fc if x < face_drift_cos]
        if below:
            cos = min(below)  # 跨人证据：取最强（最小余弦）对
            i = fc.index(cos)
            cand["identity_drift"] = {
                "conf": max(0.0, min(1.0, 1.0 - cos / face_drift_cos)),
                "kind": "face_drift", "span": pair_span(i),
                "evidence": {"pair": i, "cos": round(cos, 4)}}
        mids = [x for x in fc if face_drift_cos <= x < face_blur_cos]
        if mids:
            cos = min(mids)
            i = fc.index(cos)
            # conf = (blur_thr - cos) / (blur_thr - drift_thr)：观测点精确拟合
            cand["face_blur"] = {
                "conf": max(0.0, min(1.0, (face_blur_cos - cos) /
                                     (face_blur_cos - face_drift_cos))),
                "kind": "face_blur_cos", "span": pair_span(i),
                "evidence": {"pair": i, "cos": round(cos, 4)}}

    # ---- frame 族（帧差序列 + scene_cuts）----
    fd = meta.get("frame_diff_scores") or detector_json.get("frame_diff") or []
    fd = [x for x in fd if x is not None]
    cuts = [float(c) for c in (detector_json.get("scene_cuts") or [])]
    rule_status["frame"] = "ok"
    if fd:
        med = statistics.median(fd)
        mn = min(fd)
        frozen = sum(1 for d in fd if d < freeze_diff)
        # 冻结占比高 = 静态场景本底，不算缺陷（yaml known_broken：freeze_ratio 与 8 帧
        # 采样几何失谐 → 真冻结零触发；此处按观测定型为「上限」闸门）
        if mn < freeze_diff and (frozen / len(fd)) < freeze_ratio:
            i = fd.index(mn)
            cand["frame_freeze"] = {
                "conf": max(0.0, min(1.0, 1.0 - RECON_FREEZE_K * mn)),
                "kind": "freeze_min_diff", "span": pair_span(i),
                "evidence": {"pair": i, "score": round(mn, 3), "median": round(med, 3)}}
        spikes = [i for i, d in enumerate(fd) if d > spike_k * med]
        if len(spikes) >= 3:  # ≥3 个尖峰才成「闪」；本轮 40 条最多 2 个（零触发，与 oracle 一致）
            ratio = max(fd) / med if med else 0.0
            cand.setdefault("flicker", {
                "conf": min(flicker_cap, ratio / (2.0 * spike_k)),
                "kind": "diff_spike_burst",
                "span": {"start_s": round((spikes[0] + 0.5) * dt, 3),
                         "end_s": round((spikes[-1] + 1.5) * dt, 3)},
                "evidence": {"pairs": spikes, "median": round(med, 3),
                             "max_ratio": round(ratio, 2)}})
    if dt > 0:
        mids = [c for c in cuts if dt <= c <= dur_s - dt]  # 首尾帧间隔内的切不算「段落错乱」
        if mids:
            c0 = mids[0]
            cand["temporal_swap"] = {
                "conf": float(swap_sim), "kind": "scene_cut_mid",
                "span": {"start_s": round(max(0.0, c0 - 0.5), 3),
                         "end_s": round(c0 + 0.5, 3)},
                "evidence": {"cut_s": round(c0, 3)}}

    # ---- garble 族（OCR 逐帧置信度；mean≤0 的帧视为 OCR 无效帧剔除）----
    opf = meta.get("ocr_per_frame") or []
    means = []
    for f in opf:
        scores = f.get("scores") or []
        if scores:
            m = sum(scores) / len(scores)
            if m > 0:
                means.append(m)
    if not opf:
        rule_status["garble"] = "no_ocr_meta"
    elif not [f for f in opf if f.get("scores")]:
        rule_status["garble"] = "no_text"
    else:
        rule_status["garble"] = "ok"
        g = {}
        if len(means) >= 2:
            drop = max(means) - min(means)
            if drop >= garble_drop:
                lo, hi = means.index(min(means)), means.index(max(means))
                g["conf_drop"] = (min(1.0, drop / RECON_GARBLEDROP_DIV),
                                  {"kind": "conf_drop", "drop": round(drop, 3),
                                   "frames": [lo, hi],
                                   "mean_scores": [round(min(means), 3), round(max(means), 3)]},
                                  {"start_s": round((min(lo, hi) + 0.5) * dt, 3),
                                   "end_s": round((max(lo, hi) + 0.5) * dt, 3)})
        if means and max(means) < garble_low:
            mm = max(means)
            g["uniform_low_conf"] = (min(0.85, RECON_UNIF_A - RECON_UNIF_B * mm),
                                     {"kind": "uniform_low_conf", "max_mean": round(mm, 3)},
                                     {"start_s": 0.0, "end_s": round(dur_s, 3)})
        if g:
            kind = max(g, key=lambda k: g[k][0])
            conf, ev, span = g[kind]
            cand["garble_text"] = {"conf": max(0.0, min(1.0, conf)),
                                   "kind": ev["kind"], "span": span, "evidence": ev}

    # ---- color 族（环形色相偏移 + 饱和跳变）----
    cs = detector_json.get("color_stats") or []
    rule_status["color"] = "ok"
    if len(cs) >= 2:
        def circ(a, b):
            d = abs(a - b) % 360.0
            return 360.0 - d if d > 180.0 else d
        hit = None
        for i in range(len(cs) - 1):  # 扫到第一个超阈的可靠帧对即报（观测行为）
            w0, w1 = cs[i].get("hue_weight"), cs[i + 1].get("hue_weight")
            if w0 is None or w1 is None or min(w0, w1) < RECON_HUE_W:
                continue
            d = circ(cs[i]["hue_circ_mean_deg"], cs[i + 1]["hue_circ_mean_deg"])
            if d > hue_shift_deg:
                hit = (i, d)
                break
        if hit:
            i, d = hit
            conf = min(1.0, max(RECON_HUE_FLOOR, (d - hue_shift_deg) / (2.0 * hue_shift_deg)))
            cand["color_shift"] = {
                "conf": conf, "kind": "hue_shift", "span": pair_span(i),
                "evidence": {"pair": i, "hue_delta_deg": round(d, 1)}}
        sats = [c.get("mean_sat_0_1") for c in cs if c.get("mean_sat_0_1") is not None]
        if len(sats) >= 2:
            mj = sum(abs(sats[k + 1] - sats[k]) for k in range(len(sats) - 1)) / (len(sats) - 1)
            if mj > sat_jump:
                cand.setdefault("color_shift", {
                    "conf": min(1.0, mj / (2.0 * sat_jump)), "kind": "sat_jump_mean",
                    "span": {"start_s": 0.0, "end_s": round(dur_s, 3)},
                    "evidence": {"mean_abs_jump": round(mj, 3)}})
    return cand, rule_status


# =====================================================================
# J3 概率通道
# =====================================================================
def j3_flag(probs: dict, thr: float):
    """OmniJev flag：8 类任一 > thr 或 overall > thr（严格大于，与基准报告 §7 扫描口径一致）。
    返回 (flag, hit_types)；hit_types 只含 8 类规范型（overall 不是缺陷类型）。"""
    hits = [t for t in TYPES8 if probs.get(t) is not None and probs[t] > thr]
    overall = probs.get("overall")
    flag = bool(hits) or (overall is not None and overall > thr)
    return flag, hits


# =====================================================================
# 报告合成（纯函数）
# =====================================================================
def synthesize_qc_report(clip_id, mode, judges_raw, j6_cand, j6_emit, probs,
                         thr_cfg, ens_id, thresholds_sha, inputs, errors,
                         qc_context=None):
    """按 E10（thresholds.yaml ensemble.recommended）合成 QCReport 契约 JSON。

    judges_raw: {code -> 原始六字段协议 JSON（一字不改，供 judges.* 嵌套）}
    j6_cand:    run_j6_rules 的全部候选（未过 emit）
    j6_emit:    过了 yaml emit_conf 的候选 {type -> candidate}
    probs:      J3 九通道概率 dict 或 None
    thr_cfg:    {ensemble_def, j3_thr, auto_reject_p, j6_emit_conf}
    qc_context: 契约 1.1 可选字段 {profile, known_cuts, l0_preflight}（上游声明上下文，
                2026-10-01；回放模式不传 = 不落该字段）
    """
    j1 = judges_raw.get("J1")
    e_def = thr_cfg["ensemble_def"]
    j3_thr = float(thr_cfg["j3_thr"])
    auto_p = float(thr_cfg["auto_reject_p"])

    j1_det = bool(j1.get("defect_detected")) if j1 else False
    j3_flagged, j3_hits = (False, [])
    if probs:
        j3_flagged, j3_hits = j3_flag(probs, j3_thr)
    detected = j1_det or j3_flagged

    # decision（基准报告 §11.1 / schema verdict.description）
    if not detected:
        decision = "pass"
    else:
        chan = [probs[t] for t in TYPES8 if probs and probs.get(t) is not None]
        if probs and probs.get("overall") is not None:
            chan.append(probs["overall"])
        pmax = max(chan) if chan else None
        decision = "auto_reject" if (pmax is not None and pmax >= auto_p) else "manual_review"

    # confidence = 参与合议通道的最大缺陷侧信号强度（J3 被触发通道的最大 P，无则 J1）
    if j3_flagged and probs:
        vals = [v for v in probs.values() if v is not None]
        confidence = max(vals) if vals else 0.0
    elif j1 and isinstance(j1.get("confidence"), (int, float)):
        confidence = float(j1["confidence"])
    else:
        confidence = 0.0
        errors = dict(errors or {})
        errors.setdefault("verdict", "confidence 无信号源（J3 未触发且 J1 缺失/无效），置 0.0")

    reasons = []
    if j1:
        reasons.append("J1(detected=%s, types=%s, conf=%s)" %
                       (j1_det, j1.get("defect_types") or [], j1.get("confidence")))
    else:
        reasons.append("J1 缺席（弃权）")
    if probs:
        pmax9 = max([v for v in probs.values() if v is not None], default=None)
        reasons.append("J3@%s flag=%s hits=%s max_channel_P=%s" %
                       (j3_thr, j3_flagged, j3_hits, pmax9))
    else:
        reasons.append("J3 概率缺席（弃权）")
    if j6_emit:
        reasons.append("J6 信号(仅信号不否决): " +
                       ", ".join("%s@%.2f" % (t, c["conf"]) for t, c in sorted(j6_emit.items())))
    if errors:
        reasons.append("降级: " + "; ".join(sorted(errors)))

    # defects 归并：J1/J3 恒并入；J5 仅并入「确认缺陷」方向（yaml role=cheap_signal）；
    # J6 恒并入但 source 如实记录、不翻转 verdict（yaml role=signal_only）。J2 备用不入。
    merged = {}

    def merge(t, src, conf, span=None, evidence=None):
        t = norm_type(t)
        d = merged.setdefault(t, {"type": t, "sources": [], "confidence": 0.0,
                                  "span": None, "evidence": {}})
        if src not in d["sources"]:
            d["sources"].append(src)
        d["confidence"] = max(d["confidence"], conf if conf is not None else 0.0)
        if span and not d["span"]:
            d["span"] = span
        if evidence is not None:
            d["evidence"][src] = evidence

    if j1:
        for t in (j1.get("defect_types") or []):
            merge(t, "J1", j1.get("confidence"), None,
                  {"confidence": j1.get("confidence"), "notes": (j1.get("notes") or "")[:200]})
    if probs:
        for t in j3_hits:
            merge(t, "J3", probs[t], None, {"channel_P": probs[t]})
    j5 = judges_raw.get("J5")
    if detected and j5:
        for t in (j5.get("defect_types") or []):
            merge(t, "J5", j5.get("confidence"), None,
                  {"confidence": j5.get("confidence")})
    for t, c in sorted(j6_emit.items()):
        merge(t, "J6", c["conf"], c.get("span"), c.get("evidence"))

    defects = []
    for t in sorted(merged):
        d = merged[t]
        item = {"type": d["type"], "sources": sorted(d["sources"]),
                "confidence": round(min(1.0, d["confidence"]), 4)}
        if d["span"]:
            item["span"] = d["span"]
        if d["evidence"]:
            item["evidence"] = d["evidence"]
        defects.append(item)

    # spans：J6 规则区间为准；帧级 judge 的采样描述字符串降为 note 对象
    spans = []
    for t, c in sorted(j6_emit.items()):
        s = {"type": t}
        if c.get("span"):
            s.update({"start_s": c["span"].get("start_s"), "end_s": c["span"].get("end_s")})
        s["evidence"] = c.get("evidence") or {}
        spans.append(s)
    for code in ("J1", "J3", "J5"):
        raw = judges_raw.get(code)
        if raw and isinstance(raw.get("spans"), str):
            spans.append({"type": "note", "evidence": {"judge": code, "text": raw["spans"]}})

    per_type = {t: (probs.get(t) if probs else None) for t in TYPES8}
    overall = probs.get("overall") if probs else None

    rep = {
        "schema_version": "1.1",
        "clip_id": clip_id,
        "generated_at": now_iso(),
        "qc_mode": mode,
        "verdict": {
            "defect_detected": bool(detected),
            "decision": decision,
            "confidence": round(min(1.0, max(0.0, confidence)), 4),
            "decided_by": "%s:%s" % (ens_id, e_def),
            "reasons": reasons,
        },
        "defects": defects,
        "scores": {
            "per_type": per_type,
            "overall": overall,
            "thresholds_applied": {
                "ensemble_id": ens_id,
                "j3_thr": j3_thr,
                "auto_reject_p": auto_p,
                "j6_emit_conf": float(thr_cfg["j6_emit_conf"]),
                "thresholds_sha256": thresholds_sha,
            },
        },
        "spans": spans,
        "judges": {k: v for k, v in judges_raw.items()},
        "inputs": inputs,
        "errors": errors,
    }
    if qc_context is not None:
        rep["qc_context"] = qc_context
    return rep


# =====================================================================
# 契约校验（jsonschema 全量 → 缺库退回 required-key 并记降级）
# =====================================================================
def validate_report(rep):
    if jsonschema is not None:
        schema = load_json(SCHEMA_QC)
        errs = ["%s: %s" % (list(e.absolute_path), e.message)
                for e in jsonschema.Draft7Validator(schema).iter_errors(rep)]
        return (not errs), errs
    missing = [k for k in ("schema_version", "clip_id", "generated_at", "verdict",
                           "defects", "scores") if k not in rep]
    return (not missing), ["required-key missing: %s" % missing] if missing else []


# =====================================================================
# 回放模式
# =====================================================================
def judge_subdirs(T):
    """yaml judges 键名后缀 = 判官输出子目录名（J1_glm8 → glm8 …）。"""
    out = {}
    for code, key in JUDGE_KEYS.items():
        if (T.get("judges") or {}).get(key) is not None:
            out[code] = key.split("_", 1)[1] if "_" in key else key
    return out


def replay(args):
    T = load_thresholds(args.thresholds)
    ens = T["ensemble"]
    ens_id = ens["recommended"]
    ens_def = (ens.get("definitions") or {}).get(ens_id, ens_id)
    jd = (T["judges"])["J3_omnijev"]
    j6 = (T["judges"])["J6_detectors"]
    thr_cfg = {"ensemble_def": ens_def, "j3_thr": jd["thr"],
               "auto_reject_p": jd["auto_reject_p"], "j6_emit_conf": j6["emit_conf"]}
    thr_sha = sha256_file(args.thresholds)
    roles = {c: ((T.get("judges") or {}).get(k) or {}).get("role") for c, k in JUDGE_KEYS.items()}
    subdirs = judge_subdirs(T)
    root = Path(args.judges_root)

    gold = load_json(args.golden)
    items = gold["items"]
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 预载 J3 全量概率（回放源：judges/omnijev/run_metadata.json）
    j3_meta_path = root / subdirs.get("J3", "omnijev") / "run_metadata.json"
    j3_probs = {}
    j3_load_err = None
    try:
        rm = load_json(j3_meta_path)
        for c in rm.get("clips", []):
            if c.get("ok") and c.get("probs"):
                j3_probs[c["clip_id"]] = c["probs"]
    except Exception as e:
        j3_load_err = "%s: %s" % (type(e).__name__, e)

    consumed, reports, problems = {}, [], []
    for it in items:
        cid = it["clip_id"]
        errors = {}
        judges_raw = {}
        judge_files = {}

        def read_six_field(code, path):
            try:
                d = load_json(path)
                for k in ("clip_id", "defect_detected", "defect_types", "confidence"):
                    if k not in d:
                        raise ValueError("missing key %s" % k)
                judge_files[code] = str(path)
                return d
            except Exception as e:
                errors[code] = "读取/解析失败 %s (%s: %s)" % (path, type(e).__name__, e)
                return None

        if j3_load_err:
            errors.setdefault("J3", "run_metadata 加载失败: " + j3_load_err)
        # J1（review_parallel，进 E10）
        if roles.get("J1") in (None, "review_parallel"):
            p = root / subdirs.get("J1", "glm8") / ("%s.json" % cid)
            judges_raw["J1"] = read_six_field("J1", p)
        # J5（cheap_signal：仅并入确认缺陷方向）
        if roles.get("J5") == "cheap_signal":
            p = root / subdirs.get("J5", "videochat3") / ("%s.json" % cid)
            judges_raw["J5"] = read_six_field("J5", p)
        # J3 原始六字段（存在则一字不改嵌入；概率判定一律走 run_metadata+yaml 阈）
        p6 = root / subdirs.get("J3", "omnijev") / ("%s.json" % cid)
        if p6.exists():
            try:
                judges_raw["J3"] = load_json(p6)
                judge_files.setdefault("J3", str(j3_meta_path))
            except Exception as e:
                errors.setdefault("J3", "six-field 嵌入失败 %s (%s)" % (p6, e))
        probs = j3_probs.get(cid)
        if probs is None and not j3_load_err:
            errors.setdefault("J3", "run_metadata 无 %s 概率" % cid)

        # J6（signal_only）：raw 检测 JSON → 规则引擎 → yaml emit 闸门
        j6_emit, j6_cand = {}, {}
        p = root / subdirs.get("J6", "detectors") / "raw" / ("%s.qc.json" % cid)
        try:
            det = load_json(p)
            judge_files["J6"] = str(p)
            n_frames = len(det.get("color_stats") or []) or int(
                (it.get("verify") or {}).get("n_frames") or 8)
            dur_s = float((det.get("clip_meta") or {}).get("duration_sec") or
                          (it.get("verify") or {}).get("dur_s") or 0.0)
            j6_cand, _status = run_j6_rules(det, T, n_frames, dur_s)
            emit = float(j6["emit_conf"])
            j6_emit = {t: c for t, c in j6_cand.items() if c["conf"] >= emit}
            # J6 六字段视图（干净侧置信度=1-最强候选信号，语义同今晚转换器公开说明）
            mx = max([c["conf"] for c in j6_cand.values()], default=0.0)
            judges_raw["J6"] = {
                "clip_id": cid, "defect_detected": bool(j6_emit),
                "defect_types": sorted(j6_emit),
                "confidence": round(max((c["conf"] for c in j6_emit.values()), default=1.0 - mx), 4),
                "spans": [{"type": t,
                           **({"start_s": c["span"]["start_s"],
                               "end_s": c["span"]["end_s"]} if c.get("span") else {}),
                           "evidence": c.get("evidence") or {}} for t, c in sorted(j6_emit.items())],
                "notes": "qc_orch_v2 规则引擎重建（阈值=%s emit@%s）" % (args.thresholds, emit),
            }
            judge_files.setdefault("J6", str(p))
        except Exception as e:
            errors["J6"] = "检测 JSON 缺失/失败 %s (%s: %s)" % (p, type(e).__name__, e)

        inputs = {"clip": (it.get("paths") or {}).get("clip"),
                  "frames_dir": (it.get("paths") or {}).get("frames"),
                  "judge_files": judge_files}
        rep = synthesize_qc_report(cid, "tonight_replay", judges_raw, j6_cand, j6_emit,
                                   probs, thr_cfg, ens_id, thr_sha, inputs, errors)
        ok, errs = validate_report(rep)
        if not ok:
            problems.append({"clip_id": cid, "schema_errors": errs[:5]})
        fp = out_dir / ("%s.json" % cid)
        fp.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
        reports.append((cid, fp, rep, judges_raw, judge_files))
        consumed[cid] = {"detected": rep["verdict"]["defect_detected"],
                         "decision": rep["verdict"]["decision"],
                         "errors": sorted(errors)}

    if args.manifest:
        write_manifest(args.manifest, out_dir, reports, args.thresholds, thr_sha, T)

    # 运行摘要
    n_err = sum(1 for c in consumed.values() if c["errors"])
    print("=== qc_orch_v2 回放摘要 ===")
    print("  clips=%d  报告目录=%s  含降级 errors 的报告=%d  契约校验失败=%d"
          % (len(reports), out_dir, n_err, len(problems)))
    det = [c for c, v in consumed.items() if v["detected"]]
    print("  检出 %d/40  处置分布: %s" % (len(det), _tally([v["decision"] for v in consumed.values()])))
    for p in problems:
        print("  [契约违规]", p["clip_id"], p["schema_errors"])
    if args.manifest:
        print("  manifest ->", args.manifest)
    return 1 if (problems or len(reports) != len(items)) else 0


def _tally(xs):
    out = {}
    for x in xs:
        out[x] = out.get(x, 0) + 1
    return out


# =====================================================================
# manifest 登记（contracts/asset_manifest.schema.json）
# =====================================================================
def write_manifest(manifest_path, out_dir, reports, thr_path, thr_sha, T):
    manifest_path = Path(manifest_path)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    base = manifest_path.parent.resolve()
    prev = {"items": []}
    if manifest_path.exists():
        try:
            prev = load_json(manifest_path)
        except Exception:
            prev = {"items": []}
    kept = [i for i in prev.get("items", []) if (i.get("provenance") or {}).get("module") != "qc_orch"]
    items = list(kept)
    ts = now_iso()

    def rel(p):
        try:
            return os.path.relpath(str(p), base).replace("\\", "/")
        except ValueError:
            return str(p)

    sha_cache = {}
    for cid, fp, rep, judges_raw, judge_files in reports:
        for code, p in sorted(judge_files.items()):
            rp = str(p)
            if rp not in sha_cache:
                try:
                    sha_cache[rp] = (sha256_file(rp), os.path.getsize(rp))
                except OSError:
                    continue
            sha, size = sha_cache[rp]
            items.append({
                "asset_id": "judge:%s:%s" % (code, cid), "kind": "judge_output",
                "path": rel(rp), "sha256": sha, "size_bytes": size, "registered_at": ts,
                "provenance": {"module": "qc_orch", "source": "tonight judges-root"},
                "evidence": {"judge": code,
                             "role": ((T.get("judges") or {}).get(JUDGE_KEYS.get(code, "")) or {}).get("role")}})
        sha, size = sha256_file(fp), fp.stat().st_size
        items.append({
            "asset_id": "qc:%s" % cid, "kind": "qc_report", "path": rel(fp),
            "sha256": sha, "size_bytes": size, "registered_at": ts,
            "provenance": {"module": "qc_orch", "source": "tonight judges-root"},
            "evidence": {"thresholds": str(thr_path), "thresholds_sha256": thr_sha,
                         "ensemble": rep["verdict"]["decided_by"],
                         "detected": rep["verdict"]["defect_detected"],
                         "decision": rep["verdict"]["decision"]}})
    man = {"schema_version": "1.0", "name": prev.get("name", "vpipe-qc-golden-replay"),
           "generated_at": ts, "generator": GENERATOR, "items": items}
    manifest_path.write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")


# =====================================================================
# 在线模式
# =====================================================================
def online(args):
    T = load_thresholds(args.thresholds)
    ens = T["ensemble"]
    ens_id = ens["recommended"]
    ens_def = (ens.get("definitions") or {}).get(ens_id, ens_id)
    jd = (T["judges"])["J3_omnijev"]
    j6 = (T["judges"])["J6_detectors"]
    thr_cfg = {"ensemble_def": ens_def, "j3_thr": jd["thr"],
               "auto_reject_p": jd["auto_reject_p"], "j6_emit_conf": j6["emit_conf"]}
    thr_sha = sha256_file(args.thresholds)

    cid = args.clip_id
    errors, judges_raw, judge_files = {}, {}, {}
    j6_cand, j6_emit, probs = {}, {}, None
    n_frames, dur_s = 0, 0.0

    # ---- L0 确定性预检（拒收层：失败不进 judge，exit 4）----
    l0_result = None
    if args.clip and not args.skip_l0:
        l0_ok, l0_result = l0_preflight(args.clip, T, args.expect_duration, args.profile)
        if not l0_ok:
            out_dir0 = Path(args.out_dir or (HERE.parent / "out" / "qc_reports_online"))
            out_dir0.mkdir(parents=True, exist_ok=True)
            fp0 = out_dir0 / ("%s.l0.json" % cid)
            fp0.write_text(json.dumps(l0_result, ensure_ascii=False, indent=1),
                           encoding="utf-8")
            print("=== L0 拒收（不进 judge） === %s" % cid)
            for f in l0_result["failures"]:
                print("  [L0-FAIL]", f)
            print("  证据 ->", fp0)
            return 4
        print("=== L0 通过 === %s  %s" % (
            cid, json.dumps({k: v for k, v in l0_result["checks"].items()},
                            ensure_ascii=False)))

    if args.detector_json:
        try:
            det = load_json(args.detector_json)
            judge_files["J6"] = str(args.detector_json)
            cm = det.get("clip_meta") or {}
            dur_s = float(cm.get("duration_sec") or 0.0)
            n_frames = len(det.get("color_stats") or []) or int(cm.get("nb_frames") or 8)
            j6_cand, _ = run_j6_rules(det, T, n_frames, dur_s)
            emit = float(j6["emit_conf"])
            j6_emit = {t: c for t, c in j6_cand.items() if c["conf"] >= emit}
            mx = max([c["conf"] for c in j6_cand.values()], default=0.0)
            judges_raw["J6"] = {
                "clip_id": cid, "defect_detected": bool(j6_emit),
                "defect_types": sorted(j6_emit),
                "confidence": round(max((c["conf"] for c in j6_emit.values()), default=1.0 - mx), 4),
                "spans": [{"type": t,
                           **({"start_s": c["span"]["start_s"],
                               "end_s": c["span"]["end_s"]} if c.get("span") else {}),
                           "evidence": c.get("evidence") or {}} for t, c in sorted(j6_emit.items())],
                "notes": "qc_orch_v2 在线规则引擎（emit@%s）" % emit}
        except Exception as e:
            errors["J6"] = "detector-json 失败 (%s: %s)" % (type(e).__name__, e)
    else:
        errors["J6"] = "未提供 --detector-json（检测器弃权）"

    for kv in (args.judge_file or []):
        code, _, p = kv.partition("=")
        try:
            d = load_json(p)
            for k in ("clip_id", "defect_detected", "defect_types", "confidence"):
                if k not in d:
                    raise ValueError("missing %s" % k)
            judges_raw[code.upper()] = d
            judge_files[code.upper()] = str(p)
        except Exception as e:
            errors[code.upper()] = "judge-file 失败 %s (%s: %s)" % (p, type(e).__name__, e)

    for kv in (args.judge_probs or []):
        code, _, p = kv.partition("=")
        code = code.upper()
        try:
            rm = load_json(p)
            pr = None
            if cid in rm:                      # 裸概率 dict
                pr = rm[cid]
            elif isinstance(rm.get("probs"), dict) and rm.get("clip_id") == cid:
                pr = rm["probs"]               # 单片 six-field+probs
            else:
                for c in rm.get("clips", []):  # run_metadata 批格式
                    if c.get("clip_id") == cid and c.get("ok"):
                        pr = c["probs"]
                        break
            if pr is None:
                raise ValueError("找不到 %s 的概率" % cid)
            if code == "J3":
                probs = pr
                judge_files.setdefault("J3", str(p))
                p6 = Path(p).parent / ("%s.json" % cid)
                if p6.exists():
                    judges_raw["J3"] = load_json(p6)
            else:
                judges_raw[code] = {"clip_id": cid, "defect_detected": False,
                                    "defect_types": [], "confidence": None,
                                    "notes": "probs 判官无六字段协议（%s）" % code}
        except Exception as e:
            errors[code] = "judge-probs 失败 %s (%s: %s)" % (p, type(e).__name__, e)
    if probs is None and "J3" not in errors:
        errors["J3"] = "未提供 --judge-probs J3=...（概率通道弃权）"

    inputs = {"clip": str(args.clip) if args.clip else None,
              "frames_dir": None, "judge_files": judge_files}
    qc_context = None
    if args.profile or args.known_cuts_list or l0_result is not None:
        qc_context = {"profile": args.profile, "known_cuts": args.known_cuts_list,
                      "l0_preflight": l0_result}
    rep = synthesize_qc_report(cid, "online", judges_raw, j6_cand, j6_emit, probs,
                               thr_cfg, ens_id, thr_sha, inputs, errors,
                               qc_context=qc_context)
    ok, errs = validate_report(rep)
    out_dir = Path(args.out_dir or (HERE.parent / "out" / "qc_reports_online"))
    out_dir.mkdir(parents=True, exist_ok=True)
    fp = out_dir / ("%s.json" % cid)
    fp.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    print("=== qc_orch_v2 在线报告 === %s  detected=%s decision=%s conf=%s  errors=%s"
          % (fp, rep["verdict"]["defect_detected"], rep["verdict"]["decision"],
             rep["verdict"]["confidence"], sorted(errors)))
    if not ok:
        print("[契约违规]", errs[:5])
        return 1
    return 0


# =====================================================================
def main():
    ap = argparse.ArgumentParser(description="vpipe qc_orch_v2：检测器规则引擎 + judge 合议（E10）")
    ap.add_argument("--from-tonight", action="store_true", help="回放模式（验收路径）")
    ap.add_argument("--online", action="store_true", help="在线模式（生产形态）")
    ap.add_argument("--judges-root", default=None)
    ap.add_argument("--golden", default=str(HERE.parent / "eval" / "golden_manifest.json"))
    ap.add_argument("--thresholds", default=str(HERE.parent / "eval" / "thresholds.yaml"))
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--manifest", default=None)
    ap.add_argument("--clip-id", default=None)
    ap.add_argument("--clip", default=None)
    ap.add_argument("--detector-json", default=None)
    ap.add_argument("--judge-file", action="append", default=[],
                    help="J代码=六字段协议JSON 路径，可重复")
    ap.add_argument("--judge-probs", action="append", default=[],
                    help="J代码=概率源JSON（run_metadata 批格式或单片），可重复")
    ap.add_argument("--expect-duration", type=float, default=None,
                    help="L0 时长检查的期望时长（秒，来自 shot spec / 音频时长）")
    ap.add_argument("--profile", default=None,
                    help="素材 profile（如 avatar_talk）；影响 L0 时长豁免窗，"
                         "并落入报告 qc_context 供追溯")
    ap.add_argument("--known-cuts", dest="known_cuts_file", default=None,
                    help="已知拼接切点 JSON（登记进报告 qc_context.known_cuts；"
                         "检测器侧豁免由 qc_detectors_v2 --known-cuts 消费同一文件）")
    ap.add_argument("--skip-l0", action="store_true", help="跳过 L0 预检（默认提供 --clip 即跑）")
    args = ap.parse_args()
    args.known_cuts_list = []
    if args.known_cuts_file:
        raw = json.loads(Path(args.known_cuts_file).read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            raw = raw.get("cuts") or []
        args.known_cuts_list = sorted(float(e["t"]) if isinstance(e, dict) else float(e)
                                      for e in raw)

    if not (args.from_tonight or args.online):
        ap.error("须指定 --from-tonight 或 --online")
    if args.from_tonight:
        if not args.judges_root:
            ap.error("--from-tonight 需要 --judges-root")
        if not args.out_dir:
            args.out_dir = str(HERE.parent / "out" / "qc_reports_v2")
        return replay(args)
    if not args.clip_id:
        ap.error("--online 需要 --clip-id")
    return online(args)


if __name__ == "__main__":
    sys.exit(main())

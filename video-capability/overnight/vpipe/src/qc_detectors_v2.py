#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
qc_detectors_v2.py — J6 时序规则 v2：基于帧序列分析的四类时序缺陷检测（CPU-only，无 VLM）
=====================================================================================
修复对象（工程方案v3.md §3.2 / judge基准报告.md §11.2）：
  v1 规则在「均匀 8 帧采样」上运行，与注入几何失谐——freeze 零触发、scene_cut 误报 swap、
  ghosting/pixelate 零覆盖、flicker 依赖 spike 簇误判。v2 改为**原生帧率全序列分析**：

    frame_freeze   连续 N 帧帧差低于阈值 且 持续时长 ≥ freeze_min_s（对齐注入参数：定格 2s），
                   并要求冻结段清晰度不塌（排除 tblend/模糊造成的伪静止）。
    flicker        亮度/饱和度序列的**逐帧符号交替**（幅值、频率、持续性三重门槛）。
    temporal_swap  帧相似度矩阵的块状突变：硬切点 + **后向重入**（切点后内容与切点前更早处
                   高相似、且切点前窗对同一匹配区不相似——排除场景切换/内容复现）；
                   单切点超高相似判「子段重复」。
    ghosting       帧间结构拖影（tblend 类混叠）：**矩形帧差凹窗**（窗内帧差中位显著低于
                   窗外、两端有阶跃、窗内无硬切、严格内窗——排除自然变速与场景切换）。

  参数唯一来源：--params-yaml 的 judges.J6_detectors_v2 段（缺省用本文件 DEFAULT_PARAMS，
  与 yaml 同名键覆盖）；置信度映射保证真阳候选 ≥ emit_conf。

  2026-10-01 增量（工程方案v3.1 P0-1，QC 机理回填）：
    * 低运动平台豁免：diff 支凹窗窗内帧差中位 < ghost_plateau_in_max 时恒标注
      low_motion_plateau；仅当 --profile 声明在 ghost_plateau_exempt_profiles 名单内
      （如 avatar_talk=口播数字人）才弃权该候选——金标真混叠（golden_034/028）与
      dh 误报在 in_med 上交叠，绝对阈不可分，豁免必须声明制。
    * known_cuts 白名单：--known-cuts 传入上游拼接切点，junction cut_t 落入
      known_cuts_tol_s 容差内不计入 temporal_swap 证据（同人物 A/B 拼接后向重入是必然）。
    未声明 --profile/--known-cuts 时判定行为与 2026-09-30 版完全一致（已实测回归）。

证据基线（2026-09-30 本机实测，见 overnight/数据/j6_v2/）：
  * 金标 A 类时序 8 条中 5 条注入未生效（017/028 无定格=尾部重复；004/030 无交替=恒定曝光
    偏移；022 与源片逐帧一致）——当晚 QA raw/_aclass_integrity.json 已记 signature_present=false。
    本模块对「注入意图」负责，计分时对无效标签如实报告。
  * C 类 12 条干净片上四规则零误报（FPR 0/12）。

用法:
  单条:  python qc_detectors_v2.py --clip X.mp4 --out X.qc2.json [--params-yaml thresholds.yaml]
  批量:  python qc_detectors_v2.py --batch <clips_dir> --out-dir <dir> [--params-yaml ...]
输出 JSON 顶层键兼容 qc_detectors.py v1 契约（clip_meta/frames/errors/meta），另加：
  temporal_features（帧级特征）、temporal_candidates（全候选+证据）、temporal_protocol
  （{clip_id, defect_detected, defect_types, confidence, spans} —— 与 j6_to_protocol 同构）。
"""
import argparse
import datetime
import json
import math
import os
import sys
import time
from pathlib import Path

import numpy as np

try:
    import cv2
except ImportError as e:  # pragma: no cover
    raise SystemExit("需要 opencv-python: pip install opencv-python") from e

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ---------------------------------------------------------------- 默认参数（金标上调参定稿，round1）
DEFAULT_PARAMS = {
    # 帧特征
    "feat_width": 160,            # 特征抽取降采样宽
    "sim_width": 80,              # 自相似矩阵网格宽
    # frame_freeze
    "freeze_diff_thr": 0.8,       # 帧差绝对阈（≈编码噪声上界，0-255 MAD）
    "freeze_min_s": 2.0,          # 持续时长下限（对齐注入 2s）
    "freeze_lap_guard": 0.75,     # 冻结段 laplacian var ≥ 全片中位×此值（排伪静止）
    # flicker
    "flicker_amp_min": 6.0,       # 亮度交替事件最小幅值（0-255）
    "flicker_sat_amp_min": 0.08,  # 饱和度交替事件最小幅值（0-1）
    "flicker_rate_min": 6.0,      # 交替事件密度（事件/秒）
    "flicker_min_s": 1.0,         # 交替段最短持续
    # temporal_swap
    "cut_abs_min": 15.0,          # 硬切帧差绝对下限
    "cut_rel_k": 3.5,             # 硬切相对阈 ×(±1s 局部中位)
    "reentry_win_s": 0.4,         # 重入窗长
    "reentry_gap_s": 0.5,         # 匹配区与切点的最小时间间隔
    "reentry_margin": 0.05,       # 后窗相似 − 前窗相似 的最小对比度（合成正片证据：慢速场景
                                  # 真接缝 margin≈0.06-0.11，静态场景伪切点 margin≈0）
    "swap_multi_min_cuts": 2,     # 多切点判 swap 所需后向重入切点数
    "swap_multi_back_min": 0.62,  # 多切点模式单切点后向相似下限
    "swap_single_back_min": 0.85, # 单切点「子段重复」后向相似下限
    "swap_span_s": 3.0,           # 多切点允许的最大跨距
    # ghosting
    "ghost_dip_ratio": 0.65,      # 窗内帧差中位 / 窗外中位 上限
    "ghost_out_min": 1.2,         # 窗外帧差中位下限（须有运动可被“减半”）
    "ghost_min_s": 1.2,           # 凹窗最短持续
    "ghost_cut_free": 15.0,       # 凹窗内±0.25s 允许的最大帧差（不许含硬切）
    "ghost_interior_s": 0.5,      # 凹窗两端距片头/片尾的最小距离
    "ghost_boundary_ratio": 1.3,  # 凹窗两端外 0.33s 帧差中位 ≥ 窗内×此值（矩形阶跃）
      "ghost_lap_ratio": 0.85,      # lap 支：窗内 laplacian var 中位 / 窗外 上限（线性运动混 blend→边缘塌陷）
      "ghost_lap_out_min": 300.0,   # lap 支：窗外 laplacian var 下限（须有纹理可被模糊）
      "ghost_lap_boundary": 1.15,   # lap 支：两端阶跃比
      # 低运动平台豁免（工程方案v3.1 §3.4 机理1，2026-10-01）：说话/静台类素材的自然低运动段
      # 会被 rect_dip 误读为 blend 混叠。实测（vpipe/out/j6v2_dh_v3base，9/15 avatar 片误报）：
      # 全部 diff_dip 误报的窗内帧差中位 in_med=0.71-1.64（编码噪声级），但真混叠
      # golden_034 in_med=0.841 / golden_028 in_med=0.001 与误报区间交叠——绝对阈不可分，
      # 豁免必须由上游声明 profile（声明制，未声明时行为与原版完全一致）。
      "ghost_plateau_in_max": 2.0,                       # 窗内帧差中位低于此值 ≈ 低运动平台
      "ghost_plateau_exempt_profiles": ["avatar_talk"],  # 声明 profile 在名单内才豁免该候选
      # known_cuts 白名单（工程方案v3.1 §3.4 机理2，2026-10-01）：拼接切点由上游登记，
      # junction cut_t 落入已知切点 ±tol 不报 temporal_swap（同人物 A/B 拼接后向重入是必然）。
      "known_cuts_tol_s": 0.5,
      # 输出
      "emit_conf": 0.55,            # 候选进入 defect_types 的置信度阈（对齐 thresholds.yaml J6 emit_conf）
}

TEMPORAL_TYPES = ["frame_freeze", "flicker", "temporal_swap", "ghosting"]


def log(msg):
    print(f"[qc2 {datetime.datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def load_params(params_yaml=None, overrides=None):
    p = dict(DEFAULT_PARAMS)
    if params_yaml:
        import yaml
        doc = yaml.safe_load(Path(params_yaml).read_text(encoding="utf-8")) or {}
        sec = ((doc.get("judges") or {}).get("J6_detectors_v2") or {})
        p.update({k: v for k, v in sec.items()})
    if overrides:
        p.update({k: v for k, v in overrides.items()})
    return {k: (float(v) if isinstance(v, (int, float)) else v) for k, v in p.items()}


# =====================================================================
# 帧特征抽取（原生帧率全序列）
# =====================================================================
def read_features(clip_path, P):
    cap = cv2.VideoCapture(str(clip_path))
    if not cap.isOpened():
        raise RuntimeError(f"cv2.VideoCapture 打开失败: {clip_path}")
    fps = float(cap.get(cv2.CAP_PROP_FPS)) or 25.0
    w = int(P["feat_width"])
    gs, luma, sat = [], [], []
    while True:
        ok, f = cap.read()
        if not ok:
            break
        g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)
        h = max(8, int(round(w * g.shape[0] / g.shape[1])))
        gs.append(cv2.resize(g, (w, h)).astype(np.float32))
        luma.append(float(g.mean()))
        s = cv2.cvtColor(f, cv2.COLOR_BGR2HSV)[..., 1]
        sat.append(float(s.mean()) / 255.0)
    cap.release()
    if len(gs) < 8:
        raise RuntimeError(f"可读帧不足: {len(gs)}")
    G = np.stack(gs)
    n = len(G)
    diff = np.abs(G[1:] - G[:-1]).mean(axis=(1, 2))            # 相邻帧 MAD（0-255）
    lap = np.array([float(cv2.Laplacian(f, cv2.CV_32F).var()) for f in G])
    # 相邻帧 Pearson 相关
    F = G.reshape(n, -1)
    Fn = (F - F.mean(1, keepdims=True)) / (F.std(1, keepdims=True) + 1e-6)
    adj = (Fn[1:] * Fn[:-1]).mean(axis=1)
    # 自相似矩阵（Pearson 相关，全帧）
    sw = int(P["sim_width"])
    Gs = np.stack([cv2.resize(f, (sw, max(8, int(round(sw * f.shape[0] / f.shape[1]))))) for f in G])
    Fs = Gs.reshape(n, -1)
    Fn2 = (Fs - Fs.mean(1, keepdims=True)) / (Fs.std(1, keepdims=True) + 1e-6)
    S = (Fn2 @ Fn2.T) / Fs.shape[1]
    return {"fps": fps, "n": n, "dur": n / fps, "diff": diff, "luma": np.array(luma),
            "sat": np.array(sat), "lap": lap, "adj": adj, "S": S}


# =====================================================================
# 规则 1：frame_freeze —— 连续近零帧差段 ≥ freeze_min_s
# =====================================================================
def rule_frame_freeze(X, P, cand):
    d, fps, lap = X["diff"], X["fps"], X["lap"]
    thr = float(P["freeze_diff_thr"]); min_pairs = int(round(float(P["freeze_min_s"]) * fps))
    lap_med = float(np.median(lap))
    best = None
    run = 0
    for i, v in enumerate(d):
        if v < thr:
            run += 1
        else:
            run = 0
        if run >= max(3, min_pairs):                       # 段仍在进行/刚结束都记
            s_i, e_i = i - run + 1, i                       # 帧差对区间 [s_i, e_i]（含）
            lap_seg = float(np.median(lap[s_i:e_i + 2]))
            rec = {"run_pairs": run, "dur_s": round(run / fps, 3),
                   "start_s": round(s_i / fps, 3), "end_s": round((e_i + 1) / fps, 3),
                   "run_diff_med": round(float(np.median(d[s_i:e_i + 1])), 4),
                   "lap_guard": round(lap_seg / max(lap_med, 1e-6), 3)}
            if best is None or rec["dur_s"] > best["dur_s"]:
                best = rec
    if not best:
        return
    if best["lap_guard"] < float(P["freeze_lap_guard"]):    # 模糊造成的伪静止 → 不是定格
        best["rejected_by"] = "lap_guard"
        cand.setdefault("_rejected", {})["frame_freeze"] = best
        return
    conf = 0.55 + 0.25 * min(1.0, (best["dur_s"] - float(P["freeze_min_s"])) / max(float(P["freeze_min_s"]), 1e-6)) \
           + 0.15 * max(0.0, 1.0 - best["run_diff_med"] / max(thr, 1e-6))
    cand["frame_freeze"] = {"conf": round(min(0.95, conf), 3), "kind": "zero_diff_run", **best,
                            "span": [best["start_s"], best["end_s"]]}


# =====================================================================
# 规则 2：flicker —— 亮度/饱和度逐帧符号交替
# =====================================================================
def _alt_runs(x, amp):
    a = np.diff(x)
    ev = (np.abs(a[:-1]) >= amp) & (np.abs(a[1:]) >= amp) & (np.sign(a[:-1]) * np.sign(a[1:]) < 0)
    runs, s = [], None
    for i, v in enumerate(ev):
        if v and s is None:
            s = i
        elif not v and s is not None:
            runs.append((s, i - 1)); s = None
    if s is not None:
        runs.append((s, len(ev) - 1))
    return runs


def rule_flicker(X, P, cand):
    fps, dur = X["fps"], X["dur"]
    min_s = float(P["flicker_min_s"]); rate_min = float(P["flicker_rate_min"])
    best = None
    for ch, x, amp in (("luma", X["luma"], float(P["flicker_amp_min"])),
                       ("sat", X["sat"], float(P["flicker_sat_amp_min"]))):
        for s, e in _alt_runs(x, amp):
            ne = e - s + 1
            seg_s, seg_e = s / fps, (e + 2) / fps
            dur_seg = seg_e - seg_s
            if dur_seg < min_s:
                continue
            rate = ne / max(dur_seg, 1e-6)
            if rate < rate_min:
                continue
            rec = {"channel": ch, "events": ne, "rate_per_s": round(rate, 2),
                   "start_s": round(seg_s, 3), "end_s": round(seg_e, 3), "dur_s": round(dur_seg, 3)}
            if best is None or rec["events"] > best["events"]:
                best = rec
    if not best:
        return
    conf = 0.55 + 0.30 * min(1.0, best["dur_s"] / 2.0) + 0.10 * min(1.0, best["rate_per_s"] / (2 * rate_min))
    cand["flicker"] = {"conf": round(min(0.95, conf), 3), "kind": "sign_alternation", **best,
                       "span": [best["start_s"], best["end_s"]]}


# =====================================================================
# 规则 3：temporal_swap —— 相似度矩阵块状突变（硬切 + 后向重入）
# =====================================================================
def _find_cuts(X, P):
    d, fps = X["diff"], X["fps"]
    k = int(round(1.0 * fps))
    local = np.array([np.median(d[max(0, i - k):i + k + 1]) for i in range(len(d))])
    thr = np.maximum(float(P["cut_abs_min"]), float(P["cut_rel_k"]) * np.maximum(local, 0.5))
    cuts = [i for i in range(1, len(d) - 1) if d[i] > thr[i]]
    merged = []
    for i in cuts:
        if merged and i - merged[-1][-1] <= 2:
            merged[-1].append(i)
        else:
            merged.append([i])
    # 组内元素为绝对索引；取组内帧差最大者为该切点代表
    return [grp[int(np.argmax(d[grp[0]:grp[-1] + 1]))] for grp in merged], thr


def rule_temporal_swap(X, P, cand, known_cuts=None):
    fps, n, d, S = X["fps"], X["n"], X["diff"], X["S"]
    L = max(4, int(round(float(P["reentry_win_s"]) * fps)))
    gap = float(P["reentry_gap_s"]); margin_min = float(P["reentry_margin"])
    cuts, thr = _find_cuts(X, P)
    evs = []
    for i in cuts:
        if i + 1 + L >= n or i + 1 - L < 0:
            continue
        post = np.arange(i + 1, i + 1 + L)
        pre = np.arange(i - L + 1, i + 1)
        j_max = i + 1 - int(round(gap * fps)) - L            # 匹配窗须整体早于切点 gap 秒
        best = None
        for a in range(0, max(0, j_max)):
            sc = float(S[np.ix_(post, np.arange(a, a + L))].mean())
            if best is None or sc > best[0]:
                best = (sc, a)
        if best is None:
            continue
        sc_back, a = best
        sc_pre = float(S[np.ix_(pre, np.arange(a, a + L))].mean())
        evs.append({"cut_t": round((i + 1) / fps, 3), "diff": round(float(d[i]), 2),
                    "back_score": round(sc_back, 4), "match_t": round(a / fps, 3),
                    "pre_score": round(sc_pre, 4), "margin": round(sc_back - sc_pre, 4)})
    # known_cuts 白名单（§3.4 机理2）：上游登记的拼接切点，junction 落入 ±tol 一律不计入
    # swap 证据（同人物 A/B 拼接的后向重入是结构性必然，非缺陷）。未声明时行为不变。
    if known_cuts:
        tol = float(P.get("known_cuts_tol_s", 0.5) or 0.0)

        def _at_known_cut(e):
            return min((abs(e["cut_t"] - float(k)) for k in known_cuts), default=1e9) <= tol

        dropped = [e for e in evs if _at_known_cut(e)]
        if dropped:
            cand.setdefault("_rejected", {})["temporal_swap_known_cuts"] = {
                "reason": "known_cuts_whitelist", "tol_s": tol,
                "cutlist": sorted(float(k) for k in known_cuts),
                "exempted_junctions": dropped}
            evs = [e for e in evs if not _at_known_cut(e)]
    strong = [e for e in evs if e["margin"] >= margin_min]
    hit = None
    multi = [e for e in strong if e["back_score"] >= float(P["swap_multi_back_min"])]
    if len(multi) >= int(P["swap_multi_min_cuts"]) and \
            (multi[-1]["cut_t"] - multi[0]["cut_t"]) <= float(P["swap_span_s"]):
        mm = sum(e["margin"] for e in multi) / len(multi)
        conf = 0.60 + 0.12 * min(2, len(multi) - int(P["swap_multi_min_cuts"])) + 0.15 * min(1.0, mm / 0.20)
        hit = {"kind": "cuts_backward_reentry", "conf": round(min(0.95, conf), 3),
               "junctions": multi, "span": [multi[0]["cut_t"], multi[-1]["cut_t"]]}
    else:
        singles = [e for e in strong if e["back_score"] >= float(P["swap_single_back_min"])]
        if singles:
            e = max(singles, key=lambda x: x["back_score"])
            conf = 0.55 + 0.20 * min(1.0, (e["back_score"] - float(P["swap_single_back_min"])) / 0.15)
            hit = {"kind": "single_cut_repeat", "conf": round(min(0.90, conf), 3),
                   "junctions": [e], "span": [e["cut_t"], e["cut_t"]]}
    if hit:
        cand["temporal_swap"] = hit
    elif evs:
        cand.setdefault("_rejected", {})["temporal_swap"] = {
            "reason": "no_qualified_reentry", "evidence": evs}


# =====================================================================
# 规则 4：ghosting —— 矩形凹窗（tblend 类混叠）：帧差凹窗 ∨ 清晰度凹窗
#   · diff 支：窗内帧差中位显著低于窗外（步进/振荡运动被混合平均→帧差减半，如 LTX 源）
#   · lap 支：窗内 Laplacian 方差矩形塌陷（线性运动混合→边缘模糊，帧差可不变）
# =====================================================================
def _rect_dips(series, fps, P, dip_ratio_key, out_min_key, boundary_key):
    """在 series 上找矩形凹窗：返回最长合格窗记录或 None。"""
    W = max(4, int(round(1.0 * fps)))
    step = max(1, W // 4)
    dip_ratio = float(P[dip_ratio_key]); out_min = float(P[out_min_key])
    keep = []
    for s in range(0, len(series) - W + 1, step):
        e = s + W
        lo, hi = max(0, s - W), min(len(series), e + W)
        outside = np.concatenate([series[lo:s], series[hi:hi + W]])
        if len(outside) < 5:
            continue
        om = float(np.median(outside))
        if om < out_min:
            continue
        wm = float(np.median(series[s:e]))
        if wm <= dip_ratio * om:
            keep.append((s, e, wm, om))
    if not keep:
        return None
    runs = []
    for s, e, wm, om in keep:
        if runs and s <= runs[-1][1]:
            runs[-1][1] = max(runs[-1][1], e)
            runs[-1][2].append((s, e, wm, om))
        else:
            runs.append([s, e, [(s, e, wm, om)]])
    best = None
    for s, e, parts in runs:
        lo_bound, hi_bound = s, e
        while lo_bound > 0 and series[lo_bound - 1] <= dip_ratio * parts[0][3]:
            lo_bound -= 1
        while hi_bound < len(series) and series[hi_bound] <= dip_ratio * parts[0][3]:
            hi_bound += 1
        dur_seg = (hi_bound - lo_bound) / fps
        if dur_seg < float(P["ghost_min_s"]):
            continue
        if lo_bound / fps < float(P["ghost_interior_s"]) or \
                (len(series) - hi_bound) / fps < float(P["ghost_interior_s"]):
            continue                                        # 严格内窗（片头/尾自然减速排除）
        om = parts[0][3]
        wm = float(np.median(series[lo_bound:hi_bound]))
        w = int(round(0.33 * fps))
        pre_m = float(np.median(series[max(0, lo_bound - w):lo_bound])) if lo_bound > 0 else 0.0
        post_m = float(np.median(series[hi_bound: min(len(series), hi_bound + w)])) if hi_bound < len(series) else 0.0
        if min(pre_m, post_m) < float(P[boundary_key]) * max(wm, 1e-6):
            continue                                        # 两端须有阶跃（矩形性）
        rec = {"start_s": round(lo_bound / fps, 3), "end_s": round(hi_bound / fps, 3),
               "dur_s": round(dur_seg, 3), "dip_ratio": round(wm / om, 3),
               "out_med": round(om, 3), "in_med": round(wm, 3),
               "boundary_ratio": round(min(pre_m, post_m) / max(wm, 1e-6), 2)}
        if best is None or rec["dur_s"] > best["dur_s"]:
            best = rec
    return best


def rule_ghosting(X, P, cand, profile=None):
    fps, d, lap = X["fps"], X["diff"], X["lap"]
    cut_thr = float(P["ghost_cut_free"]); m = int(round(0.25 * fps))
    recs = []
    bd = _rect_dips(d, fps, P, "ghost_dip_ratio", "ghost_out_min", "ghost_boundary_ratio")
    if bd:
        near = d[max(0, int(bd["start_s"] * fps) - m): min(len(d), int(bd["end_s"] * fps) + m)]
        if float(near.max()) <= cut_thr:                    # 凹窗±0.25s 内无硬切
            bd["branch"] = "diff_dip"
            recs.append(bd)
    bl = _rect_dips(lap, fps, P, "ghost_lap_ratio", "ghost_lap_out_min", "ghost_lap_boundary")
    if bl:
        near = d[max(0, int(bl["start_s"] * fps) - m): min(len(d), int(bl["end_s"] * fps) + m)]
        if float(near.max()) <= cut_thr:
            bl["branch"] = "lap_dip"
            recs.append(bl)
    if not recs:
        return
    best = max(recs, key=lambda r: r["dur_s"])
    # 低运动平台标注与豁免（§3.4 机理1）：diff 支窗内帧差中位低于 plateau 阈 = 编码噪声级残余
    # 运动（口播停顿/静台的自然低运动段），恒标注 low_motion_plateau 供人审；仅当上游声明
    # profile 且在豁免名单内才弃权该候选（声明制——金标 034/028 的真混叠同样低 in_med，
    # 绝对阈不可分，未声明 profile 时行为与原版完全一致）。
    plateau = (best["branch"] == "diff_dip"
               and float(best["in_med"]) < float(P["ghost_plateau_in_max"]))
    best["low_motion_plateau"] = plateau
    if plateau and profile:
        exempt = [str(x) for x in (P.get("ghost_plateau_exempt_profiles") or [])]
        if str(profile) in exempt:
            best["rejected_by"] = "low_motion_plateau(profile=%s, in_med=%s < %s)" % (
                profile, best["in_med"], P["ghost_plateau_in_max"])
            cand.setdefault("_rejected", {})["ghosting"] = best
            return
    dip_ratio = float(P["ghost_dip_ratio"]) if best["branch"] == "diff_dip" \
        else float(P["ghost_lap_ratio"])
    conf = 0.55 + 0.25 * min(1.0, (best["dur_s"] - float(P["ghost_min_s"])) / max(float(P["ghost_min_s"]), 1e-6)) \
           + 0.15 * max(0.0, (dip_ratio - best["dip_ratio"]) / max(dip_ratio, 1e-6))
    cand["ghosting"] = {"conf": round(min(0.95, conf), 3), "kind": "rect_dip_blend", **best,
                        "span": [best["start_s"], best["end_s"]]}


# =====================================================================
# 主分析
# =====================================================================
def analyze_clip(clip_path, P, known_cuts=None, profile=None):
    t0 = time.time()
    X = read_features(clip_path, P)
    cand = {}
    rule_frame_freeze(X, P, cand)
    rule_flicker(X, P, cand)
    rule_temporal_swap(X, P, cand, known_cuts=known_cuts)
    rule_ghosting(X, P, cand, profile=profile)
    rejected = cand.pop("_rejected", {})
    emit = float(P["emit_conf"])
    emitted = {t: ev for t, ev in cand.items() if ev.get("conf", 0) >= emit}
    detected = bool(emitted)
    confidence = round(max((ev["conf"] for ev in emitted.values()), default=0.0), 3)
    proto = {"clip_id": Path(clip_path).stem,
             "defect_detected": detected,
             "defect_types": sorted(emitted, key=lambda t: -emitted[t]["conf"]),
             "confidence": confidence if detected else round(1.0 - max((ev["conf"] for ev in cand.values()), default=0.0), 3),
             "spans": [{"type": t, "start_s": ev["span"][0], "end_s": ev["span"][1],
                        "evidence": {k: v for k, v in ev.items() if k not in ("conf", "span")}}
                       for t, ev in emitted.items()]}
    out = {
        "clip": str(Path(clip_path).resolve()),
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "detector": "qc_detectors_v2.py temporal rules (frame-sequence, CPU-only, no VLM)",
        "clip_meta": {"duration_sec": round(X["dur"], 3), "fps": round(X["fps"], 3),
                      "n_frames": X["n"], "width": int(P["feat_width"])},
        "qc_context": {"profile": profile, "known_cuts": sorted(float(k) for k in known_cuts) if known_cuts else []},
        "temporal_candidates": cand,
        "temporal_rejected": rejected,
        "temporal_protocol": proto,
        "params": {k: v for k, v in P.items()},
        "errors": {},
        "meta": {"analyze_sec": round(time.time() - t0, 2)},
    }
    return out


def main():
    ap = argparse.ArgumentParser(description="J6 时序规则 v2（帧序列分析，CPU-only）")
    ap.add_argument("--clip", help="单条 clip 路径")
    ap.add_argument("--out", help="单条输出 JSON")
    ap.add_argument("--batch", help="批量模式：clips 目录")
    ap.add_argument("--out-dir", help="批量输出目录")
    ap.add_argument("--params-yaml", help="thresholds.yaml（读 judges.J6_detectors_v2 段，可选）")
    ap.add_argument("--set", action="append", default=[], help="参数覆盖 k=v，可多次")
    ap.add_argument("--profile", default=None,
                    help="上游声明的素材 profile（如 avatar_talk=口播数字人）；"
                         "在 ghost_plateau_exempt_profiles 名单内时低运动平台 ghost 候选豁免")
    ap.add_argument("--known-cuts", default=None,
                    help="已知拼接切点 JSON：数字数组或 [{\"t\": 秒, ...}]（temporal_swap 白名单）")
    args = ap.parse_args()
    ov = {}
    for kv in args.set:
        k, _, v = kv.partition("=")
        try:
            ov[k] = float(v)
        except ValueError:
            ov[k] = v
    P = load_params(args.params_yaml, ov)
    known_cuts = None
    if args.known_cuts:
        raw = json.loads(Path(args.known_cuts).read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            raw = raw.get("cuts") or []
        known_cuts = [float(e["t"]) if isinstance(e, dict) else float(e) for e in raw]
    if args.batch:
        if not args.out_dir:
            ap.error("--batch 需要 --out-dir")
        outd = Path(args.out_dir); outd.mkdir(parents=True, exist_ok=True)
        clips = sorted(Path(args.batch).glob("*.mp4"))
        summary = {"judge": "J6 时序规则 v2", "generated_by": "qc_detectors_v2.py",
                   "params": P,
                   "qc_context": {"profile": args.profile, "known_cuts": known_cuts or []},
                   "per_clip": {}}
        for c in clips:
            try:
                r = analyze_clip(c, P, known_cuts=known_cuts, profile=args.profile)
                (outd / f"{c.stem}.qc2.json").write_text(
                    json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
                summary["per_clip"][c.stem] = r["temporal_protocol"]
                log(f"{c.stem}: detected={r['temporal_protocol']['defect_detected']} "
                    f"types={r['temporal_protocol']['defect_types']}")
            except Exception as e:  # noqa: BLE001
                summary["per_clip"][c.stem] = {"ERROR": f"{type(e).__name__}: {e}"}
                log(f"{c.stem}: ERROR {e}")
        (outd / "_j6_v2_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
        nd = sum(1 for v in summary["per_clip"].values() if v.get("defect_detected"))
        log(f"batch done: {len(clips)} clips, detected={nd} → {outd}")
        return 0
    if args.clip:
        r = analyze_clip(args.clip, P, known_cuts=known_cuts, profile=args.profile)
        out = args.out or (Path(args.clip).stem + ".qc2.json")
        Path(out).write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
        log(f"WROTE {out} detected={r['temporal_protocol']['defect_detected']} "
            f"types={r['temporal_protocol']['defect_types']}")
        return 0
    ap.error("需要 --clip 或 --batch")


if __name__ == "__main__":
    sys.exit(main())

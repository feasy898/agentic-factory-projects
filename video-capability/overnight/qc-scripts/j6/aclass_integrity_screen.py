#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
aclass_integrity_screen.py — 金标集 A 类注入完整性筛查（数据集 QA，非盲测判定）

目的: 验证 /data/night/golden/clips/*.mp4 的像素内容是否真的包含 manifest 所标的
注入缺陷。起因: J6 批跑前 sanity 发现 golden_028（标 frame_freeze）整片密集采样
无任何平坦区 → inject_defects.py 的 tpad 克隆段疑似未生效。

方法: 每条 A 类 clip 以 10fps 抽 160x120 帧，在 manifest 注入窗口内/外分别统计:
  freeze:       最长"近零帧差"(<1.5)连跑时长(秒)
  flicker:      窗口内亮度交替幅度(相邻采样帧符号交替的 |Δluma| 中位数)
  color_shift:  窗口内 0.5s 间隔圆形色相差最大值
  blur/pixelate/ghost: 窗口内/外 Laplacian 方差比(锐度塌陷)
  temporal_swap: 最大相邻帧差(硬切)与窗口内 >mean+4σ 尖峰数
  garble:       委托 J6 OCR 维度，本脚本不做
输出: /data/night/results/j6/_aclass_integrity.json
本脚本只服务数据集质量报告；J6 盲测协议输出与本脚本无关。
"""
import json
import subprocess
import tempfile
from pathlib import Path

import cv2
import numpy as np

MANIFEST = Path("/data/night/golden/manifest.json")
OUT = Path("/data/night/results/j6/_aclass_integrity.json")
FPS = 10
SIZE = (160, 120)


def extract(clip: str):
    tmp = tempfile.mkdtemp(prefix="ais_", dir="/data/night/tmp")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", clip,
                    "-vf", f"fps={FPS},scale={SIZE[0]}:{SIZE[1]}",
                    "-q:v", "3", f"{tmp}/f%04d.jpg"], check=True)
    files = sorted(Path(tmp).glob("f*.jpg"))
    frames = []
    for f in files:
        img = cv2.imread(str(f))
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        h = hsv[..., 0].astype(np.float32) * 2.0
        s = hsv[..., 1].astype(np.float32) / 255.0
        w = np.clip(s - 0.15, 0, None)
        if w.sum() > 1e-6:
            ang = np.deg2rad(h)
            mh = float(np.rad2deg(np.arctan2((np.sin(ang) * w).sum(),
                                             (np.cos(ang) * w).sum())) % 360.0)
        else:
            mh = None
        frames.append({
            "luma": float(gray.mean()),
            "sat": float(s.mean()),
            "hue": mh,
            "hw": float(w.mean()),
            "lap": float(cv2.Laplacian(gray, cv2.CV_64F).var()),
            "g": cv2.resize(gray, SIZE).astype(np.float32),
        })
    return frames


def circ(a, b):
    if a is None or b is None:
        return None
    d = abs(a - b) % 360.0
    return min(d, 360.0 - d)


def diff(a, b):
    return float(np.abs(a["g"] - b["g"]).mean())


def screen_clip(item):
    clip = Path(item["paths"]["clip"])
    if not clip.is_absolute():
        clip = Path("/data/night/golden") / clip
    frames = extract(str(clip))
    n = len(frames)
    dt = 1.0 / FPS
    pos = item.get("inject_pos") or {}
    w0, w1 = float(pos.get("start_s", -1)), float(pos.get("end_s", -1))
    idx_in = [i for i in range(n) if w0 - 1e-3 <= i * dt <= w1 + 1e-3]
    idx_out = [i for i in range(n) if i not in set(idx_in)]
    diffs = [diff(frames[i], frames[i + 1]) for i in range(n - 1)]
    res = {"clip_id": item["clip_id"], "expected": item["defect_type"],
           "window": [w0, w1], "n_frames": n, "in_idx": idx_in}

    # freeze: 最长近零连跑
    run = best = 0.0
    for d in diffs:
        run = run + dt if d < 1.5 else 0.0
        best = max(best, run)
    res["freeze_longest_flat_s"] = round(best, 2)

    # flicker: 交替亮度幅度
    luma = [f["luma"] for f in frames]
    alts = []
    for i in range(n - 2):
        d1, d2 = luma[i + 1] - luma[i], luma[i + 2] - luma[i + 1]
        if d1 * d2 < 0 and i + 1 in idx_in and i + 2 in idx_in:
            alts.append(min(abs(d1), abs(d2)))
    res["flicker_alt_median"] = round(float(np.median(alts)), 2) if alts else 0.0

    # color_shift: 窗口内色相跳变(0.4s 间隔)
    dh_in = dh_out = 0.0
    for i in range(n - 4):
        dh = circ(frames[i]["hue"], frames[i + 4]["hue"])
        if dh is None or min(frames[i]["hw"], frames[i + 4]["hw"]) < 0.05:
            continue
        if i in idx_in and i + 4 in idx_in:
            dh_in = max(dh_in, dh)
        elif i not in idx_in and i + 4 not in idx_in:
            dh_out = max(dh_out, dh)
    res["hue_jump_in_deg"] = round(dh_in, 1)
    res["hue_jump_out_deg"] = round(dh_out, 1)

    # 锐度塌陷 (face_blur / pixelate / ghosting)
    lap_in = [frames[i]["lap"] for i in idx_in] or [0.0]
    lap_out = [frames[i]["lap"] for i in idx_out] or [1.0]
    res["lap_in_median"] = round(float(np.median(lap_in)), 1)
    res["lap_out_median"] = round(float(np.median(lap_out)), 1)
    res["lap_ratio_in_out"] = round(float(np.median(lap_in)) / max(1e-6, float(np.median(lap_out))), 3)

    # temporal_swap: 硬切
    mu = float(np.mean(diffs)); sd = float(np.std(diffs))
    res["max_adj_diff"] = round(max(diffs), 2) if diffs else 0.0
    res["spikes_gt_mu4sd"] = sum(1 for d in diffs if d > mu + 4 * sd)
    res["diffs"] = [round(d, 2) for d in diffs]
    return res


def verdict(res):
    e = res["expected"]
    if e == "frame_freeze":
        return res["freeze_longest_flat_s"] >= 1.0
    if e == "flicker":
        return res["flicker_alt_median"] >= 8.0
    if e == "color_shift":
        return res["hue_jump_in_deg"] >= 30.0 and res["hue_jump_in_deg"] > res["hue_jump_out_deg"] + 10
    if e in ("face_blur", "pixelate", "ghosting"):
        return res["lap_ratio_in_out"] <= 0.75
    if e == "temporal_swap":
        return res["spikes_gt_mu4sd"] >= 1 or res["max_adj_diff"] >= 40
    if e == "garble_text":
        return None  # 委托 J6 OCR
    return None


def main():
    man = json.loads(MANIFEST.read_text(encoding="utf-8"))
    items = [it for it in man["items"] if it.get("class") == "A"]
    out = {"purpose": "金标 A 类注入完整性筛查（数据集 QA）",
           "fps": FPS, "size": SIZE, "clips": []}
    for it in items:
        try:
            r = screen_clip(it)
            r["signature_present"] = verdict(r)
            out["clips"].append(r)
            print(f"{r['clip_id']} {r['expected']:>14} present={r['signature_present']} "
                  f"flat={r['freeze_longest_flat_s']} alt={r['flicker_alt_median']} "
                  f"hue_in={r['hue_jump_in_deg']} lap_r={r['lap_ratio_in_out']} "
                  f"maxd={r['max_adj_diff']}", flush=True)
        except Exception as e:  # noqa: BLE001
            out["clips"].append({"clip_id": it["clip_id"], "ERROR": f"{type(e).__name__}: {e}"})
            print(f"{it['clip_id']} ERROR {e}", flush=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"WROTE {OUT}")


if __name__ == "__main__":
    main()

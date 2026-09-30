#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
aclass_screen2.py — A 类注入二遍靶向核查（只查一遍筛查有疑问的签名）

对每条 clip 用原生帧率抽 320 宽帧，按窗口内/外对比计算:
  flicker      : 窗口内相邻帧 |Δluma|>15 且符号交替的对数
  color_shift  : 窗口外圆形均值色相 vs 窗口内 的差(度)
  temporal_swap: 窗口内最大相邻帧差；帧灰度std<8 判 blank
  pixelate     : 中央1/3裁剪区 相邻帧差 in/out 比（像素化后纹理变化坍缩）
  ghosting     : 全帧相邻帧差 in/out 比（blend 后 ~0.5）
输出: /data/night/results/j6/_aclass_screen2.json
"""
import json
import subprocess
import tempfile
from pathlib import Path

import cv2
import numpy as np

MANIFEST = Path("/data/night/golden/manifest.json")
OUT = Path("/data/night/results/j6/_aclass_screen2.json")
TARGET = {"golden_030", "golden_004", "golden_018", "golden_016",
          "golden_003", "golden_008", "golden_012", "golden_023",
          "golden_022", "golden_034"}


def extract(clip, fps):
    tmp = tempfile.mkdtemp(prefix="as2_", dir="/data/night/tmp")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", clip,
                    "-vf", f"fps={fps},scale=320:-2", "-q:v", "3",
                    f"{tmp}/f%04d.jpg"], check=True)
    out = []
    for f in sorted(Path(tmp).glob("f*.jpg")):
        img = cv2.imread(str(f))
        H, W = img.shape[:2]
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        h = hsv[..., 0].astype(np.float32) * 2.0
        s = hsv[..., 1].astype(np.float32) / 255.0
        w = np.clip(s - 0.15, 0, None)
        mh = None
        if w.sum() > 1e-6:
            ang = np.deg2rad(h)
            mh = float(np.rad2deg(np.arctan2(float((np.sin(ang) * w).sum()),
                                             float((np.cos(ang) * w).sum()))) % 360.0)
        cx0, cx1 = W // 3, 2 * W // 3
        cy0, cy1 = H // 3, 2 * H // 3
        out.append({"luma": float(gray.mean()), "hue": mh, "hw": float(w.mean()),
                    "gray_std": float(gray.std()),
                    "g": gray.astype(np.float32),
                    "c": gray[cy0:cy1, cx0:cx1].astype(np.float32)})
    return out


def circ_mean(deg_list):
    if not deg_list:
        return None
    ang = [math_r(d) for d in deg_list]
    x = sum(np.cos(a) for a in ang) / len(ang)
    y = sum(np.sin(a) for a in ang) / len(ang)
    return float(np.rad2deg(np.arctan2(y, x)) % 360.0)


def math_r(d):
    return np.deg2rad(d)


def circ_dist(a, b):
    if a is None or b is None:
        return None
    d = abs(a - b) % 360.0
    return min(d, 360.0 - d)


def run(item):
    pos = item.get("inject_pos") or {}
    w0, w1 = float(pos.get("start_s", -1)), float(pos.get("end_s", -1))
    fps = int(round(float(item["verify"]["fps"]))) or 25
    clip = Path(item["paths"]["clip"])
    if not clip.is_absolute():
        clip = Path("/data/night/golden") / clip
    fr = extract(str(clip), fps)
    n = len(fr)
    dt = 1.0 / fps
    idx_in = [i for i in range(n) if w0 <= i * dt <= w1]
    idx_out = [i for i in range(n) if i * dt < w0 - 0.2 or i * dt > w1 + 0.2]
    inS = set(idx_in)
    res = {"clip_id": item["clip_id"], "expected": item["defect_type"],
           "fps": fps, "n_frames": n, "n_in": len(idx_in)}
    diffs = [float(np.abs(fr[i]["g"] - fr[i + 1]["g"]).mean()) for i in range(n - 1)]
    cdiffs = [float(np.abs(fr[i]["c"] - fr[i + 1]["c"]).mean()) for i in range(n - 1)]

    e = item["defect_type"]
    if e == "flicker":
        alts = 0
        for i in range(n - 2):
            if i + 1 in inS and i + 2 in inS:
                d1 = fr[i + 1]["luma"] - fr[i]["luma"]
                d2 = fr[i + 2]["luma"] - fr[i + 1]["luma"]
                if d1 * d2 < 0 and min(abs(d1), abs(d2)) > 15:
                    alts += 1
        res["flicker_alt_pairs"] = alts
        res["verdict"] = alts >= 5
    elif e == "color_shift":
        hues_in = [f["hue"] for i, f in enumerate(fr) if i in inS and f["hw"] > 0.05]
        hues_out = [f["hue"] for i, f in enumerate(fr) if i not in inS and f["hw"] > 0.05]
        d = circ_dist(circ_mean(hues_out), circ_mean(hues_in))
        res["hue_out_mean"] = None if d is None else round(circ_mean(hues_out), 1)
        res["hue_in_mean"] = None if d is None else round(circ_mean(hues_in), 1)
        res["hue_out_in_delta"] = None if d is None else round(d, 1)
        res["verdict"] = (d is not None and d >= 30.0)
    elif e == "temporal_swap":
        in_d = [diffs[i] for i in range(n - 1) if i in inS or i + 1 in inS]
        blanks = [round(i * dt, 2) for i in idx_in if fr[i]["gray_std"] < 8]
        res["max_diff_in"] = round(max(in_d), 2) if in_d else 0.0
        res["blank_frames_in"] = blanks
        res["n_blank_in"] = len(blanks)
        res["verdict"] = None  # 金标语义="两段互换"→应见硬切或空白段，由人工核
    elif e == "pixelate":
        cin = [cdiffs[i] for i in range(n - 1) if i in inS and (i + 1) in inS]
        cout = [cdiffs[i] for i in range(n - 1) if i not in inS and (i + 1) not in inS]
        mi = float(np.median(cin)) if cin else -1.0
        mo = float(np.median(cdiffs)) if cdiffs else -1.0
        res["center_diff_in_median"] = round(mi, 3)
        res["center_diff_out_median"] = round(mo, 3)
        res["ratio"] = round(mi / mo, 3) if mi >= 0 and mo > 0 else None
        res["verdict"] = (res["ratio"] is not None and res["ratio"] < 0.6)
    elif e == "ghosting":
        din = [diffs[i] for i in range(n - 1) if i in inS and (i + 1) in inS]
        dout = [diffs[i] for i in range(n - 1) if i not in inS and (i + 1) not in inS]
        mi = float(np.median(din)) if din else -1.0
        mo = float(np.median(dout)) if dout else -1.0
        res["diff_in_median"] = round(mi, 3)
        res["diff_out_median"] = round(mo, 3)
        res["ratio"] = round(mi / mo, 3) if mi >= 0 and mo > 0 else None
        res["verdict"] = (res["ratio"] is not None and res["ratio"] < 0.75)
    else:
        res["verdict"] = None
    return res


def main():
    man = json.loads(MANIFEST.read_text(encoding="utf-8"))
    items = [it for it in man["items"] if it["clip_id"] in TARGET]
    out = {"purpose": "A 类注入二遍靶向核查", "clips": []}
    for it in items:
        try:
            r = run(it)
            out["clips"].append(r)
            print(json.dumps(r, ensure_ascii=False), flush=True)
        except Exception as ex:  # noqa: BLE001
            out["clips"].append({"clip_id": it["clip_id"], "ERROR": f"{type(ex).__name__}: {ex}"})
            print(f"{it['clip_id']} ERROR {ex}", flush=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"WROTE {OUT}")


if __name__ == "__main__":
    main()

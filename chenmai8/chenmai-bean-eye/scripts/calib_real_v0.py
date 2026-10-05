# -*- coding: utf-8 -*-
"""真实豆首次尺寸标定（一次性分析，产物只含数字不入库）

方法：身份证长边 85.6mm 作比例尺 → 每张分照：检测证件矩形主边(px) 得 px/mm；
     Otsu 分割白底上的豆粒 → 等效直径(px) → mm → 按档位统计分布。
输出：逐张明细 + 三档 summary（均值/中位/min/max），stdout 汇总。
"""
from __future__ import annotations

import glob
import os
import re
from collections import defaultdict

import cv2
import numpy as np

ROOT = os.path.join(os.path.dirname(__file__), "..", "data", "datasets", "hn_robusta", "v0.1", "raw_quark")
CARD_LONG_MM = 85.6
CARD_SHORT_MM = 54.0

def scale_from_card(img):
    """检测身份证（画面里最大的深色矩形）→ 返回 px/mm 或 None。"""
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    g = cv2.GaussianBlur(g, (5, 5), 0)
    # 证件+豆都比白纸暗：整体 Otsu 取暗前景
    _, fg = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(fg)
    best = None
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if area < img.shape[0] * img.shape[1] * 0.005:
            continue
        if best is None or area > best[2]:
            best = (x, y, area, w, h)
    if best is None:
        return None
    x, y, area, w, h = best
    comp = (lab[y:y + h, x:x + w] == (np.argmax(np.bincount(lab[y:y + h, x:x + w].ravel(), minlength=n)) // 1)).astype(np.uint8)
    # 以该连通域实际像素做最小外接矩形（允许旋转）
    ys, xs = np.where(lab[y:y + h, x:x + w] == lab[y + h // 2, x + w // 2])
    pts = np.column_stack([xs, ys]).astype(np.float32)
    rect = cv2.minAreaRect(pts)
    (cx, cy), (rw, rh), ang = rect
    long_px, short_px = max(rw, rh), min(rw, rh)
    # 证件长宽比应接近 85.6/54≈1.585；分照中证件可能出画——出画时比例失真则放弃该张比例尺，
    # 改用全组比例尺中位数（同机同距拍摄，差异极小）
    ratio = long_px / max(short_px, 1.0)
    return long_px / CARD_LONG_MM, short_px / CARD_SHORT_MM, ratio

def bean_diameters_mm(img, px_per_mm):
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    g = cv2.GaussianBlur(g, (5, 5), 0)
    _, fg = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(fg)
    out = []
    himg, wimg = img.shape[:2]
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        # 豆粒尺寸过滤：真实豆 ~10-20mm；面积占比与边框贴边（证件/出画元素）排除
        if x <= 2 or y <= 2 or x + w >= wimg - 2 or y + h >= himg - 2:
            continue
        if area < (3 * px_per_mm) ** 2 or area > (40 * px_per_mm) ** 2:
            continue
        d_px = 2 * np.sqrt(area / np.pi)
        out.append(d_px / px_per_mm)
    return sorted(out)

def main():
    files = sorted(glob.glob(os.path.join(ROOT, "*.jpg")))
    scales, per_img = [], []
    for f in files:
        img = cv2.imdecode(np.fromfile(f, dtype=np.uint8), cv2.IMREAD_REDUCED_COLOR_2)  # 1/2 采样足够
        s = scale_from_card(img)
        if s:
            scales.append((os.path.basename(f), s))
    # 比例尺合理性：长短边各自换算的 px/mm 应一致；取两者均值，异常者剔除后取中位数
    vals = []
    for name, (s1, s2, ratio) in scales:
        if 1.35 < ratio < 1.85:  # 证件完整在画内（85.6/54=1.585 允许透视误差）
            vals.append((s1 + s2) / 2)
    px_mm = float(np.median(vals)) if vals else float(np.median([(a + b) / 2 for _, (a, b, _) in scales]))
    print("比例尺：有效证件 %d/%d 张，px/mm 中位 = %.2f（1/2 采样后）" % (len(vals), len(files), px_mm))

    groups = defaultdict(list)
    for f in files:
        m = re.match(r"([大中小坏])（(\d)）", os.path.basename(f))
        if not m:
            continue
        img = cv2.imdecode(np.fromfile(f, dtype=np.uint8), cv2.IMREAD_REDUCED_COLOR_2)
        ds = bean_diameters_mm(img, px_mm)
        for d in ds:
            groups[m.group(1)].append(d)
        per_img.append((os.path.basename(f), [round(d, 2) for d in ds]))
    for name, ds in per_img:
        print("  %s -> %s mm" % (name, ds))
    print("\n=== 三档+坏豆 等效直径分布（mm）===")
    for k in ["大", "中", "小", "坏"]:
        ds = groups.get(k, [])
        if not ds:
            continue
        print("%s: n=%d 均值=%.1f 中位=%.1f min=%.1f max=%.1f" % (
            k, len(ds), float(np.mean(ds)), float(np.median(ds)), float(np.min(ds)), float(np.max(ds))))
    print("\n参考：screen 13=5.00mm 14=5.60 15=6.00 16=6.30 17=6.70 18=7.10（ICO口径）")

if __name__ == "__main__":
    main()

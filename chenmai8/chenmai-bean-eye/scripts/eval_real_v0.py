# -*- coding: utf-8 -*-
"""真实豆照片首测（一次性分析）：26 张夸克实拍 → 分割 → ONNX 分类 → 按堆聚合。

真值口径（用户分堆）：大/中/小 = 正常豆（按尺寸分档）；坏 = 缺陷豆。
可评估：
  1) 正常堆（大中小）预测为 normal 的比例（越高越好）；
  2) 坏豆堆预测为某缺陷类的比例（越高越好）+ 缺陷类别分布；
  3) 三档尺寸排序：大 > 中 > 小（等效直径中位数，像素口径，同机拍摄可比）。
已知限制：光影/阴影会造成分割噪声；elephant/immature 是已知易误报类。
"""
from __future__ import annotations

import glob
import os
import re
from collections import Counter, defaultdict

import cv2
import numpy as np
import onnxruntime

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "..", "data", "datasets", "hn_robusta", "v0.1", "raw_quark")
ONNX = os.path.join(HERE, "..", "train", "runs", "crop_cls", "crop_cls.onnx")
CLASSES = ["normal", "broken", "faded", "brocade", "immature", "peaberry", "shell",
           "elephant", "insect", "dried", "sour", "mold", "black"]
MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)
SIZE = 224


def card_mask(img):
    """证件区域掩码（v2）：证件冷色调（B>R）在暖光纸面上显著；膨胀留边后整体排除。"""
    b, g, r = img[:, :, 0].astype(np.int16), img[:, :, 1].astype(np.int16), img[:, :, 2].astype(np.int16)
    diff = b - r
    m = (diff > 4).astype(np.uint8) * 255
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((51, 51), np.uint8))
    m = cv2.dilate(m, np.ones((31, 31), np.uint8))
    return m


def gray_world(img):
    """灰世界白平衡（v2）：对齐合成数据的中性光源，消除室内暖色偏。"""
    res = img.astype(np.float32)
    means = res.reshape(-1, 3).mean(axis=0)
    gray = means.mean()
    gains = gray / np.maximum(means, 1e-3)
    return np.clip(res * gains[None, None, :], 0, 255).astype(np.uint8)


def seg_beans(img):
    """白底豆粒分割（v3）：屏蔽证件；HSV 饱和度逻辑（有彩度=豆，极暗=黑豆，
    低饱和灰斑=阴影出局）。"""
    work = gray_world(img)
    cmask = card_mask(work)
    cmask_inv = cv2.bitwise_not(cmask)
    hsv = cv2.cvtColor(work, cv2.COLOR_BGR2HSV)
    S = hsv[:, :, 1].astype(np.float32)
    V = hsv[:, :, 2].astype(np.float32)
    fg = (((S > 50) & (V > 55)) | (V < 42)).astype(np.uint8) * 255
    fg = cv2.bitwise_and(fg, cmask_inv)
    fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, np.ones((7, 7), np.uint8))
    fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
    n, labcc, stats, cent = cv2.connectedComponentsWithStats(fg)
    area_img = img.shape[0] * img.shape[1]
    beans = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if not (3e-5 * area_img < area < 4e-3 * area_img):
            continue
        mask = (labcc[y:y + h, x:x + w] == i).astype(np.uint8)
        # 实心度/圆度过滤（排除阴影软斑与纸面污渍）
        cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not cnts:
            continue
        c = max(cnts, key=cv2.contourArea)
        solidity = area / max(cv2.convexHull(c).astype(int), cv2.contourArea(c) + 1e-6, key=None) if False else area / max(cv2.contourArea(cv2.convexHull(c)), 1)
        (cx, cy), (rw, rh), ang = cv2.minAreaRect(c)
        aspect = max(rw, rh) / max(min(rw, rh), 1)
        eq_d = 2 * np.sqrt(area / np.pi)
        if solidity < 0.80 or aspect > 2.6:
            continue
        beans.append({"cx": cent[i][0], "cy": cent[i][1], "eq_d": eq_d,
                      "x": x, "y": y, "w": w, "h": h, "mask": mask})
    return beans


def classify_crop(sess, img, b):
    x, y, w, h = b["x"], b["y"], b["w"], b["h"]
    pad = int(0.15 * max(w, h))
    x0, y0 = max(x - pad, 0), max(y - pad, 0)
    x1, y1 = min(x + w + pad, img.shape[1]), min(y + h + pad, img.shape[0])
    crop = img[y0:y1, x0:x1]
    # 掩码外置白底（与合成裁片一致的白背景先验）
    m = cv2.resize(b["mask"], (crop.shape[1], crop.shape[0]), interpolation=cv2.INTER_NEAREST)
    crop = np.where(m[:, :, None] == 1, crop, 255).astype(np.uint8)
    crop = cv2.resize(crop, (SIZE, SIZE), interpolation=cv2.INTER_AREA)
    rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    rgb = (rgb - MEAN) / STD
    t = rgb.transpose(2, 0, 1)[None].astype(np.float32)
    out = sess.run(None, {"input": t})[0][0]
    idx = int(np.argmax(out))
    return CLASSES[idx], float(out[idx])


def main():
    sess = onnxruntime.InferenceSession(ONNX, providers=["CPUExecutionProvider"])
    files = sorted(glob.glob(os.path.join(RAW, "*.jpg")))
    piles = {"大": {"cls": Counter()}, "中": {"cls": Counter()}, "小": {"cls": Counter()}, "坏": {"cls": Counter()}}
    size_by_pile = {"大": [], "中": [], "小": [], "坏": []}
    for f in files:
        m = re.match(r"([大中小坏])", os.path.basename(f))
        if not m:
            continue
        pile = m.group(1)
        img = cv2.imdecode(np.fromfile(f, dtype=np.uint8), cv2.IMREAD_COLOR)
        img = gray_world(img)
        beans = seg_beans(img)
        for b in beans:
            cls, conf = classify_crop(sess, img, b)
            piles[pile]["cls"][cls] += 1
            size_by_pile[pile].append(b["eq_d"])
        print("%-12s 分割 %2d 粒 → %s" % (os.path.basename(f), len(beans),
              dict(Counter([classify_crop(sess, img, b)[0] for b in beans]))))
    print("\n=== 按堆聚合 ===")
    for k in ["大", "中", "小", "坏"]:
        c = piles[k]["cls"]
        tot = sum(c.values())
        if not tot:
            continue
        normal_pct = 100.0 * c.get("normal", 0) / tot
        defect_pct = 100.0 - normal_pct
        med = float(np.median(size_by_pile[k]))
        top_def = [(cls, n) for cls, n in c.most_common() if cls != "normal"][:4]
        print("%s堆: 豆数=%3d normal=%4.1f%% 缺陷=%4.1f%% 直径中位=%.0fpx 主要缺陷预测=%s"
              % (k, tot, normal_pct, defect_pct, med, top_def))

if __name__ == "__main__":
    main()

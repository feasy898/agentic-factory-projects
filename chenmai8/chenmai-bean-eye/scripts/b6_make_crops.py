# -*- coding: utf-8 -*-
"""批6步骤1：从 4 张全堆照裁粒并生成目检用 contact sheet。

产物：
  out/b6_crops/<前缀>_<序号>.jpg   单粒裁片（前缀 dan/zhong/xiao/huai）
  out/b6_sheet_<堆名>.jpg          目检拼图（每格左上角写裁片文件名）
"""
from __future__ import annotations

import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from eval_real_v0 import seg_beans, gray_world  # noqa: E402

RAW = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "datasets", "hn_robusta", "v0.1", "raw_quark")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "out", "b6_crops")
PREFIX = {"大": "dan", "中": "zhong", "小": "xiao", "坏": "huai"}


def sheet(crops, path, cols=8, cell=180):
    rows = (len(crops) + cols - 1) // cols
    canvas = np.full((rows * cell, cols * cell, 3), 255, np.uint8)
    for i, (name, im) in enumerate(crops):
        r, c = divmod(i, cols)
        im = cv2.resize(im, (cell - 8, cell - 28))
        y0, x0 = r * cell, c * cell
        canvas[y0 + 24:y0 + 24 + im.shape[0], x0 + 4:x0 + 4 + im.shape[1]] = im
        cv2.putText(canvas, name, (x0 + 4, y0 + 18), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 1)
    cv2.imencode(".jpg", canvas)[1].tofile(path)


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    made = []
    for pile, pref in PREFIX.items():
        f = os.path.join(RAW, "%s（全）.jpg" % pile)
        img = cv2.imdecode(np.fromfile(f, dtype=np.uint8), cv2.IMREAD_COLOR)
        img = gray_world(img)
        beans = seg_beans(img)
        crops = []
        for i, b in enumerate(beans):
            x, y, w, h = b["x"], b["y"], b["w"], b["h"]
            pad = int(0.15 * max(w, h))
            c = img[max(y - pad, 0):y + h + pad, max(x - pad, 0):x + w + pad]
            name = "%s_%03d.jpg" % (pref, i)
            cv2.imencode(".jpg", c, [cv2.IMWRITE_JPEG_QUALITY, 92])[1].tofile(os.path.join(OUT, name))
            crops.append((name, c))
            made.append(name)
        sheet(crops, os.path.join(os.path.dirname(OUT), "b6_sheet_%s.jpg" % pref))
        print("%s（全）: %d 粒" % (pile, len(crops)))
    print("总计裁片 %d → %s" % (len(made), OUT))
    return 0


if __name__ == "__main__":
    sys.exit(main())

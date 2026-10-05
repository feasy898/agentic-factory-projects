# -*- coding: utf-8 -*-
"""批12步骤2：二轮抓取去重（对比一轮 clean/ 已有哈希）→ 新 contact sheets。"""
from __future__ import annotations

import glob
import hashlib
import os
import sys

import cv2
import numpy as np

BASE = os.path.dirname(os.path.abspath(__file__))
RAW1 = os.path.join(BASE, "..", "data", "datasets", "web_hn", "raw")
RAW2 = os.path.join(BASE, "..", "data", "datasets", "web_hn", "raw2")
CLEAN = os.path.join(BASE, "..", "data", "datasets", "web_hn", "clean")
CLEAN2 = os.path.join(BASE, "..", "data", "datasets", "web_hn", "clean2")
SHEET = os.path.join(BASE, "..", "out", "b12_sheets")


def main() -> int:
    os.makedirs(CLEAN2, exist_ok=True)
    os.makedirs(SHEET, exist_ok=True)
    seen = set()
    for f in glob.glob(os.path.join(CLEAN, "*.jpg")):
        seen.add(hashlib.sha256(open(f, "rb").read()).hexdigest())
    kept = []
    for f in sorted(glob.glob(os.path.join(RAW2, "*", "*", "*"))):
        try:
            data = open(f, "rb").read()
        except OSError:
            continue
        if len(data) < 8_000:
            continue
        h = hashlib.sha256(data).hexdigest()
        if h in seen:
            continue
        seen.add(h)
        img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if img is None or min(img.shape[:2]) < 200:
            continue
        name = "n2_%s.jpg" % hashlib.md5(data).hexdigest()[:10]
        cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 90])[1].tofile(os.path.join(CLEAN2, name))
        kept.append((name, img))
    print("二轮去重新增：", len(kept))
    cols, cell = 10, 150
    for si in range(0, len(kept), 100):
        chunk = kept[si:si + 100]
        rows = (len(chunk) + cols - 1) // cols
        canvas = np.full((rows * cell, cols * cell, 3), 255, np.uint8)
        for i, (name, im) in enumerate(chunk):
            r, c = divmod(i, cols)
            scale = min((cell - 6) / im.shape[1], (cell - 26) / im.shape[0])
            im2 = cv2.resize(im, (int(im.shape[1] * scale), int(im.shape[0] * scale)))
            y0, x0 = r * cell, c * cell
            canvas[y0 + 22:y0 + 22 + im2.shape[0], x0 + 3:x0 + 3 + im2.shape[1]] = im2
            cv2.putText(canvas, name.replace(".jpg", "")[:22], (x0 + 3, y0 + 16), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 0), 1)
        out = os.path.join(SHEET, "b12_sheet_%02d.jpg" % (si // 100))
        cv2.imencode(".jpg", canvas, [cv2.IMWRITE_JPEG_QUALITY, 82])[1].tofile(out)
        print("sheet:", out, len(chunk))
    return 0


if __name__ == "__main__":
    sys.exit(main())

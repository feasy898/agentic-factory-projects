# -*- coding: utf-8 -*-
"""批11步骤2：网页图去重 + 尺寸过滤 + contact sheet 生成（供目检）。"""
from __future__ import annotations

import glob
import hashlib
import os
import sys

import cv2
import numpy as np

RAW = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "datasets", "web_hn", "raw")
CLEAN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "datasets", "web_hn", "clean")
SHEET = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "out", "b11_sheets")


def main() -> int:
    os.makedirs(CLEAN, exist_ok=True)
    os.makedirs(SHEET, exist_ok=True)
    seen, kept = set(), []
    for group in ("normal", "defect"):
        for f in sorted(glob.glob(os.path.join(RAW, group, "*", "*"))):
            try:
                data = open(f, "rb").read()
            except OSError:
                continue
            if len(data) < 8_000:
                continue
            h = hashlib.sha256(data).hexdigest()
            if h in seen:
                continue
            img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
            if img is None or min(img.shape[:2]) < 200:
                continue
            seen.add(h)
            name = "%s_%s.jpg" % (group, hashlib.md5(data).hexdigest()[:10])
            cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 90])[1].tofile(os.path.join(CLEAN, name))
            kept.append((name, img))
    print("去重后保留：normal=%d defect=%d 合计=%d" % (
        sum(1 for n, _ in kept if n.startswith("normal")), sum(1 for n, _ in kept if n.startswith("defect")), len(kept)))
    # contact sheets：每张 150 格
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
        out = os.path.join(SHEET, "b11_sheet_%02d.jpg" % (si // 100))
        cv2.imencode(".jpg", canvas, [cv2.IMWRITE_JPEG_QUALITY, 82])[1].tofile(out)
        print("sheet:", out, len(chunk))
    return 0


if __name__ == "__main__":
    sys.exit(main())

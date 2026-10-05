# -*- coding: utf-8 -*-
"""批12步骤3：合并二轮 KEEP 清单 → 单粒裁片（web_hn/crops_b12）→ 打包上传。

输入：out/b12_keep_normal.txt / out/b12_keep_defect.txt（每行 = clean2/ 文件名去前缀的 hash 段）。
标签：normal → normal；defect → b9.onnx 先验限定 12 缺陷类。切分 85/15。
"""
from __future__ import annotations

import os
import sys

import cv2
import numpy as np
import onnxruntime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from eval_real_v0 import seg_beans, gray_world  # noqa: E402

BASE = os.path.dirname(os.path.abspath(__file__))
CLEAN = os.path.join(BASE, "..", "data", "datasets", "web_hn", "clean2")
DST = os.path.join(BASE, "..", "data", "datasets", "web_hn", "crops_b12")
ONNX = os.path.join(BASE, "..", "train", "runs", "crop_cls", "b9.onnx")
CLASSES = ["normal", "broken", "faded", "brocade", "immature", "peaberry", "shell",
           "elephant", "insect", "dried", "sour", "mold", "black"]
MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)


def resolve(seg: str) -> str | None:
    for f in os.listdir(CLEAN):
        if seg in f:
            return os.path.join(CLEAN, f)
    return None


def main() -> int:
    if os.path.exists(DST):
        shutil.rmtree(DST)
    sess = onnxruntime.InferenceSession(ONNX, providers=["CPUExecutionProvider"])
    counters: dict[str, int] = {}
    total_img = total_crop = miss = 0

    def emit(img: np.ndarray, label: str, stem: str) -> None:
        nonlocal total_crop
        beans = seg_beans(img)
        crops = []
        if beans:
            for b in beans:
                x, y, w, h = b["x"], b["y"], b["w"], b["h"]
                pad = int(0.15 * max(w, h))
                crops.append(img[max(y - pad, 0):y + h + pad, max(x - pad, 0):x + w + pad])
        else:
            s = 224 / min(img.shape[:2])
            crops.append(cv2.resize(img, (int(img.shape[1] * s), int(img.shape[0] * s))))
        for j, c in enumerate(crops):
            if label != "normal":
                t = cv2.resize(c, (224, 224)).astype(np.float32)[:, :, ::-1] / 255.0
                t = ((t - MEAN) / STD).transpose(2, 0, 1)[None].astype(np.float32)
                out = sess.run(None, {"input": t})[0][0]
                cand = [(CLASSES[j2], out[j2]) for j2 in range(len(CLASSES)) if CLASSES[j2] != "normal"]
                cls = max(cand, key=lambda x: x[1])[0]
            else:
                cls = "normal"
            counters[cls] = counters.get(cls, 0) + 1
            total_crop += 1
            split = "valid" if counters[cls] % 9 == 0 else "train"
            d = os.path.join(DST, split, cls)
            os.makedirs(d, exist_ok=True)
            cv2.imencode(".jpg", c, [cv2.IMWRITE_JPEG_QUALITY, 90])[1].tofile(os.path.join(d, "%s_%02d.jpg" % (stem, j)))

    for listfile, label in (("b12_keep_normal.txt", "normal"), ("b12_keep_defect.txt", "defect")):
        lp = os.path.join(BASE, "..", "out", listfile)
        for seg in open(lp, encoding="utf-8").read().split():
            p = resolve(seg)
            if not p:
                miss += 1
                print("[缺]", seg)
                continue
            total_img += 1
            img = gray_world(cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR))
            emit(img, label, seg[:14])
    with open(os.path.join(DST, "labels.csv"), "w", encoding="utf-8", newline="") as f:
        f.write("class,count\n")
        for k, v in sorted(counters.items()):
            f.write("%s,%d\n" % (k, v))
    print("图像 %d（缺 %d）→ 裁片 %d；各类：%s" % (total_img, miss, total_crop, counters))
    return 0


if __name__ == "__main__":
    sys.exit(main())

# -*- coding: utf-8 -*-
"""批11步骤3：合并三张 sheet 的 KEEP 清单 → 单粒裁片（web_hn/crops_b11）→ 打包。

标签：KEEP_NORMAL → normal；KEEP_DEFECT → b9.onnx 先验限定 12 缺陷类。
切分：每类 85% train / 15% valid。裁法：seg_beans 切粒；0 粒时整图缩为裁片
（特写单豆图，缩到短边 224）。
"""
from __future__ import annotations

import os
import shutil
import sys

import cv2
import numpy as np
import onnxruntime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from eval_real_v0 import seg_beans, gray_world  # noqa: E402

BASE = os.path.dirname(os.path.abspath(__file__))
CLEAN = os.path.join(BASE, "..", "data", "datasets", "web_hn", "clean")
DST = os.path.join(BASE, "..", "data", "datasets", "web_hn", "crops_b11")
ONNX = os.path.join(BASE, "..", "train", "runs", "crop_cls", "b9.onnx")
CLASSES = ["normal", "broken", "faded", "brocade", "immature", "peaberry", "shell",
           "elephant", "insect", "dried", "sour", "mold", "black"]
DEFECT = [c for c in CLASSES if c != "normal"]
MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)

KEEP_NORMAL = [
    # sheet00
    "normal_d32f333f30", "normal_e653a907d2", "normal_93c5e2bc0f", "normal_8d0d032897", "normal_9cb58288e1",
    # sheet01
    "normal_beb9b71a7d", "normal_7c2a71f6f7", "normal_f0e11f6b82", "normal_8123667d21", "normal_5bc17f46e3",
    "normal_8824b38a10", "normal_44a4f39e1c", "normal_d035b17bad", "normal_f1c9220fee", "normal_690d0423d8",
    "normal_112634aa4b", "normal_21591f78c9", "normal_3db591e62f", "normal_56b83a52fe", "normal_48fd95cf99",
    "normal_f5960fd686", "normal_7b4945545d", "normal_7856d8506c", "normal_c42e8f6d68", "normal_b1afb6d94b",
    "normal_a000c73ebe", "normal_30215df160", "normal_9ce0b54400", "normal_39fec51f1a", "normal_74ba6eab96",
    "normal_915ed84154", "normal_a629969d84", "normal_a8ae9458d7", "normal_bb31d2633b", "normal_0fd5bf618f",
    # sheet02（hash 后缀，按 clean/ 文件名匹配）
    "cb715316a9", "d5bc8bdcf5", "545ca3c37a", "6f4681f85d", "27fa4dba48", "4b75453a1a", "3d3b07569b",
    "aa7cbc5244", "5c2c2a3602", "b9eeedee42", "3cf5dac80e",
]
KEEP_DEFECT = [
    # sheet01
    "defect_f9d0912d3f", "defect_35959d7670", "defect_65c1e30f2a", "defect_0490c58304", "defect_dae89e48e1",
    # sheet02
    "f7e41dc8e0", "3a98f8ca62", "b23a01fa36", "341eecd4e4", "3455760d45", "3acc14915b", "5f5125b349",
    "7ec35815c0", "c4141aec52", "aedd19d8c7",
]


def resolve(name: str) -> str | None:
    p = os.path.join(CLEAN, name + ".jpg")
    return p if os.path.exists(p) else None


def main() -> int:
    if os.path.exists(DST):
        shutil.rmtree(DST)
    sess = onnxruntime.InferenceSession(ONNX, providers=["CPUExecutionProvider"])
    counters: dict[str, int] = {}
    manifest = []

    def emit(img: np.ndarray, label: str, stem: str) -> int:
        beans = seg_beans(img)
        crops = []
        if beans:
            for j, b in enumerate(beans):
                x, y, w, h = b["x"], b["y"], b["w"], b["h"]
                pad = int(0.15 * max(w, h))
                c = img[max(y - pad, 0):y + h + pad, max(x - pad, 0):x + w + pad]
                crops.append(c)
        else:
            s = 224 / min(img.shape[:2])
            crops.append(cv2.resize(img, (int(img.shape[1] * s), int(img.shape[0] * s))))
        n = 0
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
            split = "valid" if counters[cls] % 7 == 0 else "train"
            d = os.path.join(DST, split, cls)
            os.makedirs(d, exist_ok=True)
            fn = "%s_%02d.jpg" % (stem, j)
            cv2.imencode(".jpg", c, [cv2.IMWRITE_JPEG_QUALITY, 90])[1].tofile(os.path.join(d, fn))
            manifest.append((split, cls, fn))
            n += 1
        return n

    for name in KEEP_NORMAL:
        p = resolve(name)
        if not p:
            print("[缺] ", name)
            continue
        img = gray_world(cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR))
        emit(img, "normal", name)
    for name in KEEP_DEFECT:
        p = resolve(name)
        if not p:
            print("[缺] ", name)
            continue
        img = gray_world(cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR))
        emit(img, "defect", name)

    with open(os.path.join(DST, "labels.csv"), "w", encoding="utf-8", newline="") as f:
        f.write("split,class,file\n")
        for r in manifest:
            f.write(",".join(r) + "\n")
    print("各类计数:", counters)
    print("总裁片:", len(manifest), "→", DST)
    return 0


if __name__ == "__main__":
    sys.exit(main())

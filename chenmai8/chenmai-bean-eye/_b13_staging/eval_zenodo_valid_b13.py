#!/usr/bin/env python3
"""批13 参考指标：Zenodo val 252 张 normal 判对率（eval_zenodo_valid_b13）。

与批12 eval_zenodo_valid_b12.py 同算法（RGB→Resize224 拉伸→ImageNet 归一化→
ONNX softmax→argmax），仅文件头适配批13。口径差异如实注记：
  这 252 张是真正的留出集（批12 起即如此）：不入训练（zenodo-robusta-normal-b12
  只含 train 1006），也不入选型 valid；批13 训练根与批12 完全相同，该 252 张
  继续保持零接触。评测用原始 PNG（b12-dl/robusta_b12/val，tarball
  sha256=4e83f37a2d01bc20d1a0a5cc41530ef5e4dcf6f5fb1432461c6537ff52e3d314），
  不经 JPG 转换。

用法：python eval_zenodo_valid_b13.py --dir <val PNG 目录> --onnx <onnx> --out <json>
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np

CLASSES = ["normal", "broken", "faded", "brocade", "immature", "peaberry", "shell",
           "elephant", "insect", "dried", "sour", "mold", "black"]
MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)
SIZE = 224


def softmax(x: np.ndarray) -> np.ndarray:
    e = np.exp(x - x.max())
    return e / e.sum()


def main() -> int:
    ap = argparse.ArgumentParser(description="批13 zenodo val 全量 252 normal 判对率（真留出）")
    ap.add_argument("--dir", required=True, help="zenodo val PNG 目录（R-* 拍平前原件）")
    ap.add_argument("--onnx", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    from PIL import Image
    import onnxruntime as ort

    files = sorted(Path(args.dir).rglob("*.png"))
    if not files:
        print(f"[FAIL] 无 PNG: {args.dir}")
        return 2

    sess = ort.InferenceSession(args.onnx, providers=["CPUExecutionProvider"])
    inp_name = sess.get_inputs()[0].name

    recs: list[dict] = []
    for f in files:
        img = Image.open(f).convert("RGB").resize((SIZE, SIZE), Image.BILINEAR)
        rgb = np.asarray(img, dtype=np.float32) / 255.0
        rgb = (rgb - MEAN) / STD
        t = rgb.transpose(2, 0, 1)[None].astype(np.float32)
        prob = softmax(sess.run(None, {inp_name: t})[0][0])
        idx = int(prob.argmax())
        recs.append({"file": f.name, "pred": CLASSES[idx],
                     "conf": round(float(prob[idx]), 4),
                     "p_normal": round(float(prob[0]), 4)})

    n = len(recs)
    n_normal = sum(1 for r in recs if r["pred"] == "normal")
    pred_counts = dict(Counter(r["pred"] for r in recs))
    out = {
        "prepared_by": "eval_zenodo_valid_b13.py（批9/b11/b12 同算法；范围=zenodo val 全量 252 原始 PNG）",
        "dir": str(args.dir),
        "onnx": args.onnx,
        "n": n,
        "normal_correct": n_normal,
        "normal_correct_rate": round(n_normal / n, 6),
        "pred_counts": pred_counts,
        "p_normal_mean": round(float(np.mean([r["p_normal"] for r in recs])), 4),
        "note": "批13 口径：这 252 张是真留出——不入训练（zenodo-robusta-normal-b12 只含 "
                "train 1006）也不入选型 valid（批12 起排除）；训练根与批12 完全相同，"
                "该 252 张保持零接触。预处理同训练 eval（Resize224 拉伸 + ImageNet 归一化，ONNX CPU）",
        "records": recs,
    }
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n",
                              encoding="utf-8")
    print(f"[zenodo-valid-b13] normal 判对 {n_normal}/{n} = {n_normal / n:.4f}")
    print(f"[zenodo-valid-b13] 预测分布: {pred_counts}")
    print(f"[out] {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""全资产 CLIP 锚点分布 → 定 D-026 校准常数 (subject_missing/appeal01 的 map01 域)。"""
import json
import os
import sys

import numpy as np
from PIL import Image

os.chdir(os.path.expanduser("~/cradle"))
sys.path.insert(0, os.getcwd())

from src.api.vlm import _load_clip_fns

ie, te = _load_clip_fns()
ANCHORS = {
    "pos": "a clear sharp professional photograph, well composed subject",
    "deformed": "a deformed melted distorted malformed blob",
    "garbled": "garbled nonsense pseudo text characters overlay",
    "dark": "a pitch black empty dark frame",
    "bright": "a blown out overexposed plain white frame",
    "blur": "heavy motion blur ghosting double exposure smear",
    "appeal": "beautiful appetizing professional food photography, warm color, shallow depth of field",
}
QC = open("src/gates/vlm_prompt.txt", encoding="utf-8").read()
ea = {k: np.asarray(te(v), dtype="float32") for k, v in ANCHORS.items()}
ea["qc"] = np.asarray(te(QC[:256]), dtype="float32")

def row_of(path):
    v = np.asarray(ie(Image.open(path).convert("RGB")), dtype="float32")
    v = v / np.linalg.norm(v)
    r = {k: round(float(np.dot(v, a)), 4) for k, a in ea.items()}
    r["content_mean"] = round((r["pos"] + r["appeal"]) / 2, 4)
    return r

out = {}
assets = []
for d in ("assets/products", "assets/scenes"):
    for f in sorted(os.listdir(d)):
        if f.endswith(".png"):
            assets.append(os.path.join(d, f))
for p in assets:
    out[p] = row_of(p)
    print(p, json.dumps(out[p]))
# LTX probe 候选的抽帧(真实生成帧)
fr = "workdir/candidates/m2_wiring_probe.mp4.frames"
if os.path.isdir(fr):
    frames = sorted(os.listdir(fr))
    for p in frames[::3][:4]:
        full = os.path.join(fr, p)
        out[full] = row_of(full)
        print(full, json.dumps(out[full]))
# 合成坏帧
import numpy as _np
os.makedirs("/tmp/m2_calib", exist_ok=True)
Image.new("RGB", (384, 512), (0, 0, 0)).save("/tmp/m2_calib/black.png")
Image.new("RGB", (384, 512), (255, 255, 255)).save("/tmp/m2_calib/white.png")
Image.new("RGB", (384, 512), (128, 128, 128)).save("/tmp/m2_calib/gray.png")
rng = np.random.default_rng(0)
Image.fromarray(rng.integers(0, 256, (512, 384, 3), dtype="uint8")).save("/tmp/m2_calib/noise.png")
for k in ("black", "white", "gray", "noise"):
    out[f"BAD_{k}"] = row_of(f"/tmp/m2_calib/{k}.png")
    print("BAD", k, json.dumps(out[f"BAD_{k}"]))

os.makedirs("workdir/logs", exist_ok=True)
with open("workdir/logs/m2_clip_anchor_assets.json", "w") as f:
    json.dump(out, f, ensure_ascii=False, indent=1)
print("ASSET ANCHOR PROBE DONE")

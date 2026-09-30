#!/usr/bin/env python3
"""CLIP 锚点实测: 好/坏帧对 7 锚点的余弦相似度分布 → 为 D-026 重校准 _map01 提供数据。"""
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
QC_PROMPT = open("src/gates/vlm_prompt.txt", encoding="utf-8").read()

ea = {k: np.asarray(te(v), dtype="float32") for k, v in ANCHORS.items()}
ea["qc_prompt"] = np.asarray(te(QC_PROMPT[:256]), dtype="float32")

def sim(v, name):
    a = ea[name]
    return float(np.dot(v, a) / (np.linalg.norm(v) * np.linalg.norm(a)))

# ---- 好/坏图像集 ----
goods = {}
goods["asset_maodu"] = "assets/products/maodu_01.png"
frames = sorted(glob_probe := [os.path.join("workdir/candidates/m2_wiring_probe.mp4.frames", f)
                               for f in os.listdir("workdir/candidates/m2_wiring_probe.mp4.frames")]) if os.path.isdir("workdir/candidates/m2_wiring_probe.mp4.frames") else []
for i, p in enumerate(frames[:: max(1, len(frames) // 3)][:3]):
    goods[f"probe_frame_{i}"] = p

bads = {}
tmp = "/tmp/m2_calib"
os.makedirs(tmp, exist_ok=True)
Image.new("RGB", (384, 512), (0, 0, 0)).save(f"{tmp}/black.png")
Image.new("RGB", (384, 512), (255, 255, 255)).save(f"{tmp}/white.png")
Image.new("RGB", (384, 512), (128, 128, 128)).save(f"{tmp}/gray.png")
Image.new("RGB", (384, 512), (30, 60, 200)).save(f"{tmp}/blue.png")
rng = np.random.default_rng(0)
Image.fromarray(rng.integers(0, 256, (512, 384, 3), dtype="uint8")).save(f"{tmp}/noise.png")
img = Image.new("RGB", (384, 512), (250, 250, 245))
from PIL import ImageDraw

d = ImageDraw.Draw(img)
for y in range(40, 480, 60):
    d.text((20, y), "MENU PRICE 39.9 text text", fill=(20, 20, 20))
img.save(f"{tmp}/text.png")

for k in ("black", "white", "gray", "blue", "noise", "text"):
    bads[k] = f"{tmp}/{k}.png"

out = {"good": {}, "bad": {}, "qc_prompt_selfsim": {}}
for tag, path in {**goods, **bads}.items():
    v = np.asarray(ie(Image.open(path).convert("RGB")), dtype="float32")
    row = {k: round(sim(v, k), 4) for k in ANCHORS}
    row["qc_prompt"] = round(sim(v, "qc_prompt"), 4)
    key = "good" if tag in goods else "bad"
    out[key][tag] = row
    print(key, tag, json.dumps(row))

# QC 提示词 vs 各锚点(自相似, 判断 camera_match 锚是否被 QC 文本污染)
for k in list(ANCHORS) + ["qc_prompt"]:
    a = ea["qc_prompt"]; b = ea[k] if k != "qc_prompt" else ea["qc_prompt"]
    out["qc_prompt_selfsim"][k] = round(float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))), 4)
print("qc_prompt selfsim:", json.dumps(out["qc_prompt_selfsim"]))

os.makedirs("workdir/logs", exist_ok=True)
with open("workdir/logs/m2_clip_anchor_probe.json", "w") as f:
    json.dump(out, f, ensure_ascii=False, indent=1)
print("CALIB PROBE DONE")

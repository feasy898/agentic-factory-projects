#!/usr/bin/env python3
"""M5 G5 分锚校准探针: 为 scene 类资产选型 appeal 锚文本与线性映射域 (lo, hi)。

背景 (M2 遗留, m2_yield_report_v1 §4): CLIP 启发式 appeal 锚是美食摄影文本,
对夜景/雨窗/背影类资产系统性打低 (0.145-0.176 vs 美食 0.19-0.23), 与合成坏帧
(0.140-0.169) 完全重叠 → G5 退化为"资产类型门"。本探针用 M2 存量候选抽帧 +
11 张资产 + 合成坏帧, 对多个候选 scene 锚实测相似度, 依据可分性选锚定域。

用法: ~/cradle/.venv/bin/python tools/m5_anchor_probe.py
输出: workdir/logs/m5_clip_anchor_scene.json (原始相似度) + stdout 摘要。
只读 M2 存量数据, 不做任何生成。
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

OUT_PATH = REPO / "workdir" / "logs" / "m5_clip_anchor_scene.json"

# 候选 scene appeal 锚 (选型依据: 与美食锚同一句式家族, 但语义针对环境/氛围类)
SCENE_ANCHOR_CANDIDATES = {
    "s1_ambient": "beautiful atmospheric professional photography, warm ambient lighting, cozy inviting mood, cinematic composition",
    "s2_cinematic": "a beautiful moody cinematic photograph, atmospheric lighting, aesthetically pleasing composition, high quality",
    "s3_night": "beautiful cozy restaurant ambiance at night, warm lantern glow, inviting cinematic atmosphere",
    "s4_grading": "stunning cinematic photography with rich color grading and beautiful lighting",
    "s5_pleasing": "an aesthetically pleasing photograph, professional composition, beautiful light and atmosphere",
}
# 现行美食锚(参照系, D-026 域 (0.145, 0.28))
FOOD_ANCHOR = "beautiful appetizing professional food photography, warm color, shallow depth of field"

# 合成坏帧配方 (对齐 M2 m2_clip_anchor_probe.json 的 bad 样本族)


def synth_bad_frames(out_dir: Path) -> dict[str, Path]:
    import numpy as np
    from PIL import Image, ImageDraw

    out_dir.mkdir(parents=True, exist_ok=True)
    w, h = 384, 512
    frames: dict[str, Path] = {}
    def save(name, arr):
        p = out_dir / f"bad_{name}.png"
        Image.fromarray(arr.astype("uint8")).save(p)
        frames[name] = p
    save("black", np.zeros((h, w, 3)))
    save("white", np.full((h, w, 3), 255.0))
    save("gray", np.full((h, w, 3), 128.0))
    save("blue", np.tile(np.array([30, 60, 180], dtype="float32"), (h, w, 1)))
    rng = np.random.default_rng(42)
    save("noise", rng.uniform(0, 255, size=(h, w, 3)))
    img = Image.new("RGB", (w, h), "white")
    d = ImageDraw.Draw(img)
    glyphs = "千丵丁乸亂亽亐乑乕乙乚乛乜龘靐齉齾齄龗鱻麤龖飍灪" * 8
    y = 10
    for row in range(16):
        d.text((10, y), glyphs[row * 12 : (row + 1) * 12], fill="black")
        y += 30
    p = out_dir / "bad_text.png"
    img.save(p)
    frames["text"] = p
    return frames


def collect_samples() -> dict[str, list[Path]]:
    """样品族: assets / 场景候选帧 / 美食候选帧 / 合成坏帧。"""
    cand = REPO / "workdir" / "candidates"
    groups: dict[str, list[Path]] = {"asset_food": [], "asset_scene": [], "scene_frames": [],
                                     "food_frames": [], "bad": []}
    for p in sorted((REPO / "assets" / "products").glob("*.png")):
        groups["asset_food"].append(p)
    for p in sorted((REPO / "assets" / "scenes").glob("*.png")):
        groups["asset_scene"].append(p)
    # 场景类被拒候选 (M2): S08 门头夜景 / S09 雨窗 / S11 背影, 每镜头 3 个候选
    for shot, tags in (("S08", ("a0_0", "a1_0", "a2_0")), ("S09", ("a0_0", "a1_0", "a2_0")),
                       ("S11", ("a0_0", "a1_0", "a2_0"))):
        for tag in tags:
            d = cand / f"{shot}_{tag}.mp4.frames"
            if d.is_dir():
                groups["scene_frames"] += sorted(d.glob("frame_*.png"))
    # 美食类通过候选 (参照): S01/S02/S03 各取 2 个候选
    for shot, tags in (("S01", ("a0_0", "a0_1")), ("S02", ("a0_0", "a0_1")), ("S03", ("a0_0", "a0_1"))):
        for tag in tags:
            d = cand / f"{shot}_{tag}.mp4.frames"
            if d.is_dir():
                groups["food_frames"] += sorted(d.glob("frame_*.png"))
    groups["bad"] = list(synth_bad_frames(REPO / "workdir" / "m5_probe_tmp").values())
    return groups


def main() -> int:
    from src.gates.g3_consistency import default_embed_fns

    image_embed, text_embed = default_embed_fns(device="cpu")
    anchors = {"food": FOOD_ANCHOR, **SCENE_ANCHOR_CANDIDATES}
    ea = {k: text_embed(v) for k, v in anchors.items()}

    groups = collect_samples()
    out: dict = {"anchors": anchors, "groups": {}}
    t0 = time.monotonic()
    for gname, paths in groups.items():
        rows = []
        for p in paths:
            v = image_embed(str(p))
            rows.append({"path": str(p.relative_to(REPO)),
                         **{k: round(float(v @ ea[k]), 4) for k in ea}})
        out["groups"][gname] = rows
        print(f"[{gname}] {len(rows)} samples ({time.monotonic() - t0:.0f}s)", flush=True)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    # 摘要: 各锚对"场景好帧 vs 坏帧"的可分性
    print("\n==== 分离度摘要 (good_scene_min - bad_max, 越大越好) ====")
    scene_vals = {k: [r[k] for r in out["groups"]["scene_frames"]] for k in ea}
    bad_vals = {k: [r[k] for r in out["groups"]["bad"]] for k in ea}
    for k in ea:
        gs, bs = min(scene_vals[k]), max(bad_vals[k])
        print(f"{k:14s} scene[min={min(scene_vals[k]):.4f} p50={sorted(scene_vals[k])[len(scene_vals[k])//2]:.4f} "
              f"max={max(scene_vals[k]):.4f}]  bad[max={bs:.4f}]  gap={gs - bs:+.4f}")
    print(f"\n已写入 {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

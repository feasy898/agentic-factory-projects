"""V2-M3: overlay 素材库生成 — Wan2.1-Fun-1.3B-InP 生成 6 条 3-5s 氛围循环素材。

素材纪律 (SPECS_V2 §5.3): 素材只承担"氛围粒子"(蒸汽/雾/光斑), 纯暗底,
入库前必须单独过 G7 审计 (tools/m3_overlay_audit.py)。首帧为程序合成的
暗底渐变 PNG (食物/产品永远不参与生成)。

用法 (GPU 沙箱内):
  python tools/m3_gen_overlays.py --out assets/overlays [--only ov_steam_thin]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

W, H = 480, 832
FPS = 16
SECONDS = 4  # 65 帧 (4k+1), 3-5s 带内
STEPS = 20

# 6 条素材: 蒸汽×2 / 雾×2 / 光斑×2 (SPECS_V2 §5.3 要求 ≥6 条蒸汽/雾/光斑循环素材)
OVERLAY_SPECS = [
    {
        "file": "ov_steam_thin.mp4",
        "kind": "steam",
        "prompt": (
            "delicate thin white steam rising slowly from bottom center, gentle wisps of vapor, "
            "pure black background, soft light, fixed camera, locked tripod, only steam moves, "
            "no objects, no food, no hands"
        ),
    },
    {
        "file": "ov_steam_dense.mp4",
        "kind": "steam",
        "prompt": (
            "dense billowing white steam rising and swirling, thick vapor plumes, "
            "pure black background, soft light, fixed camera, locked tripod, only steam moves, "
            "no objects, no food, no hands"
        ),
    },
    {
        "file": "ov_fog_low.mp4",
        "kind": "fog",
        "prompt": (
            "low drifting fog layer crawling slowly across the frame, soft mist, "
            "pure black background, fixed camera, locked tripod, only fog moves, "
            "no objects, no food, no hands"
        ),
    },
    {
        "file": "ov_mist_cool.mp4",
        "kind": "fog",
        "prompt": (
            "cool blue-white mist swirling gently in slow motion, ethereal vapor, "
            "pure black background, fixed camera, locked tripod, only mist moves, "
            "no objects, no food, no hands"
        ),
    },
    {
        "file": "ov_light_warm.mp4",
        "kind": "light",
        "prompt": (
            "warm amber light leak glowing and pulsing softly, cinematic gentle light flare, "
            "pure black background, fixed camera, locked tripod, only light moves, "
            "no objects, no food, no hands"
        ),
    },
    {
        "file": "ov_bokeh_dust.mp4",
        "kind": "light",
        "prompt": (
            "tiny golden dust motes and bokeh sparkles floating slowly, glittering particles, "
            "pure black background, fixed camera, locked tripod, only particles move, "
            "no objects, no food, no hands"
        ),
    },
]

NEGATIVE = (
    "human face, hands, fingers, text, watermark, logo, food, dish, plate, tableware, "
    "objects, solid shapes, melting, liquid, dissolving, morphing, splitting, "
    "floating debris, deformed"
)

AUDIT_TERMS = {"steam": ["steam"], "fog": ["fog"], "light": ["light"]}  # G7 审计 subject 提示口径 (D-064)


def dark_first_frame(out_png: str, kind: str, seed: int) -> str:
    """程序合成暗底首帧 (无生成模型): 近黑渐变 + 底部微光晕, 蒸汽类底部略亮。"""
    yy, xx = np.mgrid[0:H, 0:W].astype("float32")
    base = 10.0 + 8.0 * (yy / H)  # 上暗下微亮
    img = np.stack([base * 0.9, base * 0.92, base], axis=-1)
    if kind in ("steam", "fog"):
        glow = 28.0 * np.exp(-(((xx - W / 2) ** 2) / (2 * (0.22 * W) ** 2)
                               + ((yy - H * 0.86) ** 2) / (2 * (0.10 * H) ** 2)))
        img += glow[..., None] * np.array([1.0, 0.98, 0.94])
    elif kind == "light":
        glow = 22.0 * np.exp(-(((xx - W * 0.7) ** 2) / (2 * (0.3 * W) ** 2)
                               + ((yy - H * 0.2) ** 2) / (2 * (0.18 * H) ** 2)))
        img += glow[..., None] * np.array([1.0, 0.72, 0.35])
    noise = np.random.RandomState(seed).rand(H, W) * 2.0
    img += noise[..., None]
    from PIL import Image

    Image.fromarray(np.clip(img, 0, 255).astype("uint8"), mode="RGB").save(out_png)
    return out_png


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(REPO / "assets" / "overlays"))
    ap.add_argument("--only", default=None, help="只生成指定 file")
    args = ap.parse_args()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    ff_dir = out_dir / "firstframes"
    ff_dir.mkdir(exist_ok=True)

    from src.gen.wan import LTX_FPS, load_wan_pipeline

    pipe = load_wan_pipeline(device="cuda")
    num_frames = SECONDS * FPS + 1  # 65

    manifest_path = out_dir / "manifest.json"
    entries = []
    if manifest_path.exists():
        entries = json.loads(manifest_path.read_text(encoding="utf-8"))
    by_file = {e["file"]: e for e in entries}

    from src.gen.common import write_frames_mp4

    for i, spec in enumerate(OVERLAY_SPECS):
        if args.only and spec["file"] != args.only:
            continue
        out_mp4 = out_dir / spec["file"]
        seed = 20260908 + i
        if out_mp4.exists():
            print(f"skip (已存在): {spec['file']}")
            continue
        ff = dark_first_frame(str(ff_dir / f"{spec['file']}.first.png"), spec["kind"], seed)
        t0 = time.monotonic()
        frames = pipe(
            prompt=spec["prompt"],
            negative=NEGATIVE,
            first_frame=ff,
            width=W,
            height=H,
            num_frames=num_frames,
            steps=STEPS,
            seed=seed,
        )
        write_frames_mp4(frames, LTX_FPS, str(out_mp4))
        gen_seconds = round(time.monotonic() - t0, 1)
        print(f"overlay 完成: {spec['file']} ({gen_seconds}s)")
        by_file[spec["file"]] = {
            **spec,
            "seed": seed,
            "seconds": SECONDS,
            "fps": LTX_FPS,
            "num_frames": num_frames,
            "steps": STEPS,
            "first_frame": str(Path(ff).relative_to(out_dir)),
            "gen_seconds": gen_seconds,
            "g7_audit": by_file.get(spec["file"], {}).get("g7_audit", {"passed": None, "pending": True}),
        }
        manifest_path.write_text(
            json.dumps([by_file[s["file"]] for s in OVERLAY_SPECS if s["file"] in by_file],
                       ensure_ascii=False, indent=2),
            encoding="utf-8")
    print(f"manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

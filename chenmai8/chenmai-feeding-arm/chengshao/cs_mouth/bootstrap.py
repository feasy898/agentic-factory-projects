"""样本自举：由 seeds/ 真人种子确定性生成 bundled/ 变体帧与 labels.json。

D1 无硬件且真机样本未到位：assets/face_samples/seeds/ 里的 5 张公版真人种子
（来源与许可证见 assets/face_samples/README.md）经 synth.apply_variant 生成
8 个确定性变体/张，连同种子共 48 张标注帧；eval 在 labels.json 缺失时自动
调用本模块重建（确定性 → 可复现）。主人后补真实样本经
scripts/import_face_samples.py 追加进 labels.json（draft 字段），本模块不覆盖。
"""

from __future__ import annotations

import json
from pathlib import Path

from .imgio import imread_u, imwrite_u
from .synth import VARIANTS, apply_variant

SEEDS = [
    # (种子文件, jaw 标签, turn 标签, 来源图像 ID（NASA 公有领域库，见 README.md）)
    ("seed_closed_peake.jpg", "closed", False, "jsc2013e079278"),
    ("seed_open_cardman.jpg", "open", False, "iss073e0658307"),
    ("seed_open_williams.jpg", "open", False, "iss072e189112"),
    ("seed_turn_adenot.jpg", None, True, "iss074e0604606-cropA"),
    ("seed_front_hathaway.jpg", None, False, "iss074e0604606-cropB"),
]
LABELS_VERSION = 1


def ensure_bundled(input_dir: str | Path, force: bool = False) -> dict:
    """确保 bundled/ 变体与 labels.json 就位；返回统计 {written, skipped, frames}。

    - labels.json 已存在且不 force → 不动（保护主人手工修订）；
    - 种子缺失 → FileNotFoundError（提示从 README 渠道恢复种子）。
    """
    import os

    root = Path(input_dir)
    seeds_dir = root / "seeds"
    bundled_dir = root / "bundled"
    labels_path = root / "labels.json"
    if not seeds_dir.is_dir():
        raise FileNotFoundError(
            f"缺少样本种子目录：{seeds_dir}\n（种子来源与恢复方式见该目录 README.md）"
        )
    bundled_dir.mkdir(parents=True, exist_ok=True)

    if labels_path.is_file() and not force:
        return {"written": 0, "skipped": 1, "frames": _count_frames(labels_path)}

    frames: list[dict] = []
    written = 0
    for seed_name, jaw, turn, origin in SEEDS:
        seed_path = seeds_dir / seed_name
        img = imread_u(seed_path)
        if img is None:
            raise FileNotFoundError(f"种子读取失败：{seed_path}")
        stem = Path(seed_name).stem
        entries = [("v00", "identity")] + [(t, k) for t, k in VARIANTS if t != "v00"]
        for tag, kind in entries:
            frame_name = f"{stem}_{tag}.jpg"
            frame_path = bundled_dir / frame_name
            variant = apply_variant(img, kind)
            if not imwrite_u(frame_path, variant, [int(__import__("cv2").IMWRITE_JPEG_QUALITY), 88]):
                raise OSError(f"变体写出失败：{frame_path}")
            written += 1
            frames.append(
                {
                    "file": f"bundled/{frame_name}",
                    "face": True,
                    "jaw": jaw,
                    "turn": turn,
                    "seed": seed_name,
                    "origin": f"{origin}#{kind}",
                    "draft": False,
                }
            )

    payload = {
        "version": LABELS_VERSION,
        "note": "bundled 帧由 seeds 确定性变体生成；jaw 标签在头部姿态无混淆的正面帧上人工核定；"
        "转头帧与俯仰帧不参与 jaw 指标（口径比受姿态混淆）。",
        "frames": frames,
    }
    labels_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return {"written": written, "skipped": 0, "frames": len(frames)}


def _count_frames(labels_path: Path) -> int:
    try:
        data = json.loads(labels_path.read_text(encoding="utf-8"))
        return len(data.get("frames", []))
    except (OSError, ValueError):
        return 0

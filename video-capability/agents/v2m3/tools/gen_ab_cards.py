#!/usr/bin/env python3
"""M5 阶段1: 生成竖/横 A/B 镜头卡 — 5 张代表性卡 × {portrait 480×832, landscape 832×480}。

代表集: S01(毛肚特写/美食) S03(虾滑/美食) S07(店内环境) S08(门头夜景) S11(无人背影/中风险),
覆盖美食/环境/夜景/人物四类资产与 G5 分锚两类。n_best=1, retry_max=0(测量用途, 不重试)。

用法: python3 tools/gen_ab_cards.py [--out templates/abcards]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from src.schema import validate_shotcard  # noqa: E402

BASES = {
    "S01": ("assets/products/maodu_01.png",
            "extreme close-up of fresh beef tripe dipped into boiling red spicy hotpot broth, oil bubbles, rising steam",
            {"scale": "closeup", "angle": "high_45", "motion": "slow_push_in", "depth": "shallow"}),
    "S03": ("assets/products/shrimp_01.png",
            "glossy hand-made shrimp paste being scooped, bouncy translucent texture, fresh and plump",
            {"scale": "closeup", "angle": "high_45", "motion": "slow_pull_back", "depth": "shallow"}),
    "S07": ("assets/scenes/interior_01.png",
            "cozy hotpot restaurant interior, warm lantern light, steam drifting over wooden tables, bokeh",
            {"scale": "wide", "angle": "eye_level", "motion": "slow_push_in", "depth": "medium"}),
    "S08": ("assets/scenes/storefront_01.png",
            "restaurant storefront at night, glowing warm lanterns, wet stone street reflections, inviting",
            {"scale": "wide", "angle": "low_angle", "motion": "slow_push_in", "depth": "deep"}),
    "S11": ("assets/scenes/back_view_01.png",
            "a single diner silhouette seen from behind walking toward a table in a warm corridor, back view only",
            {"scale": "medium", "angle": "eye_level", "motion": "follow_slow", "depth": "medium"}),
}
STYLE = ("professional food photography, warm amber lighting, appetizing, shallow depth of field, "
         "steam rising, rich color grading, no people")
SLOT = {"S01": "evidence_product", "S03": "evidence_product", "S07": "ambiance_scene",
        "S08": "storefront_night", "S11": "ambiance_scene"}
ACCEPTANCE = {
    "clip_ref_min": 0.65, "clip_text_min": 0.22, "temporal_clip_min": 0.85,
    "vlm_overall_min": 0.70, "vlm_defect_max": 0.2, "duration_tol": 0.5,
}


def make_card(base: str, orientation: str) -> dict:
    asset, prompt, camera = BASES[base]
    res = [480, 832] if orientation == "portrait" else [832, 480]
    suffix = "P" if orientation == "portrait" else "L"
    return {
        "shot_id": f"AB{base}{suffix}",
        "narrative_slot": SLOT[base],
        "lane": "first_frame_i2v",
        "orientation": orientation,
        "duration_sec": 5,
        "resolution": res,
        "fps": 16,
        "camera": camera,
        "subject": {"type": "object" if "/products/" in asset else "environment",
                    "desc_zh": f"A/B 测试卡(继承 {base}, {orientation})"},
        "prompt_en": f"{prompt}, {STYLE}",
        "first_frame_asset": asset,
        "negative": ["human face", "hands", "fingers", "text", "watermark", "logo",
                     "deformed", "extra limbs"],
        "n_best": 1,
        "retry_max": 0,
        "acceptance": dict(ACCEPTANCE),
        "fallback": {"type": "ken_burns", "asset": asset, "motion": "zoom_in_1.06", "duration_sec": 5},
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(REPO / "templates" / "abcards"))
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    n = 0
    for base in BASES:
        for orientation in ("portrait", "landscape"):
            c = make_card(base, orientation)
            validated = validate_shotcard(c)
            path = out / f"{c['shot_id']}.json"
            path.write_text(json.dumps(validated, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            n += 1
            print(f"ok {path.name} res={c['resolution'][0]}x{c['resolution'][1]}")
    print(f"共生成 {n} 张 A/B 卡 → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

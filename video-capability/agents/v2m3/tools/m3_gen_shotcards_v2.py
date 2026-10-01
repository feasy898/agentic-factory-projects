"""V2-M3: 从 v1 镜头卡确定性重写 v2 三车道卡 (SPECS_V2 §5.5) → templates/shotcards_v2/。

映射规则 (M3 任务面 + SPECS_V2 §5.2/§5.3 红线裁定, D-063):
- 食物/产品 (S01-S06, S13, S14, S15, S17) → compositing_2d5, n_best=1/retry=0 (确定性渲染)。
  注: 任务面清单把 S15 列入环境组, 但其主体=红汤锅底(食物), 按 §5.2 红线
  (食物禁止 pure_gen_short)归 compositing_2d5 — 红线优先, 已记 D-063。
- 环境 (S07-S11, S16) → pure_gen_short, 时长 1-2s, 固定机位。
- S12 (手部高风险) → ken_burns 原样保留。
- +S18/S19 evidence_transfer 演示卡 (evidence_asset 指向合成测试源, 报告标注演示源)。

用法: python tools/m3_gen_shotcards_v2.py [--root PATH]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# 视差 preset 名对齐 (compositing25.PARALLAX_PRESETS)
MOTION_TO_PARALLAX = {
    "slow_push_in": "slow_push_in",
    "slow_pull_back": "zoom_out",
    "orbit_slow": "slow_push_in",
    "static_hold": "slow_push_in",
    "follow_slow": "pan_right",
    "pan_left": "pan_left",
    "pan_right": "pan_right",
    "zoom_out": "zoom_out",
    "zoom_in_1.06": "zoom_in_1.06",
}

COMPOSITING_SHOTS = ["S01", "S02", "S03", "S04", "S05", "S06", "S13", "S14", "S15", "S17"]
# S05 甜品/S06 饮品/S14 饮品 → product, 其余食物 → food
PRODUCT_SHOTS = {"S05", "S06", "S14"}
PUREGEN_SHOTS = ["S07", "S08", "S09", "S10", "S11", "S16"]
PUREGEN_DURATION = {"S07": 2.0, "S08": 2.0, "S09": 2.0, "S10": 1.5, "S11": 2.0, "S16": 1.5}
KENBURNS_SHOTS = ["S12"]

EVIDENCE_DEMO_CARDS = [
    {
        "shot_id": "S18",
        "narrative_slot": "evidence_product",
        "lane": "evidence_transfer",
        "orientation": "portrait",
        "duration_sec": 3,
        "resolution": [480, 832],
        "fps": 16,
        "camera": {"scale": "closeup", "angle": "high_45", "motion": "static_hold", "depth": "shallow"},
        "subject": {
            "type": "food",
            "desc_zh": "证据转移演示:鲜虾滑食材特写,画面运动全部来自合成测试源(演示源,非真实实拍)",
        },
        "prompt_en": (
            "close-up of fresh hand-made shrimp paste on a ceramic dish, warm amber lighting, "
            "professional food photography, rich color grading, no people"
        ),
        "first_frame_asset": "assets/evidence/synthetic_demo_source_01_first.png",
        "evidence_asset": "assets/evidence/synthetic_demo_source_01.mp4",
        "negative": [
            "human face", "hands", "fingers", "text", "watermark", "logo",
            "deformed", "extra limbs", "melting", "liquid", "dissolving",
        ],
        "n_best": 1,
        "retry_max": 1,
        "acceptance": {
            "clip_ref_min": 0.60,
            "clip_text_min": 0.22,
            "temporal_clip_min": 0.85,
            "vlm_overall_min": 0.7,
            "vlm_defect_max": 0.2,
            "duration_tol": 0.5,
        },
        "fallback": {
            "type": "ken_burns",
            "asset": "assets/evidence/synthetic_demo_source_01_first.png",
            "motion": "zoom_in_1.06",
            "duration_sec": 3,
        },
    },
    {
        "shot_id": "S19",
        "narrative_slot": "evidence_product",
        "lane": "evidence_transfer",
        "orientation": "portrait",
        "duration_sec": 3,
        "resolution": [480, 832],
        "fps": 16,
        "camera": {"scale": "closeup", "angle": "high_45", "motion": "static_hold", "depth": "shallow"},
        "subject": {
            "type": "food",
            "desc_zh": "证据转移演示:毛肚食材特写,画面运动全部来自合成测试源(演示源,非真实实拍)",
        },
        "prompt_en": (
            "close-up of fresh beef tripe on a dark plate, warm amber lighting, "
            "professional food photography, rich color grading, no people"
        ),
        "first_frame_asset": "assets/evidence/synthetic_demo_source_02_first.png",
        "evidence_asset": "assets/evidence/synthetic_demo_source_02.mp4",
        "negative": [
            "human face", "hands", "fingers", "text", "watermark", "logo",
            "deformed", "extra limbs", "melting", "liquid", "dissolving",
        ],
        "n_best": 1,
        "retry_max": 1,
        "acceptance": {
            "clip_ref_min": 0.60,
            "clip_text_min": 0.22,
            "temporal_clip_min": 0.85,
            "vlm_overall_min": 0.7,
            "vlm_defect_max": 0.2,
            "duration_tol": 0.5,
        },
        "fallback": {
            "type": "ken_burns",
            "asset": "assets/evidence/synthetic_demo_source_02_first.png",
            "motion": "zoom_in_1.06",
            "duration_sec": 3,
        },
    },
]


def rewrite_card(card: dict) -> dict:
    sid = card["shot_id"]
    out = json.loads(json.dumps(card, ensure_ascii=False))  # 深拷贝

    if sid in COMPOSITING_SHOTS:
        out["lane"] = "compositing_2d5"
        out["subject"]["type"] = "product" if sid in PRODUCT_SHOTS else "food"
        out["camera"]["motion"] = MOTION_TO_PARALLAX.get(card["camera"]["motion"], "slow_push_in")
        out["n_best"] = 1          # 确定性渲染 (D-013 口径扩展, D-062)
        out["retry_max"] = 0
        out["evidence_asset"] = None
    elif sid in PUREGEN_SHOTS:
        out["lane"] = "pure_gen_short"
        out["duration_sec"] = PUREGEN_DURATION[sid]
        out["camera"]["motion"] = "static_hold"  # 锁定机位语义
        out["n_best"] = 2
        out["retry_max"] = 1
        out["evidence_asset"] = None
    elif sid in KENBURNS_SHOTS:
        out["evidence_asset"] = None  # lane/其余字段原样保留
    else:
        raise ValueError(f"未知镜头: {sid}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(REPO))
    args = ap.parse_args()
    root = Path(args.root)
    src_dir = root / "templates" / "shotcards"
    dst_dir = root / "templates" / "shotcards_v2"
    dst_dir.mkdir(parents=True, exist_ok=True)

    sys.path.insert(0, str(root))
    from src.schema import validate_shotcard

    written = []
    for src in sorted(src_dir.glob("*.json")):
        with open(src, "r", encoding="utf-8") as f:
            card = json.load(f)
        out = rewrite_card(card)
        out_path = dst_dir / src.name
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
            f.write("\n")
        validate_shotcard(out)
        written.append(out["shot_id"])

    for card in EVIDENCE_DEMO_CARDS:
        out_path = dst_dir / f"{card['shot_id']}_evidence_demo.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(card, f, ensure_ascii=False, indent=2)
            f.write("\n")
        validate_shotcard(card)
        written.append(card["shot_id"])

    print(f"v2 镜头卡 {len(written)} 张: {', '.join(written)}")
    print(f"车道分布: compositing_2d5={len(COMPOSITING_SHOTS)}, "
          f"pure_gen_short={len(PUREGEN_SHOTS)}, ken_burns={len(KENBURNS_SHOTS)}, "
          f"evidence_transfer={len(EVIDENCE_DEMO_CARDS)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

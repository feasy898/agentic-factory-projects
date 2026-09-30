#!/usr/bin/env python3
"""生成火锅案例镜头卡 (SPECS §5.1 十类资产 + 2 变体 + M5 补充变体 S13-S16) 并逐一过 schema 校验。

用法: python3 tools/gen_shotcards.py [--out templates/shotcards]
        [--clip-ref-min 0.65] [--temporal-clip-min 0.85] [--landscape]
- 缺省竖版 480×832 @16fps, acceptance 完整(校准后值经参数传入, M5 阶段0.2 试点验证制), ken_burns fallback;
- S11 无人背影=中风险(n_best 放大+重试加码), S12 手部入画=高风险(强制 lane=ken_burns 演示风险表);
- S13/S14=offer_product 槽位(T3 即时优惠需要), S15=evidence 变体, S16=ambiance 变体(模板变体差异化用)。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from src.schema import validate_shotcard  # noqa: E402

ACCEPTANCE = {
    "clip_ref_min": 0.65,
    "clip_text_min": 0.22,
    "temporal_clip_min": 0.85,
    "vlm_overall_min": 0.70,
    "vlm_defect_max": 0.2,
    "duration_tol": 0.5,
}

STYLE = (
    "professional food photography, warm amber lighting, appetizing, shallow depth of field, "
    "steam rising, rich color grading, no people"
)


def card(
    shot_id: str,
    narrative_slot: str,
    subject_type: str,
    desc_zh: str,
    prompt_en: str,
    asset: str,
    camera: dict,
    duration_sec: float = 5,
    motion: str = "zoom_in_1.06",
    lane: str = "first_frame_i2v",
    n_best: int = 3,
    retry_max: int = 2,
    resolution: tuple[int, int] = (480, 832),
) -> dict:
    return {
        "shot_id": shot_id,
        "narrative_slot": narrative_slot,
        "lane": lane,
        "orientation": "landscape" if resolution[0] > resolution[1] else "portrait",
        "duration_sec": duration_sec,
        "resolution": list(resolution),
        "fps": 16,
        "camera": camera,
        "subject": {"type": subject_type, "desc_zh": desc_zh},
        "prompt_en": f"{prompt_en}, {STYLE}",
        "first_frame_asset": asset,
        "negative": ["human face", "hands", "fingers", "text", "watermark", "logo", "deformed", "extra limbs"],
        "n_best": n_best,
        "retry_max": retry_max,
        "acceptance": dict(ACCEPTANCE),
        "fallback": {"type": "ken_burns", "asset": asset, "motion": motion, "duration_sec": duration_sec},
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(REPO / "templates" / "shotcards"))
    ap.add_argument("--clip-ref-min", type=float, default=None,
                    help="G3 校准后阈值(缺省保持冷启动 0.65; M5 阶段0.2 试点验证制定案)")
    ap.add_argument("--temporal-clip-min", type=float, default=None,
                    help="G4 校准后阈值(缺省保持冷启动 0.85)")
    ap.add_argument("--landscape", action="store_true", help="横版 832×480(仅当 A/B 判定全横版时使用)")
    args = ap.parse_args()
    if args.clip_ref_min is not None:
        ACCEPTANCE["clip_ref_min"] = args.clip_ref_min
    if args.temporal_clip_min is not None:
        ACCEPTANCE["temporal_clip_min"] = args.temporal_clip_min
    res = (832, 480) if args.landscape else (480, 832)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    kw = {"resolution": res}

    cards = [
        # ---- §5.1 十类测试资产 ----
        card("S01", "evidence_product", "object",
             "毛肚浸入沸腾红汤,油花翻涌,蒸汽升腾",
             "extreme close-up of fresh beef tripe dipped into boiling red spicy hotpot broth, oil bubbles, rising steam",
             "assets/products/maodu_01.png",
             {"scale": "closeup", "angle": "high_45", "motion": "slow_push_in", "depth": "shallow"}),
        card("S02", "hook_product", "object",
             "沸腾红汤锅底特写,辣椒花椒翻滚,热气蒸腾",
             "rolling boil of spicy red hotpot soup base with dried chilies and sichuan peppercorns, dramatic steam",
             "assets/products/soup_01.png",
             {"scale": "closeup", "angle": "eye_level", "motion": "slow_push_in", "depth": "shallow"},
             duration_sec=3),
        card("S03", "evidence_product", "object",
             "鲜虾滑被勺子舀起,胶质拉丝,晶莹饱满",
             "glossy hand-made shrimp paste being scooped, bouncy translucent texture, fresh and plump",
             "assets/products/shrimp_01.png",
             {"scale": "closeup", "angle": "high_45", "motion": "slow_pull_back", "depth": "shallow"}),
        card("S04", "evidence_product", "object",
             "肥牛卷在漏勺中涮熟,油脂亮泽,纹理漂亮",
             "marbled fatty beef slices blanching in a strainer over boiling broth, glistening, beautiful marbling",
             "assets/products/beef_01.png",
             {"scale": "medium", "angle": "high_45", "motion": "slow_push_in", "depth": "shallow"}),
        card("S05", "evidence_product", "object",
             "红糖糍粑甜品装盘,撒黄豆粉,温润光泽",
             "sweet fried glutinous rice cake with brown sugar syrup and soybean powder, dessert plating",
             "assets/products/dessert_01.png",
             {"scale": "closeup", "angle": "high_45", "motion": "orbit_slow", "depth": "shallow"},
             motion="zoom_out"),
        card("S06", "evidence_product", "object",
             "冰镇酸梅饮品,杯壁挂珠,气泡上浮",
             "iced plum drink in a tall glass, condensation droplets, fine bubbles rising, refreshing",
             "assets/products/drink_01.png",
             {"scale": "closeup", "angle": "eye_level", "motion": "slow_push_in", "depth": "shallow"}),
        card("S07", "ambiance_scene", "environment",
             "店内暖光蒸汽环境,木桌热气氤氲,灯笼虚化",
             "cozy hotpot restaurant interior, warm lantern light, steam drifting over wooden tables, bokeh",
             "assets/scenes/interior_01.png",
             {"scale": "wide", "angle": "eye_level", "motion": "slow_push_in", "depth": "medium"}),
        card("S08", "storefront_night", "environment",
             "门头夜景,暖黄灯笼亮起,雨后石板路反光",
             "restaurant storefront at night, glowing warm lanterns, wet stone street reflections, inviting",
             "assets/scenes/storefront_01.png",
             {"scale": "wide", "angle": "low_angle", "motion": "slow_push_in", "depth": "deep"}),
        card("S09", "rain_window", "environment",
             "雨窗氛围,水珠沿玻璃滑落,暖光晕染",
             "rain drops sliding down a window pane, warm interior light bokeh behind glass, moody atmosphere",
             "assets/scenes/rain_window_01.png",
             {"scale": "closeup", "angle": "eye_level", "motion": "static_hold", "depth": "shallow"},
             motion="pan_left"),
        card("S10", "ambiance_scene", "environment",
             "空餐桌摆位整齐,餐具反光,等待开席",
             "neatly set empty hotpot table, polished tableware, apricot pot centered, anticipation",
             "assets/scenes/table_01.png",
             {"scale": "medium", "angle": "high_45", "motion": "orbit_slow", "depth": "medium"},
             motion="pan_right"),
        # ---- 变体 1: 中风险(无人背影) —— n_best 放大 + 重试加码 ----
        card("S11", "ambiance_scene", "figure_back",
             "顾客背影走向桌位,只见背影不见正脸,暖光长廊",
             "a single diner silhouette seen from behind walking toward a table in a warm corridor, back view only",
             "assets/scenes/back_view_01.png",
             {"scale": "medium", "angle": "eye_level", "motion": "follow_slow", "depth": "medium"},
             n_best=4, retry_max=3),
        # ---- 变体 2: 高风险(手部入画) —— 风险表强制 lane=ken_burns 演示 ----
        card("S12", "evidence_product", "hands_action",
             "手部入画:筷子夹起毛肚在红汤中涮烫(高风险演示)",
             "close-up of chopsticks held by a hand dipping beef tripe into boiling red broth",
             "assets/products/maodu_01.png",
             {"scale": "closeup", "angle": "high_45", "motion": "static_hold", "depth": "shallow"},
             lane="ken_burns"),
        # ---- M5 补充变体 (阶段2.1): T3 即时优惠的 offer_product 槽位 + 模板变体差异化镜头 ----
        card("S13", "offer_product", "object",
             "鲜虾滑生坯特写,胶质拉丝,灯下晶莹(变体:轨道机位)",
             "glossy hand-made shrimp paste balls in a ceramic dish, translucent bouncy texture, glistening under warm light",
             "assets/products/shrimp_01.png",
             {"scale": "closeup", "angle": "high_45", "motion": "orbit_slow", "depth": "shallow"}),
        card("S14", "offer_product", "object",
             "冰镇酸梅汤倒入玻璃杯,气泡与冰块碰撞(变体:拉机位)",
             "iced plum juice being poured into a tall glass, ice cubes tumbling, fine bubbles, refreshing",
             "assets/products/drink_01.png",
             {"scale": "closeup", "angle": "eye_level", "motion": "slow_pull_back", "depth": "shallow"},
             motion="zoom_out"),
        card("S15", "evidence_product", "object",
             "红汤被铁勺扬起浇回锅底,辣椒翻腾(变体:俯拍推近)",
             "ladle pouring bubbling red spicy broth back into the hotpot, dried chilies swirling, dramatic steam",
             "assets/products/soup_01.png",
             {"scale": "closeup", "angle": "high_45", "motion": "slow_push_in", "depth": "shallow"}),
        card("S16", "ambiance_scene", "environment",
             "店内长廊灯笼成排,暖光纵深,桌位虚化(变体:横移)",
             "row of warm lanterns along the restaurant corridor, cozy depth, tables in soft bokeh",
             "assets/scenes/interior_01.png",
             {"scale": "medium", "angle": "eye_level", "motion": "pan_right", "depth": "medium"},
             motion="pan_right"),
        card("S17", "offer_product", "object",
             "鲜虾滑滑入沸腾红汤,翻滚定形(变体:俯拍推近)",
             "hand-made shrimp paste balls dropped into boiling red spicy broth, rolling and setting, bubbles",
             "assets/products/shrimp_01.png",
             {"scale": "closeup", "angle": "high_45", "motion": "slow_push_in", "depth": "shallow"}),
    ]

    # 画幅后处理: --landscape 时整批转横版 (仅当 M5 A/B 判定全横版才使用)
    for c in cards:
        c["resolution"] = list(res)
        c["orientation"] = "landscape" if res[0] > res[1] else "portrait"

    n_ok = 0
    for c in cards:
        validated = validate_shotcard(c)
        path = out / f"{c['shot_id']}_{c['narrative_slot']}.json"
        path.write_text(json.dumps(validated, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        n_ok += 1
        print(f"ok {path.name} (lane={c['lane']}, n_best={c['n_best']}, retry_max={c['retry_max']}, "
              f"acc_g3={ACCEPTANCE['clip_ref_min']}, acc_g4={ACCEPTANCE['temporal_clip_min']})")
    print(f"共生成 {n_ok} 张镜头卡 → {out} (res={res}, acceptance={ACCEPTANCE})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""叙事模板与镜头卡资产测试(§5.7/§5.1/§5.2): 真实文件校验。"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.compose import render_narration
from src.schema import (
    LANES,
    load_shotcard,
    load_template,
    risk_categories,
    total_duration,
    validate_shotcard,
)

REPO = Path(__file__).resolve().parents[1]
NARRATIVE = REPO / "templates" / "narrative"
SHOTCARDS = REPO / "templates" / "shotcards"

EXPECTED_TEMPLATES = {
    "product_seeding_25s.json": (25, 30),
    "store_ambiance_22s.json": (20, 25),
    "instant_offer_17s.json": (15, 20),
}


@pytest.mark.parametrize("fname", sorted(EXPECTED_TEMPLATES))
def test_narrative_templates_valid_and_in_range(fname):
    t = load_template(NARRATIVE / fname)
    lo, hi = EXPECTED_TEMPLATES[fname]
    assert t["duration_range"] == [lo, hi]
    total = total_duration(t["scenes"])
    assert lo <= total <= hi, f"{fname} 总时长 {total} 超出 [{lo},{hi}]"
    # narration 只引用已定义变量
    render_narration(t["scenes"], t["variables"], t["numbers"])
    # 数字字段独立存放
    assert isinstance(t["numbers"], dict) and t["numbers"]
    assert not any(ch.isdigit() for ch in json_dumps(t["variables"]))


def json_dumps(d) -> str:
    import json

    return json.dumps(d, ensure_ascii=False)


def test_template_scene_slots_bind_narrative_slots():
    t = load_template(NARRATIVE / "product_seeding_25s.json")
    slots = [sc["narrative_slot"] for sc in t["scenes"]]
    assert slots == ["hook_product", "evidence_product", "evidence_product", "evidence_product",
                     "ambiance_scene", "cta_store"]
    # CTA 为程序渲染贴片(background), 不需要生成镜头
    assert t["scenes"][-1].get("background", {}).get("type") == "solid"


def test_instant_offer_numbers_never_into_video_paths():
    from src.compose import plan_compose

    t = load_template(NARRATIVE / "instant_offer_17s.json")
    plan = plan_compose(t, {"offer_product": "op.mp4", "evidence_product": "ev.mp4"})
    for p in plan["video_paths"]:
        assert "9.9" not in p and "100" not in p
    joined = " ".join(text for _, _, text in plan["cues"])
    assert "9.9" in joined and "100" in joined  # 数字只进字幕


# ---------------- 镜头卡资产 ----------------

def _shotcard_files():
    return sorted(SHOTCARDS.glob("*.json"))


def test_12_shotcards_exist_and_valid():
    files = _shotcard_files()
    if len(files) < 12:
        pytest.skip("镜头卡尚未生成(服务器上由 tools/gen_shotcards.py 生成)")
    assert len(files) >= 12
    cards = [load_shotcard(f) for f in files]
    for c in cards:
        assert c["orientation"] == "portrait"
        assert c["resolution"] == [480, 832]
        assert c["fps"] == 16
        assert set(c["acceptance"]) == {"clip_ref_min", "clip_text_min", "temporal_clip_min",
                                        "vlm_overall_min", "vlm_defect_max", "duration_tol"}
        assert c["fallback"]["type"] == "ken_burns"
        # negative 必含人脸/手/文字
        assert any("face" in n for n in c["negative"])
        assert any("hand" in n for n in c["negative"])
        assert any("text" in n for n in c["negative"])
        # 主体描述为英文食物摄影风格, 无真人
        assert "no people" in c["prompt_en"] or "back view" in c["prompt_en"]


def test_shotcards_cover_ten_assets_and_two_variants():
    files = _shotcard_files()
    if len(files) < 12:
        pytest.skip("镜头卡尚未生成")
    cards = [load_shotcard(f) for f in files]
    assert len(cards) == 17  # M5: S13-S17 双锚镜头卡扩容(D-038..D-045)
    subjects = " ".join(c["subject"]["desc_zh"] for c in cards)
    for token in ("毛肚", "红汤", "虾滑", "肥牛", "糍粑", "酸梅", "蒸汽", "门头", "雨窗", "空餐桌"):
        assert token in subjects, f"缺少资产: {token}"
    # 槽位覆盖: 模板需要的所有非 background 槽位都有卡
    slots = {c["narrative_slot"] for c in cards}
    for need in ("hook_product", "evidence_product", "ambiance_scene", "storefront_night", "rain_window"):
        assert need in slots


def test_shotcard_medium_and_high_risk_design():
    files = _shotcard_files()
    if len(files) < 12:
        pytest.skip("镜头卡尚未生成")
    cards = [load_shotcard(f) for f in files]
    by_id = {c["shot_id"]: c for c in cards}

    # S11 中风险(无人背影): 允许生成, n_best 放大 + 重试加码
    s11 = by_id["S11"]
    assert "背影" in s11["subject"]["desc_zh"]
    assert risk_categories(s11["subject"]["desc_zh"] + " " + s11["subject"]["type"]) == []
    assert s11["lane"] == "first_frame_i2v"
    assert s11["n_best"] > 3 and s11["retry_max"] > 2

    # S12 高风险(手部入画): 风险表强制 ken_burns
    s12 = by_id["S12"]
    hits = risk_categories(s12["subject"]["desc_zh"] + " " + s12["subject"]["type"])
    assert "手部" in hits
    assert s12["lane"] == "ken_burns"

    # 主体名称在模板槽位与 lane 枚举内
    for c in cards:
        assert c["lane"] in LANES

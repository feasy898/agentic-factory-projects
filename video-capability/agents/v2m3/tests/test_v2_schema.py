"""v4 schema 三车道校验测试 (SPECS_V2 §5.1-§5.4)。"""

from __future__ import annotations

import pytest

from src.schema import (
    DETERMINISTIC_LANES,
    LANES,
    WAN_CONSUMING_LANES,
    SchemaError,
    is_food_or_product_subject,
    validate_shotcard,
)


def _with(base: dict, **kw) -> dict:
    d = {**base}
    for k, v in kw.items():
        if v is ...:
            d.pop(k, None)
        else:
            d[k] = v
    return d


def _env_card(valid_card: dict) -> dict:
    """合法 pure_gen_short 环境卡基底。"""
    return _with(
        valid_card,
        shot_id="SX09",
        lane="pure_gen_short",
        duration_sec=2,
        subject={"type": "environment", "desc_zh": "雨窗氛围,水珠滑落,暖光晕染"},
        prompt_en="rain drops sliding down a window pane, warm bokeh, no people",
        first_frame_asset="assets/scenes/rain_window_01.png",
        fallback={"type": "ken_burns", "asset": "assets/scenes/rain_window_01.png",
                  "motion": "zoom_in_1.06", "duration_sec": 2},
    )


def _evidence_card(valid_card: dict) -> dict:
    return _with(
        valid_card,
        shot_id="SX18",
        lane="evidence_transfer",
        evidence_asset="assets/evidence/synthetic_demo_source_01.mp4",
    )


# ---------------- 枚举 ----------------

def test_v4_lane_enum():
    assert LANES == {
        "first_frame_i2v", "pure_gen_short", "compositing_2d5",
        "evidence_transfer", "ken_burns", "future_3d_guided",
    }
    assert "t2v" not in LANES
    assert DETERMINISTIC_LANES == {"ken_burns", "compositing_2d5"}
    assert WAN_CONSUMING_LANES == {"first_frame_i2v", "pure_gen_short", "evidence_transfer"}


def test_t2v_no_longer_valid(valid_card):
    with pytest.raises(SchemaError) as e:
        validate_shotcard(_with(valid_card, lane="t2v"))
    assert any("lane" in m for m in e.value.errors)


def test_new_lanes_accepted(valid_card):
    validate_shotcard(_env_card(valid_card))
    validate_shotcard(_evidence_card(valid_card))
    c = _with(valid_card, lane="compositing_2d5", subject={"type": "food", "desc_zh": "毛肚"})
    c["evidence_asset"] = None
    validate_shotcard(c)


# ---------------- evidence_asset 字段规则 ----------------

def test_evidence_lane_requires_asset(valid_card):
    bad = _with(valid_card, lane="evidence_transfer")
    with pytest.raises(SchemaError) as e:
        validate_shotcard(bad)
    assert any("evidence_asset" in m for m in e.value.errors)


def test_evidence_asset_only_for_evidence_lane(valid_card):
    bad = _with(valid_card, evidence_asset="assets/evidence/x.mp4")
    with pytest.raises(SchemaError) as e:
        validate_shotcard(bad)
    assert any("evidence_asset" in m for m in e.value.errors)


def test_evidence_asset_null_ok_for_other_lanes(valid_card):
    validate_shotcard(_with(valid_card, evidence_asset=None))


# ---------------- pure_gen_short 红线 (§5.2) ----------------

def test_food_subject_type_banned_in_puregen(valid_card):
    bad = _env_card(valid_card)
    bad["subject"] = {"type": "food", "desc_zh": "沸腾锅底"}
    with pytest.raises(SchemaError) as e:
        validate_shotcard(bad)
    assert any("pure_gen_short" in m and "食物" in m for m in e.value.errors)


def test_food_keyword_in_desc_banned_in_puregen(valid_card):
    bad = _env_card(valid_card)
    bad["subject"] = {"type": "environment", "desc_zh": "店内环境,桌上有虾滑与红汤锅底"}
    with pytest.raises(SchemaError) as e:
        validate_shotcard(bad)
    assert any("食物/产品" in m for m in e.value.errors)


def test_food_english_keyword_banned_in_puregen(valid_card):
    bad = _env_card(valid_card)
    bad["subject"] = {"type": "environment", "desc_zh": "店内环境",
                      "desc_en": "steaming hot pot interior"}
    with pytest.raises(SchemaError) as e:
        validate_shotcard(bad)
    assert any("食物/产品" in m for m in e.value.errors)


def test_prompt_en_food_words_do_not_trigger(valid_card):
    """判定面=subject 字段; 场景 prompt 中的 hotpot restaurant 属环境语义, 不触发红线。"""
    ok = _env_card(valid_card)
    ok["prompt_en"] = "cozy hotpot restaurant interior, steam drifting over wooden tables"
    validate_shotcard(ok)


def test_puregen_duration_constrained(valid_card):
    bad = _env_card(valid_card)
    bad["duration_sec"] = 5
    with pytest.raises(SchemaError) as e:
        validate_shotcard(bad)
    assert any("1.0-2.0s" in m for m in e.value.errors)
    validate_shotcard(_env_card(valid_card))  # 2s 合法


def test_is_food_or_product_subject(valid_card):
    assert is_food_or_product_subject({"subject": {"type": "food"}})
    assert is_food_or_product_subject({"subject": {"type": "product"}})
    assert is_food_or_product_subject({"subject": {"type": "object", "desc_zh": "鲜虾滑"}})
    assert not is_food_or_product_subject(
        {"subject": {"type": "environment", "desc_zh": "雨窗灯影"},
         "prompt_en": "hotpot restaurant storefront"})


# ---------------- v1 兼容回归 ----------------

def test_v1_valid_card_still_passes(valid_card):
    out = validate_shotcard(valid_card)
    assert out["lane"] == "first_frame_i2v"

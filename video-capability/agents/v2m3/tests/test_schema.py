"""镜头卡/叙事模板 schema 校验测试 (含风险表)。"""

from __future__ import annotations

import pytest

from src.schema import (
    SchemaError,
    load_template,
    risk_categories,
    total_duration,
    validate_narrative_template,
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


# ---------------- 合法卡 ----------------

def test_valid_card_passes(valid_card):
    out = validate_shotcard(valid_card)
    assert out["shot_id"] == "S03"
    assert out is not valid_card  # 深拷贝


# ---------------- 字段完整性 ----------------

@pytest.mark.parametrize("field", ["shot_id", "narrative_slot", "lane", "orientation", "duration_sec",
                                   "resolution", "fps", "camera", "subject", "prompt_en",
                                   "first_frame_asset", "negative", "n_best", "retry_max",
                                   "acceptance", "fallback"])
def test_missing_field_rejected(valid_card, field):
    with pytest.raises(SchemaError) as e:
        validate_shotcard(_with(valid_card, **{field: ...}))
    assert any(field in msg for msg in e.value.errors)


def test_unknown_field_rejected(valid_card):
    with pytest.raises(SchemaError) as e:
        validate_shotcard(_with(valid_card, surprise=1))
    assert any("未定义字段" in m for m in e.value.errors)


def test_errors_are_chinese(valid_card):
    bad = _with(valid_card, lane="warp_drive")
    with pytest.raises(SchemaError) as e:
        validate_shotcard(bad)
    assert "lane" in e.value.errors[0] and "车道" in str(e.value) and "镜头卡校验失败" in str(e.value)


# ---------------- 枚举/类型/范围 ----------------

def test_bad_lane(valid_card):
    with pytest.raises(SchemaError):
        validate_shotcard(_with(valid_card, lane="t2vx"))


def test_bad_orientation(valid_card):
    with pytest.raises(SchemaError):
        validate_shotcard(_with(valid_card, orientation="square"))


def test_bad_resolution(valid_card):
    with pytest.raises(SchemaError):
        validate_shotcard(_with(valid_card, resolution=[480]))
    with pytest.raises(SchemaError):
        validate_shotcard(_with(valid_card, resolution=[480, 832.5]))


def test_bad_fps_and_duration(valid_card):
    with pytest.raises(SchemaError):
        validate_shotcard(_with(valid_card, fps=0))
    with pytest.raises(SchemaError):
        validate_shotcard(_with(valid_card, duration_sec=0))
    with pytest.raises(SchemaError):
        validate_shotcard(_with(valid_card, duration_sec=999))


def test_bad_n_best_retry(valid_card):
    with pytest.raises(SchemaError):
        validate_shotcard(_with(valid_card, n_best=0))
    with pytest.raises(SchemaError):
        validate_shotcard(_with(valid_card, retry_max=-1))


def test_bad_acceptance(valid_card):
    acc = dict(valid_card["acceptance"])
    acc["clip_ref_min"] = 1.5
    with pytest.raises(SchemaError):
        validate_shotcard(_with(valid_card, acceptance=acc))
    acc2 = dict(valid_card["acceptance"])
    del acc2["duration_tol"]
    with pytest.raises(SchemaError):
        validate_shotcard(_with(valid_card, acceptance=acc2))


def test_bad_fallback_motion(valid_card):
    fb = dict(valid_card["fallback"])
    fb["motion"] = "spin_360"
    with pytest.raises(SchemaError):
        validate_shotcard(_with(valid_card, fallback=fb))


# ---------------- negative 必含语义项 ----------------

@pytest.mark.parametrize("drop_all,expect", [
    (["human face", "faces"], "人脸"),
    (["hands", "fingers"], "手部"),
    (["text", "watermark", "logo"], "文字"),
])
def test_negative_missing_semantics(valid_card, drop_all, expect):
    neg = [n for n in valid_card["negative"] if n not in drop_all]
    with pytest.raises(SchemaError) as e:
        validate_shotcard(_with(valid_card, negative=neg))
    assert any(expect in m for m in e.value.errors)


def test_negative_semantic_synonyms_accepted(valid_card):
    # 同义词条目可互相覆盖语义要求(手部: fingers; 文字: watermark)
    neg = ["human face", "fingers", "watermark", "deformed"]
    assert validate_shotcard(_with(valid_card, negative=neg))["negative"] == neg


# ---------------- 风险表 ----------------

def test_risk_categories_detection():
    assert "人脸" in risk_categories("一位女性的脸庞特写")
    assert "人脸" in risk_categories("a woman face closeup")
    assert "手部" in risk_categories("手指按快门")
    assert "手部" in risk_categories("hands holding chopsticks")
    assert "多主体" in risk_categories("两个人碰杯")
    assert "多主体" in risk_categories("a crowd of people")
    assert "文字数字" in risk_categories("菜单文字清晰可见")
    assert "文字数字" in risk_categories("price numbers on the tag")
    assert risk_categories("一碗红汤翻滚,热气腾腾") == []


def test_high_risk_requires_kenburns(valid_card):
    bad = _with(valid_card, subject={"type": "hands_action", "desc_zh": "手部入画,筷子夹菜"})
    with pytest.raises(SchemaError) as e:
        validate_shotcard(bad)
    assert any("ken_burns" in m for m in e.value.errors)

    ok = _with(valid_card, lane="ken_burns",
               subject={"type": "hands_action", "desc_zh": "手部入画,筷子夹菜"})
    assert validate_shotcard(ok)["lane"] == "ken_burns"


@pytest.mark.parametrize("desc,cat", [
    ("两个顾客碰杯大笑", "多主体"),
    ("招牌上写着数字88", "文字数字"),
    ("人脸大特写微笑", "人脸"),
])
def test_risk_table_categories(valid_card, desc, cat):
    bad = _with(valid_card, subject={"type": "object", "desc_zh": desc})
    with pytest.raises(SchemaError) as e:
        validate_shotcard(bad)
    assert any(cat in m for m in e.value.errors)


def test_low_risk_passes(valid_card):
    assert validate_shotcard(valid_card)["lane"] == "first_frame_i2v"


# ---------------- 叙事模板 ----------------

def test_template_valid_and_duration():
    t = {
        "template_id": "t1", "name_zh": "测试", "duration_range": [10, 15], "orientation": "portrait",
        "variables": {"p": "毛肚"}, "numbers": {"price": "39.9"},
        "scenes": [
            {"slot": "a", "narrative_slot": "hook_product", "duration_sec": 3, "role": "hook",
             "narration": "{p}来了"},
            {"slot": "b", "narrative_slot": "evidence_product", "duration_sec": 5, "role": "evidence",
             "narration": "只要{price}"},
            {"slot": "c", "narrative_slot": "cta_store", "duration_sec": 4, "role": "cta",
             "narration": "冲"},
        ],
    }
    out = validate_narrative_template(t)
    assert total_duration(out["scenes"]) == 12


def test_template_duration_out_of_range():
    t = {
        "template_id": "t2", "name_zh": "测试", "duration_range": [10, 12], "orientation": "portrait",
        "variables": {}, "numbers": {},
        "scenes": [
            {"slot": "a", "narrative_slot": "hook_product", "duration_sec": 8, "role": "hook", "narration": "x"},
            {"slot": "b", "narrative_slot": "cta_store", "duration_sec": 8, "role": "cta", "narration": "y"},
        ],
    }
    with pytest.raises(SchemaError) as e:
        validate_narrative_template(t)
    assert any("超出区间" in m for m in e.value.errors)


def test_template_undefined_variable():
    t = {
        "template_id": "t3", "name_zh": "测试", "duration_range": [5, 20], "orientation": "portrait",
        "variables": {}, "numbers": {},
        "scenes": [
            {"slot": "a", "narrative_slot": "hook_product", "duration_sec": 5, "role": "hook",
             "narration": "价格{price}元"},
        ],
    }
    with pytest.raises(SchemaError) as e:
        validate_narrative_template(t)
    assert any("未定义变量" in m for m in e.value.errors)


def test_template_missing_scene_field():
    t = {
        "template_id": "t4", "name_zh": "测试", "duration_range": [1, 20], "orientation": "portrait",
        "variables": {}, "numbers": {},
        "scenes": [{"slot": "a", "narrative_slot": "x", "duration_sec": 2, "narration": "n"}],
    }
    with pytest.raises(SchemaError) as e:
        validate_narrative_template(t)
    assert any("role" in m for m in e.value.errors)


# ---------------- V2-M1: expected_static_mask 可选字段 (SPECS_V2 §3-G7c) ----------------

def test_expected_static_mask_optional_valid(valid_card):
    out = validate_shotcard(_with(valid_card, expected_static_mask=None))
    assert out["expected_static_mask"] is None
    out2 = validate_shotcard(_with(valid_card, expected_static_mask="workdir/masks/S03_static.png"))
    assert out2["expected_static_mask"].endswith(".png")


def test_expected_static_mask_invalid_type(valid_card):
    with pytest.raises(SchemaError) as e:
        validate_shotcard(_with(valid_card, expected_static_mask=123))
    assert any("expected_static_mask" in m for m in e.value.errors)
    with pytest.raises(SchemaError) as e2:
        validate_shotcard(_with(valid_card, expected_static_mask="  "))
    assert any("expected_static_mask" in m for m in e2.value.errors)


def test_unknown_field_still_rejected(valid_card):
    with pytest.raises(SchemaError) as e:
        validate_shotcard(_with(valid_card, expected_mask_typo="x"))
    assert any("未定义字段" in m for m in e.value.errors)

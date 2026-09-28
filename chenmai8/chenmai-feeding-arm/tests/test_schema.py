"""cs_schema 契约测试（开发指令 §5.0）。

eval 命令（在仓库根执行）::

    .venv/Scripts/python.exe -m pytest tests/test_schema.py -q

通过线：用例全绿。覆盖面：
1) §3.1 全部 8 个契约模型可从夹具构造，JSON roundtrip 逐字段一致；
2) 全部枚举的成员值与冻结字面量完全一致，且接受字面量字符串构造；
3) 非法值负例（取值越界 / 未知枚举 / 长度不符 / NaN / 额外字段）抛 ValidationError；
4) 跨字段不变式（invalid→confidence=0、violation→clear_to_move=False、
   时间戳有序、target 长度与 mode 匹配），含属性赋值路径（validate_assignment）；
5) 夹具装载器与冻结常量。
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

import chengshao.cs_schema as cs_schema
from chengshao.cs_schema import (
    DEFAULT_DISH_REGISTRY,
    EE_POS_LEN,
    EE_QUAT_LEN,
    N_ARM_JOINTS,
    SCHEMA_VERSION,
    ArmCommand,
    ArmState,
    BiteOutcome,
    BiteRecord,
    CommandFrame,
    CommandMode,
    IntentKind,
    MealSession,
    MouthPose,
    MouthSource,
    SafetyState,
    SpoonCheck,
    ViolationKind,
    VoiceIntent,
    load_fixture,
    load_model,
    load_model_fixture,
)

# §3.1 冻结的 8 个模型 × 全部夹具样例
FIXTURE_CASES = [
    (MouthPose, "mouth_pose"),
    (ArmState, "arm_state"),
    (ArmCommand, "arm_command_joints"),
    (ArmCommand, "arm_command_cartesian"),
    (SafetyState, "safety_state_clear"),
    (SafetyState, "safety_state_estop"),
    (SpoonCheck, "spoon_check"),
    (VoiceIntent, "voice_intent_select"),
    (VoiceIntent, "voice_intent_next"),
    (BiteRecord, "bite_record"),
    (MealSession, "meal_session"),
]

ALL_MODELS = [
    MouthPose,
    ArmState,
    ArmCommand,
    SafetyState,
    SpoonCheck,
    VoiceIntent,
    BiteRecord,
    MealSession,
]


# ---- 1) 夹具构造 + JSON roundtrip -------------------------------------------


@pytest.mark.parametrize(("model_cls", "name"), FIXTURE_CASES)
def test_fixture_constructs(model_cls, name):
    model = model_cls.model_validate(load_fixture(name))
    assert isinstance(model, model_cls)


@pytest.mark.parametrize(("model_cls", "name"), FIXTURE_CASES)
def test_fixture_json_roundtrip(model_cls, name):
    model = model_cls.model_validate(load_fixture(name))
    # dict 往返
    assert model == model_cls.model_validate(model.model_dump())
    # JSON 字符串往返，且 JSON 形态与 mode="json" 的 dict 一致
    payload = model.model_dump_json()
    assert json.loads(payload) == model.model_dump(mode="json")
    assert model_cls.model_validate_json(payload) == model


@pytest.mark.parametrize("model_cls", ALL_MODELS)
def test_every_contract_model_has_model_config(model_cls):
    # 全部模型继承同一契约基类：拒额外字段、拒 NaN/Inf、赋值过校验
    assert model_cls.model_config.get("extra") == "forbid"
    assert model_cls.model_config.get("allow_inf_nan") is False
    assert model_cls.model_config.get("validate_assignment") is True


def test_every_contract_model_has_named_fixture():
    # 每个模型类名都有同名夹具（load_model_fixture 走类名 -> snake_case）
    for model_cls in ALL_MODELS:
        assert isinstance(load_model_fixture(model_cls), model_cls)


# ---- 2) 枚举冻结字面量 -------------------------------------------------------

@pytest.mark.parametrize(
    ("enum_cls", "frozen_values"),
    [
        (MouthSource, ("depth", "mono")),
        (CommandMode, ("joints", "cartesian")),
        (CommandFrame, ("base",)),
        (ViolationKind, ("none", "face_in_zone", "speed", "torque", "watchdog")),
        (IntentKind, ("next", "pause", "resume", "done", "select", "greet", "unknown")),
        (BiteOutcome, ("success", "retry", "rejected", "aborted")),
    ],
)
def test_enum_values_equal_frozen_literals(enum_cls, frozen_values):
    assert tuple(member.value for member in enum_cls) == frozen_values


def test_enum_accepts_frozen_literal_strings():
    # 字符串字面量可直接构造枚举，也可作为字段输入（校验后成为枚举成员）
    assert MouthSource("mono") is MouthSource.MONO
    pose = MouthPose.model_validate(_mouth_pose(source="mono"))
    assert pose.source is MouthSource.MONO
    assert pose.model_dump(mode="json")["source"] == "mono"
    with pytest.raises(ValidationError):
        MouthPose.model_validate(_mouth_pose(source="stereo"))


# ---- 3) MouthPose -----------------------------------------------------------


def _mouth_pose(**overrides):
    data = load_fixture("mouth_pose")
    data.update(overrides)
    return data


def test_mouth_pose_invalid_requires_zero_confidence():
    with pytest.raises(ValidationError):
        MouthPose.model_validate(_mouth_pose(valid=False, confidence=0.4))


def test_mouth_pose_invalid_with_zero_confidence_ok():
    pose = MouthPose.model_validate(_mouth_pose(valid=False, confidence=0.0))
    assert pose.valid is False
    assert pose.confidence == 0.0


@pytest.mark.parametrize(
    "overrides",
    [
        {"confidence": 1.5},  # 越上界
        {"confidence": -0.01},  # 越下界
        {"jaw_open": 1.2},
        {"frown": -0.1},
        {"ts_ns": -1},  # 时间戳非负
        {"x": float("nan")},  # NaN 拒绝
        {"source": "stereo"},  # 未知来源
    ],
)
def test_mouth_pose_rejects_bad_values(overrides):
    with pytest.raises(ValidationError):
        MouthPose.model_validate(_mouth_pose(**overrides))


def test_mouth_pose_rejects_extra_field():
    with pytest.raises(ValidationError):
        MouthPose.model_validate(_mouth_pose(depth_m=0.4))


# ---- 4) ArmState ------------------------------------------------------------


def _arm_state(**overrides):
    data = load_fixture("arm_state")
    data.update(overrides)
    return data


def test_arm_state_rejects_wrong_joint_count():
    bad = _arm_state(joint_pos=[0.0] * (N_ARM_JOINTS - 1))
    with pytest.raises(ValidationError):
        ArmState.model_validate(bad)


def test_arm_state_rejects_wrong_quat_length():
    bad = _arm_state(ee_quat=[1.0] * (EE_QUAT_LEN - 1))
    with pytest.raises(ValidationError):
        ArmState.model_validate(bad)


def test_arm_state_rejects_wrong_ee_pos_length():
    bad = _arm_state(ee_pos=[0.1] * (EE_POS_LEN + 1))
    with pytest.raises(ValidationError):
        ArmState.model_validate(bad)


def test_arm_state_rejects_duplicate_joint_names():
    names = ["joint1", "joint1", "joint3", "joint4", "joint5", "joint6", "gripper"]
    with pytest.raises(ValidationError):
        ArmState.model_validate(_arm_state(joint_names=names))


# ---- 5) ArmCommand ----------------------------------------------------------


def _arm_command(**overrides):
    data = load_fixture("arm_command_joints")
    data.update(overrides)
    return data


@pytest.mark.parametrize(
    "overrides",
    [
        {"mode": "pose"},  # 未知模式
        {"mode": "joints", "target": [0.1] * (N_ARM_JOINTS - 2)},  # 长度与模式不符
        {"mode": "cartesian", "target": [0.1] * 4},  # cartesian 只允许 3 或 7
        {"max_speed": 0.0},  # 速度上限必须为正
        {"timeout_s": -1.0},  # 超时必须为正
        {"frame": "tool"},  # MVP 冻结 base 系
    ],
)
def test_arm_command_rejects_bad_values(overrides):
    with pytest.raises(ValidationError):
        ArmCommand.model_validate(_arm_command(**overrides))


def test_arm_command_cartesian_accepts_pos_only_and_full():
    ok3 = ArmCommand.model_validate(_arm_command(mode="cartesian", target=[0.3, 0.0, 0.2]))
    assert len(ok3.target) == 3
    ok7 = ArmCommand.model_validate(
        _arm_command(mode="cartesian", target=[0.3, 0.0, 0.2, 0.0, 0.0, 0.0, 1.0])
    )
    assert len(ok7.target) == 7


# ---- 6) SafetyState ---------------------------------------------------------


def _safety_state(**overrides):
    data = load_fixture("safety_state_clear")
    data.update(overrides)
    return data


def test_safety_state_violation_forces_clear_to_move_false():
    with pytest.raises(ValidationError):
        SafetyState.model_validate(
            _safety_state(violation="face_in_zone", clear_to_move=True)
        )


def test_safety_state_unknown_violation_rejected():
    with pytest.raises(ValidationError):
        SafetyState.model_validate(_safety_state(violation="locked"))


def test_safety_state_estop_fixture_is_blocking():
    estop = load_model("safety_state_estop", SafetyState)
    assert estop.estop_latched is True
    assert estop.clear_to_move is False
    assert estop.violation is not ViolationKind.NONE


# ---- 7) SpoonCheck ----------------------------------------------------------


def _spoon_check(**overrides):
    data = load_fixture("spoon_check")
    data.update(overrides)
    return data


def test_spoon_check_rejects_score_out_of_range():
    with pytest.raises(ValidationError):
        SpoonCheck.model_validate(_spoon_check(score=1.2))


def test_spoon_check_rejects_empty_cam_ref():
    with pytest.raises(ValidationError):
        SpoonCheck.model_validate(_spoon_check(cam_ref=""))


# ---- 8) VoiceIntent ---------------------------------------------------------


def _voice_intent(**overrides):
    data = load_fixture("voice_intent_next")
    data.update(overrides)
    return data


def test_voice_intent_rejects_unknown_intent():
    with pytest.raises(ValidationError):
        VoiceIntent.model_validate(_voice_intent(intent="stop"))


def test_voice_intent_rejects_confidence_out_of_range():
    with pytest.raises(ValidationError):
        VoiceIntent.model_validate(_voice_intent(confidence=1.1))


def test_voice_intent_select_dish_in_default_registry():
    select = load_model("voice_intent_select", VoiceIntent)
    assert select.intent is IntentKind.SELECT
    assert select.slots["dish"] in DEFAULT_DISH_REGISTRY


# ---- 9) BiteRecord ----------------------------------------------------------


def _bite_record(**overrides):
    data = load_fixture("bite_record")
    data.update(overrides)
    return data


def test_bite_record_rejects_end_before_start():
    bad = _bite_record(ts_end_ns=_bite_record()["ts_start_ns"] - 1)
    with pytest.raises(ValidationError):
        BiteRecord.model_validate(bad)


def test_bite_record_rejects_unknown_outcome():
    with pytest.raises(ValidationError):
        BiteRecord.model_validate(_bite_record(outcome="failed"))


def test_bite_record_grams_optional_and_non_negative():
    # 无称重硬件时 grams 为 None（契约允许）；负数拒绝
    record = BiteRecord.model_validate(_bite_record())
    assert record.grams_before is None and record.grams_after is None
    with pytest.raises(ValidationError):
        BiteRecord.model_validate(_bite_record(grams_before=-1.0))


# ---- 10) MealSession --------------------------------------------------------


def _meal_session(**overrides):
    data = load_fixture("meal_session")
    data.update(overrides)
    return data


def test_meal_session_nested_bites_validate_and_count():
    session = MealSession.model_validate(_meal_session())
    assert len(session.bites) == 2
    assert all(isinstance(b, BiteRecord) for b in session.bites)
    assert session.ended_ns is None  # 进行中


def test_meal_session_rejects_end_before_start():
    with pytest.raises(ValidationError):
        MealSession.model_validate(_meal_session(ended_ns=1))


def test_meal_session_rejects_blank_ids():
    with pytest.raises(ValidationError):
        MealSession.model_validate(_meal_session(session_id=""))
    with pytest.raises(ValidationError):
        MealSession.model_validate(_meal_session(user_id=""))


def test_meal_session_rejects_negative_total_grams():
    with pytest.raises(ValidationError):
        MealSession.model_validate(_meal_session(total_grams=-0.5))


# ---- 11) 赋值路径同样过校验（validate_assignment） ----------------------------


def test_assignment_rejects_out_of_range():
    check = load_model("spoon_check", SpoonCheck)
    with pytest.raises(ValidationError):
        check.score = 3.0


def test_assignment_cannot_break_cross_field_invariant():
    pose = load_model("mouth_pose", MouthPose)
    with pytest.raises(ValidationError):
        pose.valid = False  # confidence 仍为 0.91 → 违反 invalid→confidence=0


# ---- 12) 夹具装载器与冻结常量 ------------------------------------------------


def test_load_fixture_returns_raw_dict():
    data = load_fixture("arm_state")
    assert isinstance(data, dict)
    assert len(data["joint_names"]) == N_ARM_JOINTS


def test_load_model_validates_against_contract():
    state = load_model("arm_state", ArmState)
    assert state.ee_pos == [0.3, 0.02, 0.18]


def test_load_unknown_fixture_raises():
    with pytest.raises(FileNotFoundError):
        load_fixture("no_such_fixture")


def test_frozen_dimension_constants():
    assert N_ARM_JOINTS == 7  # 6 臂关节 + 夹爪
    assert EE_POS_LEN == 3
    assert EE_QUAT_LEN == 4


def test_default_dish_registry_is_nonempty_and_unique():
    assert len(DEFAULT_DISH_REGISTRY) >= 3
    assert len(set(DEFAULT_DISH_REGISTRY)) == len(DEFAULT_DISH_REGISTRY)
    assert "芋泥" in DEFAULT_DISH_REGISTRY


def test_schema_version_frozen():
    assert SCHEMA_VERSION == "1.0.0"
    assert cs_schema.SCHEMA_VERSION == "1.0.0"
    assert cs_schema.CONTRACT_FROZEN_DATE == "2026-09-28"

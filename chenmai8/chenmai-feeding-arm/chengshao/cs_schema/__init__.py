"""数据契约包：跨模块数据结构、枚举与常量的唯一事实来源（pydantic v2）。

冻结契约见开发指令 §3.1：全部模型为 pydantic v2 BaseModel，JSON 可序列化，
时间戳单位为纳秒（ns）。本包不得依赖其他 cs_* 包。

版本：SCHEMA_VERSION = 1.1.0（v1.0 于 2026-09-28 冻结；v1.1 同日修订）。
v1.1 变更（只增不改名/不改既有值，修订一处维度常量）：
  - N_ARM_JOINTS 7 -> 6（与 6 舵机参考模型/cs_sim 模型一致，撤销执行层映射假设）；
  - 追加 MouthSource.WRIST（腕部双职：IPD 瞳距先验 + FK 相机位姿）；
  - 追加 CameraRole 枚举（黑板键 camera_role：scene / wrist_mouth）。
冻结纪律：模型字段名、枚举成员值、常量名只增不改名/不改值/不删除。
"""

from __future__ import annotations

from .constants import (
    CARTESIAN_TARGET_FULL,
    CARTESIAN_TARGET_POS_ONLY,
    DEFAULT_DISH_REGISTRY,
    EE_POS_LEN,
    EE_QUAT_LEN,
    FROWN_ASK_THRESHOLD,
    HEAD_YAW_TURN_THRESHOLD_RAD,
    IPD_DEFAULT_M,
    JAW_OPEN_THRESHOLD,
    MOUTH_PRIOR_DEFAULT_M,
    N_ARM_JOINTS,
)
from .enums import (
    BiteOutcome,
    CameraRole,
    CommandFrame,
    CommandMode,
    IntentKind,
    MouthSource,
    ViolationKind,
)
from .fixtures import (
    FIXTURES_DIR,
    fixture_path,
    load_fixture,
    load_model,
    load_model_fixture,
    save_fixture,
)
from .models import (
    ArmCommand,
    ArmState,
    BiteRecord,
    MealSession,
    MouthPose,
    SafetyState,
    SpoonCheck,
    VoiceIntent,
)

SCHEMA_VERSION = "1.1.0"
CONTRACT_FROZEN_DATE = "2026-09-28"

__all__ = [
    # 契约模型（§3.1 全部 8 个）
    "ArmCommand",
    "ArmState",
    "BiteRecord",
    "MealSession",
    "MouthPose",
    "SafetyState",
    "SpoonCheck",
    "VoiceIntent",
    # 枚举
    "BiteOutcome",
    "CameraRole",
    "CommandFrame",
    "CommandMode",
    "IntentKind",
    "MouthSource",
    "ViolationKind",
    # 常量
    "CARTESIAN_TARGET_FULL",
    "CARTESIAN_TARGET_POS_ONLY",
    "DEFAULT_DISH_REGISTRY",
    "EE_POS_LEN",
    "EE_QUAT_LEN",
    "FROWN_ASK_THRESHOLD",
    "HEAD_YAW_TURN_THRESHOLD_RAD",
    "IPD_DEFAULT_M",
    "JAW_OPEN_THRESHOLD",
    "MOUTH_PRIOR_DEFAULT_M",
    "N_ARM_JOINTS",
    # 夹具与版本
    "CONTRACT_FROZEN_DATE",
    "FIXTURES_DIR",
    "SCHEMA_VERSION",
    "fixture_path",
    "load_fixture",
    "load_model",
    "load_model_fixture",
    "save_fixture",
]

"""冻结数据契约（开发指令 §3.1）。

全部模型为 pydantic v2 BaseModel，JSON 可序列化，时间戳一律纳秒（ns）。
冻结纪律：字段名与取值域只增不改名。

通用约束（基类统一施加）：
- extra="forbid"：未声明字段一律拒绝（防拼写漂移、防版本串味）；
- allow_inf_nan=False：NaN/Inf 一律拒绝；
- validate_assignment=True：属性赋值同样过校验，跨字段不变式运行期不可破坏。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .constants import (
    CARTESIAN_TARGET_FULL,
    CARTESIAN_TARGET_POS_ONLY,
    EE_POS_LEN,
    EE_QUAT_LEN,
    N_ARM_JOINTS,
)
from .enums import (
    BiteOutcome,
    CommandFrame,
    CommandMode,
    IntentKind,
    MouthSource,
    ViolationKind,
)


class _ContractModel(BaseModel):
    """契约模型基类。"""

    model_config = ConfigDict(
        extra="forbid",
        allow_inf_nan=False,
        validate_assignment=True,
    )


class MouthPose(_ContractModel):
    """口部三维状态（base 系）。

    约定：valid=False 时 x/y/z 必须沿用上一有效值且 confidence=0
    （保持动作由生产方——口部估计器——负责，本契约校验 confidence 侧）。
    """

    ts_ns: int = Field(ge=0, description="采样时间戳（ns）")
    valid: bool = Field(description="本次检测是否有效")
    x: float = Field(description="口部位置 X（米，base 系，X 朝用户）")
    y: float = Field(description="口部位置 Y（米，base 系，Y 朝左）")
    z: float = Field(description="口部位置 Z（米，base 系，Z 朝上）")
    jaw_open: float = Field(ge=0.0, le=1.0, description="张嘴开合度（0-1）")
    frown: float = Field(ge=0.0, le=1.0, description="皱眉强度（0-1）")
    head_yaw: float = Field(description="头部偏航（rad）")
    head_pitch: float = Field(description="头部俯仰（rad）")
    head_roll: float = Field(description="头部翻滚（rad）")
    source: MouthSource = Field(description="坐标来源：depth / mono")
    confidence: float = Field(ge=0.0, le=1.0, description="检测置信度（0-1）")

    @model_validator(mode="after")
    def _invalid_implies_zero_confidence(self) -> "MouthPose":
        if not self.valid and self.confidence != 0.0:
            raise ValueError("valid=False 时 confidence 必须为 0（坐标沿用上一有效值）")
        return self


class ArmState(_ContractModel):
    """机械臂全量状态（回读）。

    7 关节 = 6 个臂关节 + 1 个末端夹爪关节，统一编入数组；
    ee_pos 由 FK 算出（base 系，米）；ee_quat 为单位四元数 [w, x, y, z]。
    """

    ts_ns: int = Field(ge=0, description="采样时间戳（ns）")
    joint_names: list[str] = Field(
        min_length=N_ARM_JOINTS, max_length=N_ARM_JOINTS, description="关节名（7，唯一）"
    )
    joint_pos: list[float] = Field(
        min_length=N_ARM_JOINTS, max_length=N_ARM_JOINTS, description="关节角（rad）"
    )
    joint_vel: list[float] = Field(
        min_length=N_ARM_JOINTS, max_length=N_ARM_JOINTS, description="关节角速度（rad/s）"
    )
    ee_pos: list[float] = Field(
        min_length=EE_POS_LEN,
        max_length=EE_POS_LEN,
        description="末端位置 [x, y, z]（米，base 系，FK 算出）",
    )
    ee_quat: list[float] = Field(
        min_length=EE_QUAT_LEN,
        max_length=EE_QUAT_LEN,
        description="末端姿态四元数 [w, x, y, z]",
    )

    @model_validator(mode="after")
    def _joint_names_unique(self) -> "ArmState":
        if len(set(self.joint_names)) != N_ARM_JOINTS:
            raise ValueError("joint_names 必须互不相同")
        return self


class ArmCommand(_ContractModel):
    """机械臂运动指令。

    纪律：只能由 SafetyEnvelope（限速/禁入区/急停/看门狗）组装并下发到底层，
    其他模块不得绕过包络直接触达执行器。
    """

    mode: CommandMode = Field(description="目标空间：joints / cartesian")
    target: list[float] = Field(
        description=(
            "joints：7 关节目标（rad）；"
            "cartesian：base 系 3 位置（姿态保持）或 3 位置 + 4 四元数全量"
        )
    )
    max_speed: float = Field(gt=0.0, description="速度上限（joints: rad/s；cartesian: m/s）")
    timeout_s: float = Field(gt=0.0, description="指令超时（s）")
    frame: CommandFrame = Field(default=CommandFrame.BASE, description="参考系（冻结 base）")

    @model_validator(mode="after")
    def _target_length_matches_mode(self) -> "ArmCommand":
        if self.mode is CommandMode.JOINTS:
            if len(self.target) != N_ARM_JOINTS:
                raise ValueError(f"joints 模式 target 长度必须为 {N_ARM_JOINTS}")
        elif len(self.target) not in (CARTESIAN_TARGET_POS_ONLY, CARTESIAN_TARGET_FULL):
            raise ValueError(
                "cartesian 模式 target 长度必须为 "
                f"{CARTESIAN_TARGET_POS_ONLY}（仅位置）或 {CARTESIAN_TARGET_FULL}（位姿全量）"
            )
        return self


class SafetyState(_ContractModel):
    """安全状态（SafetyEnvelope 对外快照）。

    冻结约束：violation != "none" 时 clear_to_move 必须为 False，
    直到显式 reset()；急停 latch 应同时置 violation（如 watchdog）。
    """

    ts_ns: int = Field(ge=0, description="采样时间戳（ns）")
    estop_latched: bool = Field(description="急停是否处于闩锁状态")
    human_zone_violation: bool = Field(description="禁入区是否正被侵入")
    violation: ViolationKind = Field(description="当前违规类别")
    clear_to_move: bool = Field(description="是否允许继续运动")

    @model_validator(mode="after")
    def _violation_blocks_motion(self) -> "SafetyState":
        if self.violation is not ViolationKind.NONE and self.clear_to_move:
            raise ValueError('violation != "none" 时 clear_to_move 必须为 False')
        return self


class SpoonCheck(_ContractModel):
    """勺上检查结果。

    判定阈值在 config/ 可调，且偏保守（宁可重舀，不空勺到口）。
    """

    ts_ns: int = Field(ge=0, description="采样时间戳（ns）")
    has_food: bool = Field(description="勺上是否有食物")
    score: float = Field(ge=0.0, le=1.0, description="食物置信分（0-1）")
    cam_ref: str = Field(min_length=1, description="来源相机标识（如腕部相机）")


class VoiceIntent(_ContractModel):
    """语音意图（最近一次识别结果）。

    约定：intent=select 时 slots["dish"] 必须属于预注册菜名表
    （缺省表见 constants.DEFAULT_DISH_REGISTRY，可被 config/ 扩展）。
    """

    ts_ns: int = Field(ge=0, description="采样时间戳（ns）")
    intent: IntentKind = Field(description="意图类别")
    slots: dict[str, str | None] = Field(
        default_factory=dict, description='槽位（select 时含 "dish"）'
    )
    confidence: float = Field(ge=0.0, le=1.0, description="识别置信度（0-1）")


class BiteRecord(_ContractModel):
    """单口记录（数据层最小事实单元）。"""

    bite_id: int = Field(ge=0, description="口序号（会话内自增）")
    ts_start_ns: int = Field(ge=0, description="本口开始时间（ns）")
    ts_end_ns: int = Field(ge=0, description="本口结束时间（ns）")
    outcome: BiteOutcome = Field(description="结局：success/retry/rejected/aborted")
    grams_before: float | None = Field(default=None, ge=0.0, description="舀前克数（无称重为 None）")
    grams_after: float | None = Field(default=None, ge=0.0, description="舀后克数（无称重为 None）")

    @model_validator(mode="after")
    def _time_order(self) -> "BiteRecord":
        if self.ts_end_ns < self.ts_start_ns:
            raise ValueError("ts_end_ns 不得早于 ts_start_ns")
        return self


class MealSession(_ContractModel):
    """一次进餐会话（看板唯一聚合单元）。"""

    session_id: str = Field(min_length=1, description="会话标识")
    user_id: str = Field(min_length=1, description="用户标识")
    started_ns: int = Field(ge=0, description="会话开始时间（ns）")
    ended_ns: int | None = Field(default=None, ge=0, description="会话结束时间（进行中为 None）")
    bites: list[BiteRecord] = Field(default_factory=list, description="口记录（时间序）")
    total_grams: float | None = Field(default=None, ge=0.0, description="累计摄入克数（无称重为 None）")

    @model_validator(mode="after")
    def _session_time_order(self) -> "MealSession":
        if self.ended_ns is not None and self.ended_ns < self.started_ns:
            raise ValueError("ended_ns 不得早于 started_ns")
        return self


__all__ = [
    "ArmCommand",
    "ArmState",
    "BiteRecord",
    "MealSession",
    "MouthPose",
    "SafetyState",
    "SpoonCheck",
    "VoiceIntent",
]

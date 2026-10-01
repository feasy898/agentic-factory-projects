"""SafetyEnvelope：包装任意 ArmInterface 的安全硬闸（开发指令 §5.2）。

定位（契约 §3.1）：**一切 ArmCommand 只能由本类组装并下发到底层**——
行为树（Mock 链路）与真机之间唯一的执行通道。复用 cs_sim 包络校验器
（``EnvelopeValidator``，与 cs_sim eval 同一口径）。

写路径（逐条指令）：
1. 急停闩锁 / 违规未复位 / 未使能 → 拒绝（零运动）；
2. 目标解析：joints 直接取；cartesian 经 cs_sim 求解器解算为关节目标
   （无解 → 拒绝）；**cartesian 在本层改写为 joints 下发**（底层只吃
   关节目标，真机舵机通道同理；改写记录进决策与统计）；
3. 速度硬限：joints ``max_speed`` > 关节硬限速（1.5 rad/s）、cartesian
   ``max_speed`` > 接近段限速（0.15 m/s）→ 拒绝（不静默放行）；
4. 软限速：近脸 0.10 m/s 限速场通过拉长执行时长遵守（等效改写为更低
   速，记录）；
5. cs_sim 包络校验（``check_joint_trajectory``：TCP 加密采样禁区检查 +
   连杆胶囊扫掠 + 关节角速度）：任一违规 → 拒绝。

**任何未过安全包络的 ArmCommand 必须被拒绝且零运动**（本任务的硬闸
语义）；拒绝不计入违规状态（violation 保持 none、clear_to_move 不变）
——拒绝是包络在正确工作；violation 仅保留给真实安全事件（急停/看门狗/
禁入区侵入），其置位即 ``clear_to_move=False``，直到显式 :meth:`reset`。

事件语义（契约 §3.1 SafetyState）：
- 软件急停 :meth:`estop`：同步闩锁（返回即已生效），violation 置
  ``watchdog`` 类别（契约注释指定急停复用该类别，``estop_latched``
  区分），底层立即 :meth:`~cs_arm.interface.ArmInterface.halt`；
- 禁入区监控：每次 read/poll 检查当前 TCP，侵入 → violation
  ``face_in_zone`` + 底层冻结；
- 看门狗：使能后 ``watchdog_timeout_s``（缺省 0.5s）内无任何心跳
  （read/write 活动或底层心跳）→ violation ``watchdog`` + 底层去使能。

v3 硬件语义备注：本机无急停硬件，急停=软件急停（空格键 latch 本包络，
T10 safety_drill 接线）+软勺+低速+前倾取食。
"""

from __future__ import annotations

import time

import numpy as np

try:  # 仓库根运行（pytest / 集成）与包根运行（-m cs_arm.*）双形态
    from chengshao.cs_schema import (
        ArmCommand,
        ArmState,
        CommandMode,
        SafetyState,
        ViolationKind,
    )
    from chengshao.cs_sim import ArmModel, EnvelopeValidator, load_arm
except ImportError:  # pragma: no cover - 包根直跑形态
    from cs_schema import (  # type: ignore[no-redef]
        ArmCommand,
        ArmState,
        CommandMode,
        SafetyState,
        ViolationKind,
    )
    from cs_sim import ArmModel, EnvelopeValidator, load_arm  # type: ignore[no-redef]

from .interface import ArmCommandRejected, ArmInterface
from .kinematics import arm_state_from, plan_motion, resolve_target_joints

__all__ = ["SafetyEnvelope"]


class SafetyEnvelope(ArmInterface):
    """安全包络执行器：限速 / 禁入区 / 急停闩锁 / 看门狗。"""

    def __init__(
        self,
        inner: ArmInterface,
        *,
        model: ArmModel | None = None,
        validator: EnvelopeValidator | None = None,
        clock: object | None = None,
        watchdog_timeout_s: float = 0.5,
    ) -> None:
        self._inner = inner
        if model is not None:
            self._model = model
        else:
            # 优先复用底层执行器的模型实例（校验层与执行层必须同一运动学；
            # MockArm 持有模型；真机骨架无模型时回退自动装载）
            inner_model = getattr(inner, "model", None)
            self._model = inner_model if inner_model is not None else load_arm("auto")
        self._validator = validator if validator is not None else EnvelopeValidator()
        self._clock = clock if clock is not None else _EnvelopeWallClock()
        self._watchdog_timeout_s = float(watchdog_timeout_s)

        self._enabled = False
        self._estop_latched = False
        self._violation: ViolationKind = ViolationKind.NONE
        self._zone_violation = False
        self._watchdog_armed = False
        self._last_activity_ns: int | None = None
        self._last_state: ArmState | None = None
        self._last_decision: dict = {}

        self.stats: dict = {
            "written": 0,
            "rejected": 0,
            "rejected_by_reason": {},
            "cartesian_rewritten_to_joints": 0,
            "estop_count": 0,
            "watchdog_trips": 0,
            "zone_latches": 0,
        }

    # ---- 冻结契约接口 ---------------------------------------------------------

    def read(self) -> ArmState:
        now = self._now()
        self._touch(now)
        state = self._inner.read()
        self._last_state = state
        self._check_zone(state)
        return state

    def write(self, cmd: ArmCommand) -> None:
        now = self._now()
        self._touch(now)
        try:
            # 先取底层 fresh 状态并巡检禁入区（侵入即闩锁+冻结），再做放行判定
            q0 = self._current_q()
            self._check_zone(self._last_state)  # type: ignore[arg-type]
            if self._estop_latched or self._violation is not ViolationKind.NONE:
                raise ArmCommandRejected("not_clear_to_move", {
                    "estop_latched": self._estop_latched,
                    "violation": str(self._violation),
                })
            if not self._enabled:
                raise ArmCommandRejected("disabled", {"hint": "enable() first"})

            q1 = resolve_target_joints(self._model, cmd, q0)
            plan_info = plan_motion(self._model, self._validator, q0, q1, cmd,
                                    float(self._validator.config.joint_speed_limit))
            if plan_info["noop"]:
                decision = {"accepted": True, "noop": True, "mode_in": str(cmd.mode),
                            "mode_out": str(CommandMode.JOINTS)}
                self._last_decision = decision
                self.stats["written"] += 1
                return

            rep = self._validator.check_joint_trajectory(
                [0.0, plan_info["duration_s"]],
                [[float(v) for v in q0], [float(v) for v in q1]],
                self._model,
                label="envelope_precheck",
            )
            if rep["rejected"]:
                raise ArmCommandRejected("envelope_violation", {"report": rep})

            # 改写：cartesian → joints（包络层解算，底层只吃关节目标）；
            # 软限速已通过拉长时长遵守（eff 速度 ≤ 限速场）。
            out_cmd = ArmCommand(
                mode=CommandMode.JOINTS,
                target=[float(v) for v in q1],
                max_speed=max(plan_info["eff_joint_speed_rad_s"], 1e-6),
                timeout_s=cmd.timeout_s,
            )
            self._inner.write(out_cmd)
            decision = {
                "accepted": True,
                "noop": False,
                "mode_in": str(cmd.mode),
                "mode_out": str(CommandMode.JOINTS),
                "rewritten": cmd.mode is CommandMode.CARTESIAN,
                "duration_s": plan_info["duration_s"],
                "eff_joint_speed_rad_s": plan_info["eff_joint_speed_rad_s"],
                "eff_linear_speed_mps": plan_info["eff_linear_speed_mps"],
                "linear_bound_mps": plan_info["linear_bound_mps"],
            }
            if cmd.mode is CommandMode.CARTESIAN:
                self.stats["cartesian_rewritten_to_joints"] += 1
            self._last_decision = decision
            self.stats["written"] += 1
        except ArmCommandRejected as exc:
            self.stats["rejected"] += 1
            self.stats["rejected_by_reason"][exc.reason] = (
                self.stats["rejected_by_reason"].get(exc.reason, 0) + 1
            )
            self._last_decision = {"accepted": False, "reason": exc.reason,
                                   "detail": exc.detail, "mode_in": str(cmd.mode)}
            raise

    def enable(self) -> None:
        self._touch(self._now())
        self._enabled = True
        self._watchdog_armed = True
        self._inner.enable()

    def disable(self) -> None:
        self._touch(self._now())
        self._enabled = False
        self._watchdog_armed = False
        self._inner.disable()

    def halt(self) -> None:
        self._touch(self._now())
        self._inner.halt()

    # ---- 安全事件 API ---------------------------------------------------------

    def estop(self) -> None:
        """软件急停：同步闩锁，返回即已生效（底层冻结 + 拒绝后续指令）。"""
        self.halt()
        self._estop_latched = True
        self._violation = ViolationKind.WATCHDOG  # 契约注释：急停复用 watchdog 类别
        self._watchdog_armed = False
        self.stats["estop_count"] += 1

    def reset(self) -> SafetyState:
        """显式复位安全违规（急停闩锁/看门狗/禁入区）。

        复位后立即重查禁入区：侵入仍在则如实重新闩锁（clear_to_move
        不会在侵入状态下变真）。
        """
        self._estop_latched = False
        self._violation = ViolationKind.NONE
        self._watchdog_armed = self._enabled
        self._touch(self._now())
        if self._last_state is not None:
            self._check_zone(self._last_state)
        return self.safety_state()

    def poll(self) -> SafetyState:
        """周期巡检（看门狗 + 禁入区），返回当前 SafetyState 快照。

        巡检本身**不喂**看门狗心跳（否则监控线程永远不超时）；心跳只由
        控制活动（read/write/enable/disable）与底层心跳驱动。
        """
        now = self._now()
        # 心跳先于取态采样：取态（快照/补读）不得把静默计时器清零
        hb = self._heartbeat_ns()
        snapshot = getattr(self._inner, "snapshot_state", None)
        if snapshot is not None:  # 底层提供监控快照（不喂心跳）→ 状态常新
            self._last_state = snapshot()
        elif self._last_state is None:
            self._last_state = self._inner.read()
        self._check_zone(self._last_state)
        if (
            self._watchdog_armed
            and not self._estop_latched
            and self._violation is ViolationKind.NONE
        ):
            if hb is not None and (now - hb) > int(self._watchdog_timeout_s * 1e9):
                self._violation = ViolationKind.WATCHDOG
                self._watchdog_armed = False
                self._inner.disable()
                self.stats["watchdog_trips"] += 1
        return self.safety_state()

    def safety_state(self) -> SafetyState:
        """契约 SafetyState 快照（不变式：violation!=none ⇒ clear_to_move=False）。"""
        clear = self._enabled and not self._estop_latched \
            and self._violation is ViolationKind.NONE
        return SafetyState(
            ts_ns=self._now(),
            estop_latched=self._estop_latched,
            human_zone_violation=self._zone_violation,
            violation=self._violation,
            clear_to_move=clear,
        )

    # ---- 只增扩展 -------------------------------------------------------------

    @property
    def inner(self) -> ArmInterface:
        return self._inner

    @property
    def model(self) -> ArmModel:
        return self._model

    @property
    def validator(self) -> EnvelopeValidator:
        return self._validator

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def last_decision(self) -> dict:
        """最近一条写指令的判定记录（审计/trace 用）。"""
        return dict(self._last_decision)

    def delivery_stop_point(self) -> np.ndarray:
        """名义送达停点（透传包络校验器；行为树送达目标）。"""
        return self._validator.delivery_stop_point()

    def delivery_margin(self) -> dict:
        """送达数值安全余量（透传包络校验器）。"""
        return self._validator.delivery_margin()

    # ---- 内部 -----------------------------------------------------------------

    def _now(self) -> int:
        return int(self._clock.now_ns())

    def _touch(self, now: int) -> None:
        self._last_activity_ns = now

    def _heartbeat_ns(self) -> int | None:
        """取底层与包络两侧心跳的较新者；两者皆缺 → None（跳过看门狗）。"""
        candidates = [self._last_activity_ns]
        inner_hb = getattr(self._inner, "heartbeat_ns", None)
        if inner_hb is not None:
            candidates.append(int(inner_hb))
        present = [int(v) for v in candidates if v is not None]
        return max(present) if present else None

    def _current_q(self) -> np.ndarray:
        """当前关节角（read 底层 fresh 状态；joint_pos 即 6 关节）。"""
        state = self._inner.read()
        self._last_state = state
        return np.asarray(state.joint_pos, dtype=float)

    def _check_zone(self, state: ArmState) -> None:
        """当前 TCP 禁入区检查：侵入即闩锁 FACE_IN_ZONE 并冻结底层。"""
        in_zone = self._validator.point_zone_violation(np.asarray(state.ee_pos,
                                                                  dtype=float))
        self._zone_violation = in_zone is not None
        if in_zone is not None and self._violation is ViolationKind.NONE \
                and not self._estop_latched:
            self._violation = ViolationKind.FACE_IN_ZONE
            self._inner.halt()
            self.stats["zone_latches"] += 1


class _EnvelopeWallClock:
    """缺省墙钟（与 MockArm 的墙钟口径一致）。"""

    def now_ns(self) -> int:
        return time.perf_counter_ns()


# arm_state_from 在本模块仅再导出给测试/trace 使用（保持公共 API 集中）
__all__.append("arm_state_from")

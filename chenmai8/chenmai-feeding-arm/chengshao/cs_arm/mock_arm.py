"""MockArm：cs_sim 仿真内的虚拟执行器（开发指令 §5.2）。

语义：
- **速度受限积分运动**：指令在仿真时钟上按规划时长做线性关节插值
  （等效逐点速度受限积分）；``read()`` 把状态推进到当前时钟并返回与
  仿真一致的 ArmState（ee 由 cs_sim FK 算出）；
- **消费 cs_sim IK 与安全包络**：cartesian 目标经 cs_sim 求解器解析；
  ``validate_envelope=True``（缺省）时每条指令先过 cs_sim 包络校验器
  （``EnvelopeValidator.check_joint_trajectory``：TCP 加密采样 + 连杆
  扫掠 + 关节角速度），未过包络的指令一律拒绝且零运动；
- **关节限位/限速**：目标超关节限位、速度请求超硬限速即拒绝；
  执行时长按硬限速与近脸软限速场规划（见 ``kinematics.plan_motion``）；
- **超时**：指令携带 ``timeout_s``，仿真时间越过截止时刻即冻结在当前
  位形（中止剩余行程）并计入 timeout_aborts；
- **软件急停配合**：``halt()`` 立即冻结当前位形（由 SafetyEnvelope 在
  急停/去使能时调用）；本类自身不持有急停状态（急停语义在包络层）。

时钟：缺省 ``time.perf_counter_ns``（墙钟）；测试/eval 注入虚拟时钟
（:class:`cs_arm.clock.VirtualClock`）以确定性推进仿真时间。
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np

try:  # 仓库根运行（pytest / 集成）与包根运行（-m cs_arm.*）双形态
    from chengshao.cs_schema import ArmCommand, ArmState
    from chengshao.cs_sim import ArmModel, EnvelopeValidator, load_arm
    from chengshao.cs_sim.safety_envelope import JOINT_SPEED_LIMIT_DEFAULT_RAD_S
except ImportError:  # pragma: no cover - 包根直跑形态
    from cs_schema import ArmCommand, ArmState  # type: ignore[no-redef]
    from cs_sim import ArmModel, EnvelopeValidator, load_arm  # type: ignore[no-redef]
    from cs_sim.safety_envelope import (  # type: ignore[no-redef]
        JOINT_SPEED_LIMIT_DEFAULT_RAD_S,
    )

from .interface import ArmCommandRejected, ArmInterface
from .kinematics import arm_state_from, plan_motion, resolve_target_joints

__all__ = ["MockArm", "MotionPlan"]


@dataclass
class MotionPlan:
    """一条在仿真时钟上执行的线性关节插值计划。"""

    q0: np.ndarray
    q1: np.ndarray
    vel: np.ndarray  # rad/s（带符号，恒定）
    start_ns: int
    duration_s: float
    deadline_ns: int  # 指令 timeout 截止（绝对 ns）


class _WallClock:
    """缺省墙钟（perf_counter_ns；单调，任意纪元）。"""

    def now_ns(self) -> int:
        return time.perf_counter_ns()


def _find_clean_home(model: ArmModel, validator: EnvelopeValidator,
                     min_clear_m: float = 0.03, tries: int = 500,
                     seed: int = 20260928) -> np.ndarray:
    """确定性采样一个禁入区外安全的家位形（TCP 与全部连杆参考点均有间隙）。

    全零位形的 TCP 落在面部球域内（距口部点约 0.079m < 0.12m），不能作
    缺省家位；此处按固定种子采样（可复现），并要求 TCP 落在前向工作区
    盒内（x 0.05–0.30m、|y| ≤ 0.25m、z 0.02–0.35m——碗区与送达走廊同侧，
    姿态朝前、不背向基座）；找不到时回退全零并交由包络层禁入区监控如实
    闩锁（宁可误报不可漏报）。
    """
    try:
        from chengshao.cs_sim.adversarial import _Zones
    except ImportError:  # pragma: no cover - 包根直跑形态
        from cs_sim.adversarial import _Zones  # type: ignore[no-redef]

    zones = _Zones.from_validator(validator)
    lo = np.asarray(model.joint_lower, dtype=float)
    hi = np.asarray(model.joint_upper, dtype=float)
    mid = 0.5 * (lo + hi)
    n_arm = model.n_joints - 1  # 末关节为夹爪，不影响 TCP
    rng = np.random.default_rng(seed)
    for _ in range(tries):
        q = mid.copy()
        q[:n_arm] = rng.uniform(lo[:n_arm], hi[:n_arm])
        tcp = np.asarray(model.fk([float(v) for v in q])[0:3])
        if not (0.05 <= tcp[0] <= 0.30 and abs(tcp[1]) <= 0.25 and 0.02 <= tcp[2] <= 0.35):
            continue
        if zones.point_clearance(tcp) < min_clear_m:
            continue
        lp = np.asarray(model.link_points([float(v) for v in q]))
        if min(zones.point_clearance(p) for p in lp) < min_clear_m:
            continue
        return q
    return np.zeros(len(lo))


class MockArm(ArmInterface):
    """仿真内虚拟臂：任何指令先过安全包络，再在仿真时钟上积分执行。"""

    def __init__(
        self,
        model: ArmModel | None = None,
        *,
        q_home: list[float] | None = None,
        clock: object | None = None,
        joint_speed_limit_rad_s: float = JOINT_SPEED_LIMIT_DEFAULT_RAD_S,
        validate_envelope: bool = True,
        validator: EnvelopeValidator | None = None,
    ) -> None:
        self._model = model if model is not None else load_arm("auto")
        self._validator = validator if validator is not None else EnvelopeValidator()
        self._clock = clock if clock is not None else _WallClock()
        self._joint_speed_limit = float(joint_speed_limit_rad_s)
        self._validate_envelope = bool(validate_envelope)

        lo = np.asarray(self._model.joint_lower, dtype=float)
        hi = np.asarray(self._model.joint_upper, dtype=float)
        if q_home is None:
            q0 = _find_clean_home(self._model, self._validator)
        else:
            q0 = np.asarray(q_home, dtype=float).copy()
            if q0.shape != (len(lo),):
                raise ValueError(f"q_home must have {len(lo)} elements, got {q0.shape}")
        self._q = np.clip(q0, lo, hi)
        self._qd = np.zeros_like(self._q)
        self._plan: MotionPlan | None = None

        self._enabled = False
        self._heartbeat: int | None = None
        self._last_t_ns = int(self._clock.now_ns())

        self.stats: dict = {
            "written": 0,
            "rejected": 0,
            "timeout_aborts": 0,
            "envelope_rejections": 0,
        }

    # ---- 冻结契约接口 ---------------------------------------------------------

    def read(self) -> ArmState:
        now = int(self._clock.now_ns())
        self._integrate_to(now)
        self._heartbeat = now
        return arm_state_from(self._model, self._q, self._qd, now)

    def snapshot_state(self) -> ArmState:
        """监控用快照：推进运动但**不喂心跳**（包络 poll 专用）。

        看门狗语义是监控**控制回路**活性——包络巡检自身的取态不得把
        静默计时器清零。真机通道（FeetechArm）到货后按同一语义提供：
        串口巡检读数不计入控制心跳。
        """
        now = int(self._clock.now_ns())
        self._integrate_to(now)
        return arm_state_from(self._model, self._q, self._qd, now)

    def write(self, cmd: ArmCommand) -> None:
        now = int(self._clock.now_ns())
        self._integrate_to(now)
        self._heartbeat = now
        try:
            if not self._enabled:
                raise ArmCommandRejected("disabled", {"hint": "enable() first"})
            q0 = self._q.copy()
            q1 = resolve_target_joints(self._model, cmd, q0)
            plan_info = plan_motion(self._model, self._validator, q0, q1, cmd,
                                    self._joint_speed_limit)
            if self._validate_envelope and not plan_info["noop"]:
                rep = self._validator.check_joint_trajectory(
                    [0.0, plan_info["duration_s"]],
                    [list(q0), [float(v) for v in q1]],
                    self._model,
                    label="mock_arm_precheck",
                )
                if rep["rejected"]:
                    self.stats["envelope_rejections"] += 1
                    raise ArmCommandRejected("envelope_violation", {"report": rep})
            if plan_info["noop"]:
                self.stats["written"] += 1
                return
            self._plan = MotionPlan(
                q0=q0,
                q1=q1,
                vel=(q1 - q0) / plan_info["duration_s"],
                start_ns=now,
                duration_s=plan_info["duration_s"],
                deadline_ns=now + int(cmd.timeout_s * 1e9),
            )
            self.stats["written"] += 1
        except ArmCommandRejected:
            self.stats["rejected"] += 1
            raise

    def enable(self) -> None:
        now = int(self._clock.now_ns())
        self._integrate_to(now)
        self._enabled = True
        self._heartbeat = now

    def disable(self) -> None:
        now = int(self._clock.now_ns())
        self._integrate_to(now)
        self._enabled = False
        self._plan = None  # 下力矩：运动立即冻结在当前位形
        self._qd = np.zeros_like(self._qd)
        self._heartbeat = now

    # ---- 只增扩展 -------------------------------------------------------------

    def halt(self) -> None:
        """立即冻结在当前位形（速度清零、放弃在途计划）。幂等。"""
        now = int(self._clock.now_ns())
        self._integrate_to(now)
        self._plan = None
        self._qd = np.zeros_like(self._qd)
        self._heartbeat = now

    @property
    def heartbeat_ns(self) -> int | None:
        return self._heartbeat

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def n_joints(self) -> int:
        return len(self._q)

    @property
    def joint_names(self) -> list[str]:
        return list(self._model.joint_names)

    @property
    def model(self) -> ArmModel:
        return self._model

    @property
    def validator(self) -> EnvelopeValidator:
        return self._validator

    @property
    def in_motion(self) -> bool:
        return self._plan is not None

    def current_q(self) -> np.ndarray:
        """当前关节角（推进仿真时间到当前时钟后返回副本）。"""
        self._integrate_to(int(self._clock.now_ns()))
        return self._q.copy()

    def teleport(self, q: list[float] | np.ndarray) -> None:
        """测试/装配用：无运动直接置位形（放弃在途计划；仅虚拟执行器提供）。

        真机通道没有对应操作——位形只能经指令抵达；本方法只服务于
        MockArm 的确定性场景装配（如对抗性轨迹的起点复现）。
        """
        self._integrate_to(int(self._clock.now_ns()))
        lo = np.asarray(self._model.joint_lower, dtype=float)
        hi = np.asarray(self._model.joint_upper, dtype=float)
        target = np.asarray(q, dtype=float).copy()
        if target.shape != (len(lo),):
            raise ValueError(f"teleport expects {len(lo)} joints, got {target.shape}")
        self._q = np.clip(target, lo, hi)
        self._plan = None
        self._qd = np.zeros_like(self._qd)
        self._heartbeat = int(self._clock.now_ns())

    # ---- 内部 -----------------------------------------------------------------

    def _integrate_to(self, now_ns: int) -> None:
        """把状态推进到 now_ns（线性插值 + 超时在截止位形冻结）。"""
        if now_ns < self._last_t_ns:  # 时钟不允许倒退
            now_ns = self._last_t_ns
        self._last_t_ns = now_ns
        plan = self._plan
        if plan is None:
            self._qd = np.zeros_like(self._qd)
            return
        span = max(plan.deadline_ns - plan.start_ns, 1)
        f_deadline = (now_ns - plan.start_ns) / span
        if f_deadline >= 1.0:
            # timeout 截止：冻结在截止时刻的位形（中止剩余行程），非目标位形
            f_timeout = min(1.0, (plan.deadline_ns - plan.start_ns)
                            / (plan.duration_s * 1e9))
            self._q = plan.q0 + f_timeout * (plan.q1 - plan.q0)
            self._plan = None
            self._qd = np.zeros_like(self._qd)
            self.stats["timeout_aborts"] += 1
            return
        f = (now_ns - plan.start_ns) / (plan.duration_s * 1e9)
        if f >= 1.0:
            self._q = plan.q1
            self._plan = None
            self._qd = np.zeros_like(self._qd)
            return
        self._q = plan.q0 + f * (plan.q1 - plan.q0)
        self._qd = plan.vel.copy()

"""执行层共享运动学/规划助手：目标解析、速度受限时长规划、状态装配。

被 :class:`cs_arm.mock_arm.MockArm` 与 :class:`cs_arm.safety.SafetyEnvelope`
共用，保证两层对同一条指令做出**一致**的判定（同公式、同输入、同结果）。

规划语义（v3.1，与 cs_sim 包络校验器对齐）：

- 关节硬限速 ``joint_speed_limit``（缺省 1.5 rad/s，与
  ``config/workspace.json`` 一致）：joints 指令的 ``max_speed`` 超过硬限
  → 直接拒绝（不静默改写——超硬限的速度请求按缺陷处理）；
- 笛卡尔硬限速 = 工作区接近段限速（0.15 m/s，全工作区最大）：cartesian
  指令的 ``max_speed`` 超过 → 直接拒绝；
- 软限速（位置相关的近脸 0.10 m/s 限速场）：通过**拉长执行时长**遵守
  （等效改写为更低速；记录进决策信息）；
- cartesian 指令在包络层解算为关节目标后下发（cartesian 只在包络层有
  意义，底层只吃关节目标——真机舵机通道同理）。
"""

from __future__ import annotations

import numpy as np

try:  # 仓库根运行（pytest / 集成）与包根运行（-m cs_arm.*）双形态
    from chengshao.cs_schema import (
        CARTESIAN_TARGET_FULL,
        CARTESIAN_TARGET_POS_ONLY,
        N_ARM_JOINTS,
        ArmCommand,
        ArmState,
        CommandMode,
    )
    from chengshao.cs_sim import ArmModel, EnvelopeValidator
    from chengshao.cs_sim.ik_solver import solve_with_restarts
except ImportError:  # pragma: no cover - 包根直跑形态
    from cs_schema import (  # type: ignore[no-redef]
        CARTESIAN_TARGET_FULL,
        CARTESIAN_TARGET_POS_ONLY,
        N_ARM_JOINTS,
        ArmCommand,
        ArmState,
        CommandMode,
    )
    from cs_sim import ArmModel, EnvelopeValidator  # type: ignore[no-redef]
    from cs_sim.ik_solver import solve_with_restarts  # type: ignore[no-redef]

from .interface import ArmCommandRejected

__all__ = [
    "resolve_target_joints",
    "plan_motion",
    "tcp_arc_samples",
    "arm_state_from",
    "JOINT_LIMIT_TOL_RAD",
    "TCP_LINEAR_SAMPLES",
    "LINEAR_TIME_SAFETY_FACTOR",
    "MIN_DURATION_S",
]

# 关节限位判定的数值容差（schema/浮点边界）
JOINT_LIMIT_TOL_RAD = 1e-6
# TCP 弧长采样点数（含两端；用于位置相关限速场的保守估计）
TCP_LINEAR_SAMPLES = 25
# 弧长估计 → 时长的安全系数（覆盖与校验器加密采样口径的弧长偏差）
LINEAR_TIME_SAFETY_FACTOR = 1.05
# 单条指令最短执行时长（s）：防零时长指令穿越校验器的时间检查
MIN_DURATION_S = 1e-3


def _reject(reason: str, detail: dict | None = None) -> ArmCommandRejected:
    return ArmCommandRejected(reason, detail)


def resolve_target_joints(
    model: ArmModel, cmd: ArmCommand, q_cur: np.ndarray
) -> np.ndarray:
    """把 ArmCommand 的 target 解析为 6 关节目标（不做包络/限速判定）。

    - joints 模式：校验长度与关节限位后原样返回；
    - cartesian 模式：3 维（仅位置，姿态保持，pos-only 求解）或
      7 维（位置 + 四元数全量，完整位姿求解）；夹爪关节保持当前值
      （夹爪不改变 TCP，逆解中该列为零列）；
    - 失败（超限位 / 无解）抛 :class:`ArmCommandRejected`。
    """
    target = np.asarray(cmd.target, dtype=float)
    lo = np.asarray(model.joint_lower, dtype=float)
    hi = np.asarray(model.joint_upper, dtype=float)

    if cmd.mode is CommandMode.JOINTS:
        if target.shape != (N_ARM_JOINTS,):
            raise _reject("target_length_mismatch", {"expected": N_ARM_JOINTS,
                                                     "got": int(target.size)})
        if np.any(target < lo - JOINT_LIMIT_TOL_RAD) or np.any(target > hi + JOINT_LIMIT_TOL_RAD):
            over = [int(i) for i in range(N_ARM_JOINTS)
                    if target[i] < lo[i] - JOINT_LIMIT_TOL_RAD
                    or target[i] > hi[i] + JOINT_LIMIT_TOL_RAD]
            raise _reject("target_beyond_joint_limits", {"joints": over})
        return target.copy()

    # cartesian 模式
    if target.size not in (CARTESIAN_TARGET_POS_ONLY, CARTESIAN_TARGET_FULL):
        raise _reject("cartesian_target_length_invalid", {"got": int(target.size)})
    pos = target[0:3]
    seed = np.clip(q_cur, lo, hi)

    if target.size == CARTESIAN_TARGET_FULL:
        quat = target[3:7]
        norm = float(np.linalg.norm(quat))
        if norm < 1e-9 or abs(norm - 1.0) > 1e-3:
            raise _reject("cartesian_quat_invalid", {"norm": norm})
        q = model.ik([float(v) for v in pos], [float(v) for v in quat],
                     seed=[float(v) for v in seed])
        if q is None:
            raise _reject("ik_no_solution", {"mode": "full_pose"})
        q1 = np.asarray(q, dtype=float)
    else:
        _, rot_cur = model.fk_pose([float(v) for v in seed])
        res = solve_with_restarts(model._backend, pos, rot_cur, seed=seed, pos_only=True)
        if res is None or not res.converged:
            raise _reject("ik_no_solution", {"mode": "position_only"})
        q1 = np.asarray(res.q, dtype=float)

    q1[N_ARM_JOINTS - 1] = seed[N_ARM_JOINTS - 1]  # 夹爪保持当前值
    return np.clip(q1, lo, hi)


def tcp_arc_samples(model: ArmModel, q0: np.ndarray, q1: np.ndarray,
                    n: int = TCP_LINEAR_SAMPLES) -> tuple[np.ndarray, float]:
    """关节插值弧的 TCP 采样点与弧长（位置相关限速场的输入）。

    n 为采样点数（含两端，n>=2）；直线关节插值的 TCP 轨迹是空间弧线，
    线性限速场判定必须沿实际弧线取点（而不是只看两端）。
    """
    f = np.linspace(0.0, 1.0, max(2, int(n)))[:, None]
    qs = q0[None, :] + f * (q1 - q0)[None, :]
    pts = np.asarray([model.fk([float(v) for v in q])[0:3] for q in qs], dtype=float)
    arc = float(np.sum(np.linalg.norm(np.diff(pts, axis=0), axis=1)))
    return pts, arc


def plan_motion(
    model: ArmModel,
    validator: EnvelopeValidator,
    q0: np.ndarray,
    q1: np.ndarray,
    cmd: ArmCommand,
    joint_speed_limit: float,
) -> dict:
    """速度受限的执行时长规划（不做过包络校验，只算时长/有效速度）。

    返回 dict::

        {"duration_s", "eff_joint_speed_rad_s", "eff_linear_speed_mps",
         "tcp_arc_len_m", "linear_bound_mps", "noop": bool}

    - ``noop=True``：目标与当前位形一致（零运动），时长置最小值；
    - 速度硬限违规在此抛 :class:`ArmCommandRejected`
      （joints: max_speed > joint_speed_limit；cartesian: max_speed > 接近段限速）；
    - 软限速（近脸限速场）通过拉长 duration 遵守：eff 速度 ≤ 全弧最小限速。
    """
    cfg = validator.config
    lo = np.asarray(model.joint_lower, dtype=float)
    hi = np.asarray(model.joint_upper, dtype=float)
    q0c = np.clip(np.asarray(q0, dtype=float), lo, hi)
    q1c = np.clip(np.asarray(q1, dtype=float), lo, hi)
    dq = q1c - q0c
    max_dq = float(np.max(np.abs(dq)))

    if max_dq <= JOINT_LIMIT_TOL_RAD:
        return {"duration_s": MIN_DURATION_S, "eff_joint_speed_rad_s": 0.0,
                "eff_linear_speed_mps": 0.0, "tcp_arc_len_m": 0.0,
                "linear_bound_mps": cfg.speed_approach, "noop": True}

    if cmd.mode is CommandMode.JOINTS:
        if float(cmd.max_speed) > joint_speed_limit + 1e-9:
            raise _reject("joint_speed_over_hard_limit", {
                "requested_rad_s": float(cmd.max_speed),
                "limit_rad_s": float(joint_speed_limit),
            })
        t_joint = max_dq / min(float(cmd.max_speed), joint_speed_limit)
    else:
        if float(cmd.max_speed) > cfg.speed_approach + 1e-9:
            raise _reject("linear_speed_over_hard_limit", {
                "requested_mps": float(cmd.max_speed),
                "limit_mps": float(cfg.speed_approach),
            })
        t_joint = max_dq / joint_speed_limit

    pts, arc = tcp_arc_samples(model, q0c, q1c)
    lin_bound = float(min(validator.speed_limit_at(p) for p in pts))
    t_linear = 0.0
    if arc > 1e-12:
        t_linear = arc * LINEAR_TIME_SAFETY_FACTOR / max(lin_bound, 1e-9)
        if cmd.mode is CommandMode.CARTESIAN:
            t_linear = max(t_linear, arc / float(cmd.max_speed))

    duration = max(t_joint, t_linear, MIN_DURATION_S)
    return {
        "duration_s": float(duration),
        "eff_joint_speed_rad_s": float(max_dq / duration),
        "eff_linear_speed_mps": float(arc / duration),
        "tcp_arc_len_m": arc,
        "linear_bound_mps": lin_bound,
        "noop": False,
    }


def arm_state_from(model: ArmModel, q: np.ndarray, qd: np.ndarray, ts_ns: int) -> ArmState:
    """由关节状态装配契约 ArmState（ee 由 FK 算出；单位四元数 w 在前）。"""
    pose = model.fk([float(v) for v in q])
    return ArmState(
        ts_ns=int(ts_ns),
        joint_names=list(model.joint_names),
        joint_pos=[float(v) for v in q],
        joint_vel=[float(v) for v in qd],
        ee_pos=[float(pose[0]), float(pose[1]), float(pose[2])],
        ee_quat=[float(pose[3]), float(pose[4]), float(pose[5]), float(pose[6])],
    )

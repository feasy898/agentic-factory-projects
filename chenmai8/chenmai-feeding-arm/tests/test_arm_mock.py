"""cs_arm 跨模块测试：接口契约 / MockArm 虚拟执行 / SafetyEnvelope 硬闸 / FeetechArm 骨架。

运行（仓库根）::

    python -m pytest tests/test_arm_mock.py -q

无硬件依赖。核心语义（开发指令 §5.2 + T6 硬闸要求）：
- 任何未过安全包络的 ArmCommand 必须被拒绝且零运动；
- 软件急停同步闩锁（返回即 clear_to_move=False、不再下发、运动冻结）；
- 限速被遵守（关节硬限 + 近脸软限速场）；
- 送达走廊整段在数值安全余量内；
- 看门狗断连 500ms 主动 disable；禁入区侵入闩锁。
"""

from __future__ import annotations

import inspect
import time

import numpy as np
import pytest
from pydantic import ValidationError

from chengshao.cs_arm import (
    ArmCommandRejected,
    ArmInterface,
    FeetechArm,
    FeetechArmConfig,
    HardwareUnavailable,
    MockArm,
    SafetyEnvelope,
    VirtualClock,
)
from chengshao.cs_schema import (
    N_ARM_JOINTS,
    ArmCommand,
    ArmState,
    SafetyState,
    ViolationKind,
)
from chengshao.cs_sim import ArmModel, EnvelopeValidator, load_arm
from chengshao.cs_sim.ik_solver import solve_with_restarts

STOP_POINT = np.array([0.25, 0.0, 0.30])  # 名义送达停点（validator.delivery_stop_point）


# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def model() -> ArmModel:
    return load_arm("auto")


@pytest.fixture(scope="module")
def validator() -> EnvelopeValidator:
    return EnvelopeValidator()


@pytest.fixture(scope="module")
def validator_template() -> dict:
    """口部点移到工作段旁的包络配置 dict（近脸软限速场测试用）。"""
    mouth = [0.26, -0.04, 0.16]
    return {
        "mouth_point_m": mouth,
        "forbidden_zones": [
            {"type": "sphere", "name": "face", "center_m": mouth, "radius_m": 0.12},
            {"type": "capsule", "name": "torso", "p1_m": [0.48, 0.0, -0.10],
             "p2_m": [0.48, 0.0, 0.22], "radius_m": 0.15},
        ],
        "speed_limits_mps": {"approach": 0.15, "near_face": 0.10},
        "near_face_distance_m": 0.15,
    }


@pytest.fixture()
def clock() -> VirtualClock:
    return VirtualClock()


@pytest.fixture()
def mock(model: ArmModel, validator: EnvelopeValidator, clock: VirtualClock) -> MockArm:
    arm = MockArm(model, validator=validator, clock=clock)
    arm.enable()
    return arm


@pytest.fixture()
def env(model: ArmModel, validator: EnvelopeValidator, clock: VirtualClock,
        mock: MockArm) -> SafetyEnvelope:
    envelope = SafetyEnvelope(mock, model=model, validator=validator, clock=clock)
    envelope.enable()
    return envelope


def joints_cmd(target, speed: float = 0.5, timeout: float = 120.0) -> ArmCommand:
    return ArmCommand(mode="joints", target=[float(v) for v in target],
                      max_speed=speed, timeout_s=timeout)


def cart_cmd(point, speed: float = 0.05, timeout: float = 120.0) -> ArmCommand:
    return ArmCommand(mode="cartesian", target=[float(v) for v in point],
                      max_speed=speed, timeout_s=timeout)


def stream_to(env: SafetyEnvelope, clock: VirtualClock, point, speed: float = 0.05,
              step_m: float = 0.02) -> float:
    """按小步长流式送达 point（行为树 50Hz 流式路径），返回末端跟踪误差（m）。"""
    target = np.asarray(point, dtype=float)
    q_now = env.read()
    cur = np.asarray(q_now.ee_pos, dtype=float)
    dist = float(np.linalg.norm(target - cur))
    n = max(1, int(np.ceil(dist / step_m)))
    err = float("inf")
    for i in range(1, n + 1):
        wp = cur + (target - cur) * (i / n)
        env.write(cart_cmd(wp, speed=speed))
        assert env.last_decision["accepted"] is True, env.last_decision
        clock.advance_s(env.last_decision["duration_s"] + 0.005)
        err = float(np.linalg.norm(np.asarray(env.read().ee_pos) - wp))
    return err


# ---------------------------------------------------------------------------
# 接口契约（冻结签名 §3.2）
# ---------------------------------------------------------------------------


def test_interface_contract_frozen_signatures():
    """ArmInterface 冻结签名：read/write/enable/disable；实现类均为其子类。"""
    sig_read = inspect.signature(ArmInterface.read)
    sig_write = inspect.signature(ArmInterface.write)
    assert list(sig_read.parameters) == ["self"]
    assert list(sig_write.parameters) == ["self", "cmd"]
    assert str(sig_write.parameters["cmd"].annotation).endswith("ArmCommand")
    assert str(sig_read.return_annotation).endswith("ArmState")
    for name in ("enable", "disable"):
        sig = inspect.signature(getattr(ArmInterface, name))
        assert list(sig.parameters) == ["self"]
        assert str(sig.return_annotation).endswith("None")
    for cls in (MockArm, SafetyEnvelope, FeetechArm):
        assert issubclass(cls, ArmInterface)


def test_read_returns_contract_6joint_state(env: SafetyEnvelope, model: ArmModel):
    st = env.read()
    assert isinstance(st, ArmState)
    assert len(st.joint_names) == N_ARM_JOINTS == len(st.joint_pos) == len(st.joint_vel)
    assert st.joint_names == model.joint_names
    assert len(st.ee_pos) == 3 and len(st.ee_quat) == 4
    assert abs(float(np.linalg.norm(st.ee_quat)) - 1.0) < 1e-6


def test_read_fk_consistency(env: SafetyEnvelope, mock: MockArm, model: ArmModel):
    st = env.read()
    pose = model.fk(mock.current_q().tolist())
    assert float(np.linalg.norm(np.array(st.ee_pos) - np.array(pose[0:3]))) < 1e-9
    assert float(np.linalg.norm(np.array(st.ee_quat) - np.array(pose[3:7]))) < 1e-9


def test_home_starts_outside_forbidden_zones(mock: MockArm, validator: EnvelopeValidator):
    """缺省家位形（全零位形 TCP 在面部球内，不可用）必须在禁区外。"""
    st = mock.read()
    assert validator.point_zone_violation(np.asarray(st.ee_pos)) is None


# ---------------------------------------------------------------------------
# MockArm 虚拟执行：到位精度 / 限速
# ---------------------------------------------------------------------------


def test_joint_move_settles_and_tracks_within_2mm(env: SafetyEnvelope, clock: VirtualClock,
                                                  model: ArmModel):
    q0 = np.asarray(env.read().joint_pos)
    target = q0.copy()
    target[1] += 0.25
    target[5] = 0.5  # 夹爪关节
    env.write(joints_cmd(target, speed=0.5))
    info = env.last_decision
    assert info["accepted"] is True
    clock.advance_s(info["duration_s"] + 0.01)
    st = env.read()
    assert float(np.max(np.abs(np.asarray(st.joint_pos) - target))) < 1e-9
    tcp_err = float(np.linalg.norm(np.asarray(st.ee_pos)
                                   - np.array(model.fk(target.tolist())[0:3])))
    assert tcp_err <= 0.002  # §5.2：MockArm 轨迹跟踪误差 ≤2mm（仿真内）


def test_joint_speed_limit_respected_mid_motion(env: SafetyEnvelope, clock: VirtualClock):
    q0 = np.asarray(env.read().joint_pos)
    target = q0.copy()
    target[2] += 0.60  # 0.6 rad，请求 0.3 rad/s（< 1.5 硬限）
    env.write(joints_cmd(target, speed=0.3))
    T = env.last_decision["duration_s"]
    assert T == pytest.approx(0.6 / 0.3, rel=0.15)  # 关节限速决定时长量级
    clock.advance_s(T * 0.5)
    st = env.read()
    moved = float(st.joint_pos[2] - q0[2])
    assert moved <= 0.3 * (T * 0.5) + 1e-6  # 不超请求限速
    assert st.joint_vel[2] == pytest.approx(0.6 / T, abs=1e-6)
    assert 0.6 / T <= 0.3 + 1e-6
    clock.advance_s(T + 0.5)
    st2 = env.read()
    assert float(abs(st2.joint_pos[2] - target[2])) < 1e-9
    assert all(v == 0.0 for v in st2.joint_vel)


def test_cartesian_stream_tracking_within_2mm(env: SafetyEnvelope, clock: VirtualClock):
    err = stream_to(env, clock, STOP_POINT)
    assert err <= 0.002


def test_near_face_soft_speed_field_stretches_duration(
    model: ArmModel, validator_template: dict,
):
    """近脸软限速场（0.10 m/s）：规划层通过拉长时长遵守（等效改写为更低速）。

    用位移后的口部点使 A→B 段整体处于近脸限速带（距口部点 <0.15m）且
    TCP 在面部球外。注：缺省几何下 0.12–0.15m 壳层被 30mm 连杆胶囊物理
    封锁（TCP 0.17m 停点 + 勺尖前伸负责该壳层），故本机制在规划层证明；
    执行层限速证据由走廊实测与硬限拒绝覆盖。
    """
    from chengshao.cs_arm.kinematics import plan_motion
    from chengshao.cs_sim.ik_solver import solve_with_restarts

    F = np.asarray(validator_template["mouth_point_m"])
    val2 = EnvelopeValidator(validator_template)
    A = np.array([0.19, -0.06, 0.05])
    B = np.array([0.21, -0.06, 0.05])
    assert 0.12 < float(np.linalg.norm(A - F)) < 0.15  # 近脸带内、球外
    assert 0.12 < float(np.linalg.norm(B - F)) < 0.15
    assert val2.speed_limit_at(A) == pytest.approx(0.10)
    res_a = solve_with_restarts(model._backend, A, np.eye(3), seed=None,
                                pos_only=True, restarts=32)
    res_b = solve_with_restarts(model._backend, B, np.eye(3), seed=res_a.q,
                                pos_only=True, restarts=32)
    assert res_a.converged and res_b.converged
    qa = np.clip(res_a.q, model.joint_lower, model.joint_upper)
    qb = np.clip(res_b.q, model.joint_lower, model.joint_upper)

    # 请求 0.15 m/s（硬限内、超软限）→ 时长被拉长到 eff ≤ 0.10
    cmd_fast = ArmCommand(mode="cartesian", target=B.tolist(),
                          max_speed=0.15, timeout_s=120.0)
    info = plan_motion(model, val2, qa, qb, cmd_fast, 1.5)
    assert info["linear_bound_mps"] == pytest.approx(0.10)
    assert info["eff_linear_speed_mps"] <= 0.10 + 1e-6
    # 请求 0.05 m/s（低于软限）→ 不被拉慢
    cmd_slow = ArmCommand(mode="cartesian", target=B.tolist(),
                          max_speed=0.05, timeout_s=120.0)
    info_slow = plan_motion(model, val2, qa, qb, cmd_slow, 1.5)
    assert info_slow["eff_linear_speed_mps"] <= 0.05 + 1e-6


# ---------------------------------------------------------------------------
# 拒绝语义：任何未过安全包络的指令必须被拒绝且零运动
# ---------------------------------------------------------------------------


def test_target_beyond_joint_limits_rejected_zero_motion(env: SafetyEnvelope,
                                                         clock: VirtualClock):
    q_before = np.asarray(env.read().joint_pos)
    bad = q_before.copy()
    bad[0] = 3.0  # 超出关节 1 限位（±1.92）
    with pytest.raises(ArmCommandRejected) as ei:
        env.write(joints_cmd(bad))
    assert ei.value.reason == "target_beyond_joint_limits"
    clock.advance_s(0.05)
    assert float(np.max(np.abs(np.asarray(env.read().joint_pos) - q_before))) == 0.0


def test_cartesian_unreachable_rejected(env: SafetyEnvelope):
    with pytest.raises(ArmCommandRejected) as ei:
        env.write(cart_cmd([2.5, 2.5, 2.5]))
    assert ei.value.reason == "ik_no_solution"


def test_face_sphere_target_rejected_zero_motion(env: SafetyEnvelope, clock: VirtualClock,
                                                 validator: EnvelopeValidator):
    """面部球域内的笛卡尔目标：包络拒绝、零运动（硬闸核心语义）。"""
    q_before = np.asarray(env.read().joint_pos)
    with pytest.raises(ArmCommandRejected) as ei:
        env.write(cart_cmd(validator.config.face_center))
    assert ei.value.reason == "envelope_violation"
    assert any(v["kind"] == "zone" and v.get("zone") == "face"
               for v in ei.value.detail["report"]["violations"])
    clock.advance_s(0.05)
    assert float(np.max(np.abs(np.asarray(env.read().joint_pos) - q_before))) == 0.0


def test_torso_capsule_target_rejected(env: SafetyEnvelope, validator: EnvelopeValidator):
    """躯干胶囊体内的可达点必须拒（点到胶囊轴 0.08m < 0.15m，球域外）。"""
    inside = np.array([0.40, 0.0, 0.10])
    assert validator.point_zone_violation(inside) == "torso"  # 在胶囊内
    assert validator.point_zone_violation(inside) != "face"  # 且不越到面部球
    with pytest.raises(ArmCommandRejected) as ei:
        env.write(cart_cmd(inside))
    assert ei.value.reason == "envelope_violation"


def test_zone_sweeping_joints_target_rejected(env: SafetyEnvelope, model: ArmModel,
                                              validator: EnvelopeValidator):
    """TCP 端点在面部球内的关节目标同样拒绝（包络按轨迹整段查）。"""
    res = solve_with_restarts(model._backend, validator.config.face_center,
                              np.eye(3), seed=None, pos_only=True, restarts=32)
    assert res is not None and res.converged
    q_zone = np.clip(res.q, model.joint_lower, model.joint_upper)
    q_zone[5] = env.read().joint_pos[5]
    with pytest.raises(ArmCommandRejected) as ei:
        env.write(joints_cmd(q_zone, speed=0.1))
    assert ei.value.reason == "envelope_violation"


def test_joint_hard_speed_rejected(env: SafetyEnvelope):
    q = np.asarray(env.read().joint_pos)
    target = q.copy()
    target[0] += 0.5
    with pytest.raises(ArmCommandRejected) as ei:
        env.write(joints_cmd(target, speed=5.0))  # > 1.5 rad/s 硬限
    assert ei.value.reason == "joint_speed_over_hard_limit"


def test_cartesian_hard_speed_rejected(env: SafetyEnvelope):
    with pytest.raises(ArmCommandRejected) as ei:
        env.write(cart_cmd([0.20, 0.0, 0.10], speed=0.5))  # > 0.15 m/s 硬限
    assert ei.value.reason == "linear_speed_over_hard_limit"


def test_mock_standalone_rejects_violating_command(mock: MockArm,
                                                   validator: EnvelopeValidator):
    """绕过包络直写 MockArm 也被拒（内嵌包络虚拟执行，双层硬闸）。"""
    with pytest.raises(ArmCommandRejected) as ei:
        mock.write(cart_cmd(validator.config.face_center))
    assert ei.value.reason == "envelope_violation"
    assert mock.stats["envelope_rejections"] >= 1


def test_command_schema_rejects_wrong_joint_count():
    with pytest.raises(ValidationError):
        ArmCommand(mode="joints", target=[0.0] * 7, max_speed=0.5, timeout_s=1.0)


# ---------------------------------------------------------------------------
# 软件急停 / 复位
# ---------------------------------------------------------------------------


def test_estop_halts_within_100ms_and_blocks(env: SafetyEnvelope, clock: VirtualClock,
                                             mock: MockArm):
    stream_to(env, clock, np.array([0.22, -0.18, 0.02]))  # 到碗位
    target = np.array([0.25, -0.09, 0.20])
    # 朝转运点流式飞行，在第 3 个航点运动中段注入软急停
    cur = np.asarray(env.read().ee_pos)
    wp = cur + (target - cur) * (3.0 / 11.0)
    env.write(cart_cmd(wp, speed=0.05))
    assert mock.in_motion
    clock.advance_s(env.last_decision["duration_s"] * 0.5)  # 运动中段
    st_mid = env.read()
    q_mid = np.asarray(st_mid.joint_pos)
    assert any(v != 0.0 for v in st_mid.joint_vel)  # 确在运动中

    t0 = time.perf_counter()
    env.estop()
    latency_ms = (time.perf_counter() - t0) * 1e3
    assert latency_ms <= 100.0  # §5.2：急停 latch ≤100ms

    clock.advance_s(0.2)  # 若未冻结将继续运动
    st_after = env.read()
    q_after = np.asarray(st_after.joint_pos)
    assert float(np.max(np.abs(q_after - q_mid))) == 0.0  # 位形冻结
    assert all(v == 0.0 for v in st_after.joint_vel)  # 速度清零
    assert not mock.in_motion

    ss = env.safety_state()
    assert isinstance(ss, SafetyState)
    assert ss.estop_latched is True
    assert ss.violation is ViolationKind.WATCHDOG  # 契约注释：急停复用 watchdog 类别
    assert ss.clear_to_move is False
    with pytest.raises(ArmCommandRejected) as ei:
        env.write(cart_cmd(target))
    assert ei.value.reason == "not_clear_to_move"  # 不再下发命令


def test_estop_reset_recovers_motion(env: SafetyEnvelope, clock: VirtualClock):
    env.estop()
    assert env.safety_state().clear_to_move is False
    env.reset()
    ss = env.safety_state()
    assert ss.estop_latched is False and ss.clear_to_move is True
    q0 = np.asarray(env.read().joint_pos)
    target = q0.copy()
    j = 0 if q0[0] + 0.10 <= 1.92 else 1  # 肩转关节朝可达方向动
    target[j] += 0.10
    env.write(joints_cmd(target, speed=0.3))
    clock.advance_s(env.last_decision["duration_s"] + 0.01)
    assert float(abs(env.read().joint_pos[j] - target[j])) < 1e-9


# ---------------------------------------------------------------------------
# 看门狗 / 使能 / 禁入区监控
# ---------------------------------------------------------------------------


def test_watchdog_trips_after_silence_and_disables(env: SafetyEnvelope, clock: VirtualClock,
                                                   mock: MockArm):
    env.enable()
    env.poll()  # 使能后即巡检基线
    clock.advance_s(0.6)  # > 500ms 无任何控制活动
    ss = env.poll()
    assert ss.violation is ViolationKind.WATCHDOG
    assert ss.clear_to_move is False
    assert mock.enabled is False  # 看门狗主动 disable（§5.2）


def test_watchdog_quiet_within_timeout(env: SafetyEnvelope, clock: VirtualClock):
    env.enable()
    clock.advance_s(0.1)  # < 500ms
    assert env.poll().violation is ViolationKind.NONE


def test_watchdog_poll_does_not_feed_heartbeat(env: SafetyEnvelope, clock: VirtualClock):
    """巡检本身不喂心跳：静默期持续 poll 也会在超时后跳闸。"""
    env.enable()
    for _ in range(12):
        clock.advance_s(0.1)
        if env.poll().violation is not ViolationKind.NONE:
            break
    assert env.safety_state().violation is ViolationKind.WATCHDOG


def test_watchdog_recovery_via_reset_enable(env: SafetyEnvelope, clock: VirtualClock,
                                            mock: MockArm):
    env.enable()
    clock.advance_s(0.6)
    assert env.poll().violation is ViolationKind.WATCHDOG
    env.reset()
    env.enable()
    q0 = np.asarray(env.read().joint_pos)
    target = q0.copy()
    target[3] += 0.05
    env.write(joints_cmd(target, speed=0.3))
    clock.advance_s(env.last_decision["duration_s"] + 0.01)
    assert float(abs(env.read().joint_pos[3] - target[3])) < 1e-9


def test_disable_blocks_write_read_still_works(env: SafetyEnvelope, clock: VirtualClock):
    env.disable()
    assert env.safety_state().clear_to_move is False
    with pytest.raises(ArmCommandRejected) as ei:
        env.write(cart_cmd([0.20, 0.0, 0.10]))
    assert ei.value.reason == "disabled"
    assert env.read() is not None  # 回读不受影响


def test_fresh_envelope_requires_enable(model: ArmModel, validator: EnvelopeValidator,
                                        clock: VirtualClock):
    env = SafetyEnvelope(MockArm(model, validator=validator, clock=clock),
                         model=model, validator=validator, clock=clock)
    with pytest.raises(ArmCommandRejected) as ei:
        env.write(cart_cmd([0.20, 0.0, 0.10]))
    assert ei.value.reason == "disabled"


def test_zone_monitor_latches_and_halt(model: ArmModel, clock: VirtualClock,
                                       validator: EnvelopeValidator):
    """面部移到静止臂位（用户前倾）→ 闩锁 FACE_IN_ZONE + 冻结 + 拒绝写。

    正当指令永远不会被允许进入禁区，故"侵入"场景=包络口径变化（球移过来）
    ——等价于真实系统中用户把脸凑到臂边。
    """
    # 先用缺省包络把臂合法送达停点（停点在缺省面部球外）
    arm = MockArm(model, validator=validator, clock=clock)
    arm.enable()
    env_a = SafetyEnvelope(arm, model=model, validator=validator, clock=clock)
    env_a.enable()
    assert stream_to(env_a, clock, STOP_POINT) <= 0.002

    # 面部球移到停点（新监控口径），新包络首查即应如实闩锁
    cfg = {
        "mouth_point_m": list(STOP_POINT),
        "forbidden_zones": [
            {"type": "sphere", "name": "face", "center_m": list(STOP_POINT), "radius_m": 0.12},
            {"type": "capsule", "name": "torso", "p1_m": [0.48, 0.0, -0.10],
             "p2_m": [0.48, 0.0, 0.22], "radius_m": 0.15},
        ],
        "speed_limits_mps": {"approach": 0.15, "near_face": 0.10},
        "near_face_distance_m": 0.15,
    }
    val2 = EnvelopeValidator(cfg)
    env_b = SafetyEnvelope(arm, model=model, validator=val2, clock=clock)
    env_b.enable()
    ss = env_b.poll()
    assert ss.violation is ViolationKind.FACE_IN_ZONE
    assert ss.human_zone_violation is True and ss.clear_to_move is False
    assert not arm.in_motion  # 已冻结
    with pytest.raises(ArmCommandRejected) as ei:
        env_b.write(cart_cmd([0.20, 0.0, 0.10]))
    assert ei.value.reason == "not_clear_to_move"
    # 复位但侵入仍在 → 如实重新闩锁（clear_to_move 不在侵入状态下变真）
    assert env_b.reset().violation is ViolationKind.FACE_IN_ZONE
    # 缺省口径包络不受影响（violation 是各包络实例自己的状态）
    assert env_a.safety_state().violation is ViolationKind.NONE


# ---------------------------------------------------------------------------
# 改写 / 走廊 / 注入批
# ---------------------------------------------------------------------------


def test_cartesian_rewritten_to_joints(env: SafetyEnvelope, clock: VirtualClock):
    n0 = env.stats["cartesian_rewritten_to_joints"]
    stream_to(env, clock, STOP_POINT, step_m=0.05)
    assert env.stats["cartesian_rewritten_to_joints"] > n0
    assert env.last_decision["mode_out"] == "joints"
    assert env.last_decision["rewritten"] is True


def test_delivery_corridor_in_numerical_margin(env: SafetyEnvelope, clock: VirtualClock,
                                               validator: EnvelopeValidator,
                                               model: ArmModel):
    """整段"碗→停点"走廊经包络执行：零拒绝、余量为正、停点在球外、到位 ≤2mm。"""
    margin = validator.delivery_margin()
    assert margin["pass"] is True and margin["margin_m"] >= 0.005
    stop = validator.delivery_stop_point()
    assert (float(np.linalg.norm(stop - validator.config.face_center))
            >= validator.face_radius - 1e-9)  # 停点在面部球面之外
    bowl = np.array([0.22, -0.18, 0.02])
    lift = bowl + np.array([0.0, 0.0, 0.10])
    transit = np.array([0.25, -0.09, 0.20])
    err_bowl = stream_to(env, clock, bowl)
    assert err_bowl <= 0.002
    for a, b in ((bowl, lift), (lift, transit), (transit, stop)):
        n = max(1, int(np.ceil(float(np.linalg.norm(b - a)) / 0.02)))
        for i in range(1, n + 1):
            wp = a + (b - a) * (i / n)
            env.write(cart_cmd(wp, speed=0.05))
            clock.advance_s(env.last_decision["duration_s"] + 0.005)
            st = env.read()
            assert validator.point_zone_violation(np.asarray(st.ee_pos)) is None
    final_err = float(np.linalg.norm(np.asarray(env.read().ee_pos) - stop))
    assert final_err <= 0.002


def test_mixed_injection_batch_zero_violation_executed(
    env: SafetyEnvelope, clock: VirtualClock, validator: EnvelopeValidator,
    model: ArmModel, mock: MockArm,
):
    """混合注入批（缩样）：必须拒的全拒、放行的逐条复核零违规执行。"""
    rng = np.random.default_rng(42)
    face = np.asarray(validator.config.face_center)
    counts: dict[str, dict] = {}

    def record(cat: str, rejected: bool) -> None:
        c = counts.setdefault(cat, {"n": 0, "rejected": 0})
        c["n"] += 1
        if rejected:
            c["rejected"] += 1

    def try_write(cmd: ArmCommand) -> bool:
        q_pre = np.asarray(env.read().joint_pos)
        try:
            env.write(cmd)
        except ArmCommandRejected:
            record(getattr(try_write, "cat", "misc"), True)
            clock.advance_s(0.01)
            assert float(np.max(np.abs(np.asarray(env.read().joint_pos) - q_pre))) == 0.0
            return False
        record(getattr(try_write, "cat", "misc"), False)
        if env.last_decision.get("noop"):
            return True  # 零运动指令：无可审计轨迹
        T = env.last_decision["duration_s"]
        clock.advance_s(T + 0.01)
        st = env.read()
        q_post = np.asarray(st.joint_pos)
        rep = validator.check_joint_trajectory(
            [0.0, max(T, 1e-3)], [q_pre.tolist(), q_post.tolist()], model, label="audit")
        assert not rep["rejected"], rep["violations"][:2]
        assert validator.point_zone_violation(np.asarray(st.ee_pos)) is None
        return True

    # 1) 良性笛卡尔：近旁小步（禁区外），应放行
    try_write.cat = "benign_cartesian"
    for _ in range(12):
        cur = np.asarray(env.read().ee_pos)
        for _ in range(20):
            delta = rng.uniform(-0.05, 0.05, size=3)
            cand = cur + delta
            if (validator.point_zone_violation(cand) is None
                    and validator.min_zone_clearance(cand) > 0.02
                    and 0.05 <= cand[0] <= 0.30):
                break
        else:
            continue
        try_write(cart_cmd(cand, speed=0.05))

    # 2) 良性关节：小噪声（放行后由审计复核）
    try_write.cat = "benign_joints"
    for _ in range(10):
        q0 = np.asarray(env.read().joint_pos)
        cand = np.clip(q0 + rng.uniform(-0.08, 0.08, size=N_ARM_JOINTS),
                       model.joint_lower, model.joint_upper)
        cand[5] = rng.uniform(-0.1, 1.7)  # 夹爪行程
        try_write(joints_cmd(cand, speed=0.4))

    # 3) 面部球域 / 躯干胶囊目标（必须拒）
    try_write.cat = "face_sphere_target"
    for _ in range(10):
        d = rng.uniform(0.0, 0.10)
        direction = rng.normal(size=3)
        direction /= np.linalg.norm(direction)
        try_write(cart_cmd(face + direction * d, speed=0.05))
    try_write.cat = "torso_target"
    torso = next(z for z in validator.config.zones if z.name == "torso")
    for _ in range(6):
        p = (np.asarray(torso.p1) + rng.uniform(0.2, 0.8)
             * (np.asarray(torso.p2) - np.asarray(torso.p1)))
        try_write(cart_cmd(p, speed=0.05))

    # 4) 速度超硬限（必须拒）
    try_write.cat = "joint_speed_over_hard"
    for _ in range(8):
        q0 = np.asarray(env.read().joint_pos)
        cand = np.clip(q0 + rng.uniform(-0.2, 0.2, size=N_ARM_JOINTS),
                       model.joint_lower, model.joint_upper)
        try_write(joints_cmd(cand, speed=float(rng.uniform(2.0, 8.0))))
    try_write.cat = "cart_speed_over_hard"
    for _ in range(6):
        cur = np.asarray(env.read().ee_pos)
        try_write(cart_cmd(cur + np.array([-0.02, 0.0, 0.0]),
                           speed=float(rng.uniform(0.2, 1.0))))

    # 5) 不可达（必须拒）
    try_write.cat = "unreachable"
    for _ in range(3):
        try_write(cart_cmd([2.5, 2.5, 2.5]))

    # 6) 对抗性关节轨迹（cs_sim 独立 oracle：预期全部被包络拒绝）
    #    先 teleport 到样本起点位形，保证被审轨迹与 oracle 生成的轨迹一致。
    from chengshao.cs_sim.adversarial import build_adversarial_cases

    cases = build_adversarial_cases(model, validator, n_joint_speed=4,
                                    n_link_sweep=2, n_tcp_arc=4, seed=99)
    try_write.cat = "adversarial"
    for case in cases:
        qa = np.asarray(case.q_list[0])
        mock.teleport(qa)
        q1 = np.asarray(case.q_list[-1])
        dq = float(np.max(np.abs(q1 - qa)))
        dur = float(case.times_s[-1] - case.times_s[0])
        try_write(joints_cmd(q1, speed=max(dq / dur, 1e-4), timeout=600.0))

    # 断言：必须拒的类别 100% 拒绝；放行的已被逐条审计（零违规执行）
    for cat in ("face_sphere_target", "torso_target", "joint_speed_over_hard",
                "cart_speed_over_hard", "unreachable", "adversarial"):
        assert counts[cat]["rejected"] == counts[cat]["n"], (cat, counts[cat])
    assert counts["benign_cartesian"]["rejected"] < counts["benign_cartesian"]["n"]
    assert counts["benign_joints"]["rejected"] < counts["benign_joints"]["n"]
    total = sum(c["n"] for c in counts.values())
    assert total >= 49
    assert env.stats["rejected"] == sum(c["rejected"] for c in counts.values())


# ---------------------------------------------------------------------------
# FeetechArm 骨架（真机类仅接口 + 参数）
# ---------------------------------------------------------------------------


def test_feetech_config_validation():
    FeetechArmConfig()  # 缺省合法
    with pytest.raises(ValueError):
        FeetechArmConfig(servo_ids=(1, 2, 3, 4, 5))  # 数量≠6
    with pytest.raises(ValueError):
        FeetechArmConfig(servo_ids=(1, 1, 3, 4, 5, 6))  # 重复
    with pytest.raises(ValueError):
        FeetechArmConfig(servo_ids=(1, 2, 3, 4, 5, 0))  # 非正
    with pytest.raises(ValueError):
        FeetechArmConfig(baudrate=0)


def test_feetech_skeleton_fails_loudly_without_hardware():
    arm = FeetechArm(FeetechArmConfig(port="COM3"))
    assert isinstance(arm, ArmInterface)
    assert arm.is_connected is False
    assert arm.heartbeat_ns is None
    with pytest.raises(HardwareUnavailable):
        arm.read()
    with pytest.raises(HardwareUnavailable):
        arm.write(ArmCommand(mode="joints", target=[0.0] * N_ARM_JOINTS,
                             max_speed=0.5, timeout_s=1.0))
    with pytest.raises(HardwareUnavailable):
        arm.enable()
    with pytest.raises(HardwareUnavailable):
        arm.disable()
    with pytest.raises(HardwareUnavailable):
        arm.halt()
    with pytest.raises(HardwareUnavailable):
        arm.connect()


def test_rejection_does_not_latch_violation(env: SafetyEnvelope):
    """拒绝是包络在正确工作：不计入违规状态（clear_to_move 保持）。"""
    with pytest.raises(ArmCommandRejected):
        env.write(cart_cmd([0.42, 0.0, 0.30]))
    ss = env.safety_state()
    assert ss.violation is ViolationKind.NONE
    assert ss.clear_to_move is True
    assert env.stats["rejected_by_reason"].get("envelope_violation", 0) >= 1

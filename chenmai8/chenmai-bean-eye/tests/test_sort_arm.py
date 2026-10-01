"""分拣线 eval · MockArm 协议契约（ArmProtocol 冻结接口的行为语义）。

覆盖：接口符合性（runtime_checkable）、连接生命周期、工作空间边界、限速、
急停闩锁、运动耗时模拟（可加速）、轨迹与事件记录。

运行（仓库根）::

    .venv/Scripts/python.exe -m pytest tests/test_sort_arm.py -q
"""

from __future__ import annotations

import pytest

from beaneye.sort import (
    ArmEStopError,
    ArmError,
    ArmNotConnectedError,
    ArmProtocol,
    ArmSpeedError,
    ArmWorkspaceError,
    MockArm,
    WorkspaceBounds,
)

# 统一测试包络（窄、确定；home=(60,0,40) 在包络内）
BOUNDS = WorkspaceBounds(
    x_min_mm=0.0, x_max_mm=100.0,
    y_min_mm=-50.0, y_max_mm=50.0,
    z_min_mm=0.0, z_max_mm=80.0,
    home_mm=(60.0, 0.0, 40.0),
)

MAX_SPEED = 200.0


@pytest.fixture()
def sleeps():
    """捕获 sleep 调用（零真实等待，确定性断言时长）。"""
    return []


@pytest.fixture()
def arm(sleeps):
    a = MockArm(
        BOUNDS,
        max_speed_mm_s=MAX_SPEED,
        gripper_travel_s=0.3,
        time_scale=1.0,
        now_fn=lambda: 0.0,           # 时间戳不参与本文件断言，恒 0
        sleep_fn=sleeps.append,
    )
    a.connect()
    return a


# ---------------------------------------------------------------------------
# 接口符合性
# ---------------------------------------------------------------------------


def test_mock_arm_satisfies_frozen_protocol():
    """MockArm 必须满足冻结接口 ArmProtocol（runtime_checkable）。"""
    assert isinstance(MockArm(BOUNDS), ArmProtocol)


def test_protocol_surface_is_exactly_the_frozen_six():
    """冻结接口只含六个方法（防止无意加名破坏契约）。"""
    methods = {
        name
        for name, member in vars(ArmProtocol).items()
        if callable(member) and not name.startswith("__")
    }
    assert methods == {"connect", "home", "move_to", "gripper", "estop", "close"}


# ---------------------------------------------------------------------------
# 生命周期
# ---------------------------------------------------------------------------


def test_commands_before_connect_rejected():
    a = MockArm(BOUNDS)
    with pytest.raises(ArmNotConnectedError):
        a.home()
    with pytest.raises(ArmNotConnectedError):
        a.move_to(10, 10, 10, speed=10)


def test_connect_home_close_lifecycle(arm, sleeps):
    assert arm.connected
    arm.home()
    assert arm.position_mm == BOUNDS.home_mm
    arm.close()
    assert not arm.connected
    with pytest.raises(ArmNotConnectedError):
        arm.move_to(10, 10, 10, speed=10)
    arm.close()  # 幂等


# ---------------------------------------------------------------------------
# 工作空间 / 限速校验（拒绝即零运动）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "xyz",
    [
        (100.1, 0.0, 40.0),   # x 超上界
        (-0.1, 0.0, 40.0),    # x 超下界
        (50.0, 50.1, 40.0),   # y 超上界
        (50.0, 0.0, 80.1),    # z 超上界
        (50.0, 0.0, -0.1),    # 桌面之下
    ],
)
def test_move_out_of_workspace_rejected_zero_motion(arm, xyz):
    pos_before = arm.position_mm
    with pytest.raises(ArmWorkspaceError):
        arm.move_to(*xyz, speed=10.0)
    assert arm.position_mm == pos_before  # 零运动
    assert arm.moves == 0


def test_move_within_workspace_arrives(arm):
    arm.move_to(10.0, -20.0, 5.0, speed=50.0)
    assert arm.position_mm == (10.0, -20.0, 5.0)


def test_speed_validation(arm):
    with pytest.raises(ArmSpeedError):
        arm.move_to(10, 10, 10, speed=MAX_SPEED + 0.1)
    with pytest.raises(ArmError):
        arm.move_to(10, 10, 10, speed=0.0)
    with pytest.raises(ArmError):
        arm.move_to(10, 10, 10, speed=-5.0)
    assert arm.moves == 0


# ---------------------------------------------------------------------------
# 急停闩锁
# ---------------------------------------------------------------------------


def test_estop_latches_and_blocks_motion(arm):
    arm.move_to(20, 0, 20, speed=50)
    arm.estop()
    assert arm.estop_latched
    with pytest.raises(ArmEStopError):
        arm.move_to(30, 0, 20, speed=50)
    with pytest.raises(ArmEStopError):
        arm.home()
    with pytest.raises(ArmEStopError):
        arm.gripper(True)
    assert arm.position_mm == (20.0, 0.0, 20.0)  # 急停后零运动


def test_estop_is_idempotent_and_works_when_disconnected():
    a = MockArm(BOUNDS)
    a.estop()
    a.estop()  # 幂等，不抛


def test_estop_reset_is_mock_only_extension(arm):
    """reset_estop 解锁后可恢复运动（真机无此操作，Mock 测试辅助）。"""
    arm.estop()
    arm.reset_estop()
    arm.move_to(10, 0, 10, speed=10)
    assert arm.position_mm == (10.0, 0.0, 10.0)


# ---------------------------------------------------------------------------
# 运动耗时模拟（可加速）与轨迹/事件记录
# ---------------------------------------------------------------------------


def test_motion_duration_scales_with_distance_and_speed(arm, sleeps):
    arm.move_to(0.0, 0.0, 0.0, speed=100.0)
    # 起点为 home(60,0,40)：直线距离 = sqrt(60² + 40²) = sqrt(5200) ≈ 72.11mm
    expected = (60.0**2 + 40.0**2) ** 0.5 / 100.0
    assert len(sleeps) == 1
    assert sleeps[0] == pytest.approx(expected, rel=1e-9)


def test_time_scale_accelerates_motion(sleeps):
    a = MockArm(BOUNDS, time_scale=10.0, now_fn=lambda: 0.0, sleep_fn=sleeps.append)
    a.connect()
    a.move_to(0.0, 0.0, 0.0, speed=100.0)
    expected = (60.0**2 + 40.0**2) ** 0.5 / 100.0 / 10.0
    assert sleeps[-1] == pytest.approx(expected, rel=1e-9)


def test_time_scale_below_one_rejected():
    with pytest.raises(ValueError):
        MockArm(BOUNDS, time_scale=0.5)


def test_gripper_records_state_and_duration(arm, sleeps):
    arm.gripper(False)
    assert not arm.gripper_is_open
    assert sleeps[-1] == pytest.approx(0.3, rel=1e-9)
    arm.gripper(True)
    assert arm.gripper_is_open


def test_trajectory_and_events_recorded(arm):
    arm.home()
    arm.move_to(10.0, 0.0, 5.0, speed=20.0)
    arm.gripper(False)
    arm.estop()
    arm.close()

    traj = arm.trajectory
    assert traj[0]["phase"] == "init"
    assert traj[0]["x_mm"] == pytest.approx(BOUNDS.home_mm[0])
    assert traj[-1]["x_mm"] == pytest.approx(10.0)

    kinds = [e["kind"] for e in arm.events]
    # 注：home() 内部先直线移动（产生 move）再记 home 事件；已在 home 位时零行程 move 也记录
    assert kinds == ["connect", "move", "home", "move", "gripper_close", "estop", "close"]

    assert arm.travel_mm == pytest.approx(
        ((60.0 - 10.0) ** 2 + 0.0**2 + (40.0 - 5.0) ** 2) ** 0.5,  # home→目标（home 段零行程）
        rel=1e-9,
    )


def test_hook_called_after_each_command(sleeps):
    seen: list[str] = []
    a = MockArm(BOUNDS, now_fn=lambda: 0.0, sleep_fn=sleeps.append,
                hook=lambda kind, detail: seen.append(kind))
    a.connect()
    a.home()
    assert seen == ["connect", "move", "home"]


def test_home_outside_bounds_rejected_at_construction():
    """包络不变式（含 home 可达）在 WorkspaceBounds 构造期即校验。"""
    from beaneye.sort import SortConfigError
    with pytest.raises(SortConfigError):
        WorkspaceBounds(
            x_min_mm=0.0, x_max_mm=10.0, y_min_mm=0.0, y_max_mm=10.0,
            z_min_mm=0.0, z_max_mm=10.0, home_mm=(50.0, 5.0, 5.0),
        )
    with pytest.raises(SortConfigError):
        WorkspaceBounds(
            x_min_mm=10.0, x_max_mm=0.0, y_min_mm=0.0, y_max_mm=10.0,
            z_min_mm=0.0, z_max_mm=10.0, home_mm=(5.0, 5.0, 5.0),
        )
    with pytest.raises(SortConfigError):
        WorkspaceBounds(
            x_min_mm=0.0, x_max_mm=10.0, y_min_mm=0.0, y_max_mm=10.0,
            z_min_mm=-1.0, z_max_mm=10.0, home_mm=(5.0, 5.0, 5.0),
        )


def test_bounds_contains_and_check():
    assert BOUNDS.contains(50, 0, 10)
    assert not BOUNDS.contains(150, 0, 10)
    assert not BOUNDS.contains(100.0, 0.0, 10.0, tol=-1.0)  # 负容差收紧：贴边点被拒
    assert BOUNDS.contains(100.0, 0.0, 10.0)                # 默认含边界
    from beaneye.sort import SortConfigError
    with pytest.raises(SortConfigError):
        BOUNDS.check(150, 0, 10)

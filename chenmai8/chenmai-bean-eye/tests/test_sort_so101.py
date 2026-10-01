"""分拣线 eval · SO101Arm + MockTransport 全协议自测（不 import lerobot 真件）。

覆盖：

- 本模块 import 不依赖 lerobot（模块级惰性 import 契约）；
- 未安装 lerobot 时 connect() 抛 RuntimeError 附安装指引；
- 注入 MockTransport 后 connect/home/move_to/gripper/estop/close 全协议
  逻辑走通：IK 关节角在限位内、度→raw 换算正确、到位轮询收敛、
  急停闩锁拒绝运动并下力矩、未连接拒绝、超关节限位/不可达拒绝。

运行（仓库根）::

    .venv/Scripts/python.exe -m pytest tests/test_sort_so101.py -q
"""

from __future__ import annotations

import importlib.util
import sys

import pytest

from beaneye.sort import (
    ArmEStopError,
    ArmError,
    ArmNotConnectedError,
    ArmProtocol,
    ArmWorkspaceError,
    SO101Arm,
    load_sort_config,
    solve_ik_3dof,
)
from beaneye.sort.config import SortConfig, So101Params

CFG = load_sort_config()

HAS_LEROBOT = importlib.util.find_spec("lerobot") is not None


# ---------------------------------------------------------------------------
# MockTransport：内存 Feetech 通道（协议替身，即时到位）
# ---------------------------------------------------------------------------


class MockTransport:
    """内存舵机总线：记录全部调用，写目标位置即刻反映到回读。"""

    def __init__(self, cfg: SortConfig) -> None:
        self.cfg = cfg
        self.calls: list[tuple] = []
        self._raw: dict[str, float] = {name: spec.center_raw for name, spec in cfg.so101.motors.items()}
        self._torque_on = False
        self._opened = False
        self._speed_reg: int | None = None
        # 夹爪初始记为张开（适配器构造语义：gripper_is_open 初始 True）
        self._raw["gripper"] = cfg.so101.motors["gripper"].center_raw + \
            cfg.so101.gripper_open_deg * cfg.so101.motors["gripper"].raw_per_deg

    # -- SO101Transport 协议 ---------------------------------------------------

    def open(self) -> None:
        self.calls.append(("open",))
        self._opened = True

    def close(self) -> None:
        self.calls.append(("close",))
        self._opened = False

    def enable_torque(self, on: bool) -> None:
        self.calls.append(("enable_torque", on))
        self._torque_on = on

    def set_goal_speed(self, value: int) -> None:
        self.calls.append(("set_goal_speed", value))
        self._speed_reg = value

    def read_positions(self) -> dict[str, float]:
        self.calls.append(("read_positions",))
        return dict(self._raw)

    def write_goal_positions(self, goals: dict[str, float]) -> None:
        self.calls.append(("write_goal_positions", dict(goals)))
        assert self._torque_on, "Feetech 语义：未使能力矩时目标写入不生效"
        self._raw.update(goals)

    # -- 测试辅助 ---------------------------------------------------------------

    @property
    def torque_on(self) -> bool:
        return self._torque_on

    @property
    def opened(self) -> bool:
        return self._opened

    def deg(self, name: str) -> float:
        spec = self.cfg.so101.motors[name]
        return (self._raw[name] - spec.center_raw) / spec.raw_per_deg


# ---------------------------------------------------------------------------
# 惰性 import 契约
# ---------------------------------------------------------------------------


def test_module_import_does_not_require_or_import_lerobot():
    """import beaneye.sort.so101 不得把 lerobot 拉进 sys.modules（无 lerobot 环境即可 import）。"""
    import beaneye.sort.so101 as so101_mod

    assert "lerobot" not in sys.modules
    # 真机通道构建方法体惰性 import：模块源码里 import lerobot 只能出现在函数体内
    src_lines = so101_mod.__dict__.get("__name__") and True  # 占位保证模块已加载
    assert src_lines
    import inspect
    source = inspect.getsource(so101_mod)
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith("import lerobot") or stripped.startswith("from lerobot"):
            indent = len(line) - len(line.lstrip())
            assert indent > 0, f"模块级 lerobot import 违反惰性契约: {line!r}"


@pytest.mark.skipif(HAS_LEROBOT, reason="环境已安装 lerobot，无安装指引路径可测")
def test_connect_without_lerobot_raises_runtime_error_with_install_hint():
    """未安装 lerobot 时 connect() 抛 RuntimeError 并附安装指引。"""
    arm = SO101Arm(config=CFG)
    with pytest.raises(RuntimeError, match="requirements-arm.txt"):
        arm.connect()


def test_so101_arm_satisfies_frozen_protocol():
    assert isinstance(SO101Arm(transport=MockTransport(CFG), config=CFG), ArmProtocol)


# ---------------------------------------------------------------------------
# 全协议自测（MockTransport 注入）
# ---------------------------------------------------------------------------


@pytest.fixture()
def transport():
    return MockTransport(CFG)


@pytest.fixture()
def arm(transport):
    sleeps: list[float] = []
    a = SO101Arm(transport, config=CFG, sleep_fn=sleeps.append, now_fn=lambda: 0.0)
    a.connect()
    return a


def test_connect_opens_bus_and_enables_torque(transport, arm):
    assert ("open",) in transport.calls
    assert ("enable_torque", True) in transport.calls
    assert arm.connected


def test_connect_idempotent(arm, transport):
    opens = transport.calls.count(("open",))
    arm.connect()
    assert transport.calls.count(("open",)) == opens


def test_home_moves_to_safe_joints(transport, arm):
    arm.home()
    # home 姿态 = base 0 / shoulder 0 / elbow 70 / wrist -70（度）
    assert transport.deg("base") == pytest.approx(0.0, abs=1e-6)
    assert transport.deg("shoulder") == pytest.approx(0.0, abs=1e-6)
    assert transport.deg("elbow") == pytest.approx(70.0, abs=1e-6)
    assert transport.deg("wrist") == pytest.approx(-70.0, abs=1e-6)
    # 每段运动先写速度寄存器再写目标位置
    kinds = [c[0] for c in transport.calls]
    first_move_speed = kinds.index("set_goal_speed")
    assert kinds[first_move_speed + 1] == "write_goal_positions"


def test_move_to_full_chain_ik_conversion_polling(transport, arm):
    """桌面坐标 → IK → 度→raw 广播写 → 回读收敛判定到位。"""
    arm.move_to(120.0, 20.0, 30.0, speed=60.0)
    joints = arm.joint_angles_deg()
    expect = solve_ik_3dof(
        120.0, 20.0, 30.0,
        base_offset_mm=CFG.so101.base_offset_mm,
        shoulder_z_mm=CFG.so101.shoulder_z_mm,
        l1_mm=CFG.so101.l1_mm,
        l2_mm=CFG.so101.l2_mm,
    )
    for name, deg in expect.items():
        assert joints[name] == pytest.approx(deg, abs=1e-6)
    # 速度寄存器值 = min(speed, max)*scaling（本例 60mm/s × 1.0）
    speed_calls = [c[1] for c in transport.calls if c[0] == "set_goal_speed"]
    assert speed_calls[-1] == 60


def test_move_speed_clamped_to_config_max(transport, arm):
    arm.move_to(120.0, 0.0, 30.0, speed=CFG.speeds.max_mm_s + 500.0)  # 适配器钳制到硬上限
    speed_calls = [c[1] for c in transport.calls if c[0] == "set_goal_speed"]
    assert speed_calls[-1] == int(CFG.speeds.max_mm_s * CFG.so101.speed_scaling)


def test_ik_unreachable_target_rejected_zero_motion(transport, arm):
    with pytest.raises(ArmWorkspaceError, match="可达域"):
        arm.move_to(5000.0, 0.0, 30.0, speed=50.0)  # 远超连杆和
    assert not any(c[0] == "write_goal_positions" for c in transport.calls)


def test_ik_base_offset_zone_rejected(transport, arm):
    with pytest.raises(ArmWorkspaceError, match="偏移圆"):
        arm.move_to(5.0, 0.0, 30.0, speed=50.0)  # 基座正上方，r<0


def test_joint_limit_violation_rejected():
    """收紧肩关节限位后，桌面可达但关节超限的目标必须拒绝（硬件保护第二闸）。"""
    import dataclasses
    from pathlib import Path
    import yaml
    import tempfile

    raw = yaml.safe_load(Path(CFG.source_path).read_text(encoding="utf-8"))
    raw["so101"]["motors"]["shoulder"]["min_deg"] = -30.0
    raw["so101"]["motors"]["shoulder"]["max_deg"] = 30.0
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as f:
        yaml.safe_dump(raw, f, allow_unicode=True)
        path = f.name
    try:
        tight = load_sort_config(path)
    finally:
        Path(path).unlink(missing_ok=True)
    t = MockTransport(tight)
    a = SO101Arm(t, config=tight, sleep_fn=lambda s: None, now_fn=lambda: 0.0)
    a.connect()
    # (170, 90, 8) 需要 shoulder ≈ -47°，超出 ±30° → 拒绝且零运动
    with pytest.raises(ArmWorkspaceError, match="shoulder"):
        a.move_to(170.0, 90.0, 8.0, speed=50.0)
    assert not any(c[0] == "write_goal_positions" for c in t.calls)


def test_gripper_open_close_writes_gripper_joint(transport, arm):
    arm.gripper(False)
    assert transport.deg("gripper") == pytest.approx(CFG.so101.gripper_closed_deg, abs=1e-6)
    arm.gripper(True)
    assert transport.deg("gripper") == pytest.approx(CFG.so101.gripper_open_deg, abs=1e-6)


def test_estop_latches_disables_torque_and_blocks_motion(transport, arm):
    arm.estop()
    assert arm.estop_latched
    assert ("enable_torque", False) in transport.calls  # 下力矩
    with pytest.raises(ArmEStopError):
        arm.move_to(120.0, 0.0, 30.0, speed=50.0)
    with pytest.raises(ArmEStopError):
        arm.home()
    with pytest.raises(ArmEStopError):
        arm.gripper(True)
    assert not any(c[0] == "write_goal_positions" for c in transport.calls)


def test_estop_swallows_transport_failure():
    """急停路径永不抛错：transport 下力矩炸了也要闩锁并如实记录。"""
    class BrokenTransport(MockTransport):
        def enable_torque(self, on):
            if not on:
                raise OSError("总线已死")
            super().enable_torque(on)

    t = BrokenTransport(CFG)
    a = SO101Arm(t, config=CFG, sleep_fn=lambda s: None, now_fn=lambda: 0.0)
    a.connect()
    a.estop()  # 不抛
    assert a.estop_latched
    assert "transport_error" in a.events[-1]["detail"]


def test_commands_before_connect_rejected():
    a = SO101Arm(transport=MockTransport(CFG), config=CFG)
    with pytest.raises(ArmNotConnectedError):
        a.home()
    with pytest.raises(ArmNotConnectedError):
        a.move_to(120, 0, 30, speed=50)
    with pytest.raises(ArmNotConnectedError):
        a.gripper(True)


def test_close_disables_torque_and_closes_bus(transport, arm):
    arm.close()
    assert ("enable_torque", False) in transport.calls
    assert ("close",) in transport.calls
    assert not arm.connected
    arm.close()  # 幂等


def test_events_recorded(transport, arm):
    arm.home()
    arm.move_to(150.0, 10.0, 40.0, speed=40.0)
    arm.gripper(False)
    kinds = [e["kind"] for e in arm.events]
    assert kinds[0] == "connect"
    assert "home" in kinds and "move" in kinds and "gripper_close" in kinds
    move_ev = next(e for e in arm.events if e["kind"] == "move")
    assert move_ev["detail"]["to_mm"] == [150.0, 10.0, 40.0]


# ---------------------------------------------------------------------------
# IK 纯函数
# ---------------------------------------------------------------------------


def test_solve_ik_forward_position_consistency():
    """IK 解回代：base 对准方位角；平面二连杆几何到目标点（容差 1e-6）。"""
    import math
    so = CFG.so101
    x, y, z = 150.0, -40.0, 20.0
    j = solve_ik_3dof(x, y, z, base_offset_mm=so.base_offset_mm,
                      shoulder_z_mm=so.shoulder_z_mm, l1_mm=so.l1_mm, l2_mm=so.l2_mm)
    assert j["base"] == pytest.approx(math.degrees(math.atan2(y, x)), abs=1e-9)
    r = math.hypot(x, y) - so.base_offset_mm
    h = z - so.shoulder_z_mm
    t1, t2 = math.radians(j["shoulder"]), math.radians(j["elbow"])
    # 肘上构型正解：腕点 = 肩 + L1·(cos t1, sin t1) + L2·(cos(t1+t2), sin(t1+t2))
    wx = so.l1_mm * math.cos(t1) + so.l2_mm * math.cos(t1 + t2)
    wz = so.l1_mm * math.sin(t1) + so.l2_mm * math.sin(t1 + t2)
    assert wx == pytest.approx(r, abs=1e-6)
    assert wz == pytest.approx(h, abs=1e-6)
    # wrist 保持工具竖直：wrist = -(shoulder+elbow)
    assert j["wrist"] == pytest.approx(-(j["shoulder"] + j["elbow"]), abs=1e-9)

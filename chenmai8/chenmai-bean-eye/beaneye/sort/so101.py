"""分拣线 · SO101Arm：SO-101 真机适配器（ArmProtocol 的硬件实现）。

设计要点（与冻结契约的关系）：

- **接口冻结**：对外只暴露 ArmProtocol 六方法；SO-101 专有逻辑（Feetech
  总线、关节 IK、位置寄存器换算）全部收在本实现内部；
- **lerobot 惰性 import**：``import lerobot`` 一律放在方法体内——本模块
  **不依赖 lerobot 即可 import**（测试与 Mock 链路不受影响）；未安装 lerobot
  时 :meth:`SO101Arm.connect` 抛 :class:`RuntimeError` 并附安装指引
  （独立 .venv-arm，勿污染钉版环境，见 requirements-arm.txt 与
  docs/SO101联调手册.md）;
- **transport 注入**：构造函数 ``transport=None`` 走真实 Feetech 串口总线；
  测试注入 MockTransport（鸭子类型满足 :class:`SO101Transport`）即可把
  connect/home/move/gripper/estop/close **全协议逻辑**离线走通；
- **运动学 v0**：基座偏航 + 竖直平面二连杆 IK（夹爪保持竖直向下的抓取
  姿态），几何参数读 configs/sort.yaml ``so101`` 节（占位默认值，明日实测
  核对）。不可达目标抛 :class:`ArmWorkspaceError`（零运动）；
- **急停语义**：``estop()`` 立即下力矩并闩锁（安全路径永不抛错）；闩锁中
  运动指令 :class:`ArmEStopError`。

诚实声明：真机路径（``transport=None``）的分毫秒级参数（位置换算、速度
寄存器、关节限位）是占位默认值，**今晚无硬件、未实测**；明天按
docs/SO101联调手册.md 核对回填后空载慢速试跑。
"""

from __future__ import annotations

import math
import time
from typing import Any, Callable, Protocol

from beaneye.sort.arm import (
    ArmEStopError,
    ArmError,
    ArmNotConnectedError,
    ArmWorkspaceError,
)
from beaneye.sort.config import SortConfig, load_sort_config

__all__ = ["SO101Transport", "SO101Arm", "solve_ik_3dof"]

_INSTALL_HINT = (
    "未安装 lerobot，无法连接 SO-101 真机。安装指引（独立环境，勿污染钉版核心环境）：\n"
    "  1) python -m venv .venv-arm\n"
    "  2) .venv-arm\\Scripts\\pip install -r requirements-arm.txt\n"
    "  3) 详见 docs/SO101联调手册.md（接线 / 自检 / 三点标定 / 空载试跑）"
)


class SO101Transport(Protocol):
    """底层通道接口（SO101Arm 专有，**不属于冻结 ArmProtocol**）。

    真实实现 = lerobot Feetech 总线包装（connect 内惰性构建）；测试实现 =
    MockTransport（内存舵机，见 tests/test_sort_so101.py）。
    """

    def open(self) -> None: ...
    def close(self) -> None: ...
    def enable_torque(self, on: bool) -> None: ...
    def set_goal_speed(self, value: int) -> None:
        """设置全部舵机的速度寄存器值（无量纲，换算在适配器做）。"""
        ...
    def read_positions(self) -> dict[str, float]:
        """回读全部舵机原始位置寄存器 {电机名: raw}。"""
        ...
    def write_goal_positions(self, goals: dict[str, float]) -> None:
        """下发目标位置寄存器 {电机名: raw}（广播写，不等待到位）。"""
        ...


# ---------------------------------------------------------------------------
# 运动学 v0：基座偏航 + 竖直平面二连杆（夹爪竖直向下）
# ---------------------------------------------------------------------------


def solve_ik_3dof(
    x_mm: float,
    y_mm: float,
    z_mm: float,
    *,
    base_offset_mm: float,
    shoulder_z_mm: float,
    l1_mm: float,
    l2_mm: float,
) -> dict[str, float]:
    """桌面坐标 (x, y, z) → 关节角（度）：{base, shoulder, elbow, wrist}。

    模型（抓取姿态 v0，夹爪竖直向下、wrist roll 置 0）：

    - 基座偏航 ``base = atan2(y, x)``；
    - 竖直平面内：径向 ``r = hypot(x, y) - base_offset``，高度 ``h = z - shoulder_z``；
    - 标准二连杆余弦解（肘上构型）；``wrist = -(shoulder + elbow)`` 保持工具竖直。

    不可达（r < 0 或 |D| > 1）抛 :class:`ArmWorkspaceError`。
    """
    r = math.hypot(x_mm, y_mm) - base_offset_mm
    h = z_mm - shoulder_z_mm
    if r < 0:
        raise ArmWorkspaceError(
            f"目标 ({x_mm:.1f}, {y_mm:.1f}) 落在基座偏移圆内（r={r:.1f}mm < 0），不可达"
        )
    d = (r * r + h * h - l1_mm * l1_mm - l2_mm * l2_mm) / (2.0 * l1_mm * l2_mm)
    if abs(d) > 1.0:
        raise ArmWorkspaceError(
            f"目标 ({x_mm:.1f}, {y_mm:.1f}, {z_mm:.1f}) mm 超出连杆可达域"
            f"（l1={l1_mm}+l2={l2_mm}mm，径向 r={r:.1f}，高度 h={h:.1f}）"
        )
    elbow = math.acos(d)  # 肘上构型
    shoulder = math.atan2(h, r) - math.atan2(
        l2_mm * math.sin(elbow), l1_mm + l2_mm * math.cos(elbow)
    )
    base = math.atan2(y_mm, x_mm)
    return {
        "base": math.degrees(base),
        "shoulder": math.degrees(shoulder),
        "elbow": math.degrees(elbow),
        "wrist": -(math.degrees(shoulder) + math.degrees(elbow)),
    }


# ---------------------------------------------------------------------------
# 适配器
# ---------------------------------------------------------------------------


class SO101Arm:
    """SO-101 桌面臂适配器（ArmProtocol 实现；lerobot 惰性依赖）。"""

    def __init__(
        self,
        transport: SO101Transport | None = None,
        *,
        config: SortConfig | None = None,
        ik: Callable[..., dict[str, float]] | None = None,
        now_fn: Callable[[], float] | None = None,
        sleep_fn: Callable[[float], None] | None = None,
    ) -> None:
        """``transport=None`` 走真实 Feetech 端口（connect 时惰性 import lerobot）；
        测试注入 transport 替身即可离线走通全协议。``ik`` 可注入替代运动学
        （缺省 :func:`solve_ik_3dof`，几何取 configs/sort.yaml）。
        """
        self._cfg = config if config is not None else load_sort_config()
        self._transport = transport
        self._ik = ik if ik is not None else solve_ik_3dof
        self._now = now_fn if now_fn is not None else time.perf_counter
        self._sleep = sleep_fn if sleep_fn is not None else time.sleep
        self._connected = False
        self._estop_latched = False
        self._events: list[dict] = []
        self._gripper_open = True

    # ---- 冻结接口（ArmProtocol） ------------------------------------------

    def connect(self) -> None:
        """打开 Feetech 总线并使能力矩（真机路径惰性 import lerobot）。"""
        if self._connected:
            return
        transport = self._transport if self._transport is not None else self._build_real_transport()
        transport.open()
        self._transport = transport
        transport.enable_torque(True)
        self._connected = True
        self._event("connect", {"port": self._cfg.so101.port,
                                "motors": sorted(self._cfg.so101.motors)})

    def home(self) -> None:
        """回安全位：把 IK 的中位关节角写为 home 姿态（基座回 0、臂抬起）。"""
        self._require_ready()
        joints = {"base": 0.0, "shoulder": 0.0, "elbow": 70.0, "wrist": -70.0}
        self._move_joints(joints, speed=self._cfg.speeds.travel_mm_s, phase="home")

    def move_to(self, x_mm: float, y_mm: float, z_mm: float, *, speed: float) -> None:
        """桌面坐标 → IK 关节角 → 广播写目标位置 → 轮询等待到位。"""
        self._require_ready()
        x, y, z = float(x_mm), float(y_mm), float(z_mm)
        so = self._cfg.so101
        if float(speed) <= 0:
            raise ArmError(f"speed 必须 > 0，得到 {speed}")
        joints = self._ik(
            x, y, z,
            base_offset_mm=so.base_offset_mm,
            shoulder_z_mm=so.shoulder_z_mm,
            l1_mm=so.l1_mm,
            l2_mm=so.l2_mm,
        )
        self._check_joint_limits(joints, table_target=(x, y, z))
        self._move_joints(joints, speed=float(speed), phase="move",
                          detail={"to_mm": [x, y, z]})

    def gripper(self, open: bool) -> None:  # noqa: A002 — 冻结契约参数名
        """夹爪开合（度 → 位置寄存器，等待到位）。"""
        self._require_ready()
        so = self._cfg.so101
        deg = so.gripper_open_deg if open else so.gripper_closed_deg
        self._move_joints({"gripper": deg}, speed=self._cfg.speeds.travel_mm_s,
                          phase="gripper_open" if open else "gripper_close")

    def estop(self) -> None:
        """立即下力矩并闩锁（永不抛错、幂等；transport 缺位时只记事件）。"""
        self._estop_latched = True
        detail: dict[str, Any] = {"torque_off": self._cfg.estop.torque_off}
        if self._transport is not None and self._connected:
            try:
                if self._cfg.estop.torque_off:
                    self._transport.enable_torque(False)
            except Exception as exc:  # 急停路径必须吞错并如实记录
                detail["transport_error"] = f"{exc.__class__.__name__}: {exc}"
        self._event("estop", detail)

    def close(self) -> None:
        """安全下电并关总线（幂等）。"""
        if self._transport is not None and self._connected:
            try:
                self._transport.enable_torque(False)
            except Exception:
                pass
            try:
                self._transport.close()
            except Exception:
                pass
        self._connected = False
        self._event("close", {})

    # ---- SO101 专有扩展 ------------------------------------------------------

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def estop_latched(self) -> bool:
        return self._estop_latched

    @property
    def events(self) -> list[dict]:
        return [dict(e) for e in self._events]

    def joint_angles_deg(self) -> dict[str, float]:
        """当前关节角（度；raw 反算，自检/标定用）。"""
        self._require_connected()
        assert self._transport is not None
        raw = self._transport.read_positions()
        return {name: self._raw_to_deg(name, raw[name]) for name in raw}

    # ---- 内部 ------------------------------------------------------------------

    def _build_real_transport(self) -> SO101Transport:
        """构建真实 Feetech 总线通道（惰性 import lerobot；未安装即抛安装指引）。"""
        try:
            from lerobot.motors.feetech import (  # type: ignore[import-not-found]
                FeetechMotorsBus,
            )
        except ImportError:
            try:  # 旧版布局兜底（lerobot < 0.3）
                from lerobot.common.robot_devices.motors.feetech import (  # type: ignore[import-not-found,no-redef]
                    FeetechMotorsBus,
                )
            except ImportError as exc:
                raise RuntimeError(_INSTALL_HINT) from exc
        so = self._cfg.so101
        motors = {name: {"id": spec.id, "model": "sts3215"} for name, spec in so.motors.items()}
        try:
            bus = FeetechMotorsBus(
                port=so.port,
                motors=motors,
                extra_model_resolution_table=None,  # 新版签名；旧版多余 kwargs 由 except 兜底
            )
        except TypeError:
            bus = FeetechMotorsBus(port=so.port, motors=motors)  # 旧版签名
        return _FeetechTransportAdapter(bus)

    def _require_connected(self) -> None:
        if not self._connected:
            raise ArmNotConnectedError("SO101Arm 未连接（先调用 connect()）")

    def _require_ready(self) -> None:
        if self._estop_latched:
            raise ArmEStopError("急停闩锁中：所有运动指令被拒绝")
        self._require_connected()

    def _check_joint_limits(self, joints: dict[str, float], *, table_target: tuple[float, float, float]) -> None:
        so = self._cfg.so101
        for name, deg in joints.items():
            spec = so.motors.get(name)
            if spec is None:
                raise ArmError(f"IK 输出未知关节 {name!r}（configs/sort.yaml so101.motors 缺项）")
            if not (spec.min_deg <= deg <= spec.max_deg):
                raise ArmWorkspaceError(
                    f"目标 {table_target} 需要 {name}={deg:.1f}°，超关节限位 "
                    f"[{spec.min_deg}, {spec.max_deg}]°（桌面目标不可达）"
                )

    def _move_joints(self, joints_deg: dict[str, float], *, speed: float, phase: str,
                     detail: dict | None = None) -> None:
        """写速度 → 广播目标位置 → 轮询到位（超时 :class:`ArmError`）。"""
        assert self._transport is not None
        so = self._cfg.so101
        speed_val = max(1, int(round(min(speed, self._cfg.speeds.max_mm_s) * so.speed_scaling)))
        self._transport.set_goal_speed(speed_val)
        goals = {name: self._deg_to_raw(name, deg) for name, deg in joints_deg.items()}
        self._transport.write_goal_positions(goals)

        deadline = self._now() + so.move_timeout_s
        while True:
            present = self._transport.read_positions()
            err = max(
                abs(self._raw_to_deg(name, present[name]) - deg)
                for name, deg in joints_deg.items()
            )
            if err <= so.arrival_tol_deg:
                break
            if self._now() >= deadline:
                raise ArmError(
                    f"运动超时（>{so.move_timeout_s}s 未到位，残差 {err:.1f}°）："
                    "检查供电/堵转/总线；详见 docs/SO101联调手册.md 常见问题"
                )
            self._sleep(so.poll_interval_s)
        self._event(phase, {**(detail or {}), "joints_deg": {k: round(v, 2) for k, v in joints_deg.items()},
                            "speed_reg": speed_val})

    def _deg_to_raw(self, name: str, deg: float) -> float:
        spec = self._cfg.so101.motors[name]
        return spec.center_raw + deg * spec.raw_per_deg

    def _raw_to_deg(self, name: str, raw: float) -> float:
        spec = self._cfg.so101.motors[name]
        return (float(raw) - spec.center_raw) / spec.raw_per_deg

    def _event(self, kind: str, detail: dict) -> None:
        self._events.append({"t_s": round(float(self._now()), 6), "kind": kind, "detail": detail})


class _FeetechTransportAdapter:
    """lerobot FeetechMotorsBus → SO101Transport 的真实通道包装。

    方法体全部惰性 import；接口签名以 lerobot 官方文档为准，明日装机后
    按 docs/SO101联调手册.md §3 自检核对（今晚无硬件，未实测）。
    """

    def __init__(self, bus: Any) -> None:
        self._bus = bus

    def open(self) -> None:
        self._bus.connect()

    def close(self) -> None:
        self._bus.disconnect()

    def enable_torque(self, on: bool) -> None:
        self._bus.enable_torque() if on else self._bus.disable_torque()

    def set_goal_speed(self, value: int) -> None:
        # 速度寄存器地址/量纲按 STS3215 手册核对（明日联调项）
        self._bus.write("Goal_Speed", value)  # type: ignore[attr-defined]

    def read_positions(self) -> dict[str, float]:
        return {name: float(v) for name, v in self._bus.read("Present_Position").items()}

    def write_goal_positions(self, goals: dict[str, float]) -> None:
        self._bus.write("Goal_Position", goals)  # type: ignore[attr-defined]

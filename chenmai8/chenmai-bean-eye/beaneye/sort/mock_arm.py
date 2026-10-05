"""分拣线 · MockArm：内存模拟臂（ArmProtocol 的仿真实现）。

语义（SO-101 到货前的全逻辑验证载体，今晚跑通全部分拣软件链）：

- **工作空间边界校验**：构造时给定 :class:`~beaneye.sort.config.WorkspaceBounds`，
  任何 move_to/home 越界即 :class:`ArmWorkspaceError`（零运动）；
- **限速校验**：``speed <= max_speed_mm_s``，超限 :class:`ArmSpeedError`；
- **模拟运动耗时**：按 距离/速度 计算时长并 ``sleep``（经 ``time_scale`` 加速，
  ``sleep_fn`` 可注入以便测试零等待）；同步语义——``move_to`` 返回即到位；
- **记录轨迹与事件**：``trajectory`` 逐命令记录位置采样（t + xyz），``events``
  记录 connect/home/move/gripper/estop/close 全事件（供 Session 导出 JSON 与
  render 画轨迹）；
- **软件急停**：``estop()`` 闩锁（永不抛错、幂等），闩锁中一切运动指令
  :class:`ArmEStopError`；``reset_estop()`` 仅 Mock 提供（真机无此操作，
  不属于冻结协议）。

时钟与等待可注入（测试确定性）：``now_fn()`` 单调秒，``sleep_fn(s)`` 等待。
"""

from __future__ import annotations

import time
from typing import Callable

from beaneye.sort.arm import (
    ArmEStopError,
    ArmError,
    ArmNotConnectedError,
    ArmSpeedError,
    ArmWorkspaceError,
)
from beaneye.sort.config import WorkspaceBounds

__all__ = ["MockArm"]

_EVENT_KINDS = (
    "connect", "home", "move", "gripper_open", "gripper_close",
    "estop", "estop_reset", "close",
)


class MockArm:
    """内存模拟臂：实现冻结接口 ArmProtocol 的全部语义（不接任何硬件）。"""

    def __init__(
        self,
        bounds: WorkspaceBounds,
        *,
        max_speed_mm_s: float = 120.0,
        gripper_travel_s: float = 0.3,
        time_scale: float = 1.0,
        now_fn: Callable[[], float] | None = None,
        sleep_fn: Callable[[float], None] | None = None,
        hook: Callable[[str, dict], None] | None = None,
    ) -> None:
        """``time_scale``：运动耗时的加速倍率（>=1，越大越快）；``hook``：
        每条命令完成后回调 ``hook(kind, detail)``（测试在链路中途触发急停用）。
        """
        if time_scale < 1.0:
            raise ValueError(f"time_scale 必须 >= 1（只加速不减慢），得到 {time_scale}")
        self._bounds = bounds
        self._max_speed = float(max_speed_mm_s)
        self._gripper_s = float(gripper_travel_s)
        self._time_scale = float(time_scale)
        self._now = now_fn if now_fn is not None else time.perf_counter
        self._sleep = sleep_fn if sleep_fn is not None else time.sleep
        self._hook = hook

        self._connected = False
        self._closed = False
        self._estop_latched = False
        self._gripper_open = True
        home = bounds.home_mm
        self._pos = (float(home[0]), float(home[1]), float(home[2]))
        self._trajectory: list[dict] = []
        self._events: list[dict] = []
        self._travel_mm = 0.0
        self._moves = 0
        self._record_point("init")

    # ---- 冻结接口（ArmProtocol） ------------------------------------------

    def connect(self) -> None:
        """置位连接标志（幂等；急停闩锁不受影响，复位需显式 reset_estop）。"""
        if self._closed:
            raise ArmNotConnectedError("MockArm 已 close，不可复用（请新建实例）")
        self._connected = True
        self._event("connect", {"pos_mm": list(self._pos)})

    def home(self) -> None:
        """回 home 位（按巡航直线移动，速度取硬上限的 60%）。"""
        self._require_ready()
        h = self._bounds.home_mm
        self._move(float(h[0]), float(h[1]), float(h[2]), speed=self._max_speed * 0.6)
        self._event("home", {"pos_mm": list(self._pos)})

    def move_to(self, x_mm: float, y_mm: float, z_mm: float, *, speed: float) -> None:
        """直线移动到桌面坐标 (x, y, z)；越界/超速/急停/未连接一律拒绝且零运动。"""
        self._require_ready()
        x, y, z = float(x_mm), float(y_mm), float(z_mm)
        if not self._bounds.contains(x, y, z):
            raise ArmWorkspaceError(
                f"目标 ({x:.1f}, {y:.1f}, {z:.1f}) mm 超出工作空间 "
                f"x[{self._bounds.x_min_mm}, {self._bounds.x_max_mm}] "
                f"y[{self._bounds.y_min_mm}, {self._bounds.y_max_mm}] "
                f"z[{self._bounds.z_min_mm}, {self._bounds.z_max_mm}]"
            )
        if speed <= 0:
            raise ArmSpeedError(f"speed 必须 > 0，得到 {speed}")
        if float(speed) > self._max_speed:
            raise ArmSpeedError(
                f"speed={speed} mm/s 超过硬上限 {self._max_speed} mm/s"
            )
        self._move(x, y, z, speed=float(speed))

    def gripper(self, open: bool) -> None:  # noqa: A002 — 冻结契约参数名
        """夹爪开合（模拟耗时 gripper_travel_s/time_scale）。"""
        self._require_ready()
        dur = self._gripper_s / self._time_scale
        if dur >= 1e-3:
            self._sleep(dur)
        self._gripper_open = bool(open)
        self._event("gripper_open" if open else "gripper_close", {})

    def estop(self) -> None:
        """软件急停闩锁（永不抛错、幂等；连接与否均可调）。"""
        self._estop_latched = True
        self._event("estop", {"pos_mm": list(self._pos)})

    def close(self) -> None:
        """断开（幂等；close 后实例不可复用）。"""
        self._connected = False
        self._closed = True
        self._event("close", {})

    # ---- Mock 专有扩展（不属于冻结协议，真机实现没有这些） ------------------

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def estop_latched(self) -> bool:
        return self._estop_latched

    @property
    def gripper_is_open(self) -> bool:
        return self._gripper_open

    @property
    def position_mm(self) -> tuple[float, float, float]:
        return self._pos

    @property
    def travel_mm(self) -> float:
        """累计行程（毫米）。"""
        return self._travel_mm

    @property
    def moves(self) -> int:
        return self._moves

    @property
    def bounds(self) -> WorkspaceBounds:
        return self._bounds

    @property
    def trajectory(self) -> list[dict]:
        """位置采样序列（深拷贝语义：返回前逐条浅拷贝 dict）。"""
        return [dict(p) for p in self._trajectory]

    @property
    def events(self) -> list[dict]:
        return [dict(e) for e in self._events]

    def reset_estop(self) -> None:
        """解除急停闩锁（仅 Mock 提供；调用方必须先人工确认现场安全）。"""
        self._estop_latched = False
        self._event("estop_reset", {})

    # ---- 内部 ---------------------------------------------------------------

    def _require_ready(self) -> None:
        if self._estop_latched:
            raise ArmEStopError("急停闩锁中：所有运动指令被拒绝（MockArm.reset_estop 复位）")
        if not self._connected or self._closed:
            raise ArmNotConnectedError("MockArm 未连接（先调用 connect()）")

    def _move(self, x: float, y: float, z: float, *, speed: float) -> None:
        """已过校验的执行段：模拟耗时 → 更新位置 → 记轨迹/事件。"""
        x0, y0, z0 = self._pos
        dist = ((x - x0) ** 2 + (y - y0) ** 2 + (z - z0) ** 2) ** 0.5
        duration_s = dist / speed / self._time_scale
        if duration_s >= 1e-3:
            self._sleep(duration_s)
        self._pos = (x, y, z)
        self._travel_mm += dist
        self._moves += 1
        self._record_point("move")
        self._event("move", {"to_mm": [x, y, z], "speed_mm_s": speed,
                             "dist_mm": round(dist, 3), "duration_s": round(duration_s, 6)})

    def _record_point(self, phase: str) -> None:
        self._trajectory.append(
            {"t_s": round(float(self._now()), 6), "phase": phase,
             "x_mm": self._pos[0], "y_mm": self._pos[1], "z_mm": self._pos[2]}
        )

    def _event(self, kind: str, detail: dict) -> None:
        if kind not in _EVENT_KINDS:  # pragma: no cover — 内部守卫
            raise ArmError(f"未知事件类型 {kind!r}")
        ev = {"t_s": round(float(self._now()), 6), "kind": kind, "detail": detail}
        self._events.append(ev)
        if self._hook is not None:
            self._hook(kind, dict(detail))

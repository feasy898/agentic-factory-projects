"""分拣线 · 机械臂冻结接口（SO-101 线 · 契约 v1）。

坐标系契约（全分拣线统一）：

- **桌面坐标系**：原点 = 臂基座与桌面的交点，x 向前、y 向左，单位毫米；
  z 为相对桌面高度，z=0 即桌面。凡带 ``_mm`` 后缀的分拣坐标一律是本坐标系
  （与质检线的「盘面毫米系」是两个坐标系，由 :mod:`beaneye.sort.frame` 映射）。

冻结接口（``ArmProtocol``，只增不改名不改签名）::

    connect() / home() / move_to(x_mm, y_mm, z_mm, *, speed) /
    gripper(open) / estop() / close()

``beaneye.sort.mock_arm.MockArm``（今晚全逻辑验证）与
``beaneye.sort.so101.SO101Arm``（明日真机）都遵守本接口，可互换注入
:class:`beaneye.sort.session.SortSession`。

异常语义（各实现必须一致）：

- 未 ``connect()`` 就调用运动类方法 → :class:`ArmNotConnectedError`；
- 目标超出工作空间 / 运动学不可达 → :class:`ArmWorkspaceError`；
- 急停闩锁中收到运动指令 → :class:`ArmEStopError`（**不得产生任何运动**）；
- 速度请求超实现上限 → :class:`ArmSpeedError`；
- :meth:`ArmProtocol.estop` 本身**永不抛错**（安全路径必须畅通）；
  幂等，可重复调用。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

__all__ = [
    "ArmError",
    "ArmNotConnectedError",
    "ArmWorkspaceError",
    "ArmEStopError",
    "ArmSpeedError",
    "ArmProtocol",
]


class ArmError(RuntimeError):
    """分拣臂统一异常基类。"""


class ArmNotConnectedError(ArmError):
    """未连接（未调用 connect / 已 close）就下达指令。"""


class ArmWorkspaceError(ArmError):
    """目标点超出工作空间边界或运动学不可达（拒绝时零运动）。"""


class ArmEStopError(ArmError):
    """软件急停闩锁中，运动指令被拒绝（零运动）。"""


class ArmSpeedError(ArmError):
    """速度请求超上限（拒绝时零运动）。"""


@runtime_checkable
class ArmProtocol(Protocol):
    """分拣臂冻结接口（契约 v1；Mock 与 SO101 双实现共同遵守）。"""

    def connect(self) -> None:
        """建立连接（真机：打开串口总线并使能力矩；Mock：置位连接标志）。"""
        ...

    def home(self) -> None:
        """回安全 home 位（工作空间内预置的安全高空点）。"""
        ...

    def move_to(self, x_mm: float, y_mm: float, z_mm: float, *, speed: float) -> None:
        """直线移动末端到桌面坐标 (x_mm, y_mm, z_mm)，速度 speed mm/s。

        阻塞返回即到位。越界 / 不可达 / 急停中 / 未连接 → 对应 ArmError
        子类，且**不得产生任何运动**。
        """
        ...

    def gripper(self, open: bool) -> None:
        """夹爪开合：``open=True`` 张开，``False`` 夹紧。阻塞到位。"""
        ...

    def estop(self) -> None:
        """软件急停：立即停止/冻结并闩锁；此后运动指令一律 ArmEStopError。

        永不抛错、幂等（安全路径必须畅通）。
        """
        ...

    def close(self) -> None:
        """断开连接（先安全下电再关端口）；幂等。"""
        ...

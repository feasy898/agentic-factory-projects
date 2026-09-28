"""机械臂接口抽象（开发指令 §3.2 冻结签名；契约 v1.1：N_ARM_JOINTS=6）。

冻结契约（只增不改签名）::

    class ArmInterface(ABC):
        def read(self) -> ArmState: ...
        def write(self, cmd: ArmCommand) -> None: ...
        def enable(self) -> None
        def disable(self) -> None

纪律（契约 §3.1）：ArmCommand 只能由 SafetyEnvelope 组装并下发到底层；
其他模块不得绕过包络直接触达执行器。

本文件同时定义执行层统一异常与"只增"扩展约定：

- :class:`ArmCommandRejected`：指令被拒绝（未过安全包络 / 关节限位外 /
  不可达 / 速度超硬限 / 未使能 / 急停闩锁中）。拒绝时执行器**不得产生任何
  运动**——这是行为树与真机之间的硬闸语义；
- :meth:`ArmInterface.halt`：立即冻结在当前位形（急停由包络调用；契约外
  只增扩展，各实现必须幂等）；
- :attr:`ArmInterface.heartbeat_ns`：看门狗心跳（最近活动时间戳；None =
  本实现不提供心跳，包络跳过看门狗检查）。
"""

from __future__ import annotations

from abc import ABC, abstractmethod

try:  # 仓库根运行（pytest / 集成）与包根运行（-m cs_arm.*）双形态
    from chengshao.cs_schema import ArmCommand, ArmState
except ImportError:  # pragma: no cover - 包根直跑形态
    from cs_schema import ArmCommand, ArmState  # type: ignore[no-redef]

__all__ = ["ArmInterface", "ArmCommandRejected"]


class ArmCommandRejected(RuntimeError):
    """ArmCommand 被安全层/执行器拒绝。

    ``reason`` 为稳定机器可读字符串（报告/trace 用），``detail`` 携带
    JSON 可序列化的诊断上下文（如包络校验器报告摘要）。
    拒绝语义：底层执行器状态保持不变（零运动）。
    """

    def __init__(self, reason: str, detail: dict | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.detail: dict = dict(detail or {})


class ArmInterface(ABC):
    """机械臂执行器统一接口（冻结签名 §3.2）。"""

    @abstractmethod
    def read(self) -> ArmState:
        """回读全量状态（契约 ArmState，6 关节 = 5 臂关节 + 1 夹爪）。"""

    @abstractmethod
    def write(self, cmd: ArmCommand) -> None:
        """下发运动指令；违规指令必须抛 :class:`ArmCommandRejected` 且不产生运动。"""

    @abstractmethod
    def enable(self) -> None:
        """使能（上力矩）。"""

    @abstractmethod
    def disable(self) -> None:
        """去使能（下力矩；运动立即冻结）。"""

    # ---- 只增扩展（契约允许的追加部分） -----------------------------------

    def halt(self) -> None:
        """立即冻结在当前位形（速度清零）。幂等；急停/去使能由包络调用。"""

    @property
    def heartbeat_ns(self) -> int | None:
        """最近活动时间戳（ns）；None = 不提供（包络跳过看门狗）。"""
        return None

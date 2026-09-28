"""FeetechArm 骨架：真机串口通道（仅接口 + 参数；硬件到货后 T10 实现）。

契约位置：§3.2 ``class FeetechArm(ArmInterface)  # 真机（feetech 通道封装）``。
本文件冻结**类接口与参数结构**并保证"未接硬件即显式失败"（宁可拒绝也不
装作成功）；串口轮询/力矩读写/回读校验等实现随单臂 bring-up（T10）补齐。

传输层选型（T10 实现时二选一，接口不变）：
- A. 上位机机器人框架的 follower 舵机通道适配（pip 包已在本仓 requirements，
  Windows 视频解码回退不影响串口路径）；
- B. 舵机厂商官方 Windows SDK 直连（回退 A 在原生 Windows 实测失败时启用，
  见开发指令 §9 风险表）。

Bring-up 要点（到货后执行，详见开发指令 §5.9 真机 eval 表）：
1. 舵机标定：中位/限位/回读一致（标定入口随 T10 bring-up 提供）；
2. 单臂冒烟：6/6 舵机连通、限位/温度正常、夹爪开合正常；
3. 全部运动仍必须经 :class:`cs_arm.safety.SafetyEnvelope` 下发——本类是
   包络的底层，自身不再重复包络检查（硬闸单点在包络层）；
4. 看门狗心跳由串口轮询活性驱动（``heartbeat_ns``）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

try:  # 仓库根运行（pytest / 集成）与包根运行（-m cs_arm.*）双形态
    from chengshao.cs_schema import N_ARM_JOINTS, ArmCommand, ArmState
except ImportError:  # pragma: no cover - 包根直跑形态
    from cs_schema import N_ARM_JOINTS, ArmCommand, ArmState  # type: ignore[no-redef]

from .interface import ArmInterface

__all__ = ["FeetechArm", "FeetechArmConfig", "HardwareUnavailable"]


class HardwareUnavailable(RuntimeError):
    """真机硬件未接入/未实现（骨架阶段的确定性失败）。"""


@dataclass(frozen=True)
class FeetechArmConfig:
    """真机连接参数（结构与默认值；端口现场配置，不入库密钥）。

    校验规则：``servo_ids`` 必须恰为 N_ARM_JOINTS=6 个、互不相同、正整数，
    与契约 v1.1 的 6 关节（5 臂关节 + 1 夹爪）一一对应（下标 5 = 夹爪）。
    """

    port: str = ""  # 串口号（如 "COM3" / "/dev/ttyUSB0"）；空 = 未配置
    baudrate: int = 1_000_000
    servo_ids: tuple[int, ...] = (1, 2, 3, 4, 5, 6)
    joint_speed_limit_rad_s: float = 1.5  # 与 config/workspace.json 关节限速一致
    return_delay_time_us: int = 250  # 舵机应答延时（厂商寄存器缺省）
    torque_enabled_by_default: bool = False
    extra: dict = field(default_factory=dict)  # 现场标定参数（中位/限位表等）

    def __post_init__(self) -> None:
        ids = tuple(self.servo_ids)
        if len(ids) != N_ARM_JOINTS:
            raise ValueError(
                f"servo_ids must have exactly {N_ARM_JOINTS} entries, got {len(ids)}"
            )
        if len(set(ids)) != N_ARM_JOINTS:
            raise ValueError("servo_ids must be unique")
        if any((not isinstance(v, int)) or v <= 0 for v in ids):
            raise ValueError("servo_ids must be positive integers")
        if self.baudrate <= 0:
            raise ValueError("baudrate must be positive")
        if self.joint_speed_limit_rad_s <= 0.0:
            raise ValueError("joint_speed_limit_rad_s must be positive")


class FeetechArm(ArmInterface):
    """真机执行器骨架：接口 + 参数冻结，实现待硬件到货（T10）。

    所有会触达硬件的操作在未建立串口连接时抛 :class:`HardwareUnavailable`
    （骨架阶段：任何路径都不会静默伪装成功）。
    """

    def __init__(self, config: FeetechArmConfig | None = None) -> None:
        self._config = config if config is not None else FeetechArmConfig()
        self._connected = False

    # ---- 冻结契约接口（骨架阶段全部显式失败） ---------------------------------

    def read(self) -> ArmState:
        raise HardwareUnavailable(
            "真机未接入：FeetechArm 骨架仅冻结接口与参数（T10 bring-up 实现）"
        )

    def write(self, cmd: ArmCommand) -> None:
        raise HardwareUnavailable(
            "真机未接入：FeetechArm 骨架仅冻结接口与参数（T10 bring-up 实现）"
        )

    def enable(self) -> None:
        raise HardwareUnavailable("真机未接入：使能需串口通道（T10 实现）")

    def disable(self) -> None:
        raise HardwareUnavailable("真机未接入：去使能需串口通道（T10 实现）")

    def halt(self) -> None:
        raise HardwareUnavailable("真机未接入：急停冻结需串口通道（T10 实现）")

    # ---- 只增扩展 -------------------------------------------------------------

    @property
    def config(self) -> FeetechArmConfig:
        return self._config

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def heartbeat_ns(self) -> int | None:
        return None  # 串口轮询活性接入后由 T10 提供

    def connect(self) -> None:
        """打开串口并校验 6/6 舵机在线（T10 实现；骨架阶段显式失败）。"""
        raise HardwareUnavailable(
            "真机未接入：connect() 将在 T10 单臂冒烟（6/6 舵机连通）时实现"
        )

    def disconnect(self) -> None:
        self._connected = False

"""执行包：机械臂接口抽象 + Mock 臂（仿真内速度受限积分）+ 真机串口通道 + 安全包络执行器。

安全包络执行器包装任意 ArmInterface：限速 / 禁入区 / 急停锁存 / 看门狗。
一切 ArmCommand 只能经 SafetyEnvelope 下发到底层（契约 §3.1 SafetyState）。

公开 API（契约 v1.1：N_ARM_JOINTS=6 = 5 臂关节 + 1 夹爪）::

    from cs_arm import ArmInterface, MockArm, SafetyEnvelope, FeetechArm

    mock = MockArm()                       # cs_sim 模型 + 包络虚拟执行
    env = SafetyEnvelope(mock)             # 行为树与执行器之间的硬闸
    env.enable()
    env.write(ArmCommand(mode="cartesian", target=[0.25, 0.0, 0.30],
                         max_speed=0.08, timeout_s=30.0))   # 违规 -> ArmCommandRejected
    state = env.read()                     # 契约 ArmState
    env.estop()                            # 软件急停：同步闩锁，返回即生效
    env.reset()                            # 显式复位后恢复

跨包导入约定（与 cs_voice/_compat 一致）：本包子模块用绝对导入
（``from cs_sim import ...`` / ``from cs_schema import ...``），包初始化时
把集成形态（``chengshao.cs_sim``）注册为顶层别名，保证两种运行形态
（cwd=仓库根 ``python -m chengshao.cs_arm.eval_mock``；cwd=包根
``python -m cs_arm.eval_mock``）解析到**同一**模块实例（isinstance 不跨实例）。

验收 eval（§5.2）::

    python -m cs_arm.eval_mock --report reports/arm_mock_eval.json
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

_PKG_ROOT = Path(__file__).resolve().parents[1]  # .../chengshao
_REPO_ROOT = _PKG_ROOT.parent  # 仓库根

for _p in (str(_REPO_ROOT), str(_PKG_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _alias(pkg: str) -> None:
    """把 chengshao.<pkg>（或已存在的 <pkg>）注册为顶层 <pkg> 别名。

    顺序：先试集成形态 chengshao.<pkg>（与 tests/scripts 一致），失败回退
    独立形态 <pkg>；无论哪种，顶层名都指向同一实例（sys.modules 强制别名）。
    """
    if pkg in sys.modules:  # 独立形态已在用：保持
        return
    for modname in (f"chengshao.{pkg}", pkg):
        try:
            sys.modules[pkg] = importlib.import_module(modname)
            return
        except ImportError:
            continue
    raise ImportError(f"cs_arm: cannot import contract/sim package {pkg!r}")


_alias("cs_schema")
_alias("cs_sim")

from .clock import VirtualClock  # noqa: E402
from .feetech import FeetechArm, FeetechArmConfig, HardwareUnavailable  # noqa: E402
from .interface import ArmCommandRejected, ArmInterface  # noqa: E402
from .kinematics import arm_state_from, plan_motion, resolve_target_joints  # noqa: E402
from .mock_arm import MockArm  # noqa: E402
from .safety import SafetyEnvelope  # noqa: E402

__all__ = [
    # 冻结契约（§3.2）
    "ArmInterface",
    "MockArm",
    "SafetyEnvelope",
    "FeetechArm",
    # 异常
    "ArmCommandRejected",
    "HardwareUnavailable",
    # 参数结构
    "FeetechArmConfig",
    # 测试/eval 支撑
    "VirtualClock",
    "arm_state_from",
    "plan_motion",
    "resolve_target_joints",
]

__version__ = "0.1.0"

"""仿真包：机械臂模型加载、FK/IK、可达空间统计与安全包络验证。

回退链：MJCF 模型 → URDF 直接加载 → 自建运动学链（最后手段）。
坐标系约定（冻结）：base 系，X 前向、Y 左、Z 上，单位米/弧度。

公开 API（冻结契约见开发指令 §3.2）::

    from cs_sim import load_arm, ArmModel, EnvelopeValidator

    arm = load_arm()                       # "auto"：回退链自动发现并校验
    pose = arm.fk([0.0] * arm.n_joints)    # [x,y,z, qw,qx,qy,qz]
    q = arm.ik([0.30, 0.0, 0.20], [1.0, 0.0, 0.0, 0.0])   # 无解返回 None
    stat = arm.reachable_map({"x_m": [0, .5], "y_m": [-.4, .4],
                              "z_m": [-.05, .5], "res_m": .03})
    env = EnvelopeValidator()              # 缺省装载 config/workspace.json
    rep = env.check_trajectory(times_s, points_m)          # 违规 -> rejected

验收 eval（§5.1，在包根 chengshao/ 下运行）::

    python -m cs_sim.eval --model auto --report reports/sim_eval.json
"""

from __future__ import annotations

from .arm_model import (
    DEFAULT_GRID,
    EE_POSE_VEC_LEN,
    ArmModel,
    load_arm,
)
from .backends import BUILTIN_CHAIN, URDF_TOOL_ALIGN_QUAT, IkpyChainBackend, MujocoBackend
from .model_source import (
    DEFAULT_MODEL_SOURCE,
    MODEL_TIER_CHAIN_BUILTIN,
    MODEL_TIER_MJCF,
    MODEL_TIER_URDF,
    ModelResolution,
    discover_model_file,
)
from .safety_envelope import (
    DEFAULT_ENVELOPE_CONFIG,
    CAPSULE_TORSO,
    SPHERE_FACE,
    EnvelopeConfig,
    EnvelopeValidator,
)

__all__ = [
    # 冻结契约（§3.2）
    "load_arm",
    "ArmModel",
    # 包络校验器（§5.1）
    "EnvelopeValidator",
    "EnvelopeConfig",
    "DEFAULT_ENVELOPE_CONFIG",
    "SPHERE_FACE",
    "CAPSULE_TORSO",
    # 回退链
    "DEFAULT_MODEL_SOURCE",
    "MODEL_TIER_MJCF",
    "MODEL_TIER_URDF",
    "MODEL_TIER_CHAIN_BUILTIN",
    "ModelResolution",
    "discover_model_file",
    "MujocoBackend",
    "IkpyChainBackend",
    "BUILTIN_CHAIN",
    "URDF_TOOL_ALIGN_QUAT",
    # 常量
    "EE_POSE_VEC_LEN",
    "DEFAULT_GRID",
]

__version__ = "0.1.0"

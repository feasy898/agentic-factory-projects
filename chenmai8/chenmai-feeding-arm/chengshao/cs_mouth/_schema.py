"""schema 双路径导入辅助。

cs_mouth 以包根（chengshao/）为 cwd 经 ``python -m cs_mouth.eval`` 运行时，
cs_schema 是顶层包；以仓库根为 cwd 跑 pytest 时则是 ``chengshao.cs_schema``。
两处路径都支持，包内一律经本模块取用契约对象。
"""

from __future__ import annotations

try:  # 包根 cwd：chengshao/ 在 sys.path
    from cs_schema import (  # type: ignore
        CameraRole,
        FROWN_ASK_THRESHOLD,
        HEAD_YAW_TURN_THRESHOLD_RAD,
        IPD_DEFAULT_M,
        JAW_OPEN_THRESHOLD,
        MOUTH_PRIOR_DEFAULT_M,
        MouthPose,
        MouthSource,
    )
except ImportError:  # 仓库根 cwd：pytest / 从仓库根导入
    from chengshao.cs_schema import (  # type: ignore
        CameraRole,
        FROWN_ASK_THRESHOLD,
        HEAD_YAW_TURN_THRESHOLD_RAD,
        IPD_DEFAULT_M,
        JAW_OPEN_THRESHOLD,
        MOUTH_PRIOR_DEFAULT_M,
        MouthPose,
        MouthSource,
    )

__all__ = [
    "CameraRole",
    "FROWN_ASK_THRESHOLD",
    "HEAD_YAW_TURN_THRESHOLD_RAD",
    "IPD_DEFAULT_M",
    "JAW_OPEN_THRESHOLD",
    "MOUTH_PRIOR_DEFAULT_M",
    "MouthPose",
    "MouthSource",
]

"""BeanEye 分拣线（SO-101）· 检测 → 桌面坐标 → 机械臂抓取 → 分级盒。

模块地图：

- :mod:`beaneye.sort.arm`      冻结接口 ``ArmProtocol``（契约 v1）
- :mod:`beaneye.sort.mock_arm` ``MockArm`` 内存模拟臂（今晚全逻辑验证）
- :mod:`beaneye.sort.so101`    ``SO101Arm`` 真机适配器（lerobot 惰性依赖）
- :mod:`beaneye.sort.frame`    像素 → 桌面毫米映射（ArUco H + 安装外参）
- :mod:`beaneye.sort.planner`  ``SortPlanner`` 严重度降序抓取队列 + 分级盒映射
- :mod:`beaneye.sort.session`  ``SortSession`` 作业状态机（SCAN/PLAN/PICK/急停）
- :mod:`beaneye.sort.render`   计划/轨迹可视化与前后对比图
- :mod:`beaneye.sort.config`   configs/sort.yaml 加载与校验

典型用法（仿真全链）::

    from beaneye.sort import MockArm, SortPlanner, SortSession, SortTarget, load_sort_config

    cfg = load_sort_config()
    arm = MockArm(cfg.workspace, max_speed_mm_s=cfg.speeds.max_mm_s, time_scale=100.0)
    arm.connect(); arm.home()
    session = SortSession(arm, SortPlanner(cfg), config=cfg)
    session.scan(targets)   # 一帧逐粒检测结果（桌面 mm）
    report = session.run()
    session.export_json("out/sort_sim/trajectory.json")
"""

from beaneye.sort.arm import (
    ArmEStopError,
    ArmError,
    ArmNotConnectedError,
    ArmProtocol,
    ArmSpeedError,
    ArmWorkspaceError,
)
from beaneye.sort.config import (
    SortConfig,
    SortConfigError,
    WorkspaceBounds,
    load_sort_config,
)
from beaneye.sort.frame import (
    Affine2D,
    Extrinsic2D,
    FrameMappingError,
    FrameToTable,
    fit_residual,
    frame_to_table_from_calib,
    solve_affine,
)
from beaneye.sort.mock_arm import MockArm
from beaneye.sort.planner import (
    PickStep,
    PlannerError,
    SkippedTarget,
    SortPlan,
    SortPlanner,
    SortTarget,
    targets_from_observations,
)
from beaneye.sort.session import (
    PHASE_DONE,
    PHASE_ERROR,
    PHASE_ESTOPPED,
    PHASE_IDLE,
    PHASE_PICKING,
    PHASE_PLANNED,
    SessionEStopError,
    SessionError,
    SessionReport,
    SortSession,
)
from beaneye.sort.render import (
    DEFECT_COLORS_BGR,
    area_mm_to_r,
    before_after_panel,
    draw_plan,
    draw_trajectory,
    erase_targets,
)
from beaneye.sort.so101 import SO101Arm, solve_ik_3dof

__all__ = [
    # 契约与异常
    "ArmProtocol",
    "ArmError",
    "ArmNotConnectedError",
    "ArmWorkspaceError",
    "ArmEStopError",
    "ArmSpeedError",
    # 配置
    "SortConfig",
    "SortConfigError",
    "WorkspaceBounds",
    "load_sort_config",
    # 映射
    "FrameToTable",
    "FrameMappingError",
    "Extrinsic2D",
    "Affine2D",
    "solve_affine",
    "fit_residual",
    "frame_to_table_from_calib",
    # 规划
    "SortPlanner",
    "PlannerError",
    "SortTarget",
    "SkippedTarget",
    "PickStep",
    "SortPlan",
    "targets_from_observations",
    # 执行
    "SortSession",
    "SessionError",
    "SessionEStopError",
    "SessionReport",
    "PHASE_IDLE",
    "PHASE_PLANNED",
    "PHASE_PICKING",
    "PHASE_DONE",
    "PHASE_ESTOPPED",
    "PHASE_ERROR",
    # 臂实现
    "MockArm",
    "SO101Arm",
    "solve_ik_3dof",
    # 可视化
    "DEFECT_COLORS_BGR",
    "area_mm_to_r",
    "draw_plan",
    "draw_trajectory",
    "erase_targets",
    "before_after_panel",
]

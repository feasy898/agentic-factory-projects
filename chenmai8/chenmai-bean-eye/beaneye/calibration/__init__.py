"""BeanEye · M3 标定与坐标变换（beaneye.calibration）。

ArUco 四角码检测 → 托盘平面单应（原图 px → 盘面 mm）→ 像素-毫米换算与正射网格。
配置：configs/tray.yaml（托盘几何与 ArUco 布局，规划默认值 300mm/60mm/2048²）。

快速上手::

    from beaneye.calibration import calibrate, calibrate_pair, warp_to_tray, px_to_mm

    cal = calibrate(img_bgr)               # 单面 → SingleCalib（.H / .px_per_mm）
    res = calibrate_pair(top, bottom)      # 双面 → 契约 CalibResult（入 TrayScan）
    grid = warp_to_tray(img_bgr, cal.H)    # 2048² 正射盘面图
    mm = px_to_mm([(1200.0, 800.0)], cal.H)

详细说明见 core.py 模块 docstring（求解策略/失败语义/px_per_mm 语义）。
"""

from beaneye.calibration.config import (
    DEFAULT_CONFIG_PATH,
    TrayConfig,
    TrayConfigError,
    load_tray_config,
)
from beaneye.calibration.core import (
    CalibrationError,
    SingleCalib,
    calibrate,
    calibrate_pair,
    corners_px_of,
    mm_to_px,
    px_to_mm,
    warp_to_tray,
)

__all__ = [
    "DEFAULT_CONFIG_PATH",
    "TrayConfig",
    "TrayConfigError",
    "load_tray_config",
    "CalibrationError",
    "SingleCalib",
    "calibrate",
    "calibrate_pair",
    "warp_to_tray",
    "px_to_mm",
    "mm_to_px",
    "corners_px_of",
]

"""BeanEye · M8 计量（beaneye.metrology）。

目数分布（1/64 英寸筛孔对照）、色差 ΔE（CIE76，对标准参考色）、估重
（面积×面密度回归系数 / 面积×厚度先验×体积系数，均可配）。
输入是 M6 配对后的 ``PairedBean`` 记录（几何/颜色由 M3–M5 从整盘图提前
提取），输出契约 ``Measurements``。

快速上手::

    from beaneye.metrology import measure

    m = measure(beans, calib, std_yaml)      # std_yaml=None 走契约模板默认
    m.sieve_hist        # {"13": 320, "14": 80, ...}
    m.delta_e_mean      # CIE76，对 metrology.reference_lab
    m.est_weight_g      # weight_model 决定的估重

配置口径见 config.py 模块 docstring；统计口径见 core.py 模块 docstring。
"""

from beaneye.metrology.config import (
    DEFAULT_G_PER_MM2,
    DEFAULT_G_PER_MM3,
    DEFAULT_MAX_BELOW_FRAC,
    DEFAULT_MIN_SCREEN,
    DEFAULT_REFERENCE_LAB,
    DEFAULT_THICKNESS_MM,
    WEIGHT_MODELS,
    MetrologyConfig,
    MetrologyError,
    load_metrology_config,
)
from beaneye.metrology.core import (
    DELTA_E_BUCKET_OPEN,
    DELTA_E_BUCKET_WIDTH,
    MM_PER_INCH,
    SCREENS_PER_INCH,
    SEVERE_SIDE_WEIGHT,
    cie_to_lab8,
    delta_e_cie76,
    lab8_to_cie,
    measure,
    merge_sides_lab,
    screen_mm,
    screen_of,
    screen_of_ratio,
)

__all__ = [
    # 配置
    "MetrologyConfig",
    "MetrologyError",
    "load_metrology_config",
    "WEIGHT_MODELS",
    "DEFAULT_REFERENCE_LAB",
    "DEFAULT_MIN_SCREEN",
    "DEFAULT_MAX_BELOW_FRAC",
    "DEFAULT_G_PER_MM2",
    "DEFAULT_THICKNESS_MM",
    "DEFAULT_G_PER_MM3",
    # 计量
    "measure",
    "screen_of",
    "screen_of_ratio",
    "screen_mm",
    "MM_PER_INCH",
    "SCREENS_PER_INCH",
    "SEVERE_SIDE_WEIGHT",
    "lab8_to_cie",
    "cie_to_lab8",
    "delta_e_cie76",
    "merge_sides_lab",
    "DELTA_E_BUCKET_WIDTH",
    "DELTA_E_BUCKET_OPEN",
]

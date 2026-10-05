"""M8 计量：目数分布 / 色差 ΔE / 估重（spec：plan/开发指令.md §4 M8）。

规范入口 :func:`measure`::

    measure(beans, calib, std_yaml) -> Measurements   # 契约签名

- ``beans``：M6 配对后的 ``PairedBean`` 列表（每粒已带两面
  ``BeanObservation``：mm 几何 + LAB 颜色，均来自整盘图经 M3 变换 / M4
  分割 / M5 分类的产物，因此本模块不再接整盘图）；
- ``calib``：契约 ``CalibResult | None``。v0 计量全部消费已变换到盘面 mm
  的几何，无需再做像素换算，标定对象仅做类型校验（供 M14 透传、未来
  px 空间复核留位）；
- ``std_yaml``：标准 YAML（dict / 路径 / None=模板默认），读
  ``metrology``/``weight`` 两节（见 config.py）。

口径（v0，写死在此便于验收复核）
--------------------------------
1. **粒径**：每粒取两面 ``eq_diameter_mm`` 的算术均值（单面取该面）；
   目数 ``screen = round_half_up(d_mm / 25.4 * 64)``（1/64 英寸筛，.5 进位；
   非 Python 内建 round 的银行家舍入，仅恰在 .5 时有差）。
2. **色差**：每粒先把两面 LAB 合并——severity_rank 高的一面权重 0.7
   （平级 0.5/0.5，单面全占）；合并与聚合都在与逐粒一致的 lab8 标度上做
   （lab8→CIE 是逐通道仿射，加权平均两标度可交换）；ΔE 用 **CIE76**
   （‖Lab−Lab_ref‖₂，v0 明确不宣称色差一致性更优的 ΔE2000，留升级位），
   在 CIE 标度上对 ``metrology.reference_lab`` 计算；
   ``color_lab_mean`` 输出 lab8 标度（与逐粒 ``color_lab`` 同标度可对照），
   ``delta_e_mean``/``delta_e_hist`` 为 CIE 单位。
3. **估重**：每粒面积取两面 ``area_mm2`` 均值（单面取该面），Σ×系数：
   - ``area_linear``：``Σ area × g_per_mm2``（线性回归系数，标准 YAML
     ``weight.g_per_mm2``，到货蓝牙秤标定回填）；
   - ``area_thickness``：``Σ area × thickness_mm × g_per_mm3``（面积×厚度
     先验×体积回归系数，均可配）；
   ``weight_model`` 记 ``"<model>:v1"``。
4. **sieve_pass**：对照 ``metrology.sieve_targets``——低于 ``min_screen``
   的粒占比 ≤ ``max_below_frac``（默认 0 = 全部达标）为过；无筛目目标或
   空盘 → ``None``（不判定）。色差布尔（``delta_e_max`` 对照）归 M9 定级
   消费，M8 只产出 ``delta_e_mean``/``delta_e_hist``。
5. **大中小筛段（轨2，v1.2 增补）**：``size_band_hist``/``size_band_frac``
   由 ``sieve_hist`` 按整目数聚合（大 ≥17 / 中 15-16 / 小 ≤14，口径与来源
   见 ``configs/size_bands.yaml``；``size_bands.aggregate_sieve_hist`` 与逐粒
   ``size_band_histogram`` 恒一致）；筛段配置缺失/非法时两字段为空映射
   （契约兼容：老字段语义不变）。

两面皆 ``None`` 的占位 ``PairedBean``（契约允许、正常配对不会产出）不进
任何统计，``bean_count`` 也不计。
"""

from __future__ import annotations

import math
import statistics
from collections import Counter

from beaneye.metrology.config import MetrologyConfig, MetrologyError, load_metrology_config
from beaneye.schemas import (
    BeanObservation,
    CalibResult,
    Measurements,
    PairedBean,
    StatsSummary,
)

__all__ = [
    "DELTA_E_BUCKET_OPEN",
    "DELTA_E_BUCKET_WIDTH",
    "MM_PER_INCH",
    "SCREENS_PER_INCH",
    "SEVERE_SIDE_WEIGHT",
    "MetrologyError",
    "cie_to_lab8",
    "delta_e_cie76",
    "lab8_to_cie",
    "measure",
    "merge_sides_lab",
    "screen_mm",
    "screen_of",
    "screen_of_ratio",
]

# 目（screen）= 1/64 英寸筛孔对照
MM_PER_INCH = 25.4
SCREENS_PER_INCH = 64
# 色差合并：severity 高侧权重（契约 §4 M8）
SEVERE_SIDE_WEIGHT = 0.7
# ΔE 直方分桶：2 ΔE 一桶，最后为开口桶
DELTA_E_BUCKET_WIDTH = 2.0
DELTA_E_BUCKET_OPEN = "20+"

_LAB8_L_SCALE = 255.0 / 100.0  # CIE → lab8（OpenCV 8-bit LAB）


# ---------------------------------------------------------------------------
# 筛目换算
# ---------------------------------------------------------------------------


def screen_of_ratio(ratio: float) -> int:
    """筛目数 = 四舍五入（.5 进位）到最近的 1/64 英寸整数筛号。"""
    if not math.isfinite(ratio) or ratio < 0:
        raise MetrologyError(f"筛目换算入参必须是非负有限数，得到 {ratio!r}")
    return int(math.floor(ratio + 0.5))


def screen_of(d_mm: float) -> int:
    """等效直径 mm → 目数：``round(d_mm/25.4*64)``（.5 进位）。"""
    if not math.isfinite(d_mm) or d_mm <= 0:
        raise MetrologyError(f"等效直径必须为正有限数，得到 {d_mm!r}")
    return screen_of_ratio(d_mm / MM_PER_INCH * SCREENS_PER_INCH)


def screen_mm(screen: int) -> float:
    """筛号 → 对应孔径 mm（``screen/64`` 英寸），供筛孔对照表使用。"""
    return screen * MM_PER_INCH / SCREENS_PER_INCH


# ---------------------------------------------------------------------------
# LAB 标度换算与色差
# ---------------------------------------------------------------------------


def lab8_to_cie(lab: tuple[float, float, float]) -> tuple[float, float, float]:
    """OpenCV 8-bit LAB（0-255）→ CIELAB（L 0-100，a/b ±128）。"""
    return (lab[0] * 100.0 / 255.0, lab[1] - 128.0, lab[2] - 128.0)


def cie_to_lab8(lab: tuple[float, float, float]) -> tuple[float, float, float]:
    """CIELAB → OpenCV 8-bit LAB（:func:`lab8_to_cie` 的逆）。"""
    return (lab[0] * _LAB8_L_SCALE, lab[1] + 128.0, lab[2] + 128.0)


def delta_e_cie76(
    lab1: tuple[float, float, float], lab2: tuple[float, float, float]
) -> float:
    """CIE76 色差：``‖Lab1 − Lab2‖₂``（入参同标度即可，输出同标度单位）。"""
    return math.sqrt(
        (lab1[0] - lab2[0]) ** 2 + (lab1[1] - lab2[1]) ** 2 + (lab1[2] - lab2[2]) ** 2
    )


def merge_sides_lab(
    top: BeanObservation | None, bottom: BeanObservation | None
) -> tuple[float, float, float]:
    """把一粒豆两面的 LAB（lab8 标度）按严重度加权合并。

    severity_rank 高的一面权重 0.7；平级 0.5/0.5；单面取该面。
    lab8→CIE 为逐通道仿射，故 lab8 上加权与 CIE 上加权一致。
    """
    if top is None and bottom is None:
        raise MetrologyError("merge_sides_lab 需要至少一面观测")
    if bottom is None:
        return tuple(top.color_lab)  # type: ignore[return-value]
    if top is None:
        return tuple(bottom.color_lab)  # type: ignore[return-value]
    if top.severity_rank > bottom.severity_rank:
        w = SEVERE_SIDE_WEIGHT
    elif bottom.severity_rank > top.severity_rank:
        w = 1.0 - SEVERE_SIDE_WEIGHT
    else:
        w = 0.5
    return tuple(  # type: ignore[return-value]
        w * t + (1.0 - w) * b for t, b in zip(top.color_lab, bottom.color_lab)
    )


def _delta_e_bucket(de: float) -> str:
    """ΔE → 直方桶键：2 一桶（"0-2","2-4",…），≥20 进开口桶 "20+"。"""
    if de >= 20.0:
        return DELTA_E_BUCKET_OPEN
    lo = int(de // DELTA_E_BUCKET_WIDTH) * int(DELTA_E_BUCKET_WIDTH)
    return f"{lo}-{lo + int(DELTA_E_BUCKET_WIDTH)}"


# ---------------------------------------------------------------------------
# 逐粒几何
# ---------------------------------------------------------------------------


def _sides(bean: PairedBean) -> list[BeanObservation]:
    return [o for o in (bean.top, bean.bottom) if o is not None]


def _bean_diameter(bean: PairedBean) -> float:
    """每粒等效直径：两面均值（单面取该面）。"""
    sides = _sides(bean)
    return sum(o.eq_diameter_mm for o in sides) / len(sides)


def _bean_area(bean: PairedBean) -> float:
    """每粒面积：两面均值（单面取该面），估重口径。"""
    sides = _sides(bean)
    return sum(o.mask.area_mm2 for o in sides) / len(sides)


# ---------------------------------------------------------------------------
# 规范入口
# ---------------------------------------------------------------------------


def measure(
    beans,
    calib: CalibResult | None = None,
    std_yaml=None,
    config: MetrologyConfig | None = None,
) -> Measurements:
    """整盘计量（契约签名 ``measure(beans, calib, std_yaml) -> Measurements``）。

    ``config`` 为可选直注入口（优先于 ``std_yaml``），供调用方复用已加载
    配置；两者都缺省时用契约模板默认值。
    """
    if config is not None and not isinstance(config, MetrologyConfig):
        raise MetrologyError(f"config 必须是 MetrologyConfig，得到 {type(config).__name__}")
    if calib is not None and not isinstance(calib, CalibResult):
        raise MetrologyError(f"calib 必须是 CalibResult | None，得到 {type(calib).__name__}")
    if config is None:
        config = load_metrology_config(std_yaml)

    beans = list(beans)
    for i, b in enumerate(beans):
        if not isinstance(b, PairedBean):
            raise MetrologyError(f"beans[{i}] 必须是 PairedBean，得到 {type(b).__name__}")

    real = [b for b in beans if b.top is not None or b.bottom is not None]
    n = len(real)
    diameters = [_bean_diameter(b) for b in real]
    merged8 = [merge_sides_lab(b.top, b.bottom) for b in real]

    # ---- 目数分布 --------------------------------------------------------
    sieve_hist: dict[str, int] = dict(
        sorted(
            Counter(str(screen_of(d)) for d in diameters).items(),
            key=lambda kv: int(kv[0]),
        )
    )
    # ---- 大中小筛段（轨2）：与 sieve_hist 同源聚合；筛段配置不可用时置空 ----
    # 函数内导入（size_bands 顶层反向依赖 core.screen_of，避免循环导入）
    from beaneye.metrology.size_bands import SizeBandError, aggregate_sieve_hist

    try:
        size_band_hist: dict[str, int] = aggregate_sieve_hist(sieve_hist)
    except SizeBandError:
        size_band_hist = {}  # configs/size_bands.yaml 缺失/非法 → 功能关闭（契约兼容）
    size_band_frac: dict[str, float] = {
        k: (v / n if n else 0.0) for k, v in size_band_hist.items()
    }
    if n == 0 or config.min_screen is None:
        sieve_pass: bool | None = None
    else:
        below = sum(1 for d in diameters if screen_of(d) < config.min_screen)
        sieve_pass = (below / n) <= config.max_below_frac

    # ---- 粒径统计 --------------------------------------------------------
    if n:
        stats = StatsSummary(
            min=min(diameters),
            max=max(diameters),
            mean=sum(diameters) / n,
            median=statistics.median(diameters),
        )
    else:
        stats = StatsSummary(min=0.0, max=0.0, mean=0.0, median=0.0)

    # ---- 色差 ------------------------------------------------------------
    delta_es = [delta_e_cie76(lab8_to_cie(m), config.reference_lab) for m in merged8]
    delta_e_hist: dict[str, int] = dict(
        sorted(
            Counter(_delta_e_bucket(de) for de in delta_es).items(),
            key=lambda kv: float(kv[0].split("-")[0].rstrip("+")),
        )
    )
    if n:
        color_lab_mean = tuple(
            sum(m[c] for m in merged8) / n for c in range(3)
        )
        delta_e_mean = sum(delta_es) / n
    else:
        color_lab_mean = (0.0, 0.0, 0.0)
        delta_e_mean = 0.0

    # ---- 估重 ------------------------------------------------------------
    if config.weight_model == "area_linear":
        coef_per_mm2 = config.g_per_mm2
    elif config.weight_model == "area_thickness":
        coef_per_mm2 = config.thickness_mm * config.g_per_mm3
    else:  # load_metrology_config 已把关；防御保留
        raise MetrologyError(f"未知估重模型: {config.weight_model!r}")
    est_weight_g = sum(_bean_area(b) for b in real) * coef_per_mm2

    return Measurements(
        bean_count=n,
        sieve_hist=sieve_hist,
        sieve_pass=sieve_pass,
        eq_diameter_mm_stats=stats,
        color_lab_mean=color_lab_mean,  # type: ignore[arg-type]
        delta_e_mean=delta_e_mean,
        delta_e_hist=delta_e_hist,
        est_weight_g=est_weight_g,
        weight_model=config.weight_model_tag,
        size_band_hist=size_band_hist,
        size_band_frac=size_band_frac,
    )

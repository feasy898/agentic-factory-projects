"""M8 计量配置：标准 YAML 的 ``metrology``/``weight`` 节加载与校验。

数据源是 §3.3 标准 YAML（三套：cqi_fine_robusta / nyt_604 / db46_t642）里的
两节（M9 落地前 ``std_yaml=None`` 走契约模板默认值）::

    metrology:
      sieve_targets: {min_screen: 13}     # 目=1/64 英寸
      reference_lab: [55, -12, 22]        # 参考色，CIE 标度（L 0-100, a/b ±128）
      delta_e_max: null                   # M9 定级用，M8 不消费
    weight:
      model: area_linear                  # area_linear | area_thickness
      g_per_mm2: 0.00042                  # 到货后蓝牙秤标定回填

**LAB 标度约定（重要）**：契约里逐粒 ``BeanObservation.color_lab`` 统一是
OpenCV 8-bit LAB 标度（L∈[0,255]，a/b 整体 +128，下称 *lab8*）；而标准 YAML
的 ``reference_lab`` 是常规 CIELAB 标度（L∈[0,100]，a/b∈[-128,127]，§3.3 模板
的 ``[55,-12,22]`` 即此标度）。两套标度混用是计量环节最容易踩的坑，本模块：

- 配置面显式带 ``reference_lab_scale``（默认 ``cie``；可写 ``lab8`` 声明
  配置值本身就是 lab8 标度），加载时统一归一到 CIE 标度并做量程校验；
- 计算面（core.py）在 CIE 标度上算 ΔE，聚合字段
  ``Measurements.color_lab_mean`` 保持与逐粒一致的 lab8 标度。

只依赖 PyYAML 与标准库（不 import numpy/cv2），与 ``beaneye.calibration.config``
同风格；全部失败抛 :class:`MetrologyError`，错误信息带来源与字段名。
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import yaml

__all__ = [
    "DEFAULT_G_PER_MM2",
    "DEFAULT_G_PER_MM3",
    "DEFAULT_MIN_SCREEN",
    "DEFAULT_MAX_BELOW_FRAC",
    "DEFAULT_REFERENCE_LAB",
    "DEFAULT_THICKNESS_MM",
    "WEIGHT_MODELS",
    "MetrologyConfig",
    "MetrologyError",
    "load_metrology_config",
]

# 契约模板默认值（plan/开发指令.md §3.3；到货标定后由标准 YAML 回填覆盖）
DEFAULT_REFERENCE_LAB = (55.0, -12.0, 22.0)  # CIE 标度，精品罗豆参考色（verified:false）
DEFAULT_MIN_SCREEN = 13
DEFAULT_MAX_BELOW_FRAC = 0.0  # 全部豆 ≥ min_screen 才算过（可按标准加宽）
DEFAULT_G_PER_MM2 = 0.00042
DEFAULT_THICKNESS_MM = 3.5  # area_thickness 模型的厚度先验（mm）
DEFAULT_G_PER_MM3 = 0.0011  # area_thickness 模型的体积→克回归系数

WEIGHT_MODELS = ("area_linear", "area_thickness")
REFERENCE_LAB_SCALES = ("cie", "lab8")

# lab8 → CIE 的仿射系数（OpenCV 8-bit LAB: L8 = L*255/100, a8 = a+128）
_LAB8_L_SCALE = 100.0 / 255.0


class MetrologyError(ValueError):
    """std_yaml 缺失 / 非法 / 计量参数越界时抛出。"""


def _finite(v: object, where: str) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise MetrologyError(f"{where} 必须是数值，得到 {v!r}")
    f = float(v)
    if not math.isfinite(f):
        raise MetrologyError(f"{where} 必须是有限数值，得到 {v!r}")
    return f


@dataclass(frozen=True)
class MetrologyConfig:
    """一份已校验的计量配置（_immutable_，测量全程只读）。

    ``reference_lab`` 恒为 CIE 标度（加载期归一）；``weight_model`` 是
    ``area_linear``（Σ面积×面密度系数）或 ``area_thickness``
    （Σ面积×厚度先验×体积系数），两种系数都可在标准 YAML 配置。
    """

    reference_lab: tuple[float, float, float] = DEFAULT_REFERENCE_LAB
    min_screen: int | None = DEFAULT_MIN_SCREEN
    max_below_frac: float = DEFAULT_MAX_BELOW_FRAC
    weight_model: str = "area_linear"
    g_per_mm2: float = DEFAULT_G_PER_MM2
    thickness_mm: float = DEFAULT_THICKNESS_MM
    g_per_mm3: float = DEFAULT_G_PER_MM3
    source: str = "defaults"  # defaults | <yaml 路径> | dict

    @property
    def weight_model_tag(self) -> str:
        """契约 ``Measurements.weight_model`` 的取值，如 ``area_linear:v1``。"""
        return f"{self.weight_model}:v1"


def _lab_to_cie(lab: tuple[float, float, float], scale: str, where: str) -> tuple[float, float, float]:
    l8 = lab if scale == "lab8" else None
    if l8 is not None:
        return (l8[0] * _LAB8_L_SCALE, l8[1] - 128.0, l8[2] - 128.0)
    return lab


def load_metrology_config(
    std_yaml: Mapping | str | Path | None = None,
) -> MetrologyConfig:
    """从标准 YAML（dict / 文件路径）/ None 构造计量配置。

    - ``None``：契约模板默认值（§3.3；M9 标准 YAML 落地前的兜底）；
    - ``Mapping``：直接读 ``metrology``/``weight`` 两节，其余节忽略（归 M9）；
    - ``str | Path``：按 UTF-8 YAML 文件加载。

    未知/缺失字段取默认值；类型或量程非法抛 :class:`MetrologyError`。
    """
    if std_yaml is None:
        return MetrologyConfig()

    if isinstance(std_yaml, (str, Path)):
        p = Path(std_yaml)
        if not p.is_file():
            raise MetrologyError(f"标准 YAML 文件不存在: {p}")
        try:
            raw = yaml.safe_load(p.read_text(encoding="utf-8"))
        except yaml.YAMLError as e:
            raise MetrologyError(f"标准 YAML 解析失败: {p}\n{e}") from e
        source = str(p)
    elif isinstance(std_yaml, Mapping):
        raw = dict(std_yaml)
        source = "dict"
    else:
        raise MetrologyError(
            f"std_yaml 必须是 dict / YAML 路径 / None，得到 {type(std_yaml).__name__}"
        )

    if not isinstance(raw, Mapping):
        raise MetrologyError(f"标准 YAML 顶层必须是映射（source={source}）")

    # ---- metrology 节 -----------------------------------------------------
    met = raw.get("metrology")
    if met is None:
        met = {}
    if not isinstance(met, Mapping):
        raise MetrologyError(f"`metrology` 节必须是映射（source={source}），得到 {type(met).__name__}")

    ref_raw = met.get("reference_lab", list(DEFAULT_REFERENCE_LAB))
    if not isinstance(ref_raw, (list, tuple)) or len(ref_raw) != 3:
        raise MetrologyError(
            f"`metrology.reference_lab` 必须是 [L, a, b] 三个数值（source={source}），得到 {ref_raw!r}"
        )
    ref_vals = tuple(_finite(v, f"`metrology.reference_lab[{i}]` (source={source})") for i, v in enumerate(ref_raw))
    scale = met.get("reference_lab_scale", "cie")
    if scale not in REFERENCE_LAB_SCALES:
        raise MetrologyError(
            f"`metrology.reference_lab_scale` 只能是 {'/'.join(REFERENCE_LAB_SCALES)}"
            f"（source={source}），得到 {scale!r}"
        )
    ref = _lab_to_cie(ref_vals, scale, source)  # type: ignore[arg-type]
    if not (0.0 - 1e-6 <= ref[0] <= 100.0 + 1e-6):
        raise MetrologyError(f"归一后参考色 L* 超出 [0,100]（source={source}）：{ref}")
    for i in (1, 2):
        if not (-128.0 - 1e-6 <= ref[i] <= 127.0 + 1e-6):
            raise MetrologyError(f"归一后参考色 a*/b* 超出 [-128,127]（source={source}）：{ref}")

    targets = met.get("sieve_targets")
    if targets is None:
        targets = {}
    if not isinstance(targets, Mapping):
        raise MetrologyError(
            f"`metrology.sieve_targets` 节必须是映射（source={source}），得到 {type(targets).__name__}"
        )
    min_screen_raw = targets.get("min_screen", DEFAULT_MIN_SCREEN)
    if min_screen_raw is None:
        min_screen: int | None = None  # 显式 null = 不做筛目判定
    else:
        min_screen_int = _finite(min_screen_raw, f"`metrology.sieve_targets.min_screen` (source={source})")
        if min_screen_int != int(min_screen_int) or int(min_screen_int) < 1:
            raise MetrologyError(
                f"`metrology.sieve_targets.min_screen` 必须是 >=1 的整数或 null（source={source}），"
                f"得到 {min_screen_raw!r}"
            )
        min_screen = int(min_screen_int)
    max_below_frac = _finite(
        targets.get("max_below_frac", DEFAULT_MAX_BELOW_FRAC),
        f"`metrology.sieve_targets.max_below_frac` (source={source})",
    )
    if not 0.0 <= max_below_frac <= 1.0:
        raise MetrologyError(
            f"`metrology.sieve_targets.max_below_frac` 必须在 [0,1]（source={source}），得到 {max_below_frac}"
        )

    # ---- weight 节 --------------------------------------------------------
    weight = raw.get("weight")
    if weight is None:
        weight = {}
    if not isinstance(weight, Mapping):
        raise MetrologyError(f"`weight` 节必须是映射（source={source}），得到 {type(weight).__name__}")

    model = weight.get("model", "area_linear")
    if model not in WEIGHT_MODELS:
        raise MetrologyError(
            f"`weight.model` 只能是 {'/'.join(WEIGHT_MODELS)}（source={source}），得到 {model!r}"
        )
    g_per_mm2 = _finite(
        weight.get("g_per_mm2", DEFAULT_G_PER_MM2), f"`weight.g_per_mm2` (source={source})"
    )
    if g_per_mm2 <= 0:
        raise MetrologyError(f"`weight.g_per_mm2` 必须 > 0（source={source}），得到 {g_per_mm2}")
    thickness_mm = _finite(
        weight.get("thickness_mm", DEFAULT_THICKNESS_MM), f"`weight.thickness_mm` (source={source})"
    )
    if thickness_mm <= 0:
        raise MetrologyError(f"`weight.thickness_mm` 必须 > 0（source={source}），得到 {thickness_mm}")
    g_per_mm3 = _finite(
        weight.get("g_per_mm3", DEFAULT_G_PER_MM3), f"`weight.g_per_mm3` (source={source})"
    )
    if g_per_mm3 <= 0:
        raise MetrologyError(f"`weight.g_per_mm3` 必须 > 0（source={source}），得到 {g_per_mm3}")

    return MetrologyConfig(
        reference_lab=ref,
        min_screen=min_screen,
        max_below_frac=max_below_frac,
        weight_model=model,  # type: ignore[arg-type]
        g_per_mm2=g_per_mm2,
        thickness_mm=thickness_mm,
        g_per_mm3=g_per_mm3,
        source=source,
    )

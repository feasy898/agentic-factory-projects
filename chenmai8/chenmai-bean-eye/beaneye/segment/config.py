"""M4 经典分割配置（configs/segment.yaml）的加载与校验。

只依赖 PyYAML 与标准库（不 import numpy/cv2/scipy），与
``beaneye.calibration.config`` / ``beaneye.metrology.config`` 同风格；
全部失败抛 :class:`SegmentConfigError`，错误信息带文件路径与字段名。

几何量纲约定：形态学核以**像素**为单位（作用于阈值后的掩码），
其余几何参数以 **mm** 为单位（运行期按托盘配置换算 mm/px），
见 ``configs/segment.yaml`` 头注。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = REPO_ROOT / "configs" / "segment.yaml"

CHANNELS = ("gray", "lab_b")
SIDES = ("top", "bottom")


class SegmentConfigError(ValueError):
    """分割配置缺失 / YAML 非法 / 字段越界。"""


def _num(raw: dict, key: str, where: str) -> float:
    v = raw.get(key, None)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise SegmentConfigError(f"{where}: `{key}` 必须是数值，得到 {v!r}")
    f = float(v)
    if not math.isfinite(f):
        raise SegmentConfigError(f"{where}: `{key}` 必须是有限数，得到 {v}")
    return f


def _ksize(raw: dict, key: str, where: str) -> int:
    v = raw.get(key, None)
    if isinstance(v, bool) or not isinstance(v, int):
        raise SegmentConfigError(f"{where}: `{key}` 必须是整数，得到 {v!r}")
    if v < 1 or v % 2 == 0:
        raise SegmentConfigError(f"{where}: `{key}` 必须是奇数且 >=1，得到 {v}")
    return int(v)


@dataclass(frozen=True)
class SegmentConfig:
    """一份已校验的分割配置（_immutable_，分割全程只读）。"""

    channel: str = "gray"
    blur_sigma_px: float = 1.0
    open_ksize: int = 3
    close_ksize: int = 5
    bg_delta_gray: float = 25.0
    max_component_frac: float = 0.5
    min_area_mm2: float = 6.0
    peak_min_mm: float = 1.0
    peak_min_dist_mm: float = 1.8
    seed_dominance: float = 0.7
    seed_dominance_radius_mm: float = 5.0
    mask_markers: bool = True
    marker_margin_mm: float = 2.0
    conf_single: float = 0.9
    conf_split: float = 0.72
    side: str = "top"
    source: str = "defaults"  # defaults | <yaml 路径>


def load_segment_config(path: str | Path | None = None) -> SegmentConfig:
    """加载并校验分割配置；``path=None`` 用仓库默认 ``configs/segment.yaml``。"""
    if path is None:
        return SegmentConfig()
    p = Path(path)
    if not p.is_file():
        raise SegmentConfigError(f"分割配置文件不存在: {p}")
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise SegmentConfigError(f"分割配置 YAML 解析失败 {p}: {exc}") from exc
    if not isinstance(raw, dict):
        raise SegmentConfigError(f"{p}: 顶层必须是映射，得到 {type(raw).__name__}")
    where = f"{p}"

    channel = raw.get("channel", "gray")
    if channel not in CHANNELS:
        raise SegmentConfigError(
            f"{where}: `channel` 只能是 {'/'.join(CHANNELS)}，得到 {channel!r}"
        )
    blur = _num(raw, "blur_sigma_px", where)
    if not 0.0 <= blur <= 10.0:
        raise SegmentConfigError(f"{where}: `blur_sigma_px` 必须在 [0,10]，得到 {blur}")
    open_k = _ksize(raw, "open_ksize", where)
    close_k = _ksize(raw, "close_ksize", where)
    bg_delta = _num(raw, "bg_delta_gray", where)
    if not 1.0 <= bg_delta <= 100.0:
        raise SegmentConfigError(f"{where}: `bg_delta_gray` 必须在 [1,100]，得到 {bg_delta}")
    max_frac = _num(raw, "max_component_frac", where)
    if not 0.0 < max_frac <= 1.0:
        raise SegmentConfigError(f"{where}: `max_component_frac` 必须在 (0,1]，得到 {max_frac}")
    min_area = _num(raw, "min_area_mm2", where)
    if not 0.0 < min_area <= 1000.0:
        raise SegmentConfigError(f"{where}: `min_area_mm2` 必须在 (0,1000]，得到 {min_area}")
    peak_min = _num(raw, "peak_min_mm", where)
    if not 0.0 < peak_min <= 20.0:
        raise SegmentConfigError(f"{where}: `peak_min_mm` 必须在 (0,20]，得到 {peak_min}")
    peak_dist = _num(raw, "peak_min_dist_mm", where)
    if not 0.0 < peak_dist <= 50.0:
        raise SegmentConfigError(f"{where}: `peak_min_dist_mm` 必须在 (0,50]，得到 {peak_dist}")
    if peak_dist <= peak_min:
        raise SegmentConfigError(
            f"{where}: `peak_min_dist_mm`({peak_dist}) 必须 > `peak_min_mm`({peak_min})"
        )
    dominance = _num(raw, "seed_dominance", where)
    if not 0.0 < dominance <= 1.0:
        raise SegmentConfigError(f"{where}: `seed_dominance` 必须在 (0,1]，得到 {dominance}")
    dom_radius = _num(raw, "seed_dominance_radius_mm", where)
    if not peak_dist < dom_radius <= 30.0:
        raise SegmentConfigError(
            f"{where}: `seed_dominance_radius_mm` 必须在 ({peak_dist},30]，得到 {dom_radius}"
        )
    mask_markers = raw.get("mask_markers", True)
    if not isinstance(mask_markers, bool):
        raise SegmentConfigError(f"{where}: `mask_markers` 必须是布尔，得到 {mask_markers!r}")
    margin = _num(raw, "marker_margin_mm", where)
    if not 0.0 <= margin <= 30.0:
        raise SegmentConfigError(f"{where}: `marker_margin_mm` 必须在 [0,30]，得到 {margin}")
    conf_single = _num(raw, "conf_single", where)
    conf_split = _num(raw, "conf_split", where)
    for name, v in (("conf_single", conf_single), ("conf_split", conf_split)):
        if not 0.0 <= v <= 1.0:
            raise SegmentConfigError(f"{where}: `{name}` 必须在 [0,1]，得到 {v}")
    side = raw.get("side", "top")
    if side not in SIDES:
        raise SegmentConfigError(f"{where}: `side` 只能是 {'/'.join(SIDES)}，得到 {side!r}")

    return SegmentConfig(
        channel=channel,
        blur_sigma_px=blur,
        open_ksize=open_k,
        close_ksize=close_k,
        bg_delta_gray=bg_delta,
        max_component_frac=max_frac,
        min_area_mm2=min_area,
        peak_min_mm=peak_min,
        peak_min_dist_mm=peak_dist,
        seed_dominance=dominance,
        seed_dominance_radius_mm=dom_radius,
        mask_markers=mask_markers,
        marker_margin_mm=margin,
        conf_single=conf_single,
        conf_split=conf_split,
        side=side,
        source=str(p),
    )

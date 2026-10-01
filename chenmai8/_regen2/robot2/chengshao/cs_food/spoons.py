"""勺上食物检查（spec §2，冻结接口：SpoonClassifier Protocol）。

MVP 实现 HeuristicSpoonClassifier：BGR→HSV，逐配置区间 cv2.inRange 取并集掩码；
score = 掩码均值(0-1)；has_food = score >= min_food_ratio。阈值偏保守
（宁可重舀，不空勺到口）。输入校验：必须 numpy ndarray、HxWx3、uint8、非空——
否则 ValueError。HSV 约定 8bit OpenCV：H∈[0,179]、S/V∈[0,255]；
h_lo > h_hi 表示跨 0 环绕（红色系），生效域 [h_lo,179]∪[0,h_hi]。
"""

from __future__ import annotations

import time
from typing import Protocol, runtime_checkable

import cv2
import numpy as np

from .config import FoodConfig, HsvRange, load_food_config
from chengshao.cs_schema import SpoonCheck

_H_MAX_179 = 179  # 8bit OpenCV 的 H 上界


@runtime_checkable
class SpoonClassifier(Protocol):
    """冻结接口：签名不改，实现可无感替换。"""

    def from_bgr(self, crop: np.ndarray) -> SpoonCheck: ...


def _validate_crop(crop: object) -> np.ndarray:
    """输入校验：ndarray / HxWx3 / uint8 / 非空，否则 ValueError。"""
    if not isinstance(crop, np.ndarray):
        raise ValueError(f"勺上裁剪必须是 numpy ndarray，得到 {type(crop).__name__}")
    if crop.ndim != 3 or crop.shape[2] != 3:
        raise ValueError(f"勺上裁剪必须是 HxWx3 三通道，得到 shape={crop.shape}")
    if crop.dtype != np.uint8:
        raise ValueError(f"勺上裁剪必须是 uint8，得到 {crop.dtype}")
    if crop.shape[0] == 0 or crop.shape[1] == 0:
        raise ValueError(f"勺上裁剪不能为空图，得到 shape={crop.shape}")
    return crop


def _range_mask(hsv: np.ndarray, r: HsvRange) -> np.ndarray:
    lo = (r.h_lo, r.s_lo, r.v_lo)
    hi = (r.h_hi, r.s_hi, r.v_hi)
    if r.wraps_around:
        low_part = cv2.inRange(hsv, (r.h_lo, r.s_lo, r.v_lo), (_H_MAX_179, r.s_hi, r.v_hi))
        high_part = cv2.inRange(hsv, (0, r.s_lo, r.v_lo), (r.h_hi, r.s_hi, r.v_hi))
        return low_part | high_part
    return cv2.inRange(hsv, lo, hi)


class HeuristicSpoonClassifier:
    """HSV 启发式勺检（MVP；经同一 Protocol 可被学习型分类器无感替换）。"""

    def __init__(
        self,
        config_path: str | None = None,
        cam_ref: str | None = None,
        ts_ns_source=None,
    ) -> None:
        cfg: FoodConfig = load_food_config(config_path)
        self.cam_ref: str = cam_ref if cam_ref is not None else cfg.cam_ref
        self.min_food_ratio: float = cfg.min_food_ratio
        self._ranges: tuple[HsvRange, ...] = cfg.hsv_ranges
        self._ts_ns_source = ts_ns_source if ts_ns_source is not None else time.time_ns

    def from_bgr(self, crop: np.ndarray) -> SpoonCheck:
        crop = _validate_crop(crop)
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        mask = np.zeros(hsv.shape[:2], dtype=np.uint8)
        for r in self._ranges:  # 逐区间取并集掩码（端点重叠无碍）
            mask |= _range_mask(hsv, r)
        score = float(mask.mean()) / 255.0  # 0-1
        has_food = bool(score >= self.min_food_ratio)  # 阈值之上才判有食物 → 宁可重舀
        return SpoonCheck(
            ts_ns=int(self._ts_ns_source()),
            has_food=has_food,
            score=score,
            cam_ref=self.cam_ref,
        )

"""勺上食物检查：冻结接口 + HSV 启发式 MVP 实现（开发指令 §3.2 / §5.5）。

接口冻结纪律：``SpoonClassifier.from_bgr(crop) -> SpoonCheck`` 签名不改；
延后的学习型分类器（training-plan §3）经同一 Protocol 无感替换，节点交互不变。

MVP 启发式 = 勺区域"食物色像素占比"阈值判定：
- BGR crop → HSV，逐配置区间取掩码（支持跨 0 环绕），占比 = 掩码均值；
- score = 占比（0-1）；has_food = score >= min_food_ratio（config 可调，偏保守）。

已知边界（设计内，不阻塞）：低饱和白色系食物（如椰子冻）与不锈钢勺/白瓷碗
在纯 HSV 域不可分，缺省区间不覆盖白色系；缓解路径 = config/food_hsv.json
扩区间 + 限定勺位裁剪框，或由延后的学习型分类器在同一接口下接手。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Protocol, runtime_checkable

import cv2
import numpy as np

from chengshao.cs_schema import SpoonCheck

from .config import FoodConfig, load_food_config

_H_MAX = 179  # 8bit OpenCV HSV：H ∈ [0,179]（与 config.HSVRange 同约定）


@runtime_checkable
class SpoonClassifier(Protocol):
    """勺上检查器冻结接口（开发指令 §3.2）：输入勺区域 BGR 裁剪，输出 SpoonCheck。"""

    def from_bgr(self, crop: np.ndarray) -> SpoonCheck: ...


def _validate_bgr(crop: object) -> np.ndarray:
    """校验输入为非空 3 通道 uint8 BGR 图，返回原数组。"""
    if not isinstance(crop, np.ndarray):
        raise ValueError("crop 必须是 numpy.ndarray（BGR）")
    if crop.ndim != 3 or crop.shape[2] != 3:
        raise ValueError(f"crop 必须是 HxWx3 三通道，实际 shape={crop.shape}")
    if crop.dtype != np.uint8:
        raise ValueError(f"crop 必须是 uint8，实际 dtype={crop.dtype}")
    if crop.shape[0] == 0 or crop.shape[1] == 0:
        raise ValueError("crop 尺寸为空")
    return crop


class HeuristicSpoonClassifier:
    """HSV 启发式勺上检查器（MVP 实现，满足 SpoonClassifier Protocol）。

    参数：
    - config_path：food_hsv 配置路径；None 用缺省 config/food_hsv.json；
    - cam_ref：覆盖配置中的来源相机标识（多相机场景用）；
    - ts_ns_source：纳秒时钟（缺省 time.time_ns；测试可注入固定时钟）。
    """

    def __init__(
        self,
        config_path: str | object | None = None,
        cam_ref: str | None = None,
        ts_ns_source: Callable[[], int] | None = None,
    ) -> None:
        cfg: FoodConfig = load_food_config(config_path)
        self._ranges = cfg.hsv_ranges
        self._min_ratio = cfg.min_food_ratio
        self._cam_ref = cam_ref if cam_ref is not None else cfg.cam_ref
        self._ts_ns = ts_ns_source if ts_ns_source is not None else time.time_ns

    @property
    def cam_ref(self) -> str:
        return self._cam_ref

    @property
    def min_food_ratio(self) -> float:
        return self._min_ratio

    def _food_mask(self, hsv: np.ndarray) -> np.ndarray:
        """逐区间 inRange 取并集掩码（h_lo>h_hi 的区间拆两段处理跨 0 环绕）。"""
        mask = np.zeros(hsv.shape[:2], dtype=np.uint8)
        for rng in self._ranges:
            segments = ((rng.h_lo, _H_MAX), (0, rng.h_hi)) if rng.h_lo > rng.h_hi else ((rng.h_lo, rng.h_hi),)
            for h_lo, h_hi in segments:
                lo = np.array([h_lo, rng.s_lo, rng.v_lo], dtype=np.uint8)
                hi = np.array([h_hi, rng.s_hi, rng.v_hi], dtype=np.uint8)
                mask |= cv2.inRange(hsv, lo, hi)
        return mask

    def from_bgr(self, crop: np.ndarray) -> SpoonCheck:
        bgr = _validate_bgr(crop)
        hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
        score = float(self._food_mask(hsv).mean()) / 255.0
        score = min(1.0, max(0.0, score))
        return SpoonCheck(
            ts_ns=int(self._ts_ns()),
            has_food=bool(score >= self._min_ratio),
            score=score,
            cam_ref=self._cam_ref,
        )


__all__ = ["HeuristicSpoonClassifier", "SpoonClassifier"]

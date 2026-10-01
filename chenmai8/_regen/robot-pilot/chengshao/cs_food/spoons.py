"""cs_food 勺上食物检查（HSV 启发式 MVP；cs_food spec §2）。

冻结接口（开发指令 §3.2）：``SpoonClassifier`` Protocol，``from_bgr(crop) -> SpoonCheck``，
签名不改、实现可无感替换（学习型分类器延后经同一 Protocol 接入）。

MVP ``HeuristicSpoonClassifier``：
- 输入校验：必须 numpy ndarray、HxWx3、uint8、非空——否则 ValueError；
- BGR→HSV，逐配置区间 ``cv2.inRange`` 取并集掩码；``score = 掩码均值(0-1)``；
- ``has_food = score >= min_food_ratio``。阈值偏保守（宁可重舀，不空勺到口）；
- HSV 约定：8bit OpenCV，H∈[0,179]、S/V∈[0,255]；``h_lo > h_hi`` 表示跨 0 环绕
  （红色系），生效域 [h_lo,179]∪[0,h_hi]。

已知边界（设计内）：低饱和白色系食物（椰子冻）与不锈钢勺/白瓷碗在纯 HSV 域不可分，
缺省区间不覆盖白色系；缓解 = config 扩区间 + 限定勺位裁剪框，或延后分类器接手。
"""

from __future__ import annotations

import time
from typing import Callable, Protocol, runtime_checkable

import cv2
import numpy as np

try:  # 常规路径：仓库根 cwd，chengshao 包整体可导入
    from chengshao.cs_schema import SpoonCheck
except ImportError:  # eval 入口（cwd=chengshao 包根）：cs_food 以顶层包运行
    from cs_schema import SpoonCheck  # type: ignore[no-redef]

from .config import FoodConfig, load_food_config

TsNsSource = Callable[[], int]


@runtime_checkable
class SpoonClassifier(Protocol):
    """冻结接口：勺上食物检查器（签名不改，实现可无感替换）。"""

    def from_bgr(self, crop: np.ndarray) -> SpoonCheck: ...


def _validate_crop(crop: object) -> np.ndarray:
    """勺上裁剪校验（spec §2：eval 与测试依赖该行为）。"""
    if not isinstance(crop, np.ndarray):
        raise ValueError(f"勺上裁剪必须是 numpy ndarray，得到 {type(crop).__name__}")
    if crop.ndim != 3 or crop.shape[2] != 3:
        raise ValueError(f"勺上裁剪必须是 HxWx3 BGR，得到 shape={tuple(crop.shape)}")
    if crop.dtype != np.uint8:
        raise ValueError(f"勺上裁剪必须是 uint8，得到 {crop.dtype}")
    if crop.shape[0] == 0 or crop.shape[1] == 0:
        raise ValueError(f"勺上裁剪不能为空，得到 shape={tuple(crop.shape)}")
    return crop


class HeuristicSpoonClassifier:
    """HSV 启发式 MVP 实现（满足 ``SpoonClassifier`` 冻结协议）。"""

    def __init__(
        self,
        config_path: str | None = None,
        cam_ref: str | None = None,
        ts_ns_source: TsNsSource | None = None,
    ) -> None:
        config: FoodConfig = load_food_config(config_path)
        self._config = config
        self.cam_ref = cam_ref if cam_ref is not None else config.cam_ref
        self.min_food_ratio = config.min_food_ratio
        self._ts_ns_source: TsNsSource = ts_ns_source if ts_ns_source is not None else time.time_ns

    def from_bgr(self, crop: np.ndarray) -> SpoonCheck:
        """勺上 BGR 裁剪 → SpoonCheck（score=食物掩码占比，has_food=过阈值）。"""
        frame = _validate_crop(crop)
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        mask = np.zeros(hsv.shape[:2], dtype=np.uint8)
        for band in self._config.hsv_ranges:
            mask = mask | self._band_mask(hsv, band)
        score = float(mask.mean() / 255.0)
        has_food = bool(score >= self.min_food_ratio)
        return SpoonCheck(
            ts_ns=int(self._ts_ns_source()),
            has_food=has_food,
            score=score,
            cam_ref=self.cam_ref,
        )

    @staticmethod
    def _band_mask(hsv: np.ndarray, band) -> np.ndarray:
        """单段 HSV 区间掩码；h_lo > h_hi 时跨 0 环绕取并集。"""
        s_lo = (band.s_lo, band.v_lo)
        s_hi = (band.s_hi, band.v_hi)
        if band.h_lo > band.h_hi:  # 跨 0 环绕（红色系）：[h_lo,179] ∪ [0,h_hi]
            upper = cv2.inRange(hsv, np.array([band.h_lo, *s_lo], np.uint8),
                                np.array([179, *s_hi], np.uint8))
            lower = cv2.inRange(hsv, np.array([0, *s_lo], np.uint8),
                                np.array([band.h_hi, *s_hi], np.uint8))
            return upper | lower
        return cv2.inRange(hsv, np.array([band.h_lo, *s_lo], np.uint8),
                           np.array([band.h_hi, *s_hi], np.uint8))

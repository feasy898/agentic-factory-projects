"""cs_food 基准码选碗（ArUco；cs_food spec §3）。

一码一碗：场景帧 → 灰度化 → 预二值化 → ArUco 检测 → 只留已登记码 →
码边长=四边均值 → 过小码（min_side_px）过滤 → 按（边长降序，碗序升序）排序。
未登记码一律忽略（他人干扰物不误选）。

检测前处理说明（实现自由度，spec 未冻结检测参数）：
- 合成/真实场景中基准码常无白留白、直接贴在中灰（≈90）背景上。ArUco 自适应阈值
  二值化要求"外圈留白读白"，中灰背景会使大码的码格/外圈不可同时满足。
  故先做固定阈值预二值化（非黑→白，THRESH_PRE_BINARY=45：码格黑为 0，其余→255），
  使外圈留白在任何窗口下都稳定读白；
- 自适应窗口扫描范围放宽（13..151，步长 10）以覆盖 14~150px 码格尺寸；
- minMarkerPerimeterRate 降到 0.02（缺省 0.03 会把 <17px 的码挡在候选之外，
  使 min_side_px 配置过滤形同虚设）。
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .config import BowlConfig, load_bowl_config


@dataclass(frozen=True)
class MarkerObservation:
    """一次检出的基准码观测（像素坐标系）。"""

    marker_id: int
    bowl_index: int
    center_px: tuple[float, float]
    side_px: float


# 检测前处理参数（见模块 docstring；非 spec 冻结项）
THRESH_PRE_BINARY = 45  # <45 视为码格黑（印制黑≈0），背景/码格白 → 255
_ADAPTIVE_WIN_MIN = 13
_ADAPTIVE_WIN_MAX = 151
_ADAPTIVE_WIN_STEP = 10
_MIN_MARKER_PERIMETER_RATE = 0.02
_PIXEL_PER_CELL = 8


def _validate_scene(img: object) -> np.ndarray:
    """场景帧校验：HxW 灰度或 HxWx3 BGR、uint8、非空；否则 ValueError。"""
    if not isinstance(img, np.ndarray):
        raise ValueError(f"场景帧必须是 numpy ndarray，得到 {type(img).__name__}")
    if img.ndim == 3 and img.shape[2] == 3:
        pass  # BGR
    elif img.ndim == 2:
        pass  # 灰度
    else:
        raise ValueError(f"场景帧必须是 HxW 灰度或 HxWx3 BGR，得到 shape={tuple(img.shape)}")
    if img.dtype != np.uint8:
        raise ValueError(f"场景帧必须是 uint8，得到 {img.dtype}")
    if img.shape[0] == 0 or img.shape[1] == 0:
        raise ValueError(f"场景帧不能为空，得到 shape={tuple(img.shape)}")
    return img


class BowlSelector:
    """基准码选碗器（配置见 ``config/bowl_markers.json``）。"""

    def __init__(self, config_path: str | None = None) -> None:
        self._config: BowlConfig = load_bowl_config(config_path)
        self.cam_ref = self._config.cam_ref
        self.min_side_px = self._config.min_side_px
        self._dictionary = cv2.aruco.getPredefinedDictionary(
            getattr(cv2.aruco, self._config.dictionary)
        )

    # -- 检测 ---------------------------------------------------------------

    def detect(self, img: np.ndarray) -> list[MarkerObservation]:
        """检测场景帧中的已登记基准码，按（边长降序，碗序升序）返回。"""
        frame = _validate_scene(img)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
        binary = cv2.threshold(gray, THRESH_PRE_BINARY, 255, cv2.THRESH_BINARY)[1]

        params = cv2.aruco.DetectorParameters()
        params.adaptiveThreshWinSizeMin = _ADAPTIVE_WIN_MIN
        params.adaptiveThreshWinSizeMax = _ADAPTIVE_WIN_MAX
        params.adaptiveThreshWinSizeStep = _ADAPTIVE_WIN_STEP
        params.minMarkerPerimeterRate = _MIN_MARKER_PERIMETER_RATE
        params.perspectiveRemovePixelPerCell = _PIXEL_PER_CELL
        corners, ids, _ = cv2.aruco.ArucoDetector(self._dictionary, params).detectMarkers(binary)

        observations: list[MarkerObservation] = []
        if ids is None:
            return observations
        for corner, mid in zip(corners, ids):
            marker_id = int(np.ravel(mid)[0])
            bowl_index = self._config.marker_to_bowl.get(str(marker_id))
            if bowl_index is None:
                continue  # 未登记码一律忽略（他人干扰物不误选）
            pts = np.asarray(corner, dtype=np.float64).reshape(4, 2)
            side_px = float(
                sum(np.linalg.norm(pts[i] - pts[(i + 1) % 4]) for i in range(4)) / 4.0
            )
            if side_px < self._config.min_side_px:
                continue  # 过小码 = 过远/噪声
            center = pts.mean(axis=0)
            observations.append(
                MarkerObservation(
                    marker_id=marker_id,
                    bowl_index=int(bowl_index),
                    center_px=(float(center[0]), float(center[1])),
                    side_px=side_px,
                )
            )
        observations.sort(key=lambda m: (-m.side_px, m.bowl_index))
        return observations

    def select(self, img: np.ndarray) -> int | None:
        """选碗：最大可见码（离得最近）对应碗序；无可选码返回 None。"""
        markers = self.detect(img)
        return markers[0].bowl_index if markers else None
